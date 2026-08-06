# AGENTS.md — SOWKNOW4

Personal/family knowledge vault. FastAPI + Postgres(pgvector) + Celery + Next.js,
self-hosted Docker on a single VPS. Deploy target IS this repo:
`docker compose -f docker-compose.production.yml` (container prefix `sowknow-`).

## Deploy — read before touching production

- **Only via `scripts/deploy.sh`.** It builds ALL image tags (backend, celery-*,
  telegram-bot, embed-server*, guardian-hc all have separate tags), refuses to
  deploy during index builds, and always uses `--no-deps`.
- **Never plain `docker compose up` after `.env` edits** — compose recreates
  every env_file consumer INCLUDING POSTGRES (killed a REINDEX mid-flight once).
- **Never `compose down`, never `-v`.** Data lives in named volumes.
- Index-building migrations: `CONCURRENTLY` only (migration 010's blocking
  CREATE INDEX died mid-build and left semantic search exact-scanning for months).

## Search architecture (as of 2026-07-28 P0 rebuild)

- Retrieval: pgvector HNSW (cosine) + tsvector GIN + pg_trgm, RRF fusion,
  cross-encoder rerank (`rerank-server`), agentic SSE pipeline
  (`backend/app/api/search_agent_router.py`, `services/search_agent.py`,
  `services/search_service.py`).
  pg_trgm typo-fallback is FILENAME-ONLY (2026-07-29): `chunk_text % query`
  at 1.37M chunks matched 40k+ GIN candidates = 5-13s for noise results.
  Never re-add trigram similarity over chunk_text.
- ACL: two buckets (public/confidential). `document_chunks.bucket` is
  denormalized (migration 034, trigger-maintained) — filter ACL on the chunk
  table, never via JOIN (join filter = planner abandons HNSW).
