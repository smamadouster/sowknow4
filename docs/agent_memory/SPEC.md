# Agent Memory Layer — Design Spec (draft v0.1)

**Date:** 2026-08-05
**Status:** PoC implemented (migration 037 + models + L1 distillation + Celery
task + opt-in flag). L2 clustering / L3 profile / injection / panel deferred.
**Inspiration:** TencentDB Agent-Memory layered memory model (L0→L3),
adapted to SOWKNOW's existing FastAPI + Postgres(pgvector) + Celery stack.

## 1. Problem

SOWKNOW chat today is session-scoped: `chat_service.get_conversation_history`
replays the last ~20 messages of *one* session, then discards everything.
Nothing accumulates across sessions, so agents re-learn the user (preferences,
decisions, recurring facts) on every new chat, and no conversation ever feeds
back into search or collections.

## 2. Goal

Add a **persistent, layered memory** distilled from chat conversations, stored
in new tables, retrievable via the existing search stack, and injected into
chat context only when the user opts in. **Non-breaking:** all changes are
additive migrations + new background jobs + opt-in flags. The existing hot
paths (`chat_service.get_conversation_history`, `hybrid_search`, ACL bucket
filtering, search rerank) are untouched.

## 3. Memory layers

| Layer | Stores | Retention | Source |
|---|---|---|---|
| **L0 Conversation** | raw chat messages (already in `chat_messages`) | existing | existing |
| **L1 Atom** | facts / preferences / constraints / decisions extracted from a conversation | deduped, capped | new |
| **L2 Scenario** | knowledge blocks organized around a project/scenario | capped | new |
| **L3 Profile** | long-term user + team profile (persona, stable patterns) | high-level | new |

L0 already exists (`ChatMessage`). This spec adds L1, L2, L3 as new tables
(one additive migration) plus a distillation pipeline that fills them.

## 4. Schema (migration 037, additive only)

All new tables in `sowknow` schema, GUID PKs, `TimestampMixin`, no FK to any
hot-path table. Default visibility `private`.

### 4.1 `memory_atoms` (L1)

| column | type | notes |
|---|---|---|
| id | uuid PK | |
| user_id | uuid | owner (FK `sowknow.users`, cascade) |
| kind | str | `fact` \| `preference` \| `constraint` \| `decision` |
| statement | text | canonical one-line memory |
| confidence | int | 0-100 |
| source_message_ids | jsonb | traceability back to `chat_messages` |
| source_session_ids | jsonb | |
| entity_ids | jsonb | optional links to `entities` |
| search_vector | tsvector | accent-folded (`sowknow.unaccent`), for hybrid retrieval |
| visibility | str | `private` \| `team` \| `agent` (default `private`) |
| status | str | `pending` \| `reviewed` \| `rejected` (default `pending`) |
| first_seen_at / last_seen_at | timestamptz | for decay/dedup |

### 4.2 `memory_scenarios` (L2)

| column | type | notes |
|---|---|---|
| id | uuid PK | |
| user_id | uuid | owner |
| title | text | e.g. "Relocation to Dakar — moving company negotiation" |
| summary | text | distilled block |
| scope | text | free-form project/scenario label |
| atom_ids | jsonb | L1 atoms folded into this block |
| source_session_ids | jsonb | |
| search_vector | tsvector | accent-folded |
| visibility | str | default `private` |
| status | str | `pending` \| `ready` \| `stale` (default `pending`) |
| last_used_at | timestamptz | staleness |

### 4.3 `memory_profiles` (L3)

| column | type | notes |
|---|---|---|
| id | uuid PK | |
| user_id | uuid | owner (one row per user, upsert) |
| persona | jsonb | {communication_pref, priorities, decision_style, ...} |
| stable_patterns | jsonb | recurring behaviors observed across scenarios |
| version | int | increment on each rewrite |
| updated_at | timestamptz | |

### 4.4 `memory_asset_bindings`

| column | type | notes |
|---|---|---|
| id | uuid PK | |
| agent_scope | str | e.g. `chat:default`, `collection:legal` |
| asset_type | str | `atom` \| `scenario` \| `profile` |
| asset_id | uuid | FK to the asset table |
| user_id | uuid | owner |
| priority | int | injection order |
| enabled | bool | per-binding opt-in |
| usage_count / last_used_at | int / ts | for pruning |

## 5. Distillation pipeline

### 5.1 Trigger

After an assistant turn is persisted in `chat_messages`, enqueue a lightweight
`memory.distill` task (deduped by `(session_id, message_id)` in Redis). Batched
nightly job processes accumulated sessions. Idempotency key = session id.

### 5.2 Extraction (L1)

`memory.extract_atoms(session_id)`:
1. Load full session messages (bounded, e.g. latest 40 turns).
2. LLM call (simple tier via `llm_gateway`, French-first prompts, same
   `build_service_prompt` convention) returns a JSON list of candidate atoms:
   `[{kind, statement, confidence}]`.
3. Parse via `smart_folder/query_parser.extract_first_json` (never naive
   brace-slicing — the `__USAGE__` sentinel trap).
4. **GroundingValidator-style check** (reuse `collection_orchestrator/grounding_validator.py`):
   a candidate is dropped unless its claim is traceable to a message (source
   message id) or a known entity. No fabricated atoms.
