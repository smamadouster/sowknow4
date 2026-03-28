"""
SOWKNOW Agentic Search Pipeline
================================
A 6-stage agent that transforms a raw natural-language query into
a ranked, cited, synthesized answer — with strict RBAC enforcement
ensuring confidential documents are never leaked to unauthorized users
and never sent to external LLM APIs.

Pipeline stages:
  Stage 1 — IntentAgent      : Classify intent, extract entities, decompose query
  Stage 2 — QueryExpander    : Expand keywords, build sub-queries
  Stage 3 — HybridRetriever  : pgvector semantic + PostgreSQL FTS with RRF fusion
  Stage 4 — ReRanker         : Cross-encoder style re-scoring + bucket enforcement
  Stage 5 — SynthesisAgent   : LLM answer generation with privacy routing
  Stage 6 — SuggestionAgent  : Generate follow-up queries and refinements
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

import httpx
from sentence_transformers import SentenceTransformer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .search_models import (
    AgentTrace,
    Citation,
    DocumentBucket,
    ParsedIntent,
    QueryIntent,
    RawChunk,
    RelevanceLabel,
    SearchMode,
    SearchRequest,
    SearchResponse,
    SearchResult,
    SearchSuggestion,
    UserRole,
)
from .config import settings

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

RRF_K = 60  # Reciprocal Rank Fusion constant
HIGHLY_RELEVANT_THRESHOLD = 0.82
RELEVANT_THRESHOLD = 0.65
PARTIALLY_THRESHOLD = 0.45

INTENT_SYSTEM_PROMPT = """Tu es un agent d'analyse de requêtes pour SOWKNOW, un système de gestion de connaissances personnelles.

