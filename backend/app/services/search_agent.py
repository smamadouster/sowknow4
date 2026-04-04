"""
SOWKNOW Agentic Search Pipeline
================================
6-stage agent for ranked, cited, synthesized answers with RBAC enforcement.
"""

import asyncio
import json
import logging
import re
import time
from typing import Any, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select as sa_select
from app.models.document import Document, DocumentBucket
from app.models.user import UserRole
from app.services.agent_identity import build_service_prompt
from app.services.context_block_service import get_cached_context_block
from app.services.llm_router import llm_router
from app.services.search_service import HybridSearchService
from .search_models import (
    AgenticSearchRequest,
    AgenticSearchResponse,
    AgentTrace,
    Citation,
    ParsedIntent,
    QueryIntent,
    RawChunk,
    RelevanceLabel,
    SearchMode,
    SearchResult,
    SearchSuggestion,
)

logger = logging.getLogger(__name__)

RRF_K = 60
HIGHLY_RELEVANT_THRESHOLD = 0.82
RELEVANT_THRESHOLD = 0.65
PARTIALLY_THRESHOLD = 0.45


def build_search_queries(intent: ParsedIntent, original_query: str) -> list[str]:
    queries = [original_query]
    queries.extend(intent.sub_queries)
    if intent.keywords:
        queries.append(" ".join(intent.keywords[:5]))
    seen: set[str] = set()
    result = []
    for q in queries:
        if q not in seen:
            seen.add(q)
            result.append(q)
    return result


def rerank_and_build_results(
    chunks: list[RawChunk],
    query: str,
    intent: ParsedIntent,
    top_k: int,
    user_role: UserRole,
) -> tuple[list[SearchResult], bool]:
    doc_map: dict[UUID, list[RawChunk]] = {}
    for chunk in chunks:
        doc_map.setdefault(chunk.document_id, []).append(chunk)

    results: list[SearchResult] = []
    has_confidential = False
    max_rrf = max((c.rrf_score for c in chunks), default=1.0) or 1.0

    for doc_id, doc_chunks in doc_map.items():
        sorted_chunks = sorted(doc_chunks, key=lambda c: c.rrf_score, reverse=True)
        best = sorted_chunks[0]

        if best.document_bucket == DocumentBucket.CONFIDENTIAL:
            if user_role == UserRole.USER:
                continue
            has_confidential = True

        # Top-2 average: documents with multiple relevant chunks rank higher
        top_chunks = sorted_chunks[:2]
        doc_score = sum(c.rrf_score for c in top_chunks) / len(top_chunks)
        normalized_score = min(doc_score / max_rrf, 1.0)
        label = _score_to_label(normalized_score)
        excerpt = _build_excerpt(best.text, intent.keywords)
        highlights = _extract_highlights(doc_chunks, intent.keywords)

        results.append(SearchResult(
            rank=0,
            document_id=doc_id,
            document_title=best.document_title,
            document_type=best.document_type,
            bucket=best.document_bucket,
            relevance_label=label,
            relevance_score=round(normalized_score, 4),
            excerpt=excerpt,
            highlights=highlights,
            tags=best.tags,
            page_number=best.page_number,
            document_date=best.created_at,
            match_reason=_build_match_reason(best, intent),
            is_confidential=(best.document_bucket == DocumentBucket.CONFIDENTIAL),
        ))

    results.sort(key=lambda r: r.relevance_score, reverse=True)
    for i, result in enumerate(results[:top_k], start=1):
        result.rank = i

    return results[:top_k], has_confidential


def _score_to_label(score: float) -> RelevanceLabel:
    if score >= HIGHLY_RELEVANT_THRESHOLD:
        return RelevanceLabel.HIGHLY_RELEVANT
    elif score >= RELEVANT_THRESHOLD:
        return RelevanceLabel.RELEVANT
    elif score >= PARTIALLY_THRESHOLD:
        return RelevanceLabel.PARTIALLY
    return RelevanceLabel.MARGINAL


def _build_excerpt(text: str, keywords: list[str]) -> str:
    if not keywords:
        return text[:400]
    sentences = re.split(r'(?<=[.!?])\s+', text)
    best_sent = max(
        sentences,
        key=lambda s: sum(1 for kw in keywords if kw.lower() in s.lower()),
        default=text,
    )
    return best_sent[:400]


