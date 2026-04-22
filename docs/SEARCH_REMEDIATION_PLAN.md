# SOWKNOW Search Remediation Plan
## QA-Gated Phase Implementation

**Based on:** `docs/SEARCH_ENGINEERING_AUDIT_2026-04-22.md`  
**Target State:** 98% relevance, p99 <200ms, suggestion CTR >40%, zero-result rate <5%  
**Governance:** No phase proceeds without signed QA commit (automated + manual validation)

---

## Governance Model

### QA Commit Gate Definition

Each phase ends with a **QA Commit Review** consisting of:

1. **Automated Test Pass** — All new + existing tests green (`pytest -x`, `npm test`)
2. **Performance Baseline** — Benchmarks must meet or beat the phase target
3. **Manual Validation Checklist** — Product owner signs off on user-facing behavior
4. **Rollback Script Verified** — One-command rollback tested in staging
5. **Observability Check** — New metrics visible in Prometheus/Grafana

### Branching Strategy

```
main (stable)
  └── phase/1-quick-wins
        └── phase/2-accuracy-foundation
              └── phase/3-advanced-opts
                    └── phase/4-strategic-migration
```

Each phase branch merges to `main` **only after QA commit approval**.

---

## Phase 0: Foundation & Instrumentation (Days 1–3)

**Objective:** Establish baseline metrics, write missing tests, and instrument every search stage so we can measure improvement.

### P0.1 Add Search Stage Latency Histograms

**Files:**
- `backend/app/services/prometheus_metrics.py` — add `search_stage_latency_seconds` histogram
- `backend/app/api/search_agent_router.py` — wrap each stage with timing
- `backend/app/services/search_service.py` — wrap hybrid_search sub-tasks with timing

**Implementation:**
```python
# In prometheus_metrics.py
search_stage_latency = Histogram(
    "search_stage_latency_seconds",
    "Latency per search pipeline stage",
    labels=["stage"],  # intent, retrieval, rerank, synthesis, suggestions
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

search_total_latency = Histogram(
    "search_total_latency_seconds",
    "End-to-end search latency",
    labels=["endpoint"],  # sync, stream, global
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

search_cache_hit_rate = Metric(
    "search_cache_hit_rate",
    "Cache hit rate for search operations",
    labels=["cache_type"],  # embedding, result, intent
)
```

**Validation:**
```bash
curl -s http://localhost:8000/metrics | grep search_
# Must show new metrics with zero values
```

### P0.2 Fix Missing `/search/suggest` Test

**File:** `backend/tests/unit/test_search.py`

**Issue:** Test references `/api/v1/search/suggest` which does not exist. Mark as `xfail` with reason until Phase 1 implements the endpoint.

```python
@pytest.mark.xfail(reason="Endpoint not yet implemented — see Phase 1")
def test_search_suggestions(client: TestClient, auth_headers):
    ...
```

### P0.3 Create Search Benchmark Harness

**File:** `backend/tests/performance/test_search_benchmark.py` (new)

**Implementation:**
```python
"""
Reusable benchmark for search latency across phases.
Run: pytest backend/tests/performance/test_search_benchmark.py -v -s
"""
import statistics
import time
import pytest
import numpy as np

SEARCH_QUERIES = [
    "passport",           # short keyword
    "tax 2024",           # short + temporal
    "financial report",   # medium keyword
    "insurance policy coverage",  # long keyword
    "family history genealogy",   # semantic-heavy
]

class TestSearchBenchmark:
    @pytest.mark.asyncio
    async def test_baseline_hybrid_search_latency(self, test_db_with_docs):
        """Benchmark hybrid_search() directly. Target p95 < 3000ms current."""
        ...

    @pytest.mark.asyncio
    async def test_baseline_agentic_search_latency(self, client, auth_headers):
        """Benchmark POST /api/v1/search. Target p95 < 5000ms current."""
        ...
```

### P0.4 Add Frontend Search Telemetry

**File:** `frontend/lib/api.ts`

Wrap `search()`, `searchBookmarks()`, etc. to emit `console.time/timeEnd` and optionally send to analytics:

```typescript
// Wrap search methods
async search(query: string, ...): Promise<SearchResponse> {
  const start = performance.now();
  const result = await this._search(query, ...);
  const duration = performance.now() - start;
  if (typeof window !== 'undefined' && (window as any).gtag) {
    (window as any).gtag('event', 'search_latency', {
      query_length: query.length,
      duration_ms: Math.round(duration),
      result_count: result.total_found,
    });
  }
  return result;
}
```

### P0.5 Document Current Baseline

**File:** `docs/SEARCH_BASELINE_YYYY-MM-DD.md` (auto-generated after first benchmark run)

**Contents:**
- p50/p95/p99 for each search endpoint
- Zero-result rate per query type
- Current suggestion CTR (likely 0% or undefined)
- Embedding generation latency (local vs. embed-server)

### Phase 0 QA Commit Criteria

| Gate | Criteria | Owner |
|------|----------|-------|
| Automated | `pytest backend/tests/performance/test_search_benchmark.py` runs without error | QA |
| Metrics | `curl /metrics` shows `search_stage_latency_seconds` and `search_total_latency_seconds` | DevOps |
| Baseline | Baseline document committed with actual p95 numbers | Tech Lead |
| Rollback | `git revert HEAD~2..HEAD` restores pre-Phase-0 state cleanly | Release Eng |

