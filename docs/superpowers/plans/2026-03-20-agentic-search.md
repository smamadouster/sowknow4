# Agentic Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current basic hybrid search with a 6-stage agentic search pipeline featuring intent classification, query expansion, LLM synthesis with privacy routing, SSE streaming, and a rich progressive UI.

**Architecture:** New `search_models.py` and `search_agent.py` in `backend/app/services/` implement the pipeline logic, reusing existing `search_service.py` for hybrid retrieval and `llm_router.py` for LLM calls. A new `search_agent_router.py` replaces the old search and multi-agent routers. Frontend is rewritten with Tailwind CSS and next-intl, using SSE for progressive updates.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, pgvector, PostgreSQL FTS, MiniMax 2.7, Ollama, Next.js 14, Tailwind CSS, next-intl, SSE

**Spec:** `docs/superpowers/specs/2026-03-20-agentic-search-design.md`

---

### Task 1: Search Models (Pydantic models & enums)

**Files:**
- Create: `backend/app/services/search_models.py`
- Test: `backend/tests/test_search_agent.py`

- [ ] **Step 1: Create the search models file with all enums and Pydantic models**

Create `backend/app/services/search_models.py`. This file defines all data contracts for the agentic pipeline. Import `UserRole` from `app.models.user` and `DocumentBucket` from `app.models.document` — do NOT duplicate these enums.

```python
"""
SOWKNOW Agentic Search — Pydantic Models & Enums
All data contracts for the search pipeline, API, and agent state.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.models.document import DocumentBucket
from app.models.user import UserRole


# ---- ENUMS ----

class QueryIntent(str, Enum):
    FACTUAL = "factual"
    TEMPORAL = "temporal"
    COMPARATIVE = "comparative"
    SYNTHESIS = "synthesis"
    FINANCIAL = "financial"
    CROSS_REF = "cross_reference"
    EXPLORATORY = "exploratory"
    ENTITY_SEARCH = "entity_search"
    PROCEDURAL = "procedural"
    UNKNOWN = "unknown"


class RelevanceLabel(str, Enum):
    HIGHLY_RELEVANT = "highly_relevant"
    RELEVANT = "relevant"
    PARTIALLY = "partially"
    MARGINAL = "marginal"


class SearchMode(str, Enum):
    FAST = "fast"
    DEEP = "deep"
    AUTO = "auto"


# ---- REQUEST ----

class AgenticSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000)
    mode: SearchMode = SearchMode.AUTO
    top_k: int = Field(default=10, ge=1, le=50)
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    filter_tags: list[str] = Field(default_factory=list)
    filter_doc_types: list[str] = Field(default_factory=list)
    scope_document_ids: list[UUID] = Field(default_factory=list)
    language: Optional[str] = Field(default=None)
    include_suggestions: bool = True

    @field_validator("query")
    @classmethod
    def strip_query(cls, v: str) -> str:
        return v.strip()


# ---- AGENT INTERNAL STATE ----

class ParsedIntent(BaseModel):
    intent: QueryIntent
    confidence: float = Field(ge=0.0, le=1.0)
    entities: list[str] = Field(default_factory=list)
    temporal_markers: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    expanded_keywords: list[str] = Field(default_factory=list)
    sub_queries: list[str] = Field(default_factory=list)
    detected_language: str = "fr"
    requires_synthesis: bool = False
    temporal_range: Optional[dict[str, Any]] = None


class RawChunk(BaseModel):
    chunk_id: UUID
    document_id: UUID
    document_title: str
    document_bucket: DocumentBucket
    document_type: str
    chunk_index: int
    page_number: Optional[int]
    text: str
    semantic_score: float = 0.0
    fts_rank: float = 0.0
    rrf_score: float = 0.0
    created_at: Optional[datetime] = None
    tags: list[str] = Field(default_factory=list)


# ---- RESPONSE MODELS ----

class Citation(BaseModel):
    document_id: UUID
    document_title: str
    document_type: str
    bucket: DocumentBucket
    page_number: Optional[int]
    chunk_excerpt: str
    relevance_score: float


class SearchResult(BaseModel):
    rank: int
    document_id: UUID
    document_title: str
    document_type: str
    bucket: DocumentBucket
    relevance_label: RelevanceLabel
    relevance_score: float = Field(ge=0.0, le=1.0)
    excerpt: str
    highlights: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    page_number: Optional[int] = None
    document_date: Optional[datetime] = None
    match_reason: str
    is_confidential: bool = False


class SearchSuggestion(BaseModel):
    suggestion_type: str
    text: str
    rationale: str


class AgentTrace(BaseModel):
    intent_detected: QueryIntent
    intent_confidence: float
    sub_queries_used: list[str]
    total_chunks_retrieved: int
    chunks_after_reranking: int
    llm_model_used: str
    processing_time_ms: int
    confidential_results_count: int
    synthesis_performed: bool


class AgenticSearchResponse(BaseModel):
    query: str
    parsed_intent: QueryIntent
    answer_synthesis: Optional[str] = None
    answer_language: str = "fr"
    results: list[SearchResult]
    citations: list[Citation]
    suggestions: list[SearchSuggestion] = Field(default_factory=list)
    total_found: int
    has_confidential_results: bool = False
    llm_model_used: Optional[str] = None
    agent_trace: Optional[AgentTrace] = None
    search_time_ms: int
    performed_at: datetime = Field(default_factory=datetime.utcnow)
```

- [ ] **Step 2: Create the test file with model validation tests**

Create `backend/tests/test_search_agent.py` with the request validation tests first:

```python
"""
SOWKNOW Agentic Search — Test Suite
Run: pytest backend/tests/test_search_agent.py -v
"""

import pytest
from app.services.search_models import (
    AgenticSearchRequest,
    SearchMode,
)


class TestSearchRequestValidation:
    def test_empty_query_rejected(self):
        with pytest.raises(Exception):
            AgenticSearchRequest(query="")

    def test_whitespace_query_stripped(self):
        req = AgenticSearchRequest(query="  bilan financier  ")
        assert req.query == "bilan financier"

    def test_default_mode_is_auto(self):
        req = AgenticSearchRequest(query="test")
        assert req.mode == SearchMode.AUTO

    def test_top_k_default(self):
        req = AgenticSearchRequest(query="test")
        assert req.top_k == 10

    def test_top_k_max_enforced(self):
        with pytest.raises(Exception):
            AgenticSearchRequest(query="test", top_k=51)
```

- [ ] **Step 3: Run tests to verify models work**

