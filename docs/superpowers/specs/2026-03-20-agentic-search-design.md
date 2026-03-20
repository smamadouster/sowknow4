# Agentic Search Enhancement — Design Spec

**Date:** 2026-03-20
**Status:** Approved
**Approach:** Surgical Integration — add new agentic modules, replace existing search router

## Overview

Replace the current basic hybrid search (`/api/v1/search`) and multi-agent search (`/api/v1/multi-agent/search`) with a unified 6-stage agentic search pipeline. The new pipeline provides intent classification, query expansion, hybrid retrieval, re-ranking, LLM synthesis with privacy routing, and follow-up suggestions — all exposed via both JSON and SSE streaming endpoints.

## Pipeline Stages

1. **IntentAgent** — Classify intent (factual/temporal/comparative/synthesis/financial/etc.), extract entities, decompose complex queries into sub-queries. Always uses Kimi (no document content).
2. **QueryExpander** — Build search query variants from original + sub-queries + keyword-focused variant.
3. **HybridRetriever** — pgvector semantic + PostgreSQL FTS with RRF fusion. RBAC bucket filtering at SQL level.
4. **ReRanker** — Collapse chunks to document-level results, normalize scores, assign relevance labels (highly_relevant/relevant/partially/marginal).
5. **SynthesisAgent** — LLM answer generation with privacy routing (Kimi for public, Ollama for confidential).
6. **SuggestionAgent** — Generate 3-5 follow-up query suggestions. Never includes document content (safe for Kimi).

## Backend Architecture

### New Files

| File | Purpose |
|------|---------|
| `backend/app/services/search_models.py` | Pydantic models & enums (SearchRequest, SearchResponse, ParsedIntent, RawChunk, SearchResult, Citation, etc.) |
| `backend/app/services/search_agent.py` | 6-stage orchestrator. Calls existing `search_service.py` for Stage 3 retrieval. Uses existing `llm_router.py` for LLM calls. |
| `backend/app/api/search_agent_router.py` | FastAPI router with JSON + SSE + intent preview + history endpoints |
| `backend/tests/test_search_agent.py` | Unit tests for RBAC, LLM routing, scoring, intent parsing, citations |

### Modified Files

| File | Change |
|------|--------|
| `backend/app/main.py` | Swap `search.router` and `multi_agent.router` for `search_agent_router.router` |
| `backend/app/services/search_service.py` | Keep as internal utility — `search_agent.py` reuses its hybrid_search SQL |

### Deleted Files

| File | Reason |
|------|--------|
| `backend/app/api/search.py` | Replaced by `search_agent_router.py` |
| `backend/app/api/multi_agent.py` | Subsumed by agentic search pipeline |

### Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/v1/search` | Full agentic search (JSON response) |
| POST | `/api/v1/search/stream` | SSE streaming with per-stage events |
| POST | `/api/v1/search/intent` | Lightweight intent preview (no retrieval) |
| GET | `/api/v1/search/history` | User's last N searches |

### Key Adaptations from Uploaded Reference Files

- No `from __future__ import annotations` (breaks FastAPI/Pydantic per commit d138474)
- Imports use project structure: `backend.app.core.config`, `backend.app.api.deps`, `backend.app.database`
- Router prefix: `/api/v1/search` (existing convention)
- Auth: existing `get_current_user` from `deps.py`, map `User.role` to `UserRole` enum
- LLM calls: use existing `llm_router.py` instead of raw httpx to Kimi/Ollama
- Hybrid retrieval: delegate to existing `search_service.py` SQL patterns
- Column names: `embedding_vector` (not `embedding`), `search_vector` (not `ts_vector`)
- Concurrency: keep existing semaphore pattern (max 5 concurrent)
- Search history: write-through after each search completes

## Database Migration