**Go/No-Go Decision:** Tech Lead + QA Engineer sign-off required.

---

## Phase 1: Quick Wins — Suggestions + Speed (Days 4–10)

**Objective:** Make suggestions functional and cut p95 latency by 50% with minimal architectural changes.

### P1.1 Implement `/v1/search/suggest` Endpoint

**New File:** `backend/app/api/search_suggest.py`  
**Modified:** `backend/app/main.py` (register router)

**Specification:**
```python
from fastapi import APIRouter, Query, Depends, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/search", tags=["Search Suggestions"])

SUGGESTION_LIMIT = 5
MIN_PREFIX_LENGTH = 1

@router.get("/suggest", status_code=status.HTTP_200_OK)
async def search_suggest(
    q: str = Query(..., min_length=MIN_PREFIX_LENGTH, max_length=100),
    limit: int = Query(default=SUGGESTION_LIMIT, ge=1, le=10),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Prefix-based autocomplete across vault contents.
    Target latency: p99 < 50ms.
    """
    prefix = q.strip()
    if not prefix:
        return {"query": q, "suggestions": []}

    buckets = _get_user_bucket_filter(current_user)
    pattern = prefix + "%"
    fuzzy_pattern = "%" + prefix + "%"

    # Phase 1: prefix match (fast, indexed)
    sql = text("""
        WITH matches AS (
            SELECT id, title, 'document' as type,
                   COALESCE(original_filename, filename) as display_title,
                   bucket
            FROM sowknow.documents
            WHERE status = 'indexed'
              AND bucket = ANY(:buckets)
              AND title ILIKE :prefix_pattern
            UNION ALL
            SELECT id, title, 'bookmark' as type, title as display_title, NULL
            FROM sowknow.bookmarks
            WHERE user_id = :user_id AND title ILIKE :prefix_pattern
            UNION ALL
            SELECT id, title, 'note' as type, title as display_title, NULL
            FROM sowknow.notes
            WHERE user_id = :user_id AND title ILIKE :prefix_pattern
            UNION ALL
            SELECT DISTINCT target_id as id, tag_name as title, 'tag' as type,
                   tag_name as display_title, NULL
            FROM sowknow.tags
            WHERE tag_name ILIKE :prefix_pattern
        )
        SELECT * FROM matches
        ORDER BY type, title
        LIMIT :limit
    """)

    result = await db.execute(sql, {
        "buckets": buckets,
        "user_id": str(current_user.id),
        "prefix_pattern": pattern,
        "limit": limit,
    })
    rows = result.mappings().all()

    # Fallback: fuzzy match if prefix empty
    if not rows and len(prefix) >= 2:
        fuzzy_sql = text("""
            SELECT id, title, 'document' as type,
                   COALESCE(original_filename, filename) as display_title
            FROM sowknow.documents
            WHERE status = 'indexed'
              AND bucket = ANY(:buckets)
              AND title % :prefix          -- pg_trgm similarity
            ORDER BY similarity(title, :prefix) DESC
            LIMIT :limit
        """)
        result = await db.execute(fuzzy_sql, {
            "buckets": buckets,
            "prefix": prefix,
            "limit": limit,
        })
        rows = result.mappings().all()

    # Fallback: recent items if still empty
    if not rows:
        recent_sql = text("""
            SELECT d.id, d.title, 'document' as type,
                   COALESCE(d.original_filename, d.filename) as display_title
            FROM sowknow.search_history sh
            JOIN sowknow.documents d ON d.id = (
                SELECT document_id FROM sowknow.document_chunks
                WHERE document_id = d.id LIMIT 1
            )
            WHERE sh.user_id = :user_id
            ORDER BY sh.performed_at DESC
            LIMIT :limit
        """)
        # Simplified: return empty for now, implement recent docs table in Phase 3

    suggestions = [
        {
            "id": str(row["id"]),
            "title": row["display_title"],
            "type": row["type"],
        }
        for row in rows
    ]

    return {"query": q, "suggestions": suggestions}
```

**Tests:** `backend/tests/unit/test_search_suggest.py`
```python
def test_suggest_documents_prefix(client: TestClient, auth_headers, test_document):
    """Typing 'pass' should suggest 'passport'."""
    response = client.get("/api/v1/search/suggest?q=pass", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert any("passport" in s["title"].lower() for s in data["suggestions"])

def test_suggest_empty_query_rejected(client: TestClient, auth_headers):
    response = client.get("/api/v1/search/suggest?q=", headers=auth_headers)
    assert response.status_code in [400, 422]

def test_suggest_latency_under_50ms(client: TestClient, auth_headers):
    import time
    start = time.time()
    response = client.get("/api/v1/search/suggest?q=fin", headers=auth_headers)
    elapsed = (time.time() - start) * 1000
    assert response.status_code == 200
    assert elapsed < 50, f"Suggest latency {elapsed:.1f}ms exceeds 50ms budget"
```

### P1.2 Frontend Autocomplete Integration

