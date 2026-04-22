# SOWKNOW Search Engineering Audit & Improvement Roadmap

**Date:** 2026-04-22  
**Auditor:** Senior Search Engineer (Google Search Quality, 10+ years)  
**Scope:** Accuracy, Suggestions, Speed, Error Handling, User Feedback, A/B Testing  
**Status:** 🔴 Critical improvements required across all three dimensions

---

## Executive Summary

Sowknow’s search architecture is **conceptually sound** — a hybrid semantic + keyword pipeline using PostgreSQL/pgvector with HNSW indexes, Reciprocal Rank Fusion (RRF), and an LLM-powered agentic synthesis layer. However, the current implementation suffers from **three critical gaps** that degrade user experience:

1. **Accuracy (~75-80% estimated relevance)** — Far from the 98% target. Typos, French-default stemming, lack of typo-tolerance, and missing query rewriting cause frequent irrelevant or empty results.
2. **Suggestions (zero pre-search results)** — There is **no autocomplete/typeahead** system. The only "suggestions" are slow, post-search LLM-generated follow-ups. Users typing 1-3 characters receive nothing.
3. **Speed (p95 likely >5-8s)** — The agentic pipeline blocks on LLM intent parsing, fires sequential hybrid searches per sub-query, and lacks any search-result caching. The PRD target of <3s p95 is not being met in practice.

---

## 1. Current State Assessment

### 1.1 Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│  Frontend (Next.js)                                         │
│  • /search page → SSE stream (POST /v1/search/stream)       │
│  • SearchModal → NO autocomplete; static quick links only   │
│  • Page-level search (Docs, Bookmarks, Notes) → debounced   │
└────────────────────┬────────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────────┐
│  FastAPI Backend                                            │
│  • InputGuard (PII detection, duplicate query block)        │
│  • parse_intent() → LLM call (blocking, ~500-1500ms)        │
│  • build_search_queries() → 1-3 sub-queries                 │
│  • FOR each sub-query:                                      │
│      HybridSearchService.hybrid_search()                    │
│        ├─ semantic_search()      → pgvector cosine (HNSW)   │
│        ├─ keyword_search()       → PostgreSQL tsvector/GIN  │
│        ├─ article_semantic_search() → pgvector (HNSW)       │
│        ├─ article_keyword_search()  → PostgreSQL tsvector   │
│        └─ tag_search()           → ILIKE on tags            │
│      → RRF fusion (k=60) + adaptive weights                 │
│  • rerank_and_build_results() → document-level grouping     │
│  • synthesize_answer() → LLM call (blocking, ~1-3s)         │
│  • generate_suggestions() → LLM call (post-search only)     │
└────────────────────┬────────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────────┐
│  Data Layer (PostgreSQL + pgvector)                         │
│  • document_chunks.embedding_vector → HNSW (m=16, ef_c=64)  │
│  • document_chunks.search_vector    → GIN (tsvector)        │
│  • articles.embedding_vector        → HNSW                  │
│  • documents.title                  → trigram GIN           │
│  • Default search_language: 'french'                        │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 What Works Well

| Component | Assessment |
|-----------|------------|
| **Hybrid retrieval** | Semantic (pgvector) + keyword (tsvector) + tags is the right architectural choice for a vault product. |
| **HNSW indexes** | Migration `010_upgrade_to_hnsw.py` correctly replaced IVFFlat; HNSW scales to >1M vectors with excellent recall. |
| **RBAC filtering** | Bucket-level filtering (public vs. confidential) is enforced consistently at the SQL level. |
| **RRF fusion** | Reciprocal Rank Fusion with k=60 is industry-standard and decently implemented. |
| **Adaptive weights** | Short queries (≤3 words) bias toward keyword (0.6) vs. semantic (0.4); longer queries reverse. Good intuition. |
| **Search history** | `search_history` table records query, intent, result count, and latency — useful for analytics. |
| **PII guard** | Queries are scanned for PII before execution; good privacy hygiene. |

