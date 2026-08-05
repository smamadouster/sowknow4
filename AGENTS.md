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
  needs restarting after deploys. The accented @@ branches now match nothing
  and can be pruned (verify once in production, then drop them).
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
- LLM tiers via OpenRouter env vars (gemini-2.5-flash simple/standard,
  claude-sonnet-4 complex). openrouter_service fails over to simple tier on
  400/404 (dead model IDs are config errors, not retryable). Verify model IDs
  against https://openrouter.ai/api/v1/models before changing them.
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