**Modified Files:**
- `frontend/components/SearchModal.tsx`
- `frontend/app/[locale]/search/page.tsx`
- `frontend/lib/api.ts` — add `suggest(q: string)` method

**Implementation for `SearchModal.tsx`:**
```typescript
// Add to SearchModal
const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
const [showSuggestions, setShowSuggestions] = useState(false);
const debounceRef = useRef<NodeJS.Timeout>();

const handleInputChange = (value: string) => {
  setQuery(value);
  if (debounceRef.current) clearTimeout(debounceRef.current);
  if (value.trim().length >= 1) {
    debounceRef.current = setTimeout(async () => {
      try {
        const res = await api.suggest(value);
        setSuggestions(res.suggestions);
        setShowSuggestions(res.suggestions.length > 0);
      } catch {
        setSuggestions([]);
        setShowSuggestions(false);
      }
    }, 150);
  } else {
    setSuggestions([]);
    setShowSuggestions(false);
  }
};

// Render dropdown
{showSuggestions && (
  <ul className="absolute z-50 w-full bg-vault-900 border border-vault-700 rounded-lg mt-1 max-h-60 overflow-auto">
    {suggestions.map((s) => (
      <li
        key={`${s.type}-${s.id}`}
        className="px-4 py-2 hover:bg-vault-800 cursor-pointer flex items-center gap-2"
        onClick={() => {
          if (s.type === 'document') router.push(`/${locale}/documents/${s.id}`);
          else if (s.type === 'bookmark') router.push(`/${locale}/bookmarks`);
          else if (s.type === 'note') router.push(`/${locale}/notes/${s.id}`);
          onClose();
        }}
      >
        <span className="text-xs uppercase tracking-wider text-vault-400">{s.type}</span>
        <span className="text-sm text-white">{s.title}</span>
      </li>
    ))}
  </ul>
)}
```

**Validation:**
- Open SearchModal (⌘K), type "pas" → see dropdown with matching documents/bookmarks/notes/tags
- Click suggestion → navigates directly to item
- Type "xyznonexistent" → dropdown disappears gracefully

### P1.3 Parallelize Sub-Query Execution

**File:** `backend/app/api/search_agent_router.py` (~lines 200–207)

**Current (sequential):**
```python
for query_text in queries:
    result = await search_service.hybrid_search(...)
    all_chunks.extend(...)
```

**New (parallel):**
```python
# Parallelize sub-query hybrid searches
search_tasks = [
    search_service.hybrid_search(
        query=query_text, limit=request.top_k * 3,
        offset=0, db=db, user=current_user,
    )
    for query_text in queries
]
search_results = await asyncio.gather(*search_tasks, return_exceptions=True)

for result in search_results:
    if isinstance(result, Exception):
        logger.warning("Sub-query search failed: %s", result)
        continue
    all_chunks.extend(_convert_search_results_to_chunks(result.get("results", [])))
```

**Validation:**
```python
# In test_search_agent.py
@pytest.mark.asyncio
async def test_parallel_subqueries_faster_than_sequential():
    # Mock hybrid_search to sleep 100ms
    # 3 sub-queries sequential = ~300ms
    # 3 sub-queries parallel = ~100ms + overhead
    ...
```

### P1.4 Redis Cache for Query Embeddings

**New File:** `backend/app/services/search_cache.py`

```python
"""Search-specific caching layer on top of Redis."""
import hashlib
import json
from typing import Optional

from app.core.redis_url import get_redis_client

redis = get_redis_client()

EMBEDDING_TTL = 3600  # 1 hour — embeddings don't change for same query
RESULT_TTL = 60       # 1 minute — results may change as docs are added

class SearchCache:
    @staticmethod
    def _embedding_key(query: str) -> str:
        h = hashlib.sha256(query.lower().strip().encode()).hexdigest()[:16]
        return f"sowknow:search:emb:{h}"

    @staticmethod
    def _result_key(query: str, user_role: str, top_k: int) -> str:
        h = hashlib.sha256(f"{query}:{user_role}:{top_k}".encode()).hexdigest()[:16]
        return f"sowknow:search:res:{h}"

    @classmethod
    def get_embedding(cls, query: str) -> Optional[list[float]]:
        if not redis:
            return None
        raw = redis.get(cls._embedding_key(query))
        if raw:
            return json.loads(raw)
        return None

    @classmethod
    def set_embedding(cls, query: str, embedding: list[float]) -> None:
        if not redis:
            return
        redis.setex(cls._embedding_key(query), EMBEDDING_TTL, json.dumps(embedding))

    @classmethod
    def get_result(cls, query: str, user_role: str, top_k: int) -> Optional[dict]:
        if not redis:
            return None
        raw = redis.get(cls._result_key(query, user_role, top_k))
        if raw:
            return json.loads(raw)
        return None

    @classmethod
    def set_result(cls, query: str, user_role: str, top_k: int, result: dict) -> None:
        if not redis:
            return
        redis.setex(cls._result_key(query, user_role, top_k), RESULT_TTL, json.dumps(result, default=str))

    @classmethod
    def invalidate_for_user(cls, user_id: str) -> None:
        """Invalidate result cache for a user after upload/delete."""
        if not redis:
            return
        # Phase 1: simple flush of all search result keys
        for key in redis.scan_iter(match="sowknow:search:res:*"):
            redis.delete(key)
```