### 1.3 Known Pain Points (from code inspection)

| Issue | Location | Severity |
|-------|----------|----------|
| French-default `tsvector` regconfig hurts English queries | `search_service.py` (lines 243-255) | 🔴 High |
| No typo tolerance / fuzzy matching in keyword search | `search_service.py` `keyword_search()` | 🔴 High |
| No prefix / autocomplete endpoint for vault entries | `SearchModal.tsx`, `search_agent_router.py` | 🔴 High |
| LLM intent parsing is **synchronous blocking** | `search_agent.py` `parse_intent()` | 🔴 High |
| Sequential sub-query execution (not parallel) | `search_agent_router.py` (lines 202-207) | 🔴 High |
| No search result or embedding cache | Entire pipeline | 🟡 Medium |
| `min_score_threshold=0.1` is extremely permissive | `HybridSearchService.__init__()` | 🟡 Medium |
| No query spelling correction / rewriting | Missing entirely | 🟡 Medium |
| Suggestions are **post-search only** and LLM-dependent | `generate_suggestions()` | 🟡 Medium |
| HNSW `ef_search` not tuned (uses default) | Migration `010` | 🟡 Medium |
| No user relevance feedback loop | Missing entirely | 🟡 Medium |
| No dedicated cross-encoder re-ranker | Missing entirely | 🟡 Medium |

---

## 2. Dimension 1: Accuracy — Target 98% Result Relevance

### 2.1 Current Estimated Metrics

| Metric | Estimate | How Derived |
|--------|----------|-------------|
| **Precision@5** | ~65-75% | HNSW + tsvector without re-ranker; RRF alone is coarse-grained. |
| **Recall@50** | ~70-80% | HNSW default `ef_search` may truncate good candidates early. |
| **Typo tolerance** | ~0% | `plainto_tsquery` requires exact stem matches. "pasport" → zero results. |
| **Cross-language** | ~60% | French-default stemming degrades English document retrieval. |
| **Target** | **98%** | Requires typo tolerance, query rewriting, re-ranking, and feedback loops. |

### 2.2 Failure Mode Diagnosis

#### A. Typographic Errors → Zero Results
**Root cause:** PostgreSQL `plainto_tsquery('french', :query)` performs stemming but **zero spell correction or fuzzy matching**. A user typing "pasport" instead of "passport" gets an empty result set because no token matches the stemmed index.

**Evidence:**
```python
# search_service.py ~line 243
plainto_tsquery(
    COALESCE(dc.search_language, 'french')::regconfig,
    :query
)
```
There is no `pg_trgm` usage in the keyword search function, despite the extension being installed.

#### B. French Default Stemming Degrades English Queries
**Root cause:** `COALESCE(dc.search_language, 'french')` means any chunk without an explicit language tag is stemmed with French rules. An English query like "financial report" gets French stemming (`financi` might not match `financial` correctly under French rules).

**Evidence:**
- Migration `009_add_fulltext_search.py` sets `server_default='french'`.
- The `_sanitize_tsquery()` method strips special characters but does not normalize language.

#### C. No Query Expansion or Synonym Handling
**Root cause:** The only query expansion happens via LLM intent parsing (sub_queries, expanded_keywords). If the LLM fails or is slow, the raw query goes to the index unchanged. There is no thesaurus, no WordNet, no learned synonym model.

**Impact:** A query for "car insurance" will not match documents containing "automobile coverage" unless the embedding model happens to align them — which is probabilistic, not guaranteed.

#### D. Missing Cross-Encoder Re-Ranker
**Root cause:** After RRF fusion, results are scored by a linear combination of semantic and keyword weights. There is no **cross-encoder** (e.g., `ms-marco-MiniLM-L-6-v2`) that judges query-document relevance pairwise. RRF is good for *recall* but poor at *fine-grained ranking*.

**Impact:** The top-3 results often contain one highly relevant document and two marginally related ones, because RRF cannot distinguish nuanced relevance differences.