5. Dedup vs existing atoms for the same user (embedding similarity via
   `embed_client` on `statement`; skip if > 0.92 cosine). Update `last_seen_at`
   on hit, else insert with `status=pending`.

### 5.3 Clustering (L2)

`memory.build_scenarios(user_id)`: nightly job clusters L1 atoms by
(embedding + entity overlap + temporal proximity). A cluster becomes a
`memory_scenarios` row when ≥ 3 atoms converge. Idempotent: skip clusters whose
atoms are already folded (compare `atom_ids` set).

### 5.4 Profile (L3)

`memory.build_profile(user_id)`: monthly LLM pass over reviewed atoms +
scenarios → upsert `memory_profiles` with `version+1`. Only uses
`status=reviewed` atoms (never raw pending).

## 6. Retrieval + injection (opt-in only)

### 6.1 Storage/search

`search_vector` on atoms/scenarios is accent-folded with the SAME
`to_tsvector(<cfg>, sowknow.unaccent(...))` expression as migration 036, so the
existing multi-config `@@` pattern (french/english/simple) and pgvector search
work unchanged. New search paths are additive — `hybrid_search` is untouched.

### 6.2 Injection

New `ChatService` option `memory_enabled` (per session, via
`chat_sessions.memory_enabled` — additive column, default false). When enabled:
1. Retrieve top-k memory (atoms + scenarios) for the query via the additive
   memory search service (budget: ≤ 6 atoms, ≤ 2 scenarios, ≤ 1200 chars).
2. Inject as a `memory` context block before the RAG context, labeled and
   timestamped, only for `status=reviewed|ready` assets and `visibility`
   the user can see (owner or team).
3. Exact behavior identical to today when the flag is off — zero regression.

### 6.3 ACL safety

Memory tables have their own `visibility` column. Search filters memory on the
memory table directly (no JOIN to documents). This keeps the document ACL hot
path (bucket on `document_chunks`) completely untouched. Default `private`
means nothing leaks by default.

## 7. Ops & lifecycle

- **Queue:** `collections` queue (same checkpoint idiom as
  `collection_request_tasks.py`); async runner inside `@shared_task` with its
  own `AsyncSessionLocal`. No autoretry — the memory row status is the source
  of truth; failures leave `status=pending` for a later sweep.
- **Budget caps:** `MEMORY_ATOM_MAX`, `MEMORY_SCENARIO_MAX`,
  `MEMORY_INJECT_MAX_CHARS`, `MEMORY_ATOM_SIM_THRESHOLD=0.92` — settings, not
  constants (matches `COLLECTION_*` doctrine).
- **Decay:** atoms with `last_seen_at` older than 180 days and
  `status=reviewed` are archived (moved out of search) — configurable.
- **Audit:** reuse `audit_logger` — `memory.distilled`, `memory.atom_reviewed`,
  `memory.asset_bound` actions. Append-only.
- **Migration:** 037 is additive only (new tables + new column on
  `chat_sessions`). No `CONCURRENTLY` index builds needed at first; if search
  on memory tables needs it, follow the 010/036 lessons (explicit ops step).

## 8. Non-goals / deferrals

- No codegraph / wiki / skills auto-extraction in v1 (existing SCIP + static
  skills already cover the need; revisit later).
- No cross-framework memory portability (single stack).
- No automatic routing of memory to collections without a reviewed atom.

## 9. Suggested implementation order

1. ✅ Migration 037 (tables) + models + `memory_enabled` column.
2. ✅ `memory_service.py`: atom extraction + dedup + grounding (reuse validator).
3. ✅ Celery task + trigger hook in `chat_service` (enqueue only; no behavior change).
4. ⏳ Nightly scenario clustering job.
5. ⏳ Memory search service (additive endpoint) + injection behind the flag.
6. ⏳ Panel/API to review atoms (`pending→reviewed`), bind assets, view usage.
7. ⏳ Backfill: distill existing chat sessions (id-ordered batches, resumable —
   mirror `migration036_backfill.py` lessons).

## 10. Implemented surface (2026-08-05)

- `backend/app/models/memory.py` — MemoryAtom (L1), MemoryScenario (L2),
  MemoryProfile (L3), MemoryAssetBinding. All own-schema, default `private`.
- `backend/alembic/versions/037_agent_memory.py` — additive tables +
  `chat_sessions.memory_enabled` (default false).
- `backend/app/services/memory_service.py` — `distill_session`:
  LLM extraction (French-first, JSON-only via `extract_first_json`), grounding
  (atom dropped unless traceable to a real source message index), confidence
  gate (`MEMORY_ATOM_MIN_CONFIDENCE`), semantic dedup
  (`MEMORY_ATOM_SIM_THRESHOLD`, embed-unavailable → skip not fail), all new
  atoms `status=pending` + `visibility=private`.
- `backend/app/tasks/memory_tasks.py` — `distill_chat_session` on the
  `collections` queue, async runner + NullPool idiom, no autoretry (row status
  is source of truth).
- `backend/app/api/chat.py` + `schemas/chat.py` — `memory_enabled` on session
  create/response; after each assistant turn, `_maybe_enqueue_memory_distill`
  enqueues distillation (off by default, best-effort, never blocks the reply).
- Tests: `backend/tests/unit/test_memory_service.py` (15 tests).
