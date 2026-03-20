"""
SOWKNOW Agentic Search Pipeline
================================
6-stage agent for ranked, cited, synthesized answers with RBAC enforcement.
"""

import logging
import re
from uuid import UUID

from app.models.document import DocumentBucket
from app.models.user import UserRole
from .search_models import (
    Citation,
    ParsedIntent,
    QueryIntent,
    RawChunk,
    RelevanceLabel,
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
        best = max(doc_chunks, key=lambda c: c.rrf_score)

        if best.document_bucket == DocumentBucket.CONFIDENTIAL:
            if user_role == UserRole.USER:
                continue
            has_confidential = True

        normalized_score = min(best.rrf_score / max_rrf, 1.0)
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