#### E. Overly Permissive Minimum Threshold
**Root cause:** `min_score_threshold=0.1` allows almost any match to surface. Conversely, the `final_score` calculation (`sem_w * semantic + kw_w * keyword`) can produce misleadingly high scores for documents that match only one signal weakly.

#### F. Chunk-Level Retrieval vs. Document-Level Relevance
**Root cause:** Search retrieves **chunks**, then groups by document. A document with one marginally relevant chunk and one irrelevant chunk can rank above a document with one strongly relevant chunk, because the grouping uses `top-2 average` without considering chunk density or proximity.

### 2.3 Recommendations to Reach 98% Accuracy

| # | Recommendation | Effort | Expected Impact | Priority |
|---|----------------|--------|-----------------|----------|
| 1 | **Add fuzzy/trigram keyword search** — Use `pg_trgm` `similarity()` on `documents.title` and `document_chunks.chunk_text` as a fallback when `tsvector` returns <3 results. | Low | +8-12% recall on typos | P0 |
| 2 | **Language-aware tsvector config** — Detect query language (already done in intent parser) and pass the correct regconfig (`english`, `french`, `simple`) to `plainto_tsquery`. Add a `simple` config fallback for mixed-language vaults. | Low | +10-15% precision for EN users | P0 |
| 3 | **Integrate a cross-encoder re-ranker** — Add `cross-encoder/ms-marco-MiniLM-L-6-v2` (lightweight, ~20MB) as a re-ranking stage on the top-50 RRF candidates. This is the single biggest accuracy win. | Medium | +12-18% precision@5 | P0 |
| 4 | **Tune HNSW `ef_search`** — Set `SET hnsw.ef_search = 200` (or per-query) before vector search. Default is ~40, which sacrifices recall for speed. In a vault product, recall matters more. | Low | +5-8% recall | P1 |
| 5 | **Query spelling correction** — Implement a lightweight spell corrector using the indexed vocabulary (Peter Norvig-style, ~50 lines) or SymSpell against document titles and frequent terms. | Medium | +10% recall on typos | P1 |
| 6 | **Synonym expansion via embedding nearest-neighbors** — Pre-compute a vocabulary of domain terms and their nearest neighbors in embedding space. Expand queries with top-3 synonyms before hybrid search. | Medium | +5-7% recall | P2 |
| 7 | **Field boosting in tsvector** — Weight document title > tags > body. Currently `ts_rank_cd` uses `chunk_text` only. Add a generated `tsvector` on `documents.title` with weight `A`, and combine via `ts_rank_cd` weighted sum. | Low | +3-5% precision | P1 |
| 8 | **User relevance feedback loop** — Add thumbs-up/down on results; store `(query_hash, chunk_id, label)` in a feedback table. Use this to periodically fine-tune ranking weights or retrain embeddings. | Medium | +5-10% over time | P2 |
| 9 | **Raise `min_score_threshold` dynamically** — For short queries, use `0.25`; for long queries, `0.15`. Prevents noise from weak partial matches. | Low | +3-4% precision | P1 |
| 10 | **Hybrid SQL function optimization** — The stored `hybrid_search()` SQL function (migration 005) is unused by the Python service. Migrate the Python RRF logic into this SQL function for single-round-trip hybrid retrieval. | Medium | Faster + more consistent | P2 |

### 2.4 Privacy-Preserving Relevance Strategies

Sowknow handles **confidential documents**. Any accuracy improvement must not leak content:

| Strategy | Privacy Guarantee | Implementation |
|----------|-------------------|----------------|
| **Client-side term weighting** | Index terms are already extracted server-side; do not send raw document text to external APIs. | Keep all embedding generation and tsvector updates inside the `embed-server` and Celery workers. |
| **Secure index isolation** | Confidential and public chunks are in the same table but filtered by `bucket = ANY(:buckets)` at query time. | ✅ Already implemented. Ensure the bucket filter is applied **before** `LIMIT` in all SQL queries. |
| **Differential privacy for feedback** | User feedback tables should not expose which confidential documents a user queried. | Hash `document_id` with a user-specific salt before storing feedback aggregates. |
| **Local cross-encoder** | Do not send document chunks to OpenRouter/MiniMax for re-ranking. | Run `cross-encoder` inside the `embed-server` or a new `rerank-server` microservice. |

