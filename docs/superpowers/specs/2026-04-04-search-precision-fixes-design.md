# Search Precision Fixes — Design Spec

**Date**: 2026-04-04
**Problem**: Irrelevant results ranked high, especially for short queries (2-3 words)
**Approach**: Fix foundational bugs and tuning gaps (Approach A — no new dependencies)

## Fix 1: Query Embedding Prefix

**File**: `backend/app/services/embedding_service.py`

`multilingual-e5-large` requires `"query: "` prefix for search queries and `"passage: "` for stored documents. Currently `encode_single()` always applies `"passage: "` via `encode()`. Search queries get the wrong prefix, producing noisy similarity scores.

**Change**:
- Add `encode_query(text)` method that prefixes with `"query: "` before encoding
- Keep `encode()` / `encode_single()` unchanged (they handle passages at indexing time)

**File**: `backend/app/services/search_service.py`

- Lines 150 and 383: replace `embedding_service.encode_single(query)` with `embedding_service.encode_query(query)`

## Fix 2: Apply Minimum Score Cutoff

**File**: `backend/app/services/search_service.py`

`min_score_threshold=0.1` is defined at line 68 but never applied. All results pass through regardless of score.

**Change**: In `hybrid_search()`, after computing `final_score` for each result (line 685-686), filter out results where `final_score < self.min_score_threshold` before sorting.

## Fix 3: Adaptive Weights for Short Queries

**File**: `backend/app/services/search_service.py`

Short queries (≤3 words) produce sparse embeddings with weak semantic signal. The fixed 0.7 semantic / 0.3 keyword split underweights exact keyword matches.

**Change**: At the start of `hybrid_search()`, detect short queries and adjust weights:
- `word_count <= 3`: semantic=0.4, keyword=0.6
- `word_count > 3`: keep semantic=0.7, keyword=0.3 (current default)

Use local variables, don't mutate `self` weights.

## Fix 4: Multi-Chunk Document Scoring

**File**: `backend/app/services/search_agent.py`, `rerank_and_build_results()`

Currently picks the single best chunk per document (line 76). A document with one spurious high-scoring chunk outranks a document with multiple moderately-relevant chunks.

**Change**: Score documents using top-2 chunk average:
```python
sorted_chunks = sorted(doc_chunks, key=lambda c: c.rrf_score, reverse=True)
top_chunks = sorted_chunks[:2]
avg_score = sum(c.rrf_score for c in top_chunks) / len(top_chunks)
best = sorted_chunks[0]  # still use best chunk for excerpt/metadata
```

Use `avg_score` instead of `best.rrf_score` for normalization and labeling.

## Files Changed

| File | Fixes |
|------|-------|
| `backend/app/services/embedding_service.py` | Fix 1: add `encode_query()` |
| `backend/app/services/search_service.py` | Fix 1: use `encode_query()`, Fix 2: score cutoff, Fix 3: adaptive weights |
| `backend/app/services/search_agent.py` | Fix 4: multi-chunk scoring |

## Verification

- Backend container starts without import errors
- Existing embedding tests still pass (passage encoding unchanged)
- Manual search test: short query returns fewer, more relevant results