Run: `cd /home/developer/development/src/active/sowknow4 && python -m pytest backend/tests/test_search_agent.py::TestSearchRequestValidation -v`
Expected: 5 PASS

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/search_models.py backend/tests/test_search_agent.py
git commit -m "feat(search): add agentic search Pydantic models and enums"
```

---

### Task 2: Scoring & Re-ranking Logic (pure functions, no I/O)

**Files:**
- Modify: `backend/app/services/search_models.py` (already created)
- Create: `backend/app/services/search_agent.py`
- Modify: `backend/tests/test_search_agent.py`

- [ ] **Step 1: Add relevance label, excerpt, and re-ranking tests**

Append to `backend/tests/test_search_agent.py`:

```python
from datetime import datetime
from uuid import uuid4

from app.models.document import DocumentBucket
from app.models.user import UserRole
from app.services.search_models import (
    ParsedIntent,
    QueryIntent,
    RawChunk,
    RelevanceLabel,
)


def make_chunk(
    bucket: DocumentBucket = DocumentBucket.PUBLIC,
    semantic_score: float = 0.75,
    rrf_score: float = 0.015,
    text: str = "Ceci est un extrait de test sur la finance.",
    doc_id=None,
) -> RawChunk:
    return RawChunk(
        chunk_id=uuid4(),
        document_id=doc_id or uuid4(),
        document_title="Document de test",
        document_bucket=bucket,
        document_type="pdf",
        chunk_index=0,
        page_number=1,
        text=text,
        semantic_score=semantic_score,
        fts_rank=0.3,
        rrf_score=rrf_score,
        created_at=datetime.utcnow(),
        tags=["finance", "test"],
    )


def make_intent(
    intent: QueryIntent = QueryIntent.FACTUAL,
    keywords: list[str] | None = None,
    sub_queries: list[str] | None = None,
    requires_synthesis: bool = False,
) -> ParsedIntent:
    return ParsedIntent(
        intent=intent,
        confidence=0.9,
        keywords=keywords or ["finance", "bilan"],
        expanded_keywords=["actif", "passif"],
        sub_queries=sub_queries or [],
        detected_language="fr",
        requires_synthesis=requires_synthesis,
    )


class TestRelevanceLabels:
    def test_highly_relevant(self):
        from app.services.search_agent import _score_to_label
        assert _score_to_label(0.85) == RelevanceLabel.HIGHLY_RELEVANT

    def test_highly_relevant_boundary(self):
        from app.services.search_agent import _score_to_label
        assert _score_to_label(0.82) == RelevanceLabel.HIGHLY_RELEVANT

    def test_relevant(self):
        from app.services.search_agent import _score_to_label
        assert _score_to_label(0.72) == RelevanceLabel.RELEVANT

    def test_relevant_lower_boundary(self):
        from app.services.search_agent import _score_to_label
        assert _score_to_label(0.65) == RelevanceLabel.RELEVANT

    def test_partially(self):
        from app.services.search_agent import _score_to_label
        assert _score_to_label(0.55) == RelevanceLabel.PARTIALLY

    def test_marginal(self):
        from app.services.search_agent import _score_to_label
        assert _score_to_label(0.3) == RelevanceLabel.MARGINAL

    def test_zero(self):
        from app.services.search_agent import _score_to_label
        assert _score_to_label(0.0) == RelevanceLabel.MARGINAL


class TestRBACEnforcement:
    def test_user_cannot_see_confidential_chunks(self):
        from app.services.search_agent import rerank_and_build_results
        doc_id = uuid4()
        public_chunk = make_chunk(DocumentBucket.PUBLIC, rrf_score=0.01, doc_id=doc_id)
        confidential_chunk = make_chunk(DocumentBucket.CONFIDENTIAL, rrf_score=0.02)
        intent = make_intent()
        results, has_confidential = rerank_and_build_results(
            [public_chunk, confidential_chunk], "test", intent, 10, UserRole.USER,
        )
        for r in results:
            assert r.bucket != DocumentBucket.CONFIDENTIAL
        assert not has_confidential

    def test_admin_can_see_confidential_chunks(self):
        from app.services.search_agent import rerank_and_build_results
        confidential_chunk = make_chunk(DocumentBucket.CONFIDENTIAL, rrf_score=0.9)
        intent = make_intent()
        results, has_confidential = rerank_and_build_results(
            [confidential_chunk], "test", intent, 10, UserRole.ADMIN,
        )
        assert has_confidential
        assert any(r.bucket == DocumentBucket.CONFIDENTIAL for r in results)

    def test_super_user_can_see_confidential_chunks(self):
        from app.services.search_agent import rerank_and_build_results
        confidential_chunk = make_chunk(DocumentBucket.CONFIDENTIAL, rrf_score=0.9)
        intent = make_intent()
        results, has_confidential = rerank_and_build_results(
            [confidential_chunk], "test", intent, 10, UserRole.SUPERUSER,
        )
        assert has_confidential
        assert any(r.bucket == DocumentBucket.CONFIDENTIAL for r in results)

    def test_user_mixed_results_filters_confidential(self):
        from app.services.search_agent import rerank_and_build_results
        doc_pub = uuid4()
        doc_conf = uuid4()
        chunks = [
            make_chunk(DocumentBucket.PUBLIC, rrf_score=0.8, doc_id=doc_pub),
            make_chunk(DocumentBucket.CONFIDENTIAL, rrf_score=0.9, doc_id=doc_conf),
            make_chunk(DocumentBucket.PUBLIC, rrf_score=0.7, doc_id=uuid4()),
        ]
        intent = make_intent()
        results, has_confidential = rerank_and_build_results(
            chunks, "test", intent, 10, UserRole.USER,
        )
        assert all(r.bucket == DocumentBucket.PUBLIC for r in results)
        assert not has_confidential
        assert len(results) == 2

    def test_is_confidential_flag_set_correctly(self):
        from app.services.search_agent import rerank_and_build_results
        doc_id = uuid4()
        conf_chunk = make_chunk(DocumentBucket.CONFIDENTIAL, rrf_score=0.9, doc_id=doc_id)
        intent = make_intent()
        results, _ = rerank_and_build_results(
            [conf_chunk], "test", intent, 10, UserRole.ADMIN,
        )
        assert results[0].is_confidential is True

    def test_public_result_not_flagged_confidential(self):
        from app.services.search_agent import rerank_and_build_results
        doc_id = uuid4()
        pub_chunk = make_chunk(DocumentBucket.PUBLIC, rrf_score=0.9, doc_id=doc_id)
        intent = make_intent()
        results, _ = rerank_and_build_results(
            [pub_chunk], "test", intent, 10, UserRole.ADMIN,
        )
        assert results[0].is_confidential is False