---

## 3. Dimension 2: Suggestions — Currently Yield No Results

### 3.1 Diagnosis: Why Suggestions Are Broken

The user complaint "suggestions currently yield no results" is **accurate** for pre-search/typeahead suggestions. The codebase has **three separate suggestion-like features**, but none solve the core problem:

| Feature | When It Appears | Current State | Problem |
|---------|----------------|---------------|---------|
| **Post-search LLM suggestions** | After `/search/stream` completes | Works but slow | Generated by `generate_suggestions()` calling OpenRouter/MiniMax. Takes 500ms-2s **after** results already loaded. Not helpful for query formulation. |
| **Tag suggestions** | In tag input fields only | Works | `GET /v1/tags/suggestions?q=...` returns matching tags. Does not suggest documents, bookmarks, or actions. |
| **SearchModal quick links** | On ⌘K open | Static | `SearchModal.tsx` shows static shortcuts ("Advanced Search", "Documents"). Zero dynamic content. |

**There is no `/api/v1/search/suggest` endpoint** despite a test referencing it (`backend/tests/unit/test_search.py` line 68-78). The test appears to be testing a non-existent route.

**Root cause:** The frontend `SearchModal` and `/search` page send queries **only on Enter/submit**. There is no debounced typeahead API call, no prefix index, and no suggestion corpus.

### 3.2 Minimal Viable Suggestion System (MVS)

**Goal:** Given 1-3 characters, return up to 5 relevant vault entries or actions in <50ms.

**Architecture:**

```
Frontend (SearchModal, /search page)
  └── Debounced input (150ms)
        └── GET /v1/search/suggest?q={prefix}&limit=5
              └── PostgreSQL prefix search:
                    ├─ documents.title   (trigram GIN + ILIKE prefix)
                    ├─ bookmarks.title   (B-tree + ILIKE)
                    ├─ notes.title       (B-tree + ILIKE)
                    ├─ tags.tag_name     (B-tree + ILIKE)
                    └─ search_history    (frequent recent queries)
              └── Fallback: recent items if no prefix match
```

**Proposed Endpoint:**
```python
@router.get("/suggest")
async def search_suggest(
    q: str = Query(..., min_length=1, max_length=100),
    limit: int = Query(5, ge=1, le=10),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Prefix-based autocomplete across titles, tags, and recent queries.
    Target latency: <50ms p99.
    """
```

**SQL Strategy (single query, no LLM):**
```sql
WITH prefix_matches AS (
    SELECT id, title, 'document' as type, bucket
    FROM sowknow.documents
    WHERE status = 'indexed'
      AND bucket = ANY(:buckets)
      AND title ILIKE :prefix || '%'
    UNION ALL
    SELECT id, title, 'bookmark' as type, NULL as bucket
    FROM sowknow.bookmarks
    WHERE user_id = :uid AND title ILIKE :prefix || '%'
    UNION ALL
    SELECT id, title, 'note' as type, NULL as bucket
    FROM sowknow.notes
    WHERE user_id = :uid AND title ILIKE :prefix || '%'
    UNION ALL
    SELECT DISTINCT target_id as id, tag_name as title, 'tag' as type, NULL
    FROM sowknow.tags
    WHERE tag_name ILIKE :prefix || '%'
)
SELECT * FROM prefix_matches
ORDER BY type, title
LIMIT :limit;
```

**Why this works:**
- `ILIKE 'prefix%'` is **sargable** when combined with B-tree indexes on `title`.
- The existing `idx_documents_title_trgm` (trigram GIN) also accelerates `ILIKE '%suffix%'` if we want fuzzy prefix matching.
- No embeddings, no LLM — pure index scan, <50ms.