**Integration in `search_service.py`:**
```python
from app.services.search_cache import SearchCache

async def semantic_search(self, query, ...):
    # Try cache first
    cached = SearchCache.get_embedding(query)
    if cached is not None:
        query_embedding = cached
    else:
        query_embedding = embedding_service.encode_query(query)
        SearchCache.set_embedding(query, query_embedding)
    ...
```

**Validation:**
```python
def test_embedding_cache_reduces_latency(client, auth_headers):
    # First search: cold cache
    # Second identical search: must be faster
    ...
```

### P1.5 Fast-Path for Short/Simple Queries

**File:** `backend/app/services/search_agent.py`

**Implementation:**
```python
async def run_agentic_search(...):
    start_ms = time.monotonic()
    ...

    # FAST PATH: Skip LLM intent for short, simple queries
    words = request.query.strip().split()
    is_simple = (
        len(words) <= 3
        and not any(w in request.query.lower() for w in [
            "evolution", "trend", "compare", "difference",
            "bilan", "balance sheet", "resume", "synthese"
        ])
        and request.mode != SearchMode.DEEP
    )

    if is_simple:
        intent = _fallback_intent(request.query)
        intent.confidence = 0.6  # Mark as heuristic
        logger.info("Fast path: skipped LLM intent for simple query '%s'", request.query)
    else:
        intent = await parse_intent(request.query)
    ...
```

**Validation:**
- Query "passport" → intent stage completes in <10ms (not 500-1500ms)
- Query "financial report" → still uses LLM intent (or fallback if ≤3 words)
- Query "how has my investment portfolio evolved over time" → uses LLM intent

### P1.6 Add `search_time_ms` to Streaming Endpoint

**File:** `backend/app/api/search_agent_router.py`

The streaming endpoint currently does not track `search_time_ms`. Add a timer and emit it in the `done` event.

```python
async def event_generator():
    start = time.monotonic()
    ...
    elapsed_ms = int((time.monotonic() - start) * 1000)
    yield _sse_event("done", {
        "total_found": len(results),
        "model": model_used,
        "has_confidential": has_confidential,
        "search_time_ms": elapsed_ms,
    })
```

### Phase 1 QA Commit Criteria

| Gate | Criteria | Evidence Required |
|------|----------|-------------------|
| **Automated** | All tests pass, including new `test_search_suggest.py` | CI green |
| **Latency** | Benchmark shows p95 `hybrid_search()` < 2000ms (was ~3000ms) | `test_search_benchmark.py` output |
| **Latency** | Suggest endpoint p99 < 50ms | `test_suggest_latency_under_50ms` |
| **Latency** | Simple query (≤3 words) skips LLM intent 100% of time | Log analysis |
| **Feature** | SearchModal shows live autocomplete dropdown | Screen recording |
| **Feature** | Clicking suggestion navigates to correct item | Manual test checklist |
| **Observability** | Prometheus shows `search_cache_hit_rate` | Grafana screenshot |
| **Rollback** | `git revert` + `alembic downgrade` restores pre-Phase-1 | Staging test |

**Performance Targets (Phase 1):**
- p95 search latency: **< 3000ms** (from ~5000-8000ms)
- p99 suggest latency: **< 50ms**
- Suggestion zero-result rate: **< 10%**
- Cache hit rate (repeat queries): **> 30%**

---

## Phase 2: Accuracy Foundation (Days 11–20)

**Objective:** Reach 90%+ relevance through language-aware FTS, typo tolerance, cross-encoder re-ranking, and HNSW tuning.

### P2.1 Language-Aware `tsvector` Configuration

**Files:**
- `backend/app/services/search_service.py` — `_keyword_search()`, `hybrid_search()`
- `backend/app/services/search_agent.py` — `parse_intent()` already returns `detected_language`

**Implementation:**
```python
LANGUAGE_MAP = {
    "fr": "french",
    "en": "english",
    "de": "german",
    "es": "spanish",
    "it": "italian",
}

def _get_regconfig(language_code: str) -> str:
    return LANGUAGE_MAP.get(language_code, "simple")  # 'simple' is safe fallback
```

Pass `intent.detected_language` from the router into `hybrid_search()`, then into `_keyword_search()`:

```python
# In hybrid_search()
regconfig = _get_regconfig(intent.detected_language if intent else "simple")
keyword_results = await self.keyword_search(
    query=query, limit=limit * 2, db=db, user=user,
    regconfig=regconfig,  # NEW
)
```

Update raw SQL to use parameterized regconfig:
```python
sql_query = text("""
    SELECT ...
    FROM sowknow.document_chunks dc
    JOIN sowknow.documents d ON dc.document_id = d.id
    WHERE d.bucket = ANY(:buckets)
      AND dc.search_vector IS NOT NULL
      AND dc.search_vector @@ plainto_tsquery(
              :regconfig::regconfig,  -- was hardcoded 'french'
              :query
          )
    ORDER BY ts_rank_cd(dc.search_vector, plainto_tsquery(:regconfig::regconfig, :query), 32) DESC
    LIMIT :limit OFFSET :offset
""")
```