def _extract_highlights(chunks: list[RawChunk], keywords: list[str]) -> list[str]:
    if not keywords:
        return []
    candidates = []
    for chunk in chunks:
        sentences = re.split(r'(?<=[.!?])\s+', chunk.text)
        for s in sentences:
            score = sum(1 for kw in keywords if kw.lower() in s.lower())
            if score > 0:
                candidates.append((score, s.strip()))
    candidates.sort(reverse=True, key=lambda x: x[0])
    return [s for _, s in candidates[:3] if len(s) > 20]


def _build_match_reason(chunk: RawChunk, intent: ParsedIntent) -> str:
    reasons = []
    if chunk.semantic_score > 0.7:
        reasons.append("forte similarite semantique")
    if chunk.fts_rank > 0.3:
        reasons.append("correspondance textuelle exacte")
    matched_kw = [kw for kw in intent.keywords if kw.lower() in chunk.text.lower()]
    if matched_kw:
        reasons.append(f"mots-cles: {', '.join(matched_kw[:3])}")
    if intent.entities:
        matched_ent = [e for e in intent.entities if e.lower() in chunk.text.lower()]
        if matched_ent:
            reasons.append(f"entites: {', '.join(matched_ent[:2])}")
    return " | ".join(reasons) if reasons else "correspondance globale"


def build_citations(results: list[SearchResult], raw_chunks: list[RawChunk]) -> list[Citation]:
    cited_docs: set[UUID] = set()
    citations: list[Citation] = []
    chunk_by_doc = {
        c.document_id: c
        for c in sorted(raw_chunks, key=lambda c: c.rrf_score, reverse=True)
    }

    for result in results:
        if result.document_id not in cited_docs:
            cited_docs.add(result.document_id)
            best_chunk = chunk_by_doc.get(result.document_id)
            excerpt = (best_chunk.text[:200] + "...") if best_chunk else result.excerpt[:200]
            citations.append(Citation(
                document_id=result.document_id,
                document_title=result.document_title,
                document_type=result.document_type,
                bucket=result.bucket,
                page_number=result.page_number,
                chunk_excerpt=excerpt,
                relevance_score=result.relevance_score,
            ))
    return citations[:10]


def _fallback_intent(query: str) -> ParsedIntent:
    q = query.lower()
    temporal = any(w in q for w in [
        "2020", "2021", "2022", "2023", "2024", "2025", "2026",
        "an dernier", "last year", "evolution", "trend",
    ])
    financial = any(w in q for w in [
        "bilan", "actif", "balance sheet", "financ", "asset", "tresorerie",
    ])
    intent = (
        QueryIntent.TEMPORAL if temporal
        else QueryIntent.FINANCIAL if financial
        else QueryIntent.EXPLORATORY
    )
    stop_words = {
        "le", "la", "les", "de", "du", "des", "en", "et", "ou",
        "un", "une", "the", "a", "an", "of", "in",
    }
    words = [
        w for w in re.findall(r'\b\w+\b', query.lower())
        if w not in stop_words and len(w) > 2
    ]
    return ParsedIntent(
        intent=intent,
        confidence=0.5,
        keywords=words[:8],
        requires_synthesis=True,
        detected_language=(
            "fr" if any(re.search(r'\b' + w + r'\b', q) for w in ["le", "la", "les", "des", "est", "sont"])
            else "en"
        ),
    )


# ---- LLM PROMPTS ----

_SEARCH_MISSION = (
    "Execute multi-stage agentic search across the SOWKNOW vault using intent parsing, "
    "retrieval, reranking, and synthesis"
)
_SEARCH_CONSTRAINTS = (
    "- You MUST use hybrid search (vector + full-text) for comprehensive retrieval\n"
    "- You MUST rerank results by relevance and temporal context\n"
    "- You MUST include source citations in synthesized results\n"
    "- You MUST respect vault isolation between public and confidential documents"
)

