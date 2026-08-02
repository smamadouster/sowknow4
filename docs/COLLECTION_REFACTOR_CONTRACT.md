# Collection Module Refactoring — Search Integration Contract (Phase 0 sign-off)

Date: 2026-08-02
Spec: `docs/collection_refactor/Collection_Module_Refactoring_Spec_v2.0.pdf` (§2.5)
Status: Verified against code. Signed off for Phase 1 build.

## 0. Premise correction

The spec assumes the Collection module is "non-functional". Code exploration shows
**Smart Collections** (`backend/app/api/collections.py`, `services/collection_service.py`)
and **Smart Folders v2** (`backend/app/services/smart_folder/`) are both wired and
functional (70 collection unit tests pass). Two real defects were found and fixed in
Phase 0:

1. `GET /api/v1/smart-folders/reports/{report_id}` returned 501 (`smart_folders.py`).
2. All `/api/v1/collections` endpoints were gated `require_superuser_or_admin`, so
   regular users received 403 — the probable origin of the "non-functional" report.

The refactoring therefore **extends Smart Folders v2** into the spec's Collection
orchestration layer; it does not rebuild from zero.

## 1. Verified capability table (spec §2.5)

The Collection layer consumes the Search module **as an in-process library**
(`HybridSearchService`, `backend/app/services/search_service.py`) — the same pattern
already used by `collection_service.py`. The Search module is never modified (NFR-7).

| Spec capability | Verified fact (file:line) | Adaptation |
|---|---|---|
| Keyword query with filters | `hybrid_search()` exists; `date_from/date_to/filter_tags/filter_doc_types` are declared in `AgenticSearchRequest` (`search_models.py:42`) but **never applied** | Search Adapter applies filters at **DB level** (SQL `WHERE` on `documents` metadata: `created_at`, `document_metadata`, tags) around hybrid search. This is pushdown to the database, not client-side filtering of unfiltered corpora (FR2.1 preserved in spirit). |
| User-context passthrough / ACL | ✅ `_get_user_bucket_filter` (`search_service.py:90`); denormalized `document_chunks.bucket` (migration 034); `_strip_confidential_chunks` (`search_agent.py:578`); fail-closed bucket parsing (`search_agent_router.py:64`) | Full `User` object passed on every call. Collection layer never elevates privileges (FR2.7). |
| Result metadata | title, type (file ext), bucket, score, excerpt, highlights, page_number (`search_models.py:101`). **No author, no path/URI; `document_date` always null** | Adapter enriches items from the `Document` ORM (`file_path`, `mime_type`, `created_at`, `document_metadata` JSONB). |
| Relevance scores | ✅ calibrated 0–1; RRF fusion; sigmoid-squashed rerank; absolute labels (`search_agent.py:44`) | Used as-is inside the versioned ranking formula (FR3.4). No unbounded boosts. |
| Snippets / highlights | ✅ `excerpt` (≤400 chars), `highlights` (top-3 sentences), full `chunk_text` in raw results | Annotations cite these; evidence offsets computed by the Extraction Pipeline when needed. |
| Cursor pagination | ❌ offset only (`limit/offset`, `total`); agentic `top_k` ≤ 50 | Offset pagination with duplicate-guard on page boundaries; hard cap 100,000 items (A5). |
| Semantic / vector search | ✅ pgvector HNSW cosine via `semantic_search` (`search_service.py:131`); graceful keyword-only degradation | FR2.6 "client-side reranker" satisfied by the existing `rerank_service.rerank_passages` (top-N). No new embedding infra. |
| Content fetch by item ID | ❌ no dedicated endpoint; `DocumentChunk` ORM + `GET /documents/{id}/download` exist | Adapter fetches full text via ORM (chunks) / storage service (files). |
| Multi-source federation | ❌ single corpus (documents + articles) | Query Planner decomposes into per-type calls and merges (FR2.2). |

## 2. Reused infrastructure (no new providers)

- **LLM**: `llm_router` / `openrouter_service` — tiers simple/standard = `gemini-2.5-flash`,
  complex = `claude-sonnet-4` (env `OPENROUTER_TIER_*`). Approved data boundary (FR7.5).
- **Embeddings**: `embed_client` → embed-server / embed-server-2 (`intfloat/multilingual-e5-large`).
- **Rerank**: `rerank_service` → rerank-server (cross-encoder, sigmoid-squashed).
- **Async**: Celery `collections` queue (`celery_app.py:93`); task idiom per
  `tasks/collection_report_tasks.py`; SSE-over-Celery pattern per
  `api/smart_folders.py:579` (`AsyncResult` polling, `X-Accel-Buffering: no`).
- **PDF export**: reportlab (already used by collections export).

## 3. Open questions resolved (spec §7)

1. **Search API confirmation** — done; this document is the signed-off contract.
2. **Multi-language scope** — in scope: multilingual-e5 embeddings + en/fr UI.
   Extraction regexes are language-agnostic (numbers/dates); narrative language follows
   user locale.
3. **Analysis budget** — default 10,000 items for full FR4 analysis; env-configurable
   (`COLLECTION_ANALYSIS_BUDGET`); truncation disclosure per FR6.3.
4. **Deliverable retention** — deliverables + FactSets retained until user deletes the
   collection request; audit events retained per FR8.4 (default 7 years, tenant-config).
5. **Export branding** — none for v2.0; header/footer carries request params,
   generation timestamp, data-as-of date (FR5.6).
6. **Sharing model** — deliverables are owner-only in v2.0; links are permission-bound
   and re-checked at click time (FR5.3/FR7.3).
7. **Reranker model** — existing rerank-server cross-encoder (already inside the data
   boundary); no new model approval needed.

## 4. Extraction spike baseline

See `docs/collection_refactor/EXTRACTION_SPIKE.md` — results of running the extraction
prototype (table extractor + numeric/date/entity regexes) over 50 representative chunks.

## 5. Explicit non-goals (NFR-7)

No changes to: `search_service.py`, `search_agent.py`, `search_agent_router.py`,
embed-server, rerank-server. Any capability gap is absorbed by the Search Adapter
inside the Collection layer.