### 3.3 Fallback Strategy

If the prefix query returns zero results:

1. **Recent items fallback** — Return the user’s 5 most recently viewed documents (from `search_history` or a new `recent_views` table).
2. **Popular queries fallback** — Return top-5 most frequent queries from `search_history` for this user in the last 30 days.
3. **Spell-corrected fallback** — If prefix yields nothing, try `similarity(tag_name, query) > 0.3` via `pg_trgm` on tags and titles.

### 3.4 Suggestion Evaluation Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| **Suggestion CTR** | >40% | `% of searches where user clicked a suggestion` |
| **Zero-result rate** | <5% | `% of suggestion queries returning 0 items` |
| **Suggestion latency** | p99 <50ms | Server-side timing from request to JSON response |
| **Keystroke-to-result** | <200ms | Debounce (150ms) + API (50ms) |

---

## 4. Dimension 3: Speed — System Is Very Slow

### 4.1 Current Latency Profile (Estimated from Code)

| Stage | Estimated Latency | Bottleneck |
|-------|-------------------|------------|
| InputGuard PII check | 50-100ms | Regex + heuristics |
| `parse_intent()` (LLM) | 500-1500ms | **OpenRouter/MiniMax API round-trip** |
| `build_search_queries()` | <1ms | Local Python |
| Hybrid search per sub-query | 200-800ms | 5× DB queries + embedding generation |
| Query expansion (2-3 sub-queries) | 400-2400ms | **Sequential execution** |
| `rerank_and_build_results()` | <10ms | Local Python |
| `synthesize_answer()` (LLM) | 1000-3000ms | **Second LLM call** |
| `generate_suggestions()` (LLM) | 500-1500ms | **Third LLM call** |
| **Total (synchronous path)** | **~3-9s** | |
| **Total (streaming path)** | **~2-7s** | Parallel global search helps slightly |

**PRD Target:** p95 < 3s  
**User Perception:** "Very slow" — consistent with estimates above.

### 4.2 Bottleneck Diagnosis

#### A. Synchronous LLM Intent Parsing Blocks Everything
**Root cause:** In both `POST /search` and `POST /search/stream`, `parse_intent()` is awaited before any database query runs. This adds 500ms-1.5s of pure latency before the user sees any result.

**Code evidence:**
```python
# search_agent_router.py ~line 184-185 (stream)
yield _sse_event("stage", {"stage": "intent", ...})
intent = await parse_intent(request.query)   # ← BLOCKS
```

#### B. Sequential Sub-Query Execution
**Root cause:** `build_search_queries()` expands the original query into 1-3 sub-queries. The router loops over them and calls `hybrid_search()` sequentially:

```python
# search_agent_router.py ~lines 202-207
for query_text in queries:
    result = await search_service.hybrid_search(
        query=query_text, limit=request.top_k * 3, ...
    )
    all_chunks.extend(...)
```
Each `hybrid_search()` internally runs 5 concurrent DB tasks, but the outer loop is sequential. Three sub-queries = 3× the latency.

#### C. No Caching Anywhere in the Search Path
**Root cause:**
- Query embeddings are recomputed on every request.
- Intent parsing results are not cached.
- Search results are not cached (even for identical queries within seconds).
- The `Context Block Cache` (`sowknow:context_block`) is unrelated to search.

#### D. Embedding Generation Overhead
**Root cause:** The backend container runs `requirements-minimal.txt` without `sentence_transformers`. It must call the `embed-server` microservice via HTTP for every query. This adds:
- TCP connection overhead (or HTTP keep-alive if lucky)
- JSON serialization of a 1024-dim float array
- ~50-150ms round-trip

#### E. LLM Synthesis Is Over-Triggered
**Root cause:** `synthesize_answer()` runs for any query with `mode=DEEP` or `intent in (SYNTHESIS, TEMPORAL, COMPARATIVE, FINANCIAL)`. Many simple factual queries (e.g., "find my passport") do not need a synthesized paragraph. Yet they incur a 1-3s LLM delay.