INTENT_SYSTEM_PROMPT = build_service_prompt(
    service_name="SOWKNOW Search Intent Agent",
    mission=_SEARCH_MISSION,
    constraints=_SEARCH_CONSTRAINTS,
    task_prompt="""Analyse la requete utilisateur et retourne un objet JSON **uniquement** (pas de markdown, pas d'explication).

Format de sortie obligatoire :
{
  "intent": "<factual|temporal|comparative|synthesis|financial|cross_reference|exploratory|entity_search|procedural|unknown>",
  "confidence": <0.0-1.0>,
  "entities": ["<entite1>", "<entite2>"],
  "temporal_markers": ["<marqueur1>"],
  "keywords": ["<mot-cle1>", "<mot-cle2>"],
  "expanded_keywords": ["<synonyme1>", "<terme-associe1>"],
  "sub_queries": ["<sous-requete si complexe>"],
  "detected_language": "<fr|en>",
  "requires_synthesis": <true|false>,
  "temporal_range": {"start": "<ISO date or null>", "end": "<ISO date or null>"}
}""",
)

SYNTHESIS_SYSTEM_PROMPT = build_service_prompt(
    service_name="SOWKNOW Search Synthesis Agent",
    mission=_SEARCH_MISSION,
    constraints=_SEARCH_CONSTRAINTS,
    task_prompt="""A partir des extraits de documents fournis, genere une reponse complete, structuree et citee.

Regles imperatives :
1. Commence par une reponse directe a la question (1-2 phrases).
2. Developpe avec les elements pertinents trouves dans les documents.
3. Cite chaque information avec [Source: Titre du document, p.X].
4. Si plusieurs documents sont en contradiction, mentionne-le explicitement.
5. Termine par une section "Points cles" avec 3-5 bullet points.
6. Reponds dans la meme langue que la question de l'utilisateur.
7. Si les documents ne contiennent pas d'information pertinente, dis-le clairement.
8. NE PAS inventer d'informations non presentes dans les extraits.""",
)

SUGGESTION_SYSTEM_PROMPT = build_service_prompt(
    service_name="SOWKNOW Search Suggestion Agent",
    mission=_SEARCH_MISSION,
    constraints=_SEARCH_CONSTRAINTS,
    task_prompt="""Base sur la requete originale et les resultats trouves, genere 3-5 suggestions de requetes de suivi.
Retourne uniquement un tableau JSON :
[
  {"suggestion_type": "related_query|refine|expand|temporal", "text": "...", "rationale": "..."}
]""",
    include_vault_protocol=False,
)


# ---- LLM WRAPPER ----

async def _call_llm(
    messages: list[dict],
    system: str,
    has_confidential: bool,
    temperature: float = 0.1,
    max_tokens: int = 2048,
    context_block: str | None = None,
) -> tuple[str, str]:
    """Call LLM via existing LLMRouter. Returns (response_text, provider_name)."""
    query_text = messages[0].get("content", "") if messages else ""

    decision = await llm_router.select_provider(
        query=query_text,
        has_confidential=has_confidential,
    )
    model_name = decision.provider_name

    # Prepend working memory context block to system prompt
    effective_system = system
    if context_block:
        effective_system = context_block + "\n\n" + system

    full_messages = [{"role": "system", "content": effective_system}] + messages
    chunks = []
    async for chunk in llm_router.generate_completion(
        messages=full_messages,
        query=query_text,
        has_confidential=has_confidential,
        temperature=temperature,
        max_tokens=max_tokens,
    ):
        chunks.append(chunk)

    return "".join(chunks), model_name


def _clean_json(raw: str) -> str:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return raw.strip()


# ---- STAGE 1: INTENT AGENT ----

async def parse_intent(query: str) -> ParsedIntent:
    try:
        raw, _ = await _call_llm(
            messages=[{"role": "user", "content": f"Requete : {query}"}],
            system=INTENT_SYSTEM_PROMPT,
            has_confidential=False,
            temperature=0.0,
            max_tokens=512,
        )
        data = json.loads(_clean_json(raw))
        return ParsedIntent(
            intent=QueryIntent(data.get("intent", "unknown")),
            confidence=float(data.get("confidence", 0.5)),
            entities=data.get("entities", []),
            temporal_markers=data.get("temporal_markers", []),
            keywords=data.get("keywords", []),
            expanded_keywords=data.get("expanded_keywords", []),
            sub_queries=data.get("sub_queries", []),
            detected_language=data.get("detected_language", "fr"),
            requires_synthesis=bool(data.get("requires_synthesis", False)),
            temporal_range=data.get("temporal_range"),
        )
    except Exception as exc:
        logger.warning("Intent parsing failed, using fallback: %s", exc)
        return _fallback_intent(query)