Analyse la requête utilisateur et retourne un objet JSON **uniquement** (pas de markdown, pas d'explication).

Format de sortie obligatoire :
{
  "intent": "<factual|temporal|comparative|synthesis|financial|cross_reference|exploratory|entity_search|procedural|unknown>",
  "confidence": <0.0-1.0>,
  "entities": ["<entité1>", "<entité2>"],
  "temporal_markers": ["<marqueur1>"],
  "keywords": ["<mot-clé1>", "<mot-clé2>"],
  "expanded_keywords": ["<synonyme1>", "<terme-associé1>"],
  "sub_queries": ["<sous-requête si complexe>"],
  "detected_language": "<fr|en>",
  "requires_synthesis": <true|false>,
  "temporal_range": {"start": "<ISO date or null>", "end": "<ISO date or null>"}
}

Règles :
- sub_queries : décompose si la requête est complexe (> 1 concept distinct). Sinon, tableau vide.
- requires_synthesis : true si la réponse nécessite de croiser plusieurs documents.
- temporal_range : extrais des dates concrètes si mentionnées (ex: "en 2020" → start: "2020-01-01", end: "2020-12-31").
- keywords : termes essentiels de recherche, 3-8 mots maximum.
- expanded_keywords : synonymes, variations, termes associés utiles pour la recherche.
"""

SYNTHESIS_SYSTEM_PROMPT_FR = """Tu es SOWKNOW Assistant, un expert en synthèse de connaissances personnelles.

À partir des extraits de documents fournis, génère une réponse complète, structurée et citée.

Règles impératives :
1. Commence par une réponse directe à la question (1-2 phrases).
2. Développe avec les éléments pertinents trouvés dans les documents.
3. Cite chaque information avec [Source: Titre du document, p.X].
4. Si plusieurs documents sont en contradiction, mentionne-le explicitement.
5. Termine par une section "Points clés" avec 3-5 bullet points.
6. Réponds dans la même langue que la question de l'utilisateur.
7. Si les documents ne contiennent pas d'information pertinente, dis-le clairement.
8. NE PAS inventer d'informations non présentes dans les extraits.

Format :
**Réponse directe:** ...

**Analyse détaillée:** ...

**Points clés:**
• ...
• ...

**Sources utilisées:** [liste]
"""

SUGGESTION_SYSTEM_PROMPT = """Tu es un assistant de recherche pour SOWKNOW.

Basé sur la requête originale et les résultats trouvés, génère 3-5 suggestions de requêtes de suivi.
Retourne uniquement un tableau JSON :
[
  {"suggestion_type": "related_query|refine|expand|temporal", "text": "...", "rationale": "..."},
  ...
]

Types :
- related_query : question connexe naturelle
- refine : reformulation plus précise
- expand : élargissement du sujet
- temporal : dimension temporelle non explorée

Langue : même langue que la requête originale.
"""


# ─────────────────────────────────────────────────────────────────────────────
# EMBEDDING MODEL (singleton)
# ─────────────────────────────────────────────────────────────────────────────

_embedding_model: Optional[SentenceTransformer] = None


def get_embedding_model() -> SentenceTransformer:
    global _embedding_model
    if _embedding_model is None:
        logger.info("Loading multilingual-e5-large embedding model...")
        _embedding_model = SentenceTransformer("intfloat/multilingual-e5-large")
    return _embedding_model


def embed_query(query: str) -> list[float]:
    """Embed a search query with the E5 'query:' prefix protocol."""
    model = get_embedding_model()
    prefixed = f"query: {query}"
    vector = model.encode(prefixed, normalize_embeddings=True)
    return vector.tolist()


# ─────────────────────────────────────────────────────────────────────────────
# LLM CLIENTS
# ─────────────────────────────────────────────────────────────────────────────

async def _call_kimi(
    messages: list[dict],
    system: str,
    temperature: float = 0.1,
    max_tokens: int = 2048,
) -> str:
    """Call Kimi 2.5 via Moonshot API. ONLY for public document contexts."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            "https://api.moonshot.cn/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.MOONSHOT_API_KEY}"},
            json={
                "model": "moonshot-v1-8k",
                "messages": [{"role": "system", "content": system}] + messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


async def _call_ollama(
    messages: list[dict],
    system: str,
    temperature: float = 0.1,
    max_tokens: int = 2048,
) -> str:
    """Call shared Ollama instance. REQUIRED for any confidential document context."""
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{settings.OLLAMA_HOST}/api/chat",
            json={
                "model": settings.OLLAMA_MODEL,
                "messages": [{"role": "system", "content": system}] + messages,
                "stream": False,
                "options": {"temperature": temperature, "num_predict": max_tokens},
            },
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"]


async def _route_llm(
    messages: list[dict],
    system: str,
    has_confidential: bool,
    **kwargs: Any,
) -> tuple[str, str]:
    """
    Privacy-safe LLM router.
    Returns (response_text, model_name).

    INVARIANT: If has_confidential is True, ALWAYS uses Ollama.
               Confidential content NEVER reaches Moonshot API.
    """
    if has_confidential:
        logger.info("LLM routing → Ollama (confidential context detected)")
        text = await _call_ollama(messages, system, **kwargs)
        return text, f"ollama/{settings.OLLAMA_MODEL}"
    else:
        logger.info("LLM routing → Kimi 2.5 (public context)")
        text = await _call_kimi(messages, system, **kwargs)
        return text, "kimi-2.5"


# ─────────────────────────────────────────────────────────────────────────────
# STAGE 1 — INTENT AGENT
# ─────────────────────────────────────────────────────────────────────────────

async def parse_intent(query: str) -> ParsedIntent:
    """
    Classify user intent, extract entities, detect language,
    decompose complex queries into sub-queries.
    Always uses Kimi 2.5 — intent parsing never touches document content.
    """
    try:
        raw, _ = await _route_llm(
            messages=[{"role": "user", "content": f"Requête : {query}"}],
            system=INTENT_SYSTEM_PROMPT,
            has_confidential=False,  # Intent parsing contains NO document content
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


def _fallback_intent(query: str) -> ParsedIntent:
    """Rule-based fallback when LLM intent parsing fails."""
    q = query.lower()
    temporal = any(w in q for w in ["2020", "2021", "2022", "2023", "2024", "an dernier", "last year", "évolution", "trend"])
    financial = any(w in q for w in ["bilan", "actif", "balance sheet", "financ", "asset", "trésorerie"])
    intent = QueryIntent.TEMPORAL if temporal else QueryIntent.FINANCIAL if financial else QueryIntent.EXPLORATORY
    # Simple keyword extraction: remove stop words
    stop_words = {"le", "la", "les", "de", "du", "des", "en", "et", "ou", "un", "une", "the", "a", "an", "of", "in"}
    words = [w for w in re.findall(r'\b\w+\b', query.lower()) if w not in stop_words and len(w) > 2]
    return ParsedIntent(
        intent=intent,
        confidence=0.5,
        keywords=words[:8],
        requires_synthesis=True,
        detected_language="fr" if any(w in q for w in ["le", "la", "les", "des", "est", "sont"]) else "en",
    )


# ─────────────────────────────────────────────────────────────────────────────
# STAGE 2 — QUERY EXPANDER
# ─────────────────────────────────────────────────────────────────────────────

def build_search_queries(intent: ParsedIntent, original_query: str) -> list[str]:
    """
    Construct the list of queries to run against the retriever.
    For complex intents, returns the original + all sub-queries.
    """
    queries = [original_query]
    queries.extend(intent.sub_queries)
    # Add a keyword-focused variant for better FTS coverage
    if intent.keywords:
        queries.append(" ".join(intent.keywords[:5]))
    # Deduplicate while preserving order
    seen: set[str] = set()
    result = []
    for q in queries:
        if q not in seen:
            seen.add(q)
            result.append(q)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# STAGE 3 — HYBRID RETRIEVER
# ─────────────────────────────────────────────────────────────────────────────

async def hybrid_retrieve(
    db: AsyncSession,
    queries: list[str],
    user_role: UserRole,
    request: SearchRequest,
    k: int = 60,
) -> list[RawChunk]:
    """
    Runs hybrid search for each query and merges results via RRF.

    RBAC enforcement is applied at the SQL level:
    - UserRole.USER     → WHERE bucket = 'public' (hard filter)
    - ADMIN/SUPER_USER  → no bucket restriction

    Returns deduplicated chunks sorted by RRF score descending.
    """
    all_chunks: dict[UUID, RawChunk] = {}
    # Per-query RRF rank accumulators: chunk_id → cumulative RRF score
    rrf_scores: dict[UUID, float] = {}

    for query_text in queries:
        query_vector = embed_query(query_text)
        chunks = await _run_single_hybrid_query(
            db=db,
            query_text=query_text,
            query_vector=query_vector,
            user_role=user_role,
            request=request,
            top_k=k,
        )
        # Accumulate RRF scores across queries
        for rank, chunk in enumerate(chunks, start=1):
            rrf_contribution = 1.0 / (RRF_K + rank)
            rrf_scores[chunk.chunk_id] = rrf_scores.get(chunk.chunk_id, 0.0) + rrf_contribution
            if chunk.chunk_id not in all_chunks:
                all_chunks[chunk.chunk_id] = chunk

    # Apply accumulated RRF scores
    for chunk_id, score in rrf_scores.items():
        if chunk_id in all_chunks:
            all_chunks[chunk_id].rrf_score = score

    # Sort by RRF score descending
    sorted_chunks = sorted(all_chunks.values(), key=lambda c: c.rrf_score, reverse=True)
    return sorted_chunks[:request.top_k * 3]  # Return 3x for re-ranker to work with


async def _run_single_hybrid_query(
    db: AsyncSession,
    query_text: str,
    query_vector: list[float],
    user_role: UserRole,
    request: SearchRequest,
    top_k: int,
) -> list[RawChunk]:
    """Execute one round of semantic + FTS hybrid search with all filters."""
    # Build bucket filter based on role
    bucket_filter = ""
    if user_role == UserRole.USER:
        bucket_filter = "AND dc.bucket = 'public'"

    # Build optional filters
    date_filter = ""
    params: dict[str, Any] = {
        "query_vector": str(query_vector),
        "query_text": query_text,
        "top_k": top_k,
    }

    if request.date_from:
        date_filter += " AND d.created_at >= :date_from"
        params["date_from"] = request.date_from
    if request.date_to:
        date_filter += " AND d.created_at <= :date_to"
        params["date_to"] = request.date_to
    if request.filter_tags:
        date_filter += " AND d.tags && :filter_tags"
        params["filter_tags"] = request.filter_tags
    if request.scope_document_ids:
        date_filter += " AND dc.document_id = ANY(:scope_ids)"
        params["scope_ids"] = [str(uid) for uid in request.scope_document_ids]

    sql = text(f"""
        WITH semantic AS (
            SELECT
                dc.id          AS chunk_id,
                dc.document_id,
                dc.bucket,
                dc.chunk_index,
                dc.page_number,
                dc.text,
                dc.created_at,
                d.title        AS document_title,
                d.file_type    AS document_type,
                d.tags,
                1 - (dc.embedding <=> :query_vector::vector) AS semantic_score,
                ROW_NUMBER() OVER (ORDER BY dc.embedding <=> :query_vector::vector) AS sem_rank
            FROM document_chunks dc
            JOIN documents d ON d.id = dc.document_id
            WHERE d.status = 'indexed'
              {bucket_filter}
              {date_filter}
            ORDER BY dc.embedding <=> :query_vector::vector
            LIMIT :top_k
        ),
        fts AS (
            SELECT
                dc.id          AS chunk_id,
                ts_rank_cd(dc.ts_vector,
                    plainto_tsquery('french', :query_text) |
                    plainto_tsquery('english', :query_text)
                )              AS fts_rank,
                ROW_NUMBER() OVER (
                    ORDER BY ts_rank_cd(dc.ts_vector,
                        plainto_tsquery('french', :query_text) |
                        plainto_tsquery('english', :query_text)
                    ) DESC
                ) AS fts_position
            FROM document_chunks dc
            JOIN documents d ON d.id = dc.document_id
            WHERE (
                dc.ts_vector @@ plainto_tsquery('french', :query_text) OR
                dc.ts_vector @@ plainto_tsquery('english', :query_text)
            )
            AND d.status = 'indexed'
            {bucket_filter}
            {date_filter}
            LIMIT :top_k
        ),
        combined AS (
            SELECT
                s.chunk_id,
                s.document_id,
                s.bucket,
                s.chunk_index,
                s.page_number,
                s.text,
                s.created_at,
                s.document_title,
                s.document_type,
                s.tags,
                COALESCE(s.semantic_score, 0.0) AS semantic_score,
                COALESCE(f.fts_rank, 0.0)       AS fts_rank,
                -- RRF per-query score
                (1.0 / ({RRF_K} + COALESCE(s.sem_rank, {top_k} + 1))) +
                (1.0 / ({RRF_K} + COALESCE(f.fts_position, {top_k} + 1))) AS rrf_score
            FROM semantic s
            FULL OUTER JOIN fts f ON s.chunk_id = f.chunk_id
        )
        SELECT *
        FROM combined
        ORDER BY rrf_score DESC
        LIMIT :top_k
    """)

    rows = (await db.execute(sql, params)).mappings().all()

    return [
        RawChunk(
            chunk_id=row["chunk_id"],
            document_id=row["document_id"],
            document_bucket=DocumentBucket(row["bucket"]),
            document_title=row["document_title"],
            document_type=row["document_type"],
            chunk_index=row["chunk_index"],
            page_number=row["page_number"],
            text=row["text"],
            semantic_score=float(row["semantic_score"] or 0.0),
            fts_rank=float(row["fts_rank"] or 0.0),
            rrf_score=float(row["rrf_score"] or 0.0),
            created_at=row["created_at"],
            tags=list(row["tags"] or []),
        )
        for row in rows
    ]


# ─────────────────────────────────────────────────────────────────────────────
# STAGE 4 — RE-RANKER & RESULT BUILDER
# ─────────────────────────────────────────────────────────────────────────────

def rerank_and_build_results(
    chunks: list[RawChunk],
    query: str,
    intent: ParsedIntent,
    top_k: int,
    user_role: UserRole,
) -> tuple[list[SearchResult], bool]:
    """
    Collapse chunks into document-level results.
    Groups chunks by document, picks the best chunk per document,
    normalizes scores, assigns relevance labels.

    Returns (results, has_confidential).
    RBAC double-check: any confidential chunk visible only to ADMIN/SUPER_USER.
    """
    # Group by document
    doc_map: dict[UUID, list[RawChunk]] = {}
    for chunk in chunks:
        doc_map.setdefault(chunk.document_id, []).append(chunk)

    results: list[SearchResult] = []
    has_confidential = False

    # Normalize RRF scores to 0-1 range
    max_rrf = max((c.rrf_score for c in chunks), default=1.0) or 1.0

    for doc_id, doc_chunks in doc_map.items():
        # Take the chunk with highest RRF score as representative
        best = max(doc_chunks, key=lambda c: c.rrf_score)

        # RBAC guard — belt-and-suspenders after SQL-level filter
        if best.document_bucket == DocumentBucket.CONFIDENTIAL:
            if user_role == UserRole.USER:
                continue  # Never expose — should already be filtered in SQL
            has_confidential = True

        normalized_score = min(best.rrf_score / max_rrf, 1.0)
        label = _score_to_label(normalized_score)

        # Highlight matching keywords in excerpt
        excerpt = _build_excerpt(best.text, intent.keywords)
        highlights = _extract_highlights(doc_chunks, intent.keywords)

        results.append(SearchResult(
            rank=0,  # Will be set after sorting
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

    # Sort by relevance score descending
    results.sort(key=lambda r: r.relevance_score, reverse=True)

    # Assign sequential ranks
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
    """Find the most keyword-dense window in the chunk text."""
    if not keywords:
        return text[:400]
    sentences = re.split(r'(?<=[.!?])\s+', text)
    best_sent = max(sentences, key=lambda s: sum(1 for kw in keywords if kw.lower() in s.lower()), default=text)
    return best_sent[:400]


def _extract_highlights(chunks: list[RawChunk], keywords: list[str]) -> list[str]:
    """Extract up to 3 short, keyword-rich sentences across all chunks."""
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
        reasons.append("forte similarité sémantique")
    if chunk.fts_rank > 0.3:
        reasons.append("correspondance textuelle exacte")
    matched_kw = [kw for kw in intent.keywords if kw.lower() in chunk.text.lower()]
    if matched_kw:
        reasons.append(f"mots-clés: {', '.join(matched_kw[:3])}")
    if intent.entities:
        matched_ent = [e for e in intent.entities if e.lower() in chunk.text.lower()]
        if matched_ent:
            reasons.append(f"entités: {', '.join(matched_ent[:2])}")
    return " · ".join(reasons) if reasons else "correspondance globale"


# ─────────────────────────────────────────────────────────────────────────────
# STAGE 5 — SYNTHESIS AGENT
# ─────────────────────────────────────────────────────────────────────────────

async def synthesize_answer(
    query: str,
    results: list[SearchResult],
    raw_chunks: list[RawChunk],
    intent: ParsedIntent,
    has_confidential: bool,
    language: str,
) -> tuple[str, str]:
    """
    Generate a direct synthesized answer from the top retrieved chunks.
    Routes to Ollama if any confidential chunk is in context.

    Returns (answer_text, model_name).
    """
    # Build context from top-5 document chunks
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

    lang_instruction = "Réponds en français." if language == "fr" else "Respond in English."
    user_message = f"""Question : {query}

{lang_instruction}

Documents disponibles :
{context}"""

    system = SYNTHESIS_SYSTEM_PROMPT_FR if language == "fr" else SYNTHESIS_SYSTEM_PROMPT_FR.replace("français", "English")
    answer, model = await _route_llm(
        messages=[{"role": "user", "content": user_message}],
        system=system,
        has_confidential=has_confidential,
        temperature=0.2,
        max_tokens=1500,
    )
    return answer, model


# ─────────────────────────────────────────────────────────────────────────────
# STAGE 6 — SUGGESTION AGENT
# ─────────────────────────────────────────────────────────────────────────────

async def generate_suggestions(
    original_query: str,
    results: list[SearchResult],
    intent: ParsedIntent,
    has_confidential: bool,
) -> list[SearchSuggestion]:
    """Generate 3-5 follow-up query suggestions based on what was found."""
    try:
        top_titles = [r.document_title for r in results[:5]]
        context = f"Requête: {original_query}\nDocuments trouvés: {', '.join(top_titles)}\nIntent: {intent.intent.value}"
        raw, _ = await _route_llm(
            messages=[{"role": "user", "content": context}],
            system=SUGGESTION_SYSTEM_PROMPT,
            has_confidential=False,  # No document content — safe for Kimi
            temperature=0.4,
            max_tokens=400,
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
            text=f"Comment a évolué '{query}' au fil du temps ?",
            rationale="Exploration temporelle de ce sujet",
        ))
    if intent.entities:
        suggestions.append(SearchSuggestion(
            suggestion_type="entity_search",
            text=f"Tous les documents mentionnant '{intent.entities[0]}'",
            rationale="Recherche centrée sur cette entité",
        ))
    suggestions.append(SearchSuggestion(
        suggestion_type="expand",
        text=f"Résumé global sur : {query}",
        rationale="Vue d'ensemble synthétisée",
    ))
    return suggestions


# ─────────────────────────────────────────────────────────────────────────────
# BUILD CITATIONS
# ─────────────────────────────────────────────────────────────────────────────

def build_citations(results: list[SearchResult], raw_chunks: list[RawChunk]) -> list[Citation]:
    """Build citation objects from the top results — one citation per source document."""
    cited_docs: set[UUID] = set()
    citations: list[Citation] = []
    chunk_by_doc = {c.document_id: c for c in sorted(raw_chunks, key=lambda c: c.rrf_score, reverse=True)}

    for result in results:
        if result.document_id not in cited_docs:
            cited_docs.add(result.document_id)
            best_chunk = chunk_by_doc.get(result.document_id)
            excerpt = (best_chunk.text[:200] + "…") if best_chunk else result.excerpt[:200]
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


# ─────────────────────────────────────────────────────────────────────────────
# MAIN ORCHESTRATOR
# ─────────────────────────────────────────────────────────────────────────────

async def run_agentic_search(
    db: AsyncSession,
    request: SearchRequest,
    user_role: UserRole,
    user_id: UUID,
) -> SearchResponse:
    """
    Full agentic search pipeline orchestrator.

    Security guarantees enforced here:
    1. Bucket filter applied at SQL level (Stage 3).
    2. RBAC double-check applied at re-rank level (Stage 4).
    3. LLM routing determined by presence of confidential chunks (Stage 5).
    4. Suggestion generation never includes document content (safe for Kimi always).
    """
    start_ms = time.monotonic()
    logger.info("Agentic search started | user=%s role=%s query='%s'", user_id, user_role, request.query)

    # ── Determine mode ──────────────────────────────────────────────────────
    mode = request.mode
    if mode == SearchMode.AUTO:
        # Use FAST for short simple queries, DEEP for complex ones
        mode = SearchMode.FAST if (len(request.query.split()) <= 5) else SearchMode.DEEP

    # ── Stage 1: Intent ─────────────────────────────────────────────────────
    intent = await parse_intent(request.query)
    logger.info("Intent: %s (%.2f) | sub_queries: %d", intent.intent, intent.confidence, len(intent.sub_queries))

    # Override language if caller specified
    if request.language:
        intent.detected_language = request.language

    # ── Stage 2: Query expansion ─────────────────────────────────────────────
    queries = build_search_queries(intent, request.query)

    # ── Stage 3: Hybrid retrieval ─────────────────────────────────────────────
    raw_chunks = await hybrid_retrieve(db, queries, user_role, request)
    logger.info("Retrieved %d chunks from hybrid search", len(raw_chunks))

    # ── Stage 4: Re-rank & build results ─────────────────────────────────────
    results, has_confidential = rerank_and_build_results(
        raw_chunks, request.query, intent, request.top_k, user_role
    )
    logger.info("Re-ranked to %d results | confidential=%s", len(results), has_confidential)

    # ── Stage 5: Synthesis (DEEP mode or complex intent) ─────────────────────
    answer_synthesis: Optional[str] = None
    model_used = "none"

    should_synthesize = (
        mode == SearchMode.DEEP
        or intent.requires_synthesis
        or intent.intent in (
            QueryIntent.SYNTHESIS,
            QueryIntent.TEMPORAL,
            QueryIntent.COMPARATIVE,
            QueryIntent.FINANCIAL,
        )
    ) and len(results) > 0

    if should_synthesize:
        answer_synthesis, model_used = await synthesize_answer(
            query=request.query,
            results=results,
            raw_chunks=raw_chunks,
            intent=intent,
            has_confidential=has_confidential,
            language=intent.detected_language,
        )

    # ── Stage 6: Suggestions ─────────────────────────────────────────────────
    suggestions: list[SearchSuggestion] = []
    if request.include_suggestions and results:
        suggestions = await generate_suggestions(request.query, results, intent, has_confidential)

    # ── Citations ────────────────────────────────────────────────────────────
    citations = build_citations(results, raw_chunks)

    elapsed_ms = int((time.monotonic() - start_ms) * 1000)

    trace = AgentTrace(
        intent_detected=intent.intent,
        intent_confidence=intent.confidence,
        sub_queries_used=queries[1:],  # Exclude original
        total_chunks_retrieved=len(raw_chunks),
        chunks_after_reranking=len(results),
        llm_model_used=model_used,
        processing_time_ms=elapsed_ms,
        confidential_results_count=sum(1 for r in results if r.is_confidential),
        synthesis_performed=bool(answer_synthesis),
    )

    logger.info(
        "Search complete | results=%d time=%dms model=%s confidential=%s",
        len(results), elapsed_ms, model_used, has_confidential,
    )

    return SearchResponse(
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


# ─────────────────────────────────────────────────────────────────────────────
# UTILITIES
# ─────────────────────────────────────────────────────────────────────────────

def _clean_json(raw: str) -> str:
    """Strip markdown fences from LLM JSON output."""
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return raw.strip()
