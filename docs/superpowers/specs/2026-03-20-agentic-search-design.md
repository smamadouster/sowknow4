# Agentic Search Enhancement — Design Spec

**Date:** 2026-03-20
**Status:** Approved (revised after spec review)
**Approach:** Surgical Integration — add new agentic modules, replace existing search router

## Overview

Replace the current basic hybrid search (`/api/v1/search`) and multi-agent search (`/api/v1/multi-agent/search`) with a unified 6-stage agentic search pipeline. The new pipeline provides intent classification, query expansion, hybrid retrieval, re-ranking, LLM synthesis with privacy routing, and follow-up suggestions — all exposed via both JSON and SSE streaming endpoints.

## Pipeline Stages

1. **IntentAgent** — Classify intent (factual/temporal/comparative/synthesis/financial/etc.), extract entities, decompose complex queries into sub-queries. Always uses MiniMax 2.7 (no document content).
2. **QueryExpander** — Build search query variants from original + sub-queries + keyword-focused variant.
3. **HybridRetriever** — pgvector semantic + PostgreSQL FTS with RRF fusion. RBAC bucket filtering at SQL level.
4. **ReRanker** — Collapse chunks to document-level results, normalize scores, assign relevance labels (highly_relevant/relevant/partially/marginal).
5. **SynthesisAgent** — LLM answer generation with privacy routing (MiniMax via existing LLMRouter for public RAG, Ollama for confidential).
6. **SuggestionAgent** — Generate 3-5 follow-up query suggestions. Never includes document content (safe for MiniMax 2.7).

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
- Auth: existing `get_current_user` from `deps.py`, import `UserRole` from `app.models.user` (no duplicate enum)
- LLM calls: use existing `llm_router.py` (`LLMRouter.generate_completion`) — this is an `AsyncGenerator[str, None]`, so collect full response by iterating and concatenating chunks. Construct `messages` list per existing calling convention.
- Hybrid retrieval: delegate to existing `search_service.py` SQL patterns
- Column names: `embedding_vector` (not `embedding`), `search_vector` (not `ts_vector`)
- SQL schema: all raw SQL must use `sowknow.` schema prefix (e.g., `sowknow.document_chunks`, `sowknow.documents`)
- Concurrency: keep existing semaphore pattern (max 5 concurrent)
- Search history: write-through after each search completes
- Old `/search/suggest` endpoint dropped — replaced by SuggestionAgent (Stage 6)

## Database Migration

### New Table: `sowknow.search_history`

Table must be in `sowknow` schema (matching all other tables).

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK, gen_random_uuid() |
| user_id | UUID | FK -> sowknow.users.id CASCADE |
| query | Text | |
| parsed_intent | String(50) | |
| result_count | Integer | |
| has_confidential_results | Boolean | |
| llm_model_used | String(100) | |
| search_time_ms | Integer | |
| performed_at | TimestampTZ | server_default=text("NOW()") |

Index: `(user_id, performed_at)`

Migration revision must chain from the current Alembic HEAD (determine at implementation time by running `alembic heads`).

### No schema changes to `document_chunks`

The uploaded spec proposed a denormalized `bucket` column on `document_chunks`. We skip this entirely. RBAC filtering uses the existing JOIN to `sowknow.documents` and filters on `documents.bucket` — this is already proven in `search_service.py`. The ReRanker (Stage 4) gets bucket info from the JOIN results, not a separate column.

### New Indexes (only if not already present)

- HNSW on `embedding_vector` — **already exists** from migration 010 (`ix_document_chunks_embedding_hnsw`). Skip.
- Partial index on `sowknow.documents(status)` WHERE status = 'indexed' — add with `IF NOT EXISTS`
- Trigram index on `sowknow.documents(title)` — add with `IF NOT EXISTS` (requires `pg_trgm` extension, add `CREATE EXTENSION IF NOT EXISTS pg_trgm`)

### Skipped from uploaded migration

- `ts_vector` column — already exists as `search_vector` from migration 009
- `bucket` column on `document_chunks` — use existing JOIN pattern instead
- HNSW index — already exists from migration 010

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

1. `UserRole.USER` NEVER sees confidential documents — enforced at SQL level via JOIN to `documents.bucket` (Stage 3) AND re-rank level (Stage 4)
2. Confidential document content NEVER reaches Kimi/MiniMax APIs — enforced by `LLMRouter` checking `has_confidential`
3. Intent parsing and suggestion generation NEVER include document content — always safe for MiniMax 2.7
4. All confidential access logged with user ID and timestamp
5. SSE POST endpoint (`/api/v1/search/stream`) is CSRF-safe: cookie requests include CSRF token (existing middleware), Bearer-token requests are already exempt (commit 4fa03b7)

## Privacy Routing Rules

Uses existing `LLMRouter.select_provider` chains, NOT direct httpx calls:

| Context | LLM | Notes |
|---------|-----|-------|
| Intent parsing (no doc content) | MiniMax 2.7 | Lightweight classification task, no document content |
| Synthesis with all-public results | MiniMax 2.7 (public_docs_rag chain) | Follows existing router with context caching for cost optimization |
| Synthesis with any confidential result | Ollama only | `has_confidential=True` forces Ollama, no fallback to external |
| Suggestion generation (no doc content) | MiniMax 2.7 | Lightweight generation task, no document content |

**Note:** MiniMax 2.7 replaces Kimi 2.5 for all external LLM calls (intent parsing, public synthesis, suggestions). This simplifies the tri-LLM strategy to a dual-LLM approach for search: MiniMax 2.7 for public contexts, Ollama for confidential. Context caching on MiniMax provides cost optimization on repeated queries.