# ---- STAGE 5: SYNTHESIS AGENT ----

async def synthesize_answer(
    query: str,
    results: list[SearchResult],
    raw_chunks: list[RawChunk],
    intent: ParsedIntent,
    has_confidential: bool,
    language: str,
    context_block: str | None = None,
) -> tuple[str, str]:
    top_chunks = sorted(raw_chunks, key=lambda c: c.rrf_score, reverse=True)[:5]
    context_parts = []
    for i, chunk in enumerate(top_chunks, 1):
        bucket_label = "[CONFIDENTIEL]" if chunk.document_bucket == DocumentBucket.CONFIDENTIAL else "[PUBLIC]"
        context_parts.append(
            f"[Extrait {i}] {bucket_label} Source: {chunk.document_title}"
            + (f", p.{chunk.page_number}" if chunk.page_number else "")
            + f"\n{chunk.text}\n"
        )
    context = "\n---\n".join(context_parts)
    lang_instruction = "Reponds en francais." if language == "fr" else "Respond in English."
    user_message = f"Question : {query}\n\n{lang_instruction}\n\nDocuments disponibles :\n{context}"

    return await _call_llm(
        messages=[{"role": "user", "content": user_message}],
        system=SYNTHESIS_SYSTEM_PROMPT,
        has_confidential=has_confidential,
        temperature=0.2,
        max_tokens=1500,
        context_block=context_block,
    )


# ---- STAGE 6: SUGGESTION AGENT ----

async def generate_suggestions(
    original_query: str,
    results: list[SearchResult],
    intent: ParsedIntent,
    has_confidential: bool,
    context_block: str | None = None,
) -> list[SearchSuggestion]:
    try:
        top_titles = [r.document_title for r in results[:5]]
        context = f"Requete: {original_query}\nDocuments trouves: {', '.join(top_titles)}\nIntent: {intent.intent.value}"
        raw, _ = await _call_llm(
            messages=[{"role": "user", "content": context}],
            system=SUGGESTION_SYSTEM_PROMPT,
            has_confidential=False,
            temperature=0.4,
            max_tokens=400,
            context_block=context_block,
        )
        data = json.loads(_clean_json(raw))
        return [
            SearchSuggestion(
                suggestion_type=item.get("suggestion_type", "related_query"),
                text=item["text"],
                rationale=item.get("rationale", ""),
            )
            for item in data[:5]
        ]
    except Exception as exc:
        logger.warning("Suggestion generation failed: %s", exc)
        return _fallback_suggestions(original_query, intent)


def _fallback_suggestions(query: str, intent: ParsedIntent) -> list[SearchSuggestion]:
    suggestions = []
    if intent.temporal_markers:
        suggestions.append(SearchSuggestion(
            suggestion_type="temporal",
            text=f"Comment a evolue '{query}' au fil du temps ?",
            rationale="Exploration temporelle de ce sujet",
        ))
    if intent.entities:
        suggestions.append(SearchSuggestion(
            suggestion_type="entity_search",
            text=f"Tous les documents mentionnant '{intent.entities[0]}'",
            rationale="Recherche centree sur cette entite",
        ))
    suggestions.append(SearchSuggestion(
        suggestion_type="expand",
        text=f"Resume global sur : {query}",
        rationale="Vue d'ensemble synthetisee",
    ))
    return suggestions


# ---- MAIN ORCHESTRATOR ----