- Keyword search is MULTI-CONFIG (2026-08-04): `search_vector` is stemmed with
  the chunk's `search_language` (default 'french'), so matching must OR
  `french` + `english` + `simple` (plus the caller's regconfig) in the `@@`
  filter and rank via `GREATEST` across configs. Matching with 'simple' only
  silently missed every French-stemmed body match (verified live:
  "vaccination" → 0 vs 1, "contrat de bail" → 159 vs 395). Never drop the
  multi-config branches.
- Keyword search is ACCENT-FOLDED (migration 036, 2026-08-04): `search_vector`
  is re-stemmed with `sowknow.unaccent()` applied (extension installed in the
  `sowknow` schema — the DB user's search_path puts 'sowknow' first, so a bare
  `CREATE EXTENSION` lands there too). French lexemes keep accents
  ('présence'→'présenc'), so an unaccented query missed every accented body
  match (verified live: 'presence' → 0 vs 'présence' → thousands). Every
  tsvector branch therefore runs TWICE: against the raw query AND against
  `sowknow.unaccent(:query)`. Keep BOTH branch sets — they make recall correct
  across the backfill transition (accented rows / mixed / folded rows); after
  the 036 backfill the accented branches match nothing and can be pruned, but
  only once production has verified the backfill. Always qualify the function
  as `sowknow.unaccent` (never `public.unaccent`). The existing-row backfill is
  NOT part of migration 036 (it is slow on this table — bloated heap + huge
  HNSW index thrash shared_buffers): run `scripts/migration036_backfill.py`
  (resumable, id-ordered batches, each commits). A naive `ORDER BY id LIMIT n`
  loop without an advancing `WHERE id > :last_id` re-updates the same first
  rows forever — the id window MUST advance. The backfill runs INSIDE the
  backend container (`/tmp/migration036_backfill.state`), so a backend deploy
  (deploy.sh recreates the container) kills it and its state file — restart it
  after any deploy, reseeding the state from the last logged last_id.
  COMPLETE as of 2026-08-05: 1,377,663 chunks + 17,971 articles, 0 nulls, 0
  rows differing from the folded expression, state file at max UUIDs. No longer
  needs restarting after deploys. The raw-query @@ branches were PRUNED on
  2026-08-05 (verified live: accented branch 0 hits vs 1236 folded; raw==folded
  counts for plain queries) — chunk + article keyword search now match ONLY
  against `sowknow.unaccent(:query)` across regconfig/french/english/simple.
  Do not re-add raw `:query` branches. `title_search_vector` (migration 025)
  is a separate column NOT folded by 036 — its plain `@@` stays.
- Search stream fast path (`_fallback_intent`, 2026-08-05): short/simple
  queries skip the LLM intent call; the fallback defaulted bare French nouns
  ("contrat", "vaccination") to language 'en', failing the 15-min smoke test.
  It now defaults short queries to 'fr' (French-dominant vault, matching
  input_guard) unless an English indicator is present.
- Agentic rerank is CONSOLIDATED (2026-08-04): the agentic pipeline (stream +
  non-stream) calls `hybrid_search(..., rerank=False)` per sub-query, then runs
  ONE cross-encoder pass over the merged, deduped candidate pool via
  `search_agent.rerank_merged_chunks` (top-60, blend 0.7 RRF / 0.3 cross-encoder)
  against the ORIGINAL user query. Never re-enable per-sub-query rerank there —
  it made 2-3 sequential ~500ms rerank calls with incomparable per-query scores.
  Single-query callers of hybrid_search (collections, smart folders, chat) keep
  `rerank=True`.
- Scores are calibrated: keyword rank is squashed rank/(1+rank), cross-encoder
  logits are sigmoid-squashed, labels are absolute (no relative normalization).
  Do not reintroduce unbounded boosts into final_score.
- Graph candidate expansion (2026-08-06): for `entity_search`/`cross_reference`
  intents, `search_agent.graph_expansion_chunks` matches intent entities against
  the `entities` table, expands one hop via `entity_relationships`, and appends
  ≤`SEARCH_GRAPH_EXPANSION_MAX_CHUNKS` (30) mention-linked chunks to the
  candidate pool BEFORE dedupe + the consolidated rerank — zero-scored
  (`match_source="graph"`), so the cross-encoder does the real ranking (no
  boosts). ACL filters on `document_chunks.bucket`, fail-open on any error.
  Enabled live via `SEARCH_GRAPH_EXPANSION_ENABLED=true` in `.env` (2026-08-06).
  The KG tables are populated (38k entities / 343k mentions) but were never
  wired into the agentic pipeline before this. IMPORTANT: the extraction
  pipeline is document-level — `entity_mentions.chunk_id` is NULL for ALL
  343k mentions, so chunk-linked lookup finds nothing; the function falls back
  to chunks from the mentioned documents (≤3 chunks/doc so one heavily
  mentioned doc can't flood the pool). A future chunk-level extraction pass
  would re-activate the precise path automatically.
- Collections gather (2026-08-02): reranks top-60 candidates with the
  cross-encoder (blend 0.3 raw / 0.7 rerank) and applies an ABSOLUTE gate
  (0.35). Scores are displayed ABSOLUTE — relative max-normalization was
  removed (it inflated every top doc to 100% / marginal ones to 97%).
  Degenerate chunks ("-", ",", repeated headers) embed near
  the corpus mean and outrank real content — never trust raw vector top-N
  without the reranker. Once the gate ran, do NOT broaden the query: few
  results means few relevant docs. semantic_search excludes chunk_text < 30
  chars from the candidate pool. Chunk branches search at limit=150,
  collection cap 120.
- Collection orchestrator searches the FOCUSED topic, never the raw request
  sentence (2026-08-04): `build_confirmed_params` derives `search_query` from
  the parsed focus_aspects / entities ("me réunir tous les dossiers
  concernants les salaires" → query "salaires"); `query_planner._base_query`
  prefers it over `query_text`, which stays the original request for memo
  language/context. Feeding hybrid_search the raw sentence keyword-ANDs filler
  words and collapsed collection recall.
- Collection ZIP export (FR6.9, 2026-08-04): `/deliverable/export?format=zip`
  bundles memo.md + memo.pdf + memo.docx + one source file per document (read
  from the mounted `/data`, path from `Document.file_path`) + index.json with
  items and relevance scores. Missing/oversized files are skipped (recorded in
  the index), never fatal. Bundling many files makes the archive large and slow
  to stream on this VPS — expected for big collections.
- LLM stream sentinel: providers yield "\n__USAGE__: {...}" as a trailing
  chunk — `startswith("__USAGE__")` MISSES the leading newline and leaked
  usage JSON into stored summaries (2026-08-02). Match `"__USAGE__" in chunk`
  or split the joined text on it.
- rerank-server is latency-critical: 0.5 CPU throttled it to ~6s/request and
  the client's 5s timeout silently disabled reranking fleet-wide. Keep its
  2.0 CPU limit and torch thread clamp (RERANK_TORCH_THREADS).
- LLM tiers via OpenRouter env vars (deepseek/deepseek-v4-flash-0731
  simple/standard, deepseek/deepseek-v4-pro complex, qwen/qwen3.8-max
  model-level fallback per tier). openrouter_service fails over to the tier's
  fallback model (qwen/qwen3.8-max) once on 400/404/429/5xx — dead model IDs
  are config errors, not retryable. Verify model IDs against
  https://openrouter.ai/api/v1/models before changing them.
- Embedding: `intfloat/multilingual-e5-large` via embed-server + embed-server-2
  (HTTP, circuit breaker). Chunk-level backfill: `scripts/backfill_null_chunks.py`.

## Collection Orchestrator (2026-08-02, spec v2.0 in docs/collection_refactor/)

- Orchestration layer over Search (`backend/app/services/collection_orchestrator/`,
  API `/api/v1/collection-requests`, frontend `app/[locale]/collection-requests/`).
  Defining rule: **compute first, narrate second** — the LLM only narrates
  pre-computed analysis outputs; the GroundingValidator strips any narrative
  claim that doesn't match a computed value (verified live: it rejects real
  fabricated claims on every run). Never let raw document text reach the
  summary prompt outside `<verified_data>` segments.
- Absolute relevance gate (`COLLECTION_RELEVANCE_GATE=0.45`) after ranking —
  marginal semantic matches are not results; all-gated = honest zero-result
  outcome, never a fabricated summary.
- LLM streams may append a `__USAGE__` sentinel trailer (base_llm_service
  convention). Any JSON parse of LLM output must go through
  `smart_folder/query_parser.extract_first_json` — naive find("{")..rfind("}")
  spans the sentinel's JSON and fails.
- Job model: Celery `collections` queue, checkpointed stages (resume on
  retry), cooperative cancel, idempotency keys, ≤3 concurrent jobs/user.
  Relevance/dedup/extraction/thresholds are `COLLECTION_*` settings, not
  constants.
- `/api/v1/collections` and smart-folder reports are owner-scoped for ALL
  authenticated users since 2026-08-02 (was admin-only — that was the
  "collections are broken" report's real cause).
- Migration 035 applied live 2026-08-02 (additive only). Audit retention
  purge: daily beat `collection-audit-retention` (03:30 UTC).
- Live scenario harness: `scripts/collection_scenario_check.py`.
- Legacy `/api/v1/collections` (collection_service.py): gather keywords are
  stopword-filtered via `gather_query_text()` (unfiltered intent keywords
  ANDed by plainto_tsquery killed recall). After a deploy, never refresh a
  collection until `search/health` is healthy — a gather that races
  embed-server warmup times out, breaks the session (`greenlet_spawn`), and
  refresh then commits the empty result set over the old items.

## Agent Memory (2026-08-05, PoC — spec in docs/agent_memory/SPEC.md)

- Persistent layered memory distilled from chat: L0 = existing `chat_messages`,
  L1 = `memory_atoms`, L2 = `memory_scenarios`, L3 = `memory_profiles`
  (migration 037, additive). Inspired by TencentDB Agent-Memory's L0→L3 model.
- **Off by default**: `chat_sessions.memory_enabled` (default false). Only
  opted-in sessions enqueue `app.tasks.memory_tasks.distill_chat_session` (on
  the `collections` queue) after each assistant turn. No behavior change
  otherwise.
- Atoms are `status=pending` + `visibility=private` by default — they never
  enter search/context until reviewed. Grounding: an atom is DROPPED unless
  its `source_message_index` points at a real message in the transcript
  (verified live: the extractor produces valid JSON atoms for a French
  preference/fact conversation).
- **LLM extraction gotchas (verified live 2026-08-05)**: (1) the memory system
  prompt MUST be included in the messages sent — a bare transcript yields
  prose, not atoms; (2) pass a per-session `collection_id` scope to the LLM
  gateway so a memory extraction never collides with an unrelated
  conversation's cached response; (3) memory model enum columns use
  `native_enum=False` (String columns) — the native PG enum type mismatch
  (`character varying = memorystatus`) broke the worker's dedup query until
  fixed.
- When deploying the memory PoC, deploy BOTH `backend` AND `celery-collections`
  — the worker runs its own copy of the task code and must be recreated too.
  The nightly L2 clustering beat (`memory-scenario-clustering`, 03:45 UTC) also
  needs `celery-beat` recreated when the schedule changes.
- **Review + injection live (2026-08-05)**: `/api/v1/memory/atoms` lists the
  owner's atoms+scenarios; `PATCH /api/v1/memory/atoms/{id}` flips
  pending→reviewed/rejected. Only `status=reviewed` atoms / `status=reviewed`
  scenarios are injected into chat context (via `memory_search_service`,
  budget-capped by `MEMORY_INJECT_*` settings), and only when the session has
  `memory_enabled=true`. Verified live: reviewing a French-preference atom made
  a later chat turn recall it across sessions.
- **Backfill**: `scripts/memory_backfill.py` (docker-cp into the backend
  container like migration036_backfill) distills existing sessions — resumable
  advancing id window + state file. `--all` distills every session, default
  only opted-in ones. ~3 sessions ≈ 11s (one LLM call per session). The full
  backfill ran live 2026-08-05: 21 sessions in ~3 min → 33 atoms (20/13 across
  two owners), all `private`, mostly `pending`.
- **Spec complete (2026-08-05)**: L3 profile builder
  (`memory_service.build_profile`, monthly beat `memory-profile-builder`
  04:15 UTC on the 1st) — one LLM pass over the owner's REVIEWED atoms +
  scenarios → persona + stable patterns, upserted with version+1. Global
  search now returns the owner's reviewed atoms/scenarios: `/v1/search/global`
  accepts type=memory (included by default); `search_all_types` → `_search_memory`
  emits `memory_atom` / `memory_scenario` results (owner-scoped, private-only).
  The full L0→L3 loop is live: chat distillation → backfill → review panel →
  injection + search.
- **Review done live (2026-08-05)**: 10/33 atoms approved (durable facts:
  Mansour/Mamadou/Moussa Sow family, BICIS virement pref, Dakar rent, French
  language), 23 rejected (transient LLM output, search noise, duplicate
  virement). 2 L2 scenarios reviewed + profile rebuilt to v2 with real
  priorities/patterns. The review decision was rule-based markers + reject
  defaults — future review batches should follow the same durable-vs-noise
  split.
- **Learned skills (2026-08-05, extension)**: `memory_skills` table (migration
  038) + `skill_extraction_service` distills runbook skills from completed
  collection audit traces (`collection_audit_events`, ≥3 stages per job) —
  weekly beat `skill-extraction` (04:30 UTC Mondays). Skills start `draft`,
  review via `PATCH /api/v1/memory/skills/{id}` → active/archived. Never
  injects a skill before review.
- **Ops (2026-08-05)**: guardian sentinel `memory_backlog` check warns at
  ≥50 pending atoms (advisory, no auto-heal); memory distillation/profile
  record Prometheus counters (`sowknow_memory_atoms_distilled_total`,
  `sowknow_memory_profiles_built_total`).

## Ops rules (incident-forged)

- Guardian-HC (`monitoring/guardian-hc/`) watches and ALERTS. It must never
  auto-restart postgres or backend (config + code-enforced in core.py).
  Container matching is exact-name — keep it that way.
- Guardian daily report + `/status` Telegram send iterate `AgentRegistry.agents`
  — that property was missing until 2026-08-05 (only `_agents`/`get`/`summary`
  existed), so the 06:00 daily report crashed with
  `'AgentRegistry' object has no attribute 'agents'` and Telegram alerts never
  sent (email still worked). The property is exposed now — if Telegram alerts
  go silent again, check this first.
- A slow query is not a dead database. No watchdog restarts Postgres. Ever.
- Backups: restic daily (`scripts/backup*.sh`), memo in docs/operations/BACKUP_MEMO.md.
- Two compose generations once ran mixed (orphan `sowknow4-*` containers from
  /var/docker/sowknow4) — that directory is retired; this repo is the only
  source of truth.

## Testing

- Backend: `cd backend && pytest` (venv in backend/venv).
- Search QA: `scripts/run_search_qa.py`, smoke test `scripts/search_smoke_test.py`
  (cron every 15 min, see scripts/crontab additions).
