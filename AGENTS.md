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
- Scores are calibrated: keyword rank is squashed rank/(1+rank), cross-encoder
  logits are sigmoid-squashed, labels are absolute (no relative normalization).
  Do not reintroduce unbounded boosts into final_score.
- LLM tiers via OpenRouter env vars (gemini-2.5-flash simple/standard,
  claude-sonnet-4 complex). openrouter_service fails over to simple tier on
  400/404 (dead model IDs are config errors, not retryable). Verify model IDs
  against https://openrouter.ai/api/v1/models before changing them.
- Embedding: `intfloat/multilingual-e5-large` via embed-server + embed-server-2
  (HTTP, circuit breaker). Chunk-level backfill: `scripts/backfill_null_chunks.py`.

## Ops rules (incident-forged)

- Guardian-HC (`monitoring/guardian-hc/`) watches and ALERTS. It must never
  auto-restart postgres or backend (config + code-enforced in core.py).
  Container matching is exact-name — keep it that way.
- A slow query is not a dead database. No watchdog restarts Postgres. Ever.
- Backups: restic daily (`scripts/backup*.sh`), memo in docs/operations/BACKUP_MEMO.md.
- Two compose generations once ran mixed (orphan `sowknow4-*` containers from
  /var/docker/sowknow4) — that directory is retired; this repo is the only
  source of truth.

## Testing

- Backend: `cd backend && pytest` (venv in backend/venv).
- Search QA: `scripts/run_search_qa.py`, smoke test `scripts/search_smoke_test.py`
  (cron every 15 min, see scripts/crontab additions).