**Migration:** If `search_language` column default is `'french'`, add a data migration to set `simple` for documents detected as English.

**Validation:**
```python
def test_english_query_uses_english_stemming(client, auth_headers, english_document):
    # Document contains "financial reports"
    # Query "financial report" should match using english stemmer
    response = client.post("/api/v1/search", json={"query": "financial report"}, headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert any("financial" in r["excerpt"].lower() for r in data["results"])
```

### P2.2 Fuzzy / Trigram Fallback Keyword Search

**File:** `backend/app/services/search_service.py`

**Implementation:**
```python
async def keyword_search_with_fallback(
    self, query: str, limit: int = 50, db: AsyncSession = None, user: User = None,
    regconfig: str = "simple"
) -> list[SearchResult]:
    # 1. Try exact tsvector search first
    results = await self.keyword_search(query, limit, db=db, user=user, regconfig=regconfig)
    if len(results) >= 3:
        return results

    # 2. Fallback: trigram similarity on titles
    logger.info("Keyword search returned %d results; trying trigram fallback", len(results))
    fallback = await self._trigram_fallback_search(query, limit, db=db, user=user)
    # Merge, deduplicate, preserve tsvector rank ordering
    seen = {r.chunk_id for r in results}
    for r in fallback:
        if r.chunk_id not in seen:
            results.append(r)
    return results[:limit]
```

```python
async def _trigram_fallback_search(self, query, limit, db, user):
    bucket_filter = self._get_user_bucket_filter(user) if user else [DocumentBucket.PUBLIC.value]
    sql = text("""
        SELECT
            dc.id as chunk_id, dc.document_id,
            COALESCE(d.original_filename, d.filename) as document_name,
            d.bucket as document_bucket, dc.chunk_text,
            dc.chunk_index, dc.page_number,
            similarity(COALESCE(d.original_filename, d.filename), :query) as rank
        FROM sowknow.document_chunks dc
        JOIN sowknow.documents d ON dc.document_id = d.id
        WHERE d.bucket = ANY(:buckets)
          AND dc.search_vector IS NOT NULL
          AND (COALESCE(d.original_filename, d.filename) % :query
               OR dc.chunk_text % :query)
        ORDER BY GREATEST(
            similarity(COALESCE(d.original_filename, d.filename), :query),
            similarity(dc.chunk_text, :query)
        ) DESC
        LIMIT :limit
    """)
    result = await db.execute(sql, {"query": query, "buckets": bucket_filter, "limit": limit})
    return [...]
```

**Validation:**
```python
def test_typo_query_returns_results_via_trigram(client, auth_headers, test_document):
    # test_document.title = "passport_scan.pdf"
    response = client.post("/api/v1/search", json={"query": "pasport"}, headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["total_found"] > 0, "Typo 'pasport' should find 'passport' via trigram"
```

### P2.3 Integrate Cross-Encoder Re-Ranker

**New File:** `backend/app/services/rerank_service.py`

**Architecture:** Add a lightweight `rerank-server` microservice (similar to `embed-server`) to avoid loading another model in the backend container.

```python
"""Cross-encoder re-ranking service.
Model: cross-encoder/ms-marco-MiniLM-L-6-v2 (~20MB, fast on CPU)
"""
from sentence_transformers import CrossEncoder

class RerankService:
    def __init__(self):
        self.model = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")

    def rerank(self, query: str, passages: list[str]) -> list[tuple[int, float]]:
        """Returns (original_index, score) sorted by score descending."""
        pairs = [(query, p) for p in passages]
        scores = self.model.predict(pairs)
        return sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
```

**New File:** `backend/rerank_server/main.py` (mirrors `embed_server/main.py`)
- Endpoint: `POST /rerank` → accepts `{query: str, passages: list[str]}` → returns `{scores: list[float]}`

**Integration in `search_service.py`:**
```python
async def hybrid_search(self, query, limit=50, ..., rerank: bool = True):
    ...
    # After RRF fusion, before pagination
    if rerank and len(sorted_results) > 1:
        passages = [r["result"].chunk_text for r in sorted_results[:50]]
        rerank_scores = await rerank_client.rerank(query, passages)
        for idx, score in rerank_scores:
            sorted_results[idx]["result"].final_score = (
                0.7 * sorted_results[idx]["result"].final_score +
                0.3 * score  # blend RRF with cross-encoder
            )
        sorted_results.sort(key=lambda x: x["result"].final_score, reverse=True)
    ...
```

**Validation:**
```python
def test_reranker_improves_ordering(client, auth_headers):
    # Seed documents where exact keyword match is less relevant than semantic match
    response = client.post("/api/v1/search", json={"query": "vehicle insurance"}, headers=auth_headers)
    data = response.json()
    # "car insurance policy" should rank above "vehicle registration form"
    # because cross-encoder understands semantic relevance better than RRF alone
    ...
```

### P2.4 Tune HNSW `ef_search`

**File:** `backend/alembic/versions/025_tune_hnsw_ef_search.py` (new migration)