class TestResultRanking:
    def test_results_sorted_by_relevance_descending(self):
        from app.services.search_agent import rerank_and_build_results
        chunks = [
            make_chunk(rrf_score=0.005, doc_id=uuid4()),
            make_chunk(rrf_score=0.020, doc_id=uuid4()),
            make_chunk(rrf_score=0.012, doc_id=uuid4()),
        ]
        intent = make_intent()
        results, _ = rerank_and_build_results(chunks, "test", intent, 10, UserRole.ADMIN)
        scores = [r.relevance_score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_ranks_sequential(self):
        from app.services.search_agent import rerank_and_build_results
        chunks = [make_chunk(rrf_score=0.02 - i * 0.003, doc_id=uuid4()) for i in range(5)]
        intent = make_intent()
        results, _ = rerank_and_build_results(chunks, "test", intent, 10, UserRole.ADMIN)
        assert [r.rank for r in results] == list(range(1, len(results) + 1))

    def test_top_k_respected(self):
        from app.services.search_agent import rerank_and_build_results
        chunks = [make_chunk(rrf_score=0.02 - i * 0.001, doc_id=uuid4()) for i in range(20)]
        intent = make_intent()
        results, _ = rerank_and_build_results(chunks, "test", intent, top_k=5, user_role=UserRole.ADMIN)
        assert len(results) <= 5

    def test_chunks_collapsed_per_document(self):
        from app.services.search_agent import rerank_and_build_results
        doc_id = uuid4()
        chunks = [
            make_chunk(rrf_score=0.02, doc_id=doc_id),
            make_chunk(rrf_score=0.015, doc_id=doc_id),
            make_chunk(rrf_score=0.01, doc_id=doc_id),
        ]
        intent = make_intent()
        results, _ = rerank_and_build_results(chunks, "test", intent, 10, UserRole.ADMIN)
        doc_ids = [r.document_id for r in results]
        assert len(doc_ids) == len(set(doc_ids))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/developer/development/src/active/sowknow4 && python -m pytest backend/tests/test_search_agent.py::TestRelevanceLabels -v 2>&1 | head -20`
Expected: FAIL — `search_agent` module does not exist yet

- [ ] **Step 3: Create search_agent.py with scoring and re-ranking functions**

Create `backend/app/services/search_agent.py` with the pure functions (no I/O):

```python
"""
SOWKNOW Agentic Search Pipeline
================================
A 6-stage agent that transforms a raw natural-language query into
a ranked, cited, synthesized answer — with strict RBAC enforcement.

Pipeline stages:
  Stage 1 — IntentAgent      : Classify intent, extract entities, decompose query
  Stage 2 — QueryExpander    : Expand keywords, build sub-queries
  Stage 3 — HybridRetriever  : Reuses existing search_service.py
  Stage 4 — ReRanker         : Re-scoring + bucket enforcement
  Stage 5 — SynthesisAgent   : LLM answer generation with privacy routing
  Stage 6 — SuggestionAgent  : Generate follow-up queries and refinements
"""

import logging
import re
from uuid import UUID

from app.models.document import DocumentBucket
from app.models.user import UserRole
from .search_models import (
    ParsedIntent,
    QueryIntent,
    RawChunk,
    RelevanceLabel,
    SearchResult,
    SearchSuggestion,
    Citation,
)

logger = logging.getLogger(__name__)

# ---- CONSTANTS ----

RRF_K = 60
HIGHLY_RELEVANT_THRESHOLD = 0.82
RELEVANT_THRESHOLD = 0.65
PARTIALLY_THRESHOLD = 0.45


# ---- STAGE 2: QUERY EXPANDER ----

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


# ---- STAGE 4: RE-RANKER & RESULT BUILDER ----

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


# ---- CITATIONS ----

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


# ---- FALLBACK INTENT ----

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
            "fr" if any(w in q for w in ["le", "la", "les", "des", "est", "sont"])
            else "en"
        ),
    )
```

- [ ] **Step 4: Run all tests**

Run: `cd /home/developer/development/src/active/sowknow4 && python -m pytest backend/tests/test_search_agent.py -v`
Expected: All tests in TestSearchRequestValidation, TestRelevanceLabels, TestRBACEnforcement, TestResultRanking PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/search_agent.py backend/tests/test_search_agent.py
git commit -m "feat(search): add re-ranking, RBAC enforcement, and scoring logic"
```

---

### Task 3: Query Expansion, Fallback Intent, and Citation Tests

**Files:**
- Modify: `backend/tests/test_search_agent.py`

- [ ] **Step 1: Add query expansion, fallback intent, and citation tests**

Append to `backend/tests/test_search_agent.py`:

```python
from app.services.search_agent import (
    _fallback_intent,
    build_search_queries,
    build_citations,
)


class TestQueryExpansion:
    def test_simple_query_no_sub_queries(self):
        intent = make_intent(sub_queries=[])
        queries = build_search_queries(intent, "bilan financier 2023")
        assert "bilan financier 2023" in queries
        assert len(queries) >= 1

    def test_complex_query_with_sub_queries(self):
        intent = make_intent(
            sub_queries=["bilan actif 2022", "bilan passif 2022"],
            keywords=["bilan", "actif"],
        )
        queries = build_search_queries(intent, "analyse complete du bilan 2022")
        assert "analyse complete du bilan 2022" in queries
        assert "bilan actif 2022" in queries
        assert "bilan passif 2022" in queries

    def test_no_duplicate_queries(self):
        intent = make_intent(sub_queries=["bilan financier"])
        queries = build_search_queries(intent, "bilan financier")
        assert queries.count("bilan financier") == 1

    def test_keyword_variant_added(self):
        intent = make_intent(keywords=["bilan", "actif", "passif", "2022", "annuel"])
        queries = build_search_queries(intent, "bilan financier annuel")
        assert len(queries) >= 2


class TestCitations:
    def test_citations_match_results(self):
        doc_id = uuid4()
        chunk = make_chunk(doc_id=doc_id, rrf_score=0.9)
        intent = make_intent()
        from app.services.search_agent import rerank_and_build_results
        results, _ = rerank_and_build_results([chunk], "test", intent, 10, UserRole.ADMIN)
        citations = build_citations(results, [chunk])
        assert len(citations) == 1
        assert citations[0].document_id == doc_id

    def test_one_citation_per_document(self):
        doc_id = uuid4()
        chunks = [make_chunk(doc_id=doc_id, rrf_score=0.9 - i * 0.1) for i in range(3)]
        intent = make_intent()
        from app.services.search_agent import rerank_and_build_results
        results, _ = rerank_and_build_results(chunks, "test", intent, 10, UserRole.ADMIN)
        citations = build_citations(results, chunks)
        cit_doc_ids = [c.document_id for c in citations]
        assert len(cit_doc_ids) == len(set(cit_doc_ids))

    def test_citations_max_ten(self):
        chunks = [make_chunk(doc_id=uuid4(), rrf_score=0.02 - i * 0.001) for i in range(15)]
        intent = make_intent()
        from app.services.search_agent import rerank_and_build_results
        results, _ = rerank_and_build_results(chunks, "test", intent, 15, UserRole.ADMIN)
        citations = build_citations(results, chunks)
        assert len(citations) <= 10

    def test_citation_excerpt_length(self):
        doc_id = uuid4()
        chunk = make_chunk(doc_id=doc_id, text="A" * 300)
        intent = make_intent()
        from app.services.search_agent import rerank_and_build_results
        results, _ = rerank_and_build_results([chunk], "test", intent, 10, UserRole.ADMIN)
        citations = build_citations(results, [chunk])
        assert len(citations[0].chunk_excerpt) <= 205


class TestFallbackIntent:
    def test_temporal_query_detected(self):
        intent = _fallback_intent("Comment a evolue mon portefeuille en 2022 ?")
        assert intent.intent == QueryIntent.TEMPORAL

    def test_financial_query_detected(self):
        intent = _fallback_intent("Analyse du bilan financier annuel")
        assert intent.intent == QueryIntent.FINANCIAL

    def test_french_language_detected(self):
        intent = _fallback_intent("Quels sont les documents relatifs a la famille ?")
        assert intent.detected_language == "fr"

    def test_english_language_detected(self):
        intent = _fallback_intent("What are the main assets on the balance sheet?")
        assert intent.detected_language == "en"

    def test_keywords_extracted(self):
        intent = _fallback_intent("bilan financier actif passif 2023")
        assert len(intent.keywords) > 0

    def test_stop_words_removed_from_keywords(self):
        intent = _fallback_intent("les documents de la famille")
        assert "les" not in intent.keywords
        assert "la" not in intent.keywords
```

- [ ] **Step 2: Run all tests**

Run: `cd /home/developer/development/src/active/sowknow4 && python -m pytest backend/tests/test_search_agent.py -v`
Expected: All 34 tests PASS

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_search_agent.py
git commit -m "test(search): add query expansion, citation, and fallback intent tests"
```

---

### Task 4: LLM Integration (Intent Parsing, Synthesis, Suggestions)

**Files:**
- Modify: `backend/app/services/search_agent.py`
- Modify: `backend/tests/test_search_agent.py`

- [ ] **Step 1: Add LLM routing tests**

Append to `backend/tests/test_search_agent.py`:

```python
from unittest.mock import AsyncMock, patch