### New Table: `search_history`

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK, gen_random_uuid() |
| user_id | UUID | FK -> users.id CASCADE |
| query | Text | |
| parsed_intent | String(50) | |
| result_count | Integer | |
| has_confidential_results | Boolean | |
| llm_model_used | String(100) | |
| search_time_ms | Integer | |
| performed_at | TimestampTZ | default NOW() |

Index: `(user_id, performed_at)`

### Schema Additions to `document_chunks`

- `bucket` column (String(20), default 'public') — denormalized from parent document
- Trigger `trg_sync_chunk_bucket` — auto-populate bucket from parent on INSERT/UPDATE
- Composite index `idx_chunks_bucket_doc` on `(bucket, document_id)`

### New Indexes (if not already present)

- HNSW on `embedding_vector` (vector_cosine_ops, m=16, ef_construction=64)
- Partial index on `documents(status)` WHERE status = 'indexed'
- Trigram index on `documents(title)` (requires pg_trgm extension)

### Skipped from uploaded migration

- `ts_vector` column — already exists as `search_vector` from migration 009

## Frontend Design

### Modified File

`frontend/app/[locale]/search/page.tsx` — full rewrite

### Adaptations

- **Styling:** Tailwind CSS (no inline styles)
- **i18n:** All strings via `useTranslations('search')` from next-intl, added to `en.json` and `fr.json`
- **Auth:** httpOnly cookie auth via `credentials: 'include'` on fetch, CSRF token included
- **State:** Local `useState` (page-scoped, no Zustand needed)

### Components (all in search/page.tsx)

- `PipelineProgress` — stage dots with Tailwind transitions
- `IntentBadge` — intent type + confidence + keyword chips
- `SynthesisBlock` — collapsible answer card with Ollama/Kimi model badge
- `ResultCard` — tiered result with relevance dot, excerpt, highlights, tags
- `Suggestions` — follow-up query chips
- `CitationsPanel` — sticky sidebar with source excerpts

### New Translation Keys (~30)

Added under `search` namespace in both `en.json` and `fr.json`:
- Stage messages: `search.stage.intent`, `search.stage.retrieval`, `search.stage.reranking`, `search.stage.synthesis`
- Labels: `search.synthesizedAnswer`, `search.sources`, `search.suggestions`, `search.confidence`
- Empty state: `search.empty.title`, `search.empty.subtitle`
- Relevance tiers: `search.relevance.highlyRelevant`, `search.relevance.relevant`, `search.relevance.partially`, `search.relevance.marginal`
- Intent types: `search.intent.factual`, `search.intent.temporal`, etc.

## Test Coverage

38 unit tests across 8 test classes:

- `TestRelevanceLabels` (7) — threshold boundary tests
- `TestRBACEnforcement` (6) — confidential visibility per role (SECURITY CRITICAL)
- `TestLLMRouting` (3) — privacy invariant: confidential -> Ollama
- `TestQueryExpansion` (4) — sub-queries, dedup, keyword variants
- `TestResultRanking` (4) — sort order, ranks, top_k, chunk collapse
- `TestCitations` (4) — match results, one-per-doc, max 10, excerpt length
- `TestFallbackIntent` (6) — temporal/financial detection, language, keywords
- `TestSearchRequestValidation` (4) — empty query, whitespace, defaults, bounds

## Security Invariants

1. `UserRole.USER` NEVER sees confidential documents — enforced at SQL level (Stage 3) AND re-rank level (Stage 4)
2. Confidential document content NEVER reaches Kimi/MiniMax APIs — enforced by `_route_llm` checking `has_confidential`
3. Intent parsing and suggestion generation NEVER include document content — always safe for external LLM
4. All confidential access logged with user ID and timestamp

## Privacy Routing Rules

| Context | LLM Used |
|---------|----------|
| Intent parsing (no doc content) | Kimi |
| Synthesis with all-public results | Kimi |
| Synthesis with any confidential result | Ollama |
| Suggestion generation (no doc content) | Kimi |