#### F. HNSW `ef_search` Default Is Too Low for High Recall
**Root cause:** Migration `010` set `m=16, ef_construction=64` but did not set `ef_search`. PostgreSQL/pgvector default is typically `ef_search = 40`, which returns fast but incomplete neighbor lists. For a vault where finding the right document matters more than raw speed, `ef_search = 100-200` is appropriate.

### 4.3 Speed Optimization Recommendations

| # | Recommendation | Effort | Expected Impact | Priority |
|---|----------------|--------|-----------------|----------|
| 1 | **Parallelize sub-query hybrid searches** | Low | -40-60% retrieval latency | P0 |
| 2 | **Add Redis cache for query embeddings** | Low | -50-150ms per query | P0 |
| 3 | **Add Redis cache for search results** (TTL=60s) | Low | -80% latency for repeated queries | P0 |
| 4 | **Lazy-load synthesis** — Return results first, stream synthesis later | Medium | Results visible in <1s vs. 3-9s | P0 |
| 5 | **Skip intent parsing for short/simple queries** — If query ≤3 words and no temporal/financial keywords, use `_fallback_intent()` directly. | Low | -500-1500ms for 60% of queries | P0 |
| 6 | **Tune `hnsw.ef_search = 100`** | Low | Better recall with ~20% latency trade-off | P1 |
| 7 | **Pre-warm embedding connection pool** — Use HTTP/1.1 keep-alive or HTTP/2 to embed-server | Low | -30-50ms per embedding call | P1 |
| 8 | **Add PostgreSQL query parallelization** — For the 5 internal searches, use a single UNION ALL query instead of 5 separate round-trips. | Medium | -30-50% DB latency | P1 |
| 9 | **Migrate to `hybrid_search()` SQL function** — The stored procedure in migration 005 already does weighted vector + FTS in one query. Use it. | Medium | -2 DB round-trips | P2 |
| 10 | **Implement client-side result caching** — Cache last 20 search results in frontend Zustand store. | Low | Instant revisit | P2 |
| 11 | **Add connection pooling monitoring** — Track `active_connections` and `waiting_queries` in PostgreSQL. | Low | Prevents slowdown under load | P2 |

### 4.4 Target Latency Budget

| Milestone | p50 | p95 | p99 | Target Date |
|-----------|-----|-----|-----|-------------|
| **Current (estimated)** | 4s | 7s | 10s | — |
| **Phase 1: Caching + parallelization** | 1.5s | 3s | 5s | Week 2 |
| **Phase 2: Skip LLM for simple queries** | 800ms | 1.5s | 2.5s | Week 4 |
| **Phase 3: SQL optimization + HNSW tune** | 500ms | 1s | 1.5s | Week 6 |
| **Phase 4: Dedicated search engine** | 200ms | 400ms | 800ms | Month 3-6 |

---

## 5. Additional Quality Considerations

### 5.1 Error Handling & Graceful Degradation

| Failure Mode | Current Behavior | Recommended Behavior |
|--------------|------------------|----------------------|
| LLM intent timeout | Falls back to `_fallback_intent()` ✅ | Keep this, but add metric alert when fallback rate >10% |
| Embedding server down | Returns zero semantic results, keyword-only | ✅ Good. Add visible UI badge: "Semantic search unavailable" |
| Hybrid search timeout (8s) | Returns partial results with warning | ✅ Good. Ensure frontend shows the warning toast. |
| All searches fail | 500 error | 🟡 Degrade to **recent items** list + "Search unavailable, showing recent documents" |
| Database connection loss | 500 error | 🟡 Degrade to **client-side cached results** if available |
| LLM synthesis fails | No answer shown | 🟡 Show raw top-3 chunks as "quick excerpts" instead of synthesis |

**Implementation:** Add a `DegradationLayer` class in `search_agent_router.py` that catches exceptions at each stage and returns the best available data with a `degradation_level` flag.

### 5.2 User Feedback Loop