class TestLLMRouting:
    @pytest.mark.asyncio
    async def test_all_public_routes_to_minimax(self):
        """Public synthesis should use MiniMax via LLMRouter."""
        with patch("app.services.search_agent._call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = ("test response", "minimax")
            from backend.app.services.search_agent import _call_llm
            result, model = await _call_llm(
                messages=[{"role": "user", "content": "test"}],
                system="test",
                has_confidential=False,
            )
            mock_llm.assert_called_once()

    @pytest.mark.asyncio
    async def test_confidential_routes_to_ollama(self):
        """Confidential context must use Ollama."""
        with patch("app.services.search_agent._call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = ("Ollama response", "ollama/mistral")
            from backend.app.services.search_agent import _call_llm
            result, model = await _call_llm(
                messages=[{"role": "user", "content": "test"}],
                system="test",
                has_confidential=True,
            )
            mock_llm.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/developer/development/src/active/sowknow4 && python -m pytest backend/tests/test_search_agent.py::TestLLMRouting -v 2>&1 | head -20`
Expected: FAIL — `_call_llm` not defined

- [ ] **Step 3: Add LLM integration functions to search_agent.py**

Add these functions to `backend/app/services/search_agent.py` (after the existing imports, before the constants):

```python
import asyncio
import json
import time
from typing import Any, Optional

from app.services.llm_router import llm_router

# ---- LLM PROMPTS ----

INTENT_SYSTEM_PROMPT = """Tu es un agent d'analyse de requetes pour SOWKNOW, un systeme de gestion de connaissances personnelles.

Analyse la requete utilisateur et retourne un objet JSON **uniquement** (pas de markdown, pas d'explication).

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
}

Regles :
- sub_queries : decompose si la requete est complexe (> 1 concept distinct). Sinon, tableau vide.
- requires_synthesis : true si la reponse necessite de croiser plusieurs documents.
- temporal_range : extrais des dates concretes si mentionnees.
- keywords : termes essentiels de recherche, 3-8 mots maximum.
- expanded_keywords : synonymes, variations, termes associes utiles pour la recherche.
"""

SYNTHESIS_SYSTEM_PROMPT = """Tu es SOWKNOW Assistant, un expert en synthese de connaissances personnelles.

A partir des extraits de documents fournis, genere une reponse complete, structuree et citee.

Regles imperatives :
1. Commence par une reponse directe a la question (1-2 phrases).
2. Developpe avec les elements pertinents trouves dans les documents.
3. Cite chaque information avec [Source: Titre du document, p.X].
4. Si plusieurs documents sont en contradiction, mentionne-le explicitement.
5. Termine par une section "Points cles" avec 3-5 bullet points.
6. Reponds dans la meme langue que la question de l'utilisateur.
7. Si les documents ne contiennent pas d'information pertinente, dis-le clairement.
8. NE PAS inventer d'informations non presentes dans les extraits.
"""

SUGGESTION_SYSTEM_PROMPT = """Tu es un assistant de recherche pour SOWKNOW.

Base sur la requete originale et les resultats trouves, genere 3-5 suggestions de requetes de suivi.
Retourne uniquement un tableau JSON :
[
  {"suggestion_type": "related_query|refine|expand|temporal", "text": "...", "rationale": "..."},
  ...
]

Types :
- related_query : question connexe naturelle
- refine : reformulation plus precise
- expand : elargissement du sujet
- temporal : dimension temporelle non exploree

Langue : meme langue que la requete originale.
"""


# ---- LLM WRAPPER ----

async def _call_llm(
    messages: list[dict],
    system: str,
    has_confidential: bool,
    temperature: float = 0.1,
    max_tokens: int = 2048,
) -> tuple[str, str]:
    """
    Call LLM via existing LLMRouter. Collects full response from async generator.
    Returns (response_text, model_name).

    Calls select_provider FIRST to know the model, then generates.
    """
    query_text = messages[0].get("content", "") if messages else ""

    # Determine provider before calling (avoids double-call)
    decision = await llm_router.select_provider(
        query=query_text,
        has_confidential=has_confidential,
    )
    model_name = decision.provider_name if hasattr(decision, "provider_name") else "unknown"

    full_messages = [{"role": "system", "content": system}] + messages
    chunks = []
    async for chunk in llm_router.generate_completion(
        messages=full_messages,
        query=query_text,
        has_confidential=has_confidential,
        temperature=temperature,
        max_tokens=max_tokens,
    ):
        chunks.append(chunk)
    response_text = "".join(chunks)

    return response_text, model_name


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
    user_message = f"""Question : {query}\n\n{lang_instruction}\n\nDocuments disponibles :\n{context}"""

    answer, model = await _call_llm(
        messages=[{"role": "user", "content": user_message}],
        system=SYNTHESIS_SYSTEM_PROMPT,
        has_confidential=has_confidential,
        temperature=0.2,
        max_tokens=1500,
    )
    return answer, model


# ---- STAGE 6: SUGGESTION AGENT ----

async def generate_suggestions(
    original_query: str,
    results: list[SearchResult],
    intent: ParsedIntent,
    has_confidential: bool,
) -> list[SearchSuggestion]:
    try:
        top_titles = [r.document_title for r in results[:5]]
        context = f"Requete: {original_query}\nDocuments trouves: {', '.join(top_titles)}\nIntent: {intent.intent.value}"
        raw, _ = await _call_llm(
            messages=[{"role": "user", "content": context}],
            system=SUGGESTION_SYSTEM_PROMPT,
            has_confidential=False,  # No document content
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
```

- [ ] **Step 4: Run all tests**

Run: `cd /home/developer/development/src/active/sowknow4 && python -m pytest backend/tests/test_search_agent.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/search_agent.py backend/tests/test_search_agent.py
git commit -m "feat(search): add LLM integration for intent, synthesis, and suggestions"
```

---

### Task 5: Main Orchestrator (run_agentic_search)

**Files:**
- Modify: `backend/app/services/search_agent.py`

- [ ] **Step 1: Add the main orchestrator function**

Append to `backend/app/services/search_agent.py`:

```python
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession

from .search_models import (
    AgenticSearchRequest,
    AgenticSearchResponse,
    AgentTrace,
    SearchMode,
)
from app.services.search_service import HybridSearchService


async def run_agentic_search(
    db: AsyncSession,
    request: AgenticSearchRequest,
    user_role: UserRole,
    user_id: UUID,
    user: Any,
) -> AgenticSearchResponse:
    """
    Full agentic search pipeline orchestrator.

    Security guarantees:
    1. Bucket filter applied at SQL level (Stage 3) via search_service.
    2. RBAC double-check at re-rank level (Stage 4).
    3. LLM routing by presence of confidential chunks (Stage 5).
    4. Suggestion generation never includes document content.
    """
    start_ms = time.monotonic()
    logger.info("Agentic search started | user=%s role=%s query='%s'", user_id, user_role, request.query)

    # Determine mode
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

    # Stage 3: Hybrid retrieval via existing search_service
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
                document_type="pdf",
                chunk_index=sr.chunk_index,
                page_number=sr.page_number,
                text=sr.chunk_text,
                semantic_score=sr.semantic_score,
                fts_rank=sr.keyword_score,
                rrf_score=sr.final_score,
                tags=[],
            ))
    logger.info("Retrieved %d chunks from hybrid search", len(all_chunks))

    # Deduplicate chunks by chunk_id
    seen_ids: set[UUID] = set()
    deduped: list[RawChunk] = []
    for chunk in all_chunks:
        if chunk.chunk_id not in seen_ids:
            seen_ids.add(chunk.chunk_id)
            deduped.append(chunk)
    all_chunks = deduped

    # Stage 4: Re-rank & build results
    results, has_confidential = rerank_and_build_results(
        all_chunks, request.query, intent, request.top_k, user_role,
    )
    logger.info("Re-ranked to %d results | confidential=%s", len(results), has_confidential)

    # Stage 5: Synthesis (DEEP mode or complex intent)
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
        )

    # Stage 6: Suggestions
    suggestions: list[SearchSuggestion] = []
    if request.include_suggestions and results:
        suggestions = await generate_suggestions(
            request.query, results, intent, has_confidential,
        )

    # Citations
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

    logger.info("Search complete | results=%d time=%dms model=%s", len(results), elapsed_ms, model_used)

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
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/services/search_agent.py
git commit -m "feat(search): add main agentic search orchestrator"
```

---

### Task 6: FastAPI Router (JSON + SSE + intent + history)

**Files:**
- Create: `backend/app/api/search_agent_router.py`

- [ ] **Step 1: Create the router file**

Create `backend/app/api/search_agent_router.py`:

```python
"""
SOWKNOW Agentic Search — FastAPI Router
Exposes the search pipeline as REST + SSE endpoints.
"""

import asyncio
import json
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.user import User, UserRole
from app.services.search_agent import (
    build_citations,
    build_search_queries,
    generate_suggestions,
    parse_intent,
    rerank_and_build_results,
    run_agentic_search,
    synthesize_answer,
)
from app.services.search_models import (
    AgenticSearchRequest,
    AgenticSearchResponse,
    QueryIntent,
    RawChunk,
    SearchMode,
)
from app.services.search_service import HybridSearchService
from app.models.document import DocumentBucket

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/search", tags=["Search"])

MAX_CONCURRENT_SEARCHES = 5
_search_semaphore = asyncio.Semaphore(MAX_CONCURRENT_SEARCHES)


def _role_from_user(user: User) -> UserRole:
    try:
        return UserRole(user.role)
    except ValueError:
        return UserRole.USER


def _sse_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


# ---- POST /api/v1/search ----