async def run_agentic_search(
    db: AsyncSession,
    request: AgenticSearchRequest,
    user_role: UserRole,
    user_id: UUID,
    user: Any,
) -> AgenticSearchResponse:
    start_ms = time.monotonic()
    logger.info("Agentic search started | user=%s role=%s query='%s'", user_id, user_role, request.query)

    # Fetch working memory context block once for all LLM calls
    _context_block: str | None = None
    try:
        _context_block = await get_cached_context_block(db)
    except Exception:
        pass

    mode = request.mode
    if mode == SearchMode.AUTO:
        mode = SearchMode.FAST if len(request.query.split()) <= 5 else SearchMode.DEEP

    # Stage 1: Intent
    intent = await parse_intent(request.query)
    logger.info("Intent: %s (%.2f) | sub_queries: %d", intent.intent, intent.confidence, len(intent.sub_queries))
    if request.language:
        intent.detected_language = request.language

    # Stage 2: Query expansion
    queries = build_search_queries(intent, request.query)

    # Stage 3: Hybrid retrieval
    search_service = HybridSearchService()
    all_chunks: list[RawChunk] = []
    for query_text in queries:
        result = await search_service.hybrid_search(
            query=query_text,
            limit=request.top_k * 3,
            offset=0,
            db=db,
            user=user,
        )
        for sr in result.get("results", []):
            all_chunks.append(RawChunk(
                chunk_id=sr.chunk_id,
                document_id=sr.document_id,
                document_title=sr.document_name,
                document_bucket=DocumentBucket(sr.document_bucket),
                document_type=sr.document_name.rsplit(".", 1)[-1] if "." in sr.document_name else "unknown",
                chunk_index=sr.chunk_index,
                page_number=sr.page_number,
                text=sr.chunk_text,
                semantic_score=sr.semantic_score,
                fts_rank=sr.keyword_score,
                rrf_score=sr.final_score,
                tags=[],
            ))

    # Stage 3b: Filter to journal entries if requested
    if request.journal_only:
        journal_doc_ids = set()
        doc_ids_to_check = {c.document_id for c in all_chunks}
        if doc_ids_to_check:
            result = await db.execute(
                sa_select(Document.id).where(
                    Document.id.in_(doc_ids_to_check),
                    Document.document_metadata["document_type"].astext == "journal",
                )
            )
            journal_doc_ids = {row[0] for row in result.fetchall()}
        all_chunks = [c for c in all_chunks if c.document_id in journal_doc_ids]

    # Deduplicate by chunk_id
    seen_ids: set[UUID] = set()
    deduped: list[RawChunk] = []
    for chunk in all_chunks:
        if chunk.chunk_id not in seen_ids:
            seen_ids.add(chunk.chunk_id)
            deduped.append(chunk)
    all_chunks = deduped
    logger.info("Retrieved %d chunks from hybrid search", len(all_chunks))

    # Stage 4: Re-rank
    results, has_confidential = rerank_and_build_results(
        all_chunks, request.query, intent, request.top_k, user_role,
    )
    logger.info("Re-ranked to %d results | confidential=%s", len(results), has_confidential)

    # Stage 5: Synthesis
    answer_synthesis: Optional[str] = None
    model_used = "none"

    should_synthesize = (
        mode == SearchMode.DEEP
        or intent.requires_synthesis
        or intent.intent in (
            QueryIntent.SYNTHESIS, QueryIntent.TEMPORAL,
            QueryIntent.COMPARATIVE, QueryIntent.FINANCIAL,
        )
    ) and len(results) > 0

    if should_synthesize:
        answer_synthesis, model_used = await synthesize_answer(
            query=request.query,
            results=results,
            raw_chunks=all_chunks,
            intent=intent,
            has_confidential=has_confidential,
            language=intent.detected_language,
            context_block=_context_block,
        )

    # Stage 6: Suggestions
    suggestions: list[SearchSuggestion] = []
    if request.include_suggestions and results:
        suggestions = await generate_suggestions(
            request.query, results, intent, has_confidential,
            context_block=_context_block,
        )

    citations = build_citations(results, all_chunks)
    elapsed_ms = int((time.monotonic() - start_ms) * 1000)

    trace = AgentTrace(
        intent_detected=intent.intent,
        intent_confidence=intent.confidence,
        sub_queries_used=queries[1:],
        total_chunks_retrieved=len(all_chunks),
        chunks_after_reranking=len(results),
        llm_model_used=model_used,
        processing_time_ms=elapsed_ms,
        confidential_results_count=sum(1 for r in results if r.is_confidential),
        synthesis_performed=bool(answer_synthesis),
    )

    return AgenticSearchResponse(
        query=request.query,
        parsed_intent=intent.intent,
        answer_synthesis=answer_synthesis,
        answer_language=intent.detected_language,
        results=results,
        citations=citations,
        suggestions=suggestions,
        total_found=len(results),
        has_confidential_results=has_confidential,
        llm_model_used=model_used if model_used != "none" else None,
        agent_trace=trace,
        search_time_ms=elapsed_ms,
    )