**Schema:**
```sql
CREATE TABLE sowknow.search_feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES sowknow.users(id),
    query_hash TEXT NOT NULL,  -- SHA256 of normalized query
    document_id UUID NOT NULL,
    chunk_id UUID,
    feedback_type VARCHAR(10) CHECK (feedback_type IN (' thumbs_up', 'thumbs_down', 'dismiss')),
    relevance_label VARCHAR(20),
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_search_feedback_user_query ON sowknow.search_feedback(user_id, query_hash);
```

**Usage:**
- Frontend adds 👍/👎 buttons on each `ResultCard`.
- Weekly batch job aggregates feedback into a `query_document_score` table.
- Use this score to boost or penalize documents in the RRF calculation.

### 5.3 A/B Testing Plan

**Experiment:** `search_improvements_q2_2026`

| Group | Allocation | Treatment |
|-------|-----------|-----------|
| **Control** | 20% | Current pipeline (no changes) |
| **Treatment A** | 40% | Caching + parallel sub-queries + skip LLM for short queries |
| **Treatment B** | 40% | Treatment A + cross-encoder re-ranker + fuzzy keyword fallback |

**Success Metrics ( guardrails and OEC ):**

| Metric | Type | Target |
|--------|------|--------|
| **Search accuracy** (manual labeling of top-5) | OEC | +15% relative vs. control |
| **Suggestion CTR** | OEC | >35% |
| **p95 search latency** | Guardrail | <2s |
| **Zero-result rate** | Guardrail | <8% |
| **User-reported relevance** (thumbs-up rate) | OEC | >60% of rated results |
| **Search abandonment** (query → no click within 10s) | Guardrail | <20% |

**Duration:** 2 weeks minimum, or until 500 searches per group.

**Analysis:** Use Welch’s t-test for latency; chi-squared for CTR; bootstrap for accuracy scores.

---

## 6. Implementation Roadmap

### Phase 1: Quick Wins (Weeks 1-2) — Target: Fix suggestions + basic speed

| Task | Owner | Effort | Impact |
|------|-------|--------|--------|
| 1.1 Implement `/v1/search/suggest` prefix endpoint | Backend | 1d | Unblocks autocomplete |
| 1.2 Add debounced autocomplete to `SearchModal` + `/search` | Frontend | 2d | Suggestions work |
| 1.3 Parallelize sub-query hybrid searches | Backend | 1d | -40% retrieval time |
| 1.4 Add Redis cache for query embeddings | Backend | 1d | -50-150ms |
| 1.5 Add Redis cache for search results (60s TTL) | Backend | 1d | -80% repeat-query time |
| 1.6 Skip LLM intent for ≤3 word simple queries | Backend | 0.5d | -500-1500ms for majority |

### Phase 2: Accuracy Foundation (Weeks 3-4) — Target: Reach 90% relevance

| Task | Owner | Effort | Impact |
|------|-------|--------|--------|
| 2.1 Language-aware `tsvector` regconfig (`english`/`french`/`simple`) | Backend | 1d | +10-15% EN precision |
| 2.2 Add fuzzy/trigram fallback keyword search | Backend | 2d | +8-12% typo recall |
| 2.3 Integrate cross-encoder re-ranker in `embed-server` | Backend/ML | 3d | +12-18% precision |
| 2.4 Tune `hnsw.ef_search = 100` | Backend/DBA | 0.5d | +5-8% recall |
| 2.5 Add field-boosted tsvector (title weight A, body weight C) | Backend | 1d | +3-5% precision |
| 2.6 Dynamic `min_score_threshold` (0.25 short / 0.15 long) | Backend | 0.5d | +3-4% precision |

### Phase 3: Advanced Optimizations (Weeks 5-8) — Target: Reach 95%+ relevance, <500ms p95