```python
"""Tune HNSW ef_search for better recall."""
from alembic import op

def upgrade():
    op.execute("ALTER INDEX ix_document_chunks_embedding_hnsw SET (ef_search = 100)")
    op.execute("ALTER INDEX ix_articles_embedding_vector SET (ef_search = 100)")

def downgrade():
    op.execute("ALTER INDEX ix_document_chunks_embedding_hnsw SET (ef_search = 40)")
    op.execute("ALTER INDEX ix_articles_embedding_vector SET (ef_search = 40)")
```

**Validation:**
```python
def test_hnsw_ef_search_is_100(test_db):
    result = test_db.execute(text("""
        SELECT reloptions FROM pg_index
        WHERE indexrelname = 'ix_document_chunks_embedding_hnsw'
    """)).scalar()
    assert "ef_search=100" in result
```

### P2.5 Field-Boosted tsvector

**Migration:** `backend/alembic/versions/026_add_weighted_title_tsvector.py`

```python
def upgrade():
    op.execute("""
        ALTER TABLE sowknow.documents
        ADD COLUMN title_search_vector TSVECTOR
        GENERATED ALWAYS AS (
            setweight(to_tsvector('simple', COALESCE(title, '')), 'A') ||
            setweight(to_tsvector('simple', COALESCE(original_filename, '')), 'A')
        ) STORED
    """)
    op.execute("CREATE INDEX idx_documents_title_search ON sowknow.documents USING GIN (title_search_vector)")

def downgrade():
    op.drop_index("idx_documents_title_search", table_name="documents", schema="sowknow")
    op.drop_column("documents", "title_search_vector", schema="sowknow")
```

**Integration:** In `keyword_search()`, combine chunk tsvector rank with title tsvector rank using `ts_rank_cd` weighted sum.

### P2.6 Dynamic Minimum Score Threshold

**File:** `backend/app/services/search_service.py`

```python
def _get_thresholds(query: str) -> tuple[float, float]:
    word_count = len(query.split())
    if word_count <= 3:
        return 0.25, 0.6  # short: strict keyword, looser semantic
    return 0.15, 0.7      # long: looser keyword, strong semantic
```

### Phase 2 QA Commit Criteria

| Gate | Criteria | Evidence |
|------|----------|----------|
| **Automated** | All tests pass; typo recovery test green | CI |
| **Accuracy** | Manual labeling of 50 queries shows Precision@5 ≥ 90% | Spreadsheet + sign-off |
| **Accuracy** | Typo query recovery rate ≥ 80% (e.g., "pasport", "insurnce") | Automated test suite |
| **Accuracy** | English queries show ≥10% improvement over French-default baseline | A/B metric |
| **Latency** | Cross-encoder adds <200ms p95 to hybrid search | Benchmark |
| **Latency** | HNSW tune does not regress p95 by >20% | Benchmark comparison |
| **Observability** | `search_relevance_precision_at_5` gauge visible in Grafana | Screenshot |
| **Rollback** | `alembic downgrade` reverts HNSW + tsvector changes cleanly | Staging test |

---

## Phase 3: Advanced Optimizations (Days 21–35)

**Objective:** Reach 95%+ relevance and p95 <1000ms through lazy synthesis, SQL optimization, spell correction, and user feedback.

### P3.1 Lazy-Load Synthesis in Streaming

**File:** `backend/app/api/search_agent_router.py`

**Current:** Synthesis blocks before `done` event.  
**New:** Emit `results` immediately, then stream `synthesis` as it generates.

```python
async def event_generator():
    ...
    # Stage 4: Results — EMIT IMMEDIATELY
    yield _sse_event("results", {
        "results": [r.model_dump() for r in results],
        "total_found": len(results),
        "has_confidential_results": has_confidential,
    })

    # Stage 5: Synthesis — LAZY, non-blocking for UX
    mode = request.mode
    if mode == SearchMode.AUTO:
        mode = SearchMode.FAST if len(request.query.split()) <= 5 else SearchMode.DEEP

    if results and (mode == SearchMode.DEEP or intent.requires_synthesis):
        yield _sse_event("stage", {"stage": "synthesis", "message": "Synthese de la reponse..."})
        try:
            answer, model_used = await synthesize_answer(...)
            yield _sse_event("synthesis", {
                "answer": answer, "model": model_used, ...
            })
        except Exception as exc:
            logger.warning("Synthesis failed, returning results without answer: %s", exc)
            yield _sse_event("synthesis", {"answer": None, "model": None, "error": True})

    yield _sse_event("done", {...})
```

**Frontend change:** Render results as soon as `event: results` arrives; show a skeleton loader for synthesis.

### P3.2 Single-Query UNION ALL Hybrid Search

**File:** `backend/app/services/search_service.py`

Replace 5 separate DB round-trips with a single UNION ALL query:

```sql
WITH semantic_chunks AS (
    SELECT dc.id as chunk_id, dc.document_id, ...,
           1 - (dc.embedding_vector <=> :embedding::vector) as score,
           'semantic_chunk' as source
    FROM sowknow.document_chunks dc
    JOIN sowknow.documents d ON dc.document_id = d.id
    WHERE d.bucket = ANY(:buckets) AND dc.embedding_vector IS NOT NULL
    ORDER BY dc.embedding_vector <=> :embedding::vector
    LIMIT :limit
),
keyword_chunks AS (
    SELECT dc.id as chunk_id, dc.document_id, ...,
           ts_rank_cd(dc.search_vector, plainto_tsquery(:regconfig, :query), 32) as score,
           'keyword_chunk' as source
    FROM sowknow.document_chunks dc
    JOIN sowknow.documents d ON dc.document_id = d.id
    WHERE d.bucket = ANY(:buckets)
      AND dc.search_vector @@ plainto_tsquery(:regconfig, :query)
    ORDER BY score DESC
    LIMIT :limit
),
-- ... semantic_articles, keyword_articles, tags
combined AS (
    SELECT * FROM semantic_chunks
    UNION ALL SELECT * FROM keyword_chunks
    -- ... etc
)
SELECT * FROM combined
ORDER BY score DESC
LIMIT :limit;
```

### P3.3 Query Spelling Correction (SymSpell)

**New File:** `backend/app/services/spell_service.py`

Use a lightweight SymSpell implementation against document titles and tags:

```python
from symspellpy import SymSpell, Verbosity

class SpellService:
    def __init__(self):
        self.sym_spell = SymSpell(max_dictionary_edit_distance=2, prefix_length=7)
        # Populate from documents.title + tags.tag_name at startup

    def correct(self, query: str) -> tuple[str, bool]:
        suggestions = self.sym_spell.lookup_compound(query, max_edit_distance=2)
        if suggestions and suggestions[0].distance > 0:
            return suggestions[0].term, True
        return query, False
```

### P3.4 Client-Side Search Result Cache

**File:** `frontend/lib/store.ts`

```typescript
interface SearchCache {
  [key: string]: {
    results: SearchResult[];
    timestamp: number;
    query: string;
  }
}

// Add to Zustand store
searchCache: SearchCache;
setSearchCache: (key: string, data: SearchCache[string]) => void;
getCachedSearch: (query: string) => SearchCache[string] | null;

// TTL: 2 minutes
const CACHE_TTL = 120000;
```

### P3.5 User Feedback Loop

**Migration:** `backend/alembic/versions/027_add_search_feedback.py`

```python
op.create_table(
    "search_feedback",
    sa.Column("id", sa.UUID(), primary_key=True),
    sa.Column("user_id", sa.UUID(), nullable=False),
    sa.Column("query_hash", sa.Text(), nullable=False),
    sa.Column("document_id", sa.UUID(), nullable=False),
    sa.Column("feedback_type", sa.Enum("thumbs_up", "thumbs_down", "dismiss", name="feedback_type")),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    schema="sowknow",
)
op.create_index("idx_search_feedback_query", "search_feedback", ["query_hash", "feedback_type"], schema="sowknow")
```

**API:** `POST /api/v1/search/feedback` — body: `{document_id, feedback_type}`

**Frontend:** Add 👍/👎 icons to `ResultCard`.

### Phase 3 QA Commit Criteria

| Gate | Criteria | Evidence |
|------|----------|----------|
| **Automated** | All tests pass | CI |
| **Perceived Speed** | Results visible in <1s for 90% of queries (Web Vitals / custom timing) | RUM data |
| **Accuracy** | Precision@5 ≥ 95% on labeled set | Manual evaluation |
| **Engagement** | User feedback submission rate ≥ 5% of searches | Analytics |
| **Robustness** | Synthesis failure gracefully degrades to raw excerpts | Chaos test |
| **Rollback** | Feature flags allow disabling synthesis, spell correction, and feedback independently | Config test |

---

## Phase 4: Strategic Migration (Months 3–6)

**Objective:** Reach 98% relevance and p99 <200ms through dedicated search infrastructure.

### P4.1 Evaluate Meilisearch as Shadow Index

**Tasks:**
1. Deploy Meilisearch container alongside existing stack
2. Implement dual-write in document upload pipeline (`document_tasks.py`)
3. Build `MeilisearchService` mirroring `HybridSearchService` interface
4. Route 5% of search traffic to Meilisearch via feature flag
5. Compare precision, recall, and latency against PostgreSQL baseline

**Why Meilisearch:**
- Built-in typo tolerance (prefix + Levenshtein)
- Sub-50ms typo-tolerant search out of the box
- Faceting, filtering, and ranking rules are configurable
- Self-hostable (no SaaS dependency)

### P4.2 Domain-Specific Embedding Fine-Tuning

**Tasks:**
1. Collect top-10k most frequent queries + clicked documents from `search_history`
2. Build a contrastive training dataset: (query, positive_doc, negative_doc)
3. Fine-tune `multilingual-e5-large` with 3 epochs
4. A/B test fine-tuned vs. base model on semantic recall

### P4.3 Learned Ranking Model

**Tasks:**
1. Export `search_feedback` + `search_history` as training data
2. Features: semantic_score, keyword_score, cross-encoder_score, user_feedback_avg, click-through rate
3. Train LightGBM LambdaRank model
4. Deploy as `rank-server` microservice; replace linear RRF weights with model inference

### P4.4 Dedicated Search Cluster

**Tasks:**
1. Separate read-replica for search queries
2. Move `embed-server` + `rerank-server` + optional `meilisearch` to dedicated nodes
3. Implement circuit breakers between search cluster and main API

### Phase 4 QA Commit Criteria