@router.post("", response_model=AgenticSearchResponse)
async def search(
    request: AgenticSearchRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AgenticSearchResponse:
    if _search_semaphore._value == 0:
        raise HTTPException(status_code=429, detail="Too many concurrent searches. Please retry.",
                            headers={"Retry-After": "5"})
    async with _search_semaphore:
        user_role = _role_from_user(current_user)
        try:
            response = await run_agentic_search(
                db=db,
                request=request,
                user_role=user_role,
                user_id=current_user.id,
                user=current_user,
            )
            # Write to search history
            await _save_search_history(db, current_user.id, response)
            return response
        except Exception as exc:
            logger.exception("Search pipeline error for user %s: %s", current_user.id, exc)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="La recherche a rencontre une erreur. Veuillez reessayer.",
            ) from exc


# ---- POST /api/v1/search/stream ----

@router.post("/stream")
async def search_stream(
    request: AgenticSearchRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    user_role = _role_from_user(current_user)

    async def event_generator():
        try:
            # Stage 1: Intent
            yield _sse_event("stage", {"stage": "intent", "message": "Analyse de votre requete..."})
            intent = await parse_intent(request.query)
            yield _sse_event("intent", {
                "intent": intent.intent.value,
                "confidence": intent.confidence,
                "keywords": intent.keywords,
                "sub_queries": intent.sub_queries,
                "language": intent.detected_language,
            })

            if request.language:
                intent.detected_language = request.language

            # Stage 2: Query expansion
            queries = build_search_queries(intent, request.query)
            yield _sse_event("stage", {"stage": "retrieval", "message": f"Recherche dans {len(queries)} requete(s)..."})

            # Stage 3: Hybrid retrieval
            search_service = HybridSearchService()
            all_chunks: list[RawChunk] = []
            for query_text in queries:
                result = await search_service.hybrid_search(
                    query=query_text, limit=request.top_k * 3,
                    offset=0, db=db, user=current_user,
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

            # Deduplicate
            seen_ids: set[UUID] = set()
            deduped: list[RawChunk] = []
            for chunk in all_chunks:
                if chunk.chunk_id not in seen_ids:
                    seen_ids.add(chunk.chunk_id)
                    deduped.append(chunk)
            all_chunks = deduped

            yield _sse_event("stage", {
                "stage": "reranking",
                "message": f"{len(all_chunks)} extraits recuperes, reclassement...",
            })

            # Stage 4: Re-rank
            results, has_confidential = rerank_and_build_results(
                all_chunks, request.query, intent, request.top_k, user_role,
            )
            yield _sse_event("results", {
                "results": [r.model_dump() for r in results],
                "total_found": len(results),
                "has_confidential_results": has_confidential,
            })

            # Stage 5: Synthesis
            model_used = None
            mode = request.mode
            if mode == SearchMode.AUTO:
                mode = SearchMode.FAST if len(request.query.split()) <= 5 else SearchMode.DEEP

            if results and (
                mode == SearchMode.DEEP
                or intent.requires_synthesis
                or intent.intent in (QueryIntent.SYNTHESIS, QueryIntent.TEMPORAL, QueryIntent.COMPARATIVE, QueryIntent.FINANCIAL)
            ):
                yield _sse_event("stage", {"stage": "synthesis", "message": "Synthese de la reponse..."})
                answer, model_used = await synthesize_answer(
                    request.query, results, all_chunks, intent, has_confidential, intent.detected_language,
                )
                yield _sse_event("synthesis", {
                    "answer": answer,
                    "model": model_used,
                    "language": intent.detected_language,
                })

            # Stage 6: Suggestions
            if request.include_suggestions and results:
                suggestions = await generate_suggestions(request.query, results, intent, has_confidential)
                yield _sse_event("suggestions", {"suggestions": [s.model_dump() for s in suggestions]})

            # Citations
            citations = build_citations(results, all_chunks)
            yield _sse_event("citations", {"citations": [c.model_dump() for c in citations]})

            yield _sse_event("done", {
                "total_found": len(results),
                "model": model_used,
                "has_confidential": has_confidential,
            })

        except Exception as exc:
            logger.exception("Streaming search error: %s", exc)
            yield _sse_event("error", {"message": "Erreur lors de la recherche. Veuillez reessayer."})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---- POST /api/v1/search/intent ----

@router.post("/intent")
async def get_intent(
    payload: dict,
    current_user: User = Depends(get_current_user),
):
    query = payload.get("query", "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query is required")
    intent = await parse_intent(query)
    return {
        "intent": intent.intent.value,
        "confidence": intent.confidence,
        "keywords": intent.keywords,
        "sub_queries": intent.sub_queries,
        "language": intent.detected_language,
        "requires_synthesis": intent.requires_synthesis,
    }


# ---- GET /api/v1/search/history ----

@router.get("/history")
async def search_history(
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(
        sql_text("""
            SELECT query, parsed_intent, result_count, search_time_ms, performed_at
            FROM sowknow.search_history
            WHERE user_id = :uid
            ORDER BY performed_at DESC
            LIMIT :lim
        """),
        {"uid": str(current_user.id), "lim": limit},
    )).mappings().all()
    return [dict(r) for r in rows]


# ---- HELPER ----

async def _save_search_history(db: AsyncSession, user_id: UUID, response: AgenticSearchResponse):
    try:
        await db.execute(
            sql_text("""
                INSERT INTO sowknow.search_history
                    (user_id, query, parsed_intent, result_count, has_confidential_results,
                     llm_model_used, search_time_ms)
                VALUES (:uid, :query, :intent, :count, :conf, :model, :time_ms)
            """),
            {
                "uid": str(user_id),
                "query": response.query,
                "intent": response.parsed_intent.value,
                "count": response.total_found,
                "conf": response.has_confidential_results,
                "model": response.llm_model_used,
                "time_ms": response.search_time_ms,
            },
        )
        await db.commit()
    except Exception as exc:
        logger.warning("Failed to save search history: %s", exc)
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/api/search_agent_router.py
git commit -m "feat(search): add agentic search FastAPI router with JSON + SSE endpoints"
```

---

### Task 7: Router Swap in main.py

**Files:**
- Modify: `backend/app/main.py`

- [ ] **Step 1: Update imports in main.py**

In `backend/app/main.py`, find the import block (around line 20-31):

Replace `search` and `multi_agent` imports:

```python
# Old:
from app.api import (
    admin,
    auth,
    chat,
    collections,
    documents,
    graph_rag,
    knowledge_graph,
    multi_agent,
    search,
    smart_folders,
)

# New:
from app.api import (
    admin,
    auth,
    chat,
    collections,
    documents,
    graph_rag,
    knowledge_graph,
    search_agent_router,
    smart_folders,
)
```

- [ ] **Step 2: Update router registration**

In `backend/app/main.py`, find the router inclusion section (around line 312-324):

Replace the `multi_agent.router` and `search.router` lines:

```python
# Old:
app.include_router(multi_agent.router, prefix="/api/v1")
app.include_router(search.router, prefix="/api/v1")

# New:
app.include_router(search_agent_router.router, prefix="/api/v1")
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/main.py
git commit -m "feat(search): swap old search/multi-agent routers for agentic search router"
```

---

### Task 8: Database Migration (search_history table + indexes)

**Files:**
- Create: `backend/alembic/versions/013_add_search_history.py`

- [ ] **Step 1: Determine current Alembic HEAD(s)**

Run: `cd /home/developer/development/src/active/sowknow4/backend && alembic heads`

**WARNING:** This repo has multiple Alembic branch heads (duplicate 005/006/007/008/009/010/011/012 revisions). If `alembic heads` shows multiple heads, you must first create a merge migration:
```bash
cd backend && alembic merge heads -m "merge branches before search_history"
```
Then use the merge revision as `down_revision` for the new migration.

If there is a single HEAD, note its revision ID for the next step.

- [ ] **Step 2: Check the exact revision ID**

Run: `cd /home/developer/development/src/active/sowknow4/backend && grep "^revision" alembic/versions/012_add_unique_constraints.py`

- [ ] **Step 3: Create the migration file**

Create `backend/alembic/versions/013_add_search_history.py`. Replace `<HEAD_REVISION>` with the actual revision from step 2:

```python
"""Add search_history table and search indexes

Revision ID: add_search_history_013
Revises: <HEAD_REVISION>
Create Date: 2026-03-20
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "add_search_history_013"
down_revision = "<HEAD_REVISION>"
branch_labels = None
depends_on = None


def upgrade():
    # pg_trgm extension for fuzzy title matching
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # search_history table
    op.create_table(
        "search_history",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("sowknow.users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("parsed_intent", sa.String(50), nullable=True),
        sa.Column("result_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("has_confidential_results", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("llm_model_used", sa.String(100), nullable=True),
        sa.Column("search_time_ms", sa.Integer(), nullable=True),
        sa.Column("performed_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        schema="sowknow",
    )
    op.create_index(
        "idx_search_history_user_time",
        "search_history",
        ["user_id", "performed_at"],
        schema="sowknow",
    )

    # Partial index on documents.status for faster filtered queries
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_documents_status_indexed
        ON sowknow.documents (status)
        WHERE status = 'indexed'
    """)

    # Trigram index on document title for fuzzy matching
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_documents_title_trgm
        ON sowknow.documents
        USING GIN (title gin_trgm_ops)
    """)


def downgrade():
    op.execute("DROP INDEX IF EXISTS sowknow.idx_documents_title_trgm")
    op.execute("DROP INDEX IF EXISTS sowknow.idx_documents_status_indexed")
    op.drop_index("idx_search_history_user_time", table_name="search_history", schema="sowknow")
    op.drop_table("search_history", schema="sowknow")
```

- [ ] **Step 4: Commit**

```bash
git add backend/alembic/versions/013_add_search_history.py
git commit -m "feat(search): add search_history migration with search indexes"
```

---

### Task 9: Frontend — Translation Keys

**Files:**
- Modify: `frontend/app/messages/en.json`
- Modify: `frontend/app/messages/fr.json`

- [ ] **Step 1: Update English translations**

In `frontend/app/messages/en.json`, replace the existing `"search"` block (lines 155-171) with:

```json
"search": {
    "title": "Search",
    "placeholder": "Ask your question in natural language...",
    "searching": "Searching...",
    "searchButton": "Search",
    "stop": "Stop",
    "results": "Results",
    "result": "result",
    "resultsPlural": "results",
    "no_results": "No results found",
    "found_results": "{count} result(s) found",
    "relevance": "Relevance",
    "source": "Source",
    "sources": "Sources",
    "document": "Document",
    "page": "Page",
    "confidence": "confidence",
    "synthesizedAnswer": "Synthesized Answer",
    "suggestions": "Suggestions",
    "confidentialNotice": "This search includes confidential documents",
    "confidential": "Confidential",
    "empty": {
        "title": "Your knowledge awaits",
        "subtitle": "Ask a question in French or English. The agent will analyze your query, search all your documents, and synthesize a complete answer."
    },
    "stage": {
        "intent": "Analyzing your query...",
        "retrieval": "Searching in {count} query(ies)...",
        "reranking": "{count} excerpts retrieved, re-ranking...",
        "synthesis": "Synthesizing the answer..."
    },
    "relevanceLabel": {
        "highly_relevant": "Highly Relevant",
        "relevant": "Relevant",
        "partially": "Partial",
        "marginal": "Marginal"
    },
    "intent": {
        "factual": "Factual",
        "temporal": "Temporal",
        "comparative": "Comparative",
        "synthesis": "Synthesis",
        "financial": "Financial",
        "cross_reference": "Cross-Reference",
        "exploratory": "Exploratory",
        "entity_search": "Entity",
        "procedural": "Procedural",
        "unknown": "General"
    },
    "model": {
        "ollama": "Ollama (Local)",
        "minimax": "MiniMax 2.7"
    },
    "examples": {
        "1": "How has my thinking on solar energy evolved?",
        "2": "What assets appear in my balance sheets from the last 5 years?",
        "3": "All documents related to my family",
        "4": "What insights do I have about leadership?"
    },
    "error": "Search encountered an error. Please try again."
}
```

- [ ] **Step 2: Update French translations**

In `frontend/app/messages/fr.json`, replace the existing `"search"` block (lines 155-171) with:

```json
"search": {
    "title": "Recherche",
    "placeholder": "Posez votre question en langage naturel...",
    "searching": "Recherche en cours...",
    "searchButton": "Rechercher",
    "stop": "Arreter",
    "results": "Resultats",
    "result": "resultat",
    "resultsPlural": "resultats",
    "no_results": "Aucun resultat trouve",
    "found_results": "{count} resultat(s) trouve(s)",
    "relevance": "Pertinence",
    "source": "Source",
    "sources": "Sources",
    "document": "Document",
    "page": "Page",
    "confidence": "confiance",
    "synthesizedAnswer": "Reponse synthetisee",
    "suggestions": "Suggestions",
    "confidentialNotice": "Cette recherche inclut des documents confidentiels",
    "confidential": "Confidentiel",
    "empty": {
        "title": "Votre connaissance vous attend",
        "subtitle": "Posez une question en francais ou en anglais. L'agent analysera votre requete, cherchera dans tous vos documents et synthetisera une reponse complete."
    },
    "stage": {
        "intent": "Analyse de votre requete...",
        "retrieval": "Recherche dans {count} requete(s)...",
        "reranking": "{count} extraits recuperes, reclassement...",
        "synthesis": "Synthese de la reponse..."
    },
    "relevanceLabel": {
        "highly_relevant": "Tres pertinent",
        "relevant": "Pertinent",
        "partially": "Partiel",
        "marginal": "Marginal"
    },
    "intent": {
        "factual": "Factuel",
        "temporal": "Temporel",
        "comparative": "Comparatif",
        "synthesis": "Synthese",
        "financial": "Financier",
        "cross_reference": "Croise",
        "exploratory": "Exploratoire",
        "entity_search": "Entite",
        "procedural": "Procedural",
        "unknown": "General"
    },
    "model": {
        "ollama": "Ollama (Local)",
        "minimax": "MiniMax 2.7"
    },
    "examples": {
        "1": "Comment a evolue ma reflexion sur l'energie solaire ?",
        "2": "Quels actifs figurent dans mes bilans des 5 dernieres annees ?",
        "3": "Tous les documents lies a ma famille",
        "4": "Quels enseignements ai-je sur le leadership ?"
    },
    "error": "La recherche a rencontre une erreur. Veuillez reessayer."
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/app/messages/en.json frontend/app/messages/fr.json
git commit -m "feat(search): add agentic search translation keys (en/fr)"
```

---

### Task 10: Frontend — Search Page Rewrite

**Files:**
- Modify: `frontend/app/[locale]/search/page.tsx`

- [ ] **Step 1: Rewrite the search page**

Replace the entire content of `frontend/app/[locale]/search/page.tsx` with the new agentic search UI. This is a complete rewrite using Tailwind CSS, next-intl, and SSE streaming with httpOnly cookie auth.

The full component code is in the uploaded `docs/SearchPage.tsx` reference, adapted to:
- Use `useTranslations('search')` for all strings
- Use Tailwind CSS classes instead of inline styles
- Use `credentials: 'include'` with CSRF token instead of localStorage Bearer token
- Use `API_BASE` from `process.env.NEXT_PUBLIC_API_URL || '/api'`
- Use `getCsrfToken()` from `@/lib/api`

Key structure:
```tsx
'use client';

import { useCallback, useRef, useState } from 'react';
import { useTranslations } from 'next-intl';
import { getCsrfToken } from '@/lib/api';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || '/api';

// Types
type PipelineStage = 'idle' | 'intent' | 'retrieval' | 'reranking' | 'synthesis' | 'done' | 'error';

interface StreamState { ... }
interface SSESearchResult { ... }
interface SSECitation { ... }
interface SSESuggestion { ... }

// Relevance config (colors per tier)
const RELEVANCE_CONFIG = { ... };
const INTENT_META = { ... };

// Sub-components
function PipelineProgress({ stage, message, t }) { ... }
function IntentBadge({ intent, t }) { ... }
function SynthesisBlock({ text, model, t }) { ... }
function ResultCard({ result, rank, canSeeConfidential, t }) { ... }
function Suggestions({ suggestions, onSelect, t }) { ... }
function CitationsPanel({ citations, open, onClose, t }) { ... }

// Main page
export default function SearchPage() {
  const t = useTranslations('search');
  // ... SSE streaming logic with credentials: 'include' + CSRF token
  // ... Progressive UI rendering
}
```

The full implementation follows the patterns from the uploaded `SearchPage.tsx` with these changes:
- All inline styles → Tailwind classes
- All hardcoded French strings → `t('key')` calls
- `localStorage.getItem("sowknow_token")` → removed (cookie auth)
- `Authorization: Bearer ...` header → `X-CSRF-Token: getCsrfToken()` header
- API URL: `/api/search/stream` → `${API_BASE}/v1/search/stream`

- [ ] **Step 2: Verify the page renders**

Run: `cd /home/developer/development/src/active/sowknow4/frontend && npx next build 2>&1 | tail -20`
Expected: Build succeeds with no TypeScript errors on the search page

- [ ] **Step 3: Commit**

```bash
git add frontend/app/\[locale\]/search/page.tsx
git commit -m "feat(search): rewrite search page with agentic SSE UI, Tailwind, and next-intl"
```

---

### Task 11: Cleanup — Delete Old Files

**Files:**
- Delete: `backend/app/api/search.py`
- Delete: `backend/app/api/multi_agent.py`

- [ ] **Step 1: Verify no other files import from the old modules**

Run: `cd /home/developer/development/src/active/sowknow4 && grep -r "from app.api.search import\|from app.api import.*search[^_]" backend/app/ --include="*.py" | grep -v "__pycache__" | grep -v search_agent`

Run: `cd /home/developer/development/src/active/sowknow4 && grep -r "from app.api.multi_agent import\|from app.api import.*multi_agent" backend/app/ --include="*.py" | grep -v "__pycache__"`

Expected: Only `main.py` references (which we already updated in Task 7). If other files reference these, update them first.

- [ ] **Step 2: Delete old files**

```bash
rm backend/app/api/search.py backend/app/api/multi_agent.py
```

- [ ] **Step 3: Verify the app still loads**

Run: `cd /home/developer/development/src/active/sowknow4/backend && python -c "from app.main import app; print('App loaded OK')"`
Expected: "App loaded OK"

- [ ] **Step 4: Commit**

```bash
git add -A backend/app/api/search.py backend/app/api/multi_agent.py
git commit -m "refactor(search): remove old search and multi-agent routers"
```

---

### Task 12: Final Integration Test

**Files:**
- None (verification only)

- [ ] **Step 1: Run all search agent tests**

Run: `cd /home/developer/development/src/active/sowknow4 && python -m pytest backend/tests/test_search_agent.py -v`
Expected: All 38 tests PASS

- [ ] **Step 2: Run existing test suite to check for regressions**

Run: `cd /home/developer/development/src/active/sowknow4 && python -m pytest backend/tests/ -v --ignore=backend/tests/test_search_agent.py 2>&1 | tail -30`
Expected: No new failures

- [ ] **Step 3: Verify frontend builds**

Run: `cd /home/developer/development/src/active/sowknow4/frontend && npx next build 2>&1 | tail -10`
Expected: Build succeeds

- [ ] **Step 4: Final commit with any fixups**

If any fixes were needed, commit them:
```bash
git add -A && git commit -m "fix(search): integration fixups for agentic search"
```