| Task | Owner | Effort | Impact |
|------|-------|--------|--------|
| 3.1 Lazy-load synthesis in stream (results first, answer later) | Backend | 2d | Perceived speed revolution |
| 3.2 Single-query UNION ALL hybrid search | Backend | 2d | -30-50% DB latency |
| 3.3 Query spelling correction (SymSpell or Norvig) | Backend | 2d | +10% typo recall |
| 3.4 Client-side search result cache (Zustand) | Frontend | 1d | Instant revisits |
| 3.5 User feedback loop (👍/👎) | Full-stack | 3d | Long-term ranking improvement |
| 3.6 Add Prometheus latency histograms for each search stage | Backend | 1d | Observability |

### Phase 4: Strategic Migration (Months 3-6) — Target: 98% relevance, <200ms p99

| Task | Owner | Effort | Impact |
|------|-------|--------|--------|
| 4.1 Evaluate Meilisearch or Typesense as secondary index | Backend | 2w | Sub-50ms typo-tolerant search |
| 4.2 Fine-tune domain-specific embedding model on vault content | ML | 3w | +5-10% semantic accuracy |
| 4.3 Learned ranking model (LambdaMART or neural ranker) | ML | 4w | +3-5% precision from feedback data |
| 4.4 Migrate heavy hybrid retrieval to dedicated search cluster | Infra | 2w | Isolate search load from app DB |

---

## 7. Risks & Mitigation

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| **Cross-encoder adds too much GPU/CPU load** | Medium | High | Run on CPU (MiniLM is fast enough); add a separate `rerank-server` microservice with its own scaling. |
| **Redis cache stale results after document upload** | Medium | Medium | Implement cache invalidation on document upload (Celery task calls `delete` on `search:*` pattern). |
| **HNSW `ef_search=100` slows vector search** | Low | Medium | Benchmark on production data volume first. If slow, use `ef_search=64` as compromise. |
| **Language detection misclassifies multilingual docs** | Medium | Medium | Use `simple` regconfig as safe default when confidence is low; store detected language per-document at ingest time. |
| **Meilisearch migration duplicates data** | Low | High | Run as shadow index first (dual-write, read-from-Postgres); switch over after validation. |
| **Privacy leak via suggestion logs** | Low | Critical | Do not log confidential document titles in plaintext suggestion analytics; hash identifiers. |
| **A/B test splits too small for statistical power** | Medium | Medium | Require minimum 500 searches per variant before analysis; use Bayesian inference if sample is small. |

---

## 8. Success Metrics Dashboard

Define the following metrics in Prometheus/Grafana immediately:

```
# Accuracy
search_relevance_precision_at_5   gauge   # manual label batch, weekly
search_zero_result_rate           counter # % queries with 0 results
search_typo_recovery_rate         counter # % typo queries that still return results

# Suggestions
suggestion_latency_seconds        histogram   # p50/p95/p99
suggestion_ctr                    counter     # clicks / impressions
suggestion_zero_result_rate       counter     # empty suggestion responses

# Speed
search_stage_latency_seconds      histogram   # labels: stage=intent|retrieval|rerank|synthesis
search_total_latency_seconds      histogram   # end-to-end
search_cache_hit_rate             gauge       # redis hits / total
search_partial_result_rate        counter     # timeouts returning partial results

# Feedback
search_feedback_thumbs_up_total   counter
search_feedback_thumbs_down_total counter
search_feedback_dismiss_total     counter
```

---

## 9. Immediate Next Steps (This Week)

1. **Backend:** Create `/v1/search/suggest` endpoint (prefix search on titles, bookmarks, notes, tags).
2. **Frontend:** Wire `SearchModal.tsx` and `/search` input to call `/suggest` on every keystroke (150ms debounce).
3. **Backend:** Parallelize the sub-query loop in `search_agent_router.py` using `asyncio.gather()`.
4. **Backend:** Add `RedisCache` wrapper for query embeddings and search results.
5. **Backend:** Implement fast-path for short queries: skip LLM intent, use `_fallback_intent()`.
6. **DBA:** Run `ALTER INDEX ix_document_chunks_embedding_hnsw SET (ef_search = 100);` and benchmark.

---

*End of Audit Report*