| Gate | Criteria | Evidence |
|------|----------|----------|
| **Accuracy** | Precision@5 ≥ 98% | Independent evaluation |
| **Latency** | p99 < 200ms | Load test (100 concurrent users) |
| **Availability** | Search cluster survives single-node failure | Chaos engineering test |
| **Cost** | Search infrastructure cost < 2× current | Cloud billing report |

---

## Rollback Procedures

### Per-Phase Rollback Commands

```bash
# Phase 1 rollback
git revert --no-commit HEAD~6..HEAD  # adjust commit count
alembic downgrade -1  # if any migration was added
sudo systemctl restart sowknow-backend

# Phase 2 rollback (has DB migrations)
git revert --no-commit HEAD~10..HEAD
alembic downgrade 026->025->024  # step through migrations
# Rebuild embed-server / rerank-server images if changed
docker compose up -d --build embed-server rerank-server

# Emergency: disable all new features via feature flags
curl -X POST /admin/flags/search_v2/enabled=false
```

### Feature Flags Table

| Flag | Default | Purpose |
|------|---------|---------|
| `search.skip_llm_intent` | `true` (Phase 1+) | Fast-path simple queries |
| `search.cache.enabled` | `true` (Phase 1+) | Redis embedding + result cache |
| `search.reranker.enabled` | `true` (Phase 2+) | Cross-encoder re-ranking |
| `search.suggestions.enabled` | `true` (Phase 1+) | `/suggest` endpoint + UI |
| `search.language_aware` | `true` (Phase 2+) | Language-specific regconfig |
| `search.lazy_synthesis` | `true` (Phase 3+) | Stream results before synthesis |
| `search.spell_correction` | `true` (Phase 3+) | SymSpell query correction |
| `search.meilisearch.shadow` | `false` (Phase 4) | Dual-write to Meilisearch |
| `search.meilisearch.read` | `false` (Phase 4) | Read from Meilisearch |

---

## Testing Strategy by Phase

### Unit Tests (Every Phase)
- Every new function gets a unit test
- Every bug fix gets a regression test
- Mock external services (LLM, embed-server, rerank-server)

### Integration Tests (Phase 1, 2, 3)
- End-to-end search flow via `TestClient`
- Redis cache hit/miss validation
- Database index usage verification (`EXPLAIN ANALYZE`)

### Performance Tests (Phase 1, 2, 3, 4)
- `backend/tests/performance/test_search_benchmark.py` run before and after each phase
- p95/p99 must improve or stay within 10% of baseline
- Load test with `locust` for concurrent user simulation

### Manual QA Checklist (Every Phase)
- [ ] Search for "passport" → finds passport documents
- [ ] Search for "pasport" (typo) → still finds passport documents (Phase 2+)
- [ ] Type "fin" in SearchModal → sees "financial_report.pdf" suggestion (Phase 1+)
- [ ] Switch language to English → "financial report" finds English docs (Phase 2+)
- [ ] Search results appear in <1s (Phase 1+), <500ms (Phase 3+)
- [ ] Confidential documents only visible to Admin/SuperUser
- [ ] Synthesis failure shows raw excerpts, not error page (Phase 3+)
- [ ] Thumbs up/down buttons visible and clickable (Phase 3+)

---

## Communication Plan

| Stakeholder | Update Frequency | Channel |
|-------------|------------------|---------|
| Engineering Team | Daily standup | Slack #search-improvements |
| Product Owner | Phase boundaries + QA commits | Email + Notion |
| QA Engineer | Weekly + per-phase sign-off | Jira + QA portal |
| Users | After Phase 1 and Phase 3 | In-app changelog |
| Exec Sponsors | Monthly | Dashboard + brief |

---

## Appendix: File Inventory

### New Files
```
backend/app/api/search_suggest.py
backend/app/services/search_cache.py
backend/app/services/rerank_service.py
backend/app/services/spell_service.py
backend/rerank_server/main.py
backend/rerank_server/Dockerfile
backend/rerank_server/requirements.txt
backend/tests/unit/test_search_suggest.py
backend/tests/performance/test_search_benchmark.py
backend/alembic/versions/025_tune_hnsw_ef_search.py
backend/alembic/versions/026_add_weighted_title_tsvector.py
backend/alembic/versions/027_add_search_feedback.py
```

### Modified Files
```
backend/app/main.py                          # Register suggest router
backend/app/api/search_agent_router.py       # Parallel sub-queries, lazy synthesis, timing
backend/app/services/search_service.py       # Language-aware FTS, fuzzy fallback, cache hooks
backend/app/services/search_agent.py         # Fast-path intent, feedback integration
backend/app/services/prometheus_metrics.py   # New histograms
backend/app/services/embed_client.py         # Cache-aware
backend/tests/unit/test_search.py            # Fix xfail suggest test
backend/tests/unit/test_search_agent.py      # Parallelism tests
frontend/components/SearchModal.tsx          # Autocomplete dropdown
frontend/app/[locale]/search/page.tsx        # Suggest integration, lazy synthesis skeleton
frontend/lib/api.ts                          # suggest() method
frontend/lib/store.ts                        # Search cache
```

---

*Remediation Plan v1.0 — Ready for Phase 0 kickoff*
