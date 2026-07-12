# SOWKNOW Wiring Audit — Remediation Plan

**Date:** 2026-07-12  
**Scope:** Full codebase (backend, frontend, infrastructure, metrics, workers)  
**Based on:** `WIRING_AUDIT_REPORT.md` (corrected edition)  

---

## 1. Corrections Applied to the Audit

After double-checking the main findings, the following adjustments were made to the original audit report:

| Original finding | Correction |
|------------------|------------|
| **A6** `document_tasks.py` "crashes" | The broken `metrics` import is wrapped in `try/except Exception: pass`; it does **not** crash, but the task-failure counter is never incremented. Re-worded as a missing-metric bug, not a crash. |
| **A17** `space_tasks` not loaded | The API endpoint intentionally catches `ImportError` and returns HTTP 501 with the message "Sync task not yet available; sync will be available after Task 5". Reclassified from **A** to **C15** (dormant by design). |
| **A22** `deploy-production.sh` generates inline compose | **False flag.** `deploy-production.sh` correctly uses `docker-compose -f docker-compose.production.yml`. Removed from the report. |
| **A23** ambiguous compose files | Renamed to **A21** and reworded: the real problem is that `docker-compose.production.yml` (used by the deploy script) is an incomplete topology compared to the committed `docker-compose.yml`. |
| **A25** `/collections` gating | Renamed to **A23** and corrected: `CommandPalette.tsx` is just a `SearchModal` wrapper and does **not** expose `/collections`; only the home-page service grid does. |

Updated headline counts:

| Category | Count |
|----------|-------|
| A — Wiring bug (should be live) | 24 |
| B — Dead code (safe to delete) | 26 |
| C — Dormant by design (decision needed) | 15 |
| D — Redundant / consolidate | 8 |

---

## 2. Guiding Principles

1. **Fix wiring before deleting.** Many Category B modules are referenced by Category A defects (e.g., `main_minimal.py` contains monitoring endpoints that should move to `main.py`). Deleting them first would lose the only implementation.
2. **One canonical topology.** Stop maintaining parallel compose files; pick one production compose and archive the others.
3. **Make dormancy explicit.** Every intentionally-dormant feature must have a 501/error path, a feature flag, or a dated decision record so it is not mistaken for a bug.
4. **Prevent recurrence with CI gates.** Every PR must be checked for router registration, Celery module registration, env-var usage, and cron-script endpoint validity.

---

## 3. PR Roadmap

### PR #1 — Critical one-line wiring fixes (merge first)
**Goal:** Restore code that is already built and intended to be live with minimal risk.
**Items:** A1, A2, A6, A7, A15, A16, A23, A24
**Estimated effort:** 1 engineer, 1 day
**Risk:** Low
**Validation:** Backend starts, affected endpoints return 200, Celery worker logs show task modules loaded.

| Item | File | Exact change |
|------|------|--------------|
| **A1** Register `pipeline_admin` router | `backend/app/main.py` | Add `from app.api import pipeline_admin` and `app.include_router(pipeline_admin.router, prefix="/api/v1")` alongside the other `include_router` calls. |
| **A2** Register `reports` router | `backend/app/main.py` | Add `app.include_router(reports.router, prefix="/api/v1")` after the existing include block. |
| **A6** Fix `metrics` import in document tasks | `backend/app/tasks/document_tasks.py:650` | Replace `from app.services.prometheus_metrics import metrics` with `from app.services.prometheus_metrics import get_metrics`, then call `get_metrics().counter("sowknow_task_failures_total", "Document task failures", ["task_name"]).labels(task_name="process_document").inc()`. Remove the broad `except Exception: pass` or narrow it to metric-update failures only. |
| **A7** Fix `cache_monitor_service` import | `backend/app/services/performance_service.py:17` | Change `from app.services.cache_monitor import cache_monitor_service` to `from app.services.cache_monitor import cache_monitor` and update method calls (`get_daily_stats`, `get_stats_summary`) to use `cache_monitor`. |
| **A15** Load `subscription_tasks` in Celery | `backend/app/celery_app.py:35-50` | Add `"app.tasks.subscription_tasks"` to the `include=[...]` list. |
| **A16** Load `health_report_tasks` in Celery | `backend/app/celery_app.py:35-50` | Add `"app.tasks.health_report_tasks"` to the `include=[...]` list. |
| **A23** Unify `/collections` role gating | `frontend/components/Navigation.tsx:61-70` and `frontend/app/[locale]/page.tsx:72-83,217-253` | Decide intended audience. If collections are for all authenticated users, remove `roles: ['admin','superuser']` from `Navigation.tsx`. If admin-only, add the same role check to the home-page service-grid card. |
| **A24** Add client role guards to admin pages | `frontend/app/[locale]/settings/page.tsx`, `frontend/app/[locale]/monitoring/page.tsx`, `frontend/app/[locale]/admin/search-debug/page.tsx` | Copy the `useEffect` redirect pattern from `frontend/app/[locale]/dashboard/page.tsx:122-128` into each page. |

**Acceptance criteria:**
- `pytest backend/tests` passes.
- `GET /api/v1/admin/pipeline/status` returns 200.
- `POST /api/v1/reports/generate` returns 202.
- Celery worker startup log lists `subscription_tasks` and `health_report_tasks`.
- Frontend build passes and `/collections` behavior matches the chosen role policy.

---

### PR #2 — Restore monitoring & metrics visibility
**Goal:** Make host monitoring cron jobs and Prometheus metrics actually useful.
**Items:** A18, A19, A20, A3, A4, A8, A11 (partial)
**Estimated effort:** 1–2 engineers, 2–3 days
**Risk:** Medium (adds new services to compose)
**Validation:** Cron scripts return useful data, Prometheus scrapes `/metrics`, default alerts are registered.

| Item | File | Exact change |
|------|------|--------------|
| **A18** Add monitoring endpoints to live backend | `backend/app/main.py`, new `backend/app/api/monitoring.py` | Port the monitoring router from `main_minimal.py:328-520` into a new `api/monitoring.py` module and `app.include_router(...)` it in `main.py` under `/api/v1/monitoring`. Ensure it depends on `get_db` and `get_current_user` appropriately. |
| **A19** Fix `monitor_resources.sh` 5xx source | `scripts/monitor_resources.sh:84-106` | Replace the `sowknow4-nginx` container query with a query against Caddy access logs (`/var/log/caddy/access.log`) or against the backend `/metrics` endpoint's `sowknow_http_requests_total{status=~"5.."}` counter. |
| **A20** Derive memory thresholds from env | `backend/app/tasks/monitoring_tasks.py:26-27` | Replace hard-coded `1024/1152` with env vars (`CELERY_MEMORY_WARN_MB`, `CELERY_MEMORY_CRIT_MB`) and set them per worker in compose. |
| **A3** Add Prometheus service to compose | `docker-compose.production.yml` and `monitoring/prometheus.yml` | Add a `prometheus` service (not profile-gated) mounting `monitoring/prometheus.yml` and scraping `backend:8000/metrics`. Expose only internally. |
| **A4** Replace `track_http_request` decorator with middleware | `backend/app/main.py`, `backend/app/services/prometheus_metrics.py:386-419` | Remove the unused decorator. Add FastAPI middleware after `ErrorRateMiddleware` that records actual method, route, and status code to `sowknow_http_requests_total` and `sowknow_http_request_duration_seconds`. |
| **A8** Call `setup_default_alerts()` on startup | `backend/app/main.py` lifespan | Add `from app.services.monitoring import setup_default_alerts` and call `setup_default_alerts()` during startup. Ensure alert evaluation is wired into the beat schedule or a periodic task. |

**Acceptance criteria:**
- `scripts/monitor-alerts.sh` returns JSON data, not 404.
- `docker compose ps` shows `prometheus` healthy.
- `curl http://backend:8000/metrics` returns non-zero HTTP counters after traffic.
- `setup_default_alerts()` is idempotent and does not duplicate alert rows on restart.

---

### PR #3 — Fix production topology
**Goal:** Ensure the deployed compose file actually runs the full document pipeline, embeddings, reranking, and the services the backend expects.
**Items:** A21, A9, A10, A24
**Estimated effort:** 1–2 engineers, 2–3 days + SRE review
**Risk:** High (changes production resource profile)
**Validation:** Document upload flows through all pipeline stages; workers consume `pipeline.*` queues.

| Item | File | Exact change |
|------|------|--------------|
| **A21 / A9** Make `docker-compose.production.yml` the canonical full topology | `docker-compose.production.yml` | Copy the missing services and worker definitions from `docker-compose.yml`: `embed-server`, `embed-server-2`, `rerank-server`, per-stage Celery workers (`celery-light`, `celery-heavy`, `celery-entities`, `celery-articles`, `celery-collections`), and the `pipeline.*` queue routing. Set `EMBED_SERVER_URL` and `RERANK_SERVER_URL` for backend and workers. **Alternative:** update `deploy-production.sh` to use `docker-compose.yml` and delete `docker-compose.production.yml`. |
| **A10** Remove NATS initialization (unless planned) | `backend/app/main.py` lifespan | Remove `get_messaging_client()` / `close_messaging_client()` calls and the `nats` dependency if no feature is scheduled to use it. If a feature is planned, convert this finding to a C item with a decision date. |
| **A24** Align watchdog expected containers | `monitoring/guardian-hc/scripts/watchdog.sh:33` | Either start `telegram-bot` in `docker-compose.production.yml` or remove `sowknow4-telegram-bot` from `EXPECTED_CONTAINERS`. |

**Acceptance criteria:**
- `docker-compose -f docker-compose.production.yml config` validates.
- After deploy, `celery inspect active` shows workers consuming `pipeline.ocr`, `pipeline.chunk`, `pipeline.embed`, `pipeline.index`, `pipeline.articles`, `pipeline.entities`.
- A test document upload reaches the `completed` state.

---

### PR #4 — Feature activation decisions
**Goal:** Convert every intentionally-dormant item into a go/no-go decision with an owner and date.
**Items:** A17, C1–C15
**Estimated effort:** Varies by feature
**Risk:** Varies

| Item | Decision needed | Recommended owner | Suggested action if "go" | Suggested action if "no-go" |
|------|-----------------|-------------------|--------------------------|----------------------------|
| **A17** Auto-tagging | Add to document pipeline? | Product | Call `auto_tagging_service.tag_document(...)` in `document_tasks.py:process_document` after extraction; feature-flag and run async. | Remove from `status.py` and archive `auto_tagging_service.py`. |
| **C1** Embedding variants | Keep 3 implementations? | ML/Platform | Document roles; keep `embed_client.py` as backend interface, `embed_server` picks ONNX vs sentence-transformers. | Delete unused variants and tests. |
| **C2** Search variants | Consolidate search vs agentic search? | Product | Keep both but unify UI entry points. | Merge into single search path. |
| **C3** Tencent OCR | Implement cloud OCR or remove config? | Product | Add Tencent client path in `ocr_service.py`. | Remove `TENCENT_OCR_*` from `.env.example`. |
| **C4** Together/Ollama fallback | Configure fallback keys? | Platform | Add keys to `.env.example` and wire into `llm_router.py` priority list. | Remove fallback providers. |
| **C5** Multi-agent search | Ship v2? | Engineering lead | Wire `agent_orchestrator.py` into a router. | Delete orchestrator and update `status.py`. |
| **C6** Push notifications | Keep auto-subscribe? | Product | Verify VAPID keys; consider explicit opt-in. | Disable auto-subscribe in `AppHooks.tsx`. |
| **C7** Subscriptions page | Billing feature or reminder? | Product | Clarify UX and backend model. | Remove page and unused backend routes. |
| **C8** Upload pause toggle | Verify dashboard exposes it? | Engineering | Add toggle UI if missing. | None; already working. |
| **C9** Backfill tasks | Register for manual use? | Engineering | Add `"app.tasks.backfill_tasks"` to `include`. | Delete module. |
| **C10** Smart-folders polling fallback | Wire on SSE failure? | Engineering | Set `useFallbackPolling(true)` on SSE error. | Delete fallback branch. |
| **C11** `/verify-email/[token]` | Email-only is acceptable? | Product | None needed. | None needed. |
| **C12** `/offline` page | PWA-only is acceptable? | Product | None needed. | None needed. |
| **C13** Frontend `/api/health` | Keep for infra probes? | SRE | Keep or delete after confirming probes. | Delete route. |
| **C14** Settings "System" tab | Implement or remove? | Product | Build endpoints + controls. | Remove tab. |
| **C15** Space rule sync | Activate `space_tasks`? | Engineering | Add to `celery_app.include` and remove 501 placeholder. | Remove sync endpoint from `spaces.py`. |

**Acceptance criteria:**
- Every C item has a recorded decision, owner, and target date.
- "Go" items are converted to engineering tickets with exact wiring steps.
- "No-go" items are added to PR #5 deletion list.

---

### PR #5 — Dead-code deletion
**Goal:** Remove confirmed-unused modules, stale entrypoints, and abandoned experiments.
**Items:** B1–B26 (pending PR #4 no-go decisions)
**Estimated effort:** 1 engineer, 2–3 days
**Risk:** Low–Medium (verify no hidden imports)
**Estimated line reduction:** ~8,200 lines

**Pre-deletion checklist for each module:**
1. Search production code for any import.
2. Check `main.py`, `celery_app.py`, routers, and the frontend import graph.
3. If a module contains logic that should be live, move/re-wire it before deleting.
4. Remove associated tests or move them to an `archive/` folder if product wants to keep them.

**High-impact deletions:**
- `backend/app/main_minimal.py` (580 lines) — after porting monitoring endpoints to `main.py`.
- `backend/app/performance.py` (327 lines) — never imported.
- `backend/app/services/swarm/v2/` (~1,500 lines) — no callers.
- `frontend/components/BatchUploader.tsx` — never imported.
- Unused i18n keys related to dead features.

**Acceptance criteria:**
- `pytest` passes.
- Frontend build passes.
- `docker-compose` build passes.
- No new "module not found" errors in worker or backend logs.

---

### PR #6 — Consolidate redundancies
**Goal:** Merge overlapping implementations into a single supported path.
**Items:** D1–D8
**Estimated effort:** 1–2 engineers, 3–5 days
**Risk:** Medium

| Item | Action |
|------|--------|
| **D1** Three monitoring systems | Make Prometheus the canonical export. Have `CostTracker` and `rollback_monitor` push to `get_metrics()`. |
| **D2** Two LLM abstraction layers | Route all consumers through `llm_gateway`; deprecate direct `llm_router` usage. |
| **D3** Two FastAPI entrypoints | Delete `main_minimal.py` after PR #2 ports its monitoring endpoints. |
| **D4** Two health endpoints | Keep `/api/v1/health` canonical; redirect root `/health` to it or remove. |
| **D5** Two pipeline diagnostics endpoints | Merge `admin.py` diagnostics and `pipeline_admin.py` status into one router after A1. |
| **D6** Inline API base URLs | Migrate all direct `fetch` calls to `lib/api.ts`. |
| **D7/D8** (if any) | Address per report. |

---

### PR #7 — Process & CI gates
**Goal:** Prevent the next unwired feature from reaching `main`.
**Estimated effort:** 1 engineer, 2–3 days
**Risk:** Low

Add the following checks to CI (GitHub Actions / pre-commit):

#### Gate 1 — Router registration completeness
A Python script that:
1. Parses `backend/app/main.py`.
2. Lists every module imported from `app.api.*`.
3. Verifies each imported module's `router` is passed to `app.include_router(...)`.
4. Fails if any router is imported but not included.

#### Gate 2 — Celery module / beat schedule consistency
A Python script that:
1. Reads `celery_app.conf.include`.
2. Reads `celery_app.conf.beat_schedule`.
3. Ensures every task referenced in the beat schedule belongs to a module in `include=`.
4. Scans `app/api/**/*.py` for `.delay(` / `.apply_async(` calls and warns if the target module is not in `include=`.

#### Gate 3 — Environment variable usage
A script that:
1. Collects all env vars referenced in code (`os.getenv`, `os.environ`, `settings.*`).
2. Verifies they are documented in `.env.example`.
3. Verifies `NEXT_PUBLIC_*` vars are actually read in the frontend.

#### Gate 4 — Cron script endpoint validity
A script that:
1. Parses `scripts/*.sh` for `curl` calls to `/api/v1/*`.
2. Checks those paths exist in the live router registry (`main.py` + included routers).
3. Fails if a cron script calls a missing endpoint.

#### Gate 5 — Compose / deploy script consistency
A script that:
1. Ensures `deploy-production.sh` references exactly one compose file.
2. Verifies that compose file defines all queues referenced in `celery_app.py` routes and all services referenced by env vars.

#### PR template updates
Add these checkboxes to `.github/pull_request_template.md`:

```markdown
- [ ] New API router is imported and `include_router`-ed in `backend/app/main.py`
- [ ] New Celery task module is added to `celery_app.conf.include`
- [ ] New beat-scheduled task is loaded by a worker queue
- [ ] New env vars are documented in `.env.example` and read somewhere
- [ ] New monitoring endpoint is reachable from `scripts/*.sh` if intended
- [ ] Feature flags are read in code, not only set in deploy scripts
- [ ] Manual test confirms the feature is reachable from a real request path
```

#### Code review checklist
Add to `docs/operations/CODE_REVIEW_CHECKLIST.md` (or create it):
- "Does this PR add code that is actually wired into the live app?"
- "If a new service/queue is added, is it in the production compose file?"
- "If a new metric is added, is it scraped by Prometheus and used by a dashboard/alert?"
- "If a new endpoint is added, is it covered by a cron script or frontend call?"

---

## 4. Top 10 Quick Wins (Ranked)

| Rank | Finding | Category | File(s) | Fix | Effort | Risk | Impact |
|------|---------|----------|---------|-----|--------|------|--------|
| 1 | `pipeline_admin` not registered | A | `backend/app/main.py` | Add import + `include_router` | 1 line | low | Dashboard pipeline UI fixed |
| 2 | `reports` router not registered | A | `backend/app/main.py` | Add `include_router` | 1 line | low | Reports API live |
| 3 | Celery missing `subscription_tasks` and `health_report_tasks` | A | `backend/app/celery_app.py:35-50` | Add to `include=[...]` | 2 lines | low | Scheduled tasks actually run |
| 4 | Host monitoring cron calls missing endpoints | A | `backend/app/main.py`, `scripts/monitor-alerts.sh` | Add monitoring endpoints to `main.py` | small | low | Cron monitoring stops 404ing |
| 5 | Broken `metrics` import in document tasks | A | `backend/app/tasks/document_tasks.py:650` | Import `get_metrics` and increment counter | 1 line | low | Task-failure metric records |
| 6 | Broken `cache_monitor_service` import | A/B | `backend/app/services/performance_service.py:17` | Import `cache_monitor` or delete file | 1 line | low | Removes latent ImportError |
| 7 | `setup_default_alerts()` not called | A | `backend/app/main.py` lifespan | Add call | 2 lines | low | PRD alerts evaluate |
| 8 | `docker-compose.production.yml` is an incomplete topology | A | `docker-compose.production.yml`, `scripts/deploy-production.sh` | Add missing services/workers or switch compose file | small | high | Prevents degraded deployments |
| 9 | Add Prometheus service to compose | A | `docker-compose.production.yml`, `monitoring/prometheus.yml` | Add service + mount config | small | low | Metrics visible |
| 10 | Fix `/collections` role gating inconsistency | A | `frontend/components/Navigation.tsx`, `frontend/app/[locale]/page.tsx` | Unify role check | small | low | Consistent UX/permissions |

---

## 5. Deletion Candidates (Category B Summary)

**Precondition:** Complete PR #4 decisions first; any C item marked "no-go" joins this list.

| Module / file | Lines | Why safe to delete |
|---------------|-------|-------------------|
| `backend/app/main_minimal.py` | ~580 | Unused; broken imports; logic to be ported in PR #2 first. |
| `backend/app/performance.py` | ~327 | No production imports. |
| `backend/app/services/swarm/v2/` | ~1,500 | No callers; depends on unused NATS client. |
| `frontend/components/BatchUploader.tsx` | ~? | Never imported. |
| `backend/app/services/auto_tagging_service.py` | ~384 | If PR #4 decides no-go. |
| `backend/app/services/together_service.py`, `ollama_service.py` | ~? each | If PR #4 decides no-go on fallbacks. |
| `backend/app/tasks/backfill_tasks.py` | ~377 | If PR #4 decides no-go. |
| `frontend/app/[locale]/subscriptions/page.tsx` + backend routes | ~? | If PR #4 decides no-go. |
| Unused i18n keys for dead features | ~? | Reduce bundle size. |

**Estimated total line reduction after PR #4 no-go decisions:** 8,000–9,000 lines.

---

## 6. Activation Decisions (Category C Summary)

| Item | Question | Owner |
|------|----------|-------|
| Auto-tagging | Add to document pipeline or remove from status page? | Product |
| Embedding variants | Keep 3 implementations? | ML/Platform |
| Search variants | Consolidate? | Product |
| Tencent OCR | Implement or remove config? | Product |
| Together/Ollama fallback | Configure keys or remove? | Platform |
| Multi-agent search | Ship v2? | Engineering lead |
| Push notifications | Keep auto-subscribe? | Product |
| Subscriptions page | Billing or reminder? | Product |
| Backfill tasks | Register or delete? | Engineering |
| Smart-folders polling fallback | Wire or delete? | Engineering |
| Settings "System" tab | Implement or remove? | Product |
| Space rule sync | Activate `space_tasks`? | Engineering |
| Prometheus scraper | Enable or remove config? | SRE |
| nginx/certbot/Ollama/Vault profiles | Keep for dev or delete? | Platform |

**Decision format:** Each item should have a one-page decision record in `docs/decisions/` or a comment in code with owner, date, and go/no-go.

---

## 7. Suggested Sprint Plan

| Week | PR | Focus | Output |
|------|-----|-------|--------|
| **Week 1** | PR #1 | Merge critical one-line fixes | A1, A2, A6, A7, A15, A16, A23, A24 fixed |
| **Week 1–2** | PR #2 | Restore monitoring & metrics | Host cron works, Prometheus scrapes, alerts registered |
| **Week 2** | PR #3 | Fix production topology | `docker-compose.production.yml` is canonical and complete |
| **Week 2–3** | PR #4 | Run activation decision meeting | Every C item has go/no-go, tickets created |
| **Week 3** | PR #5 | Delete dead code | ~8k lines removed, build still green |
| **Week 4** | PR #6 | Consolidate redundancies | Single LLM path, single health endpoint, etc. |
| **Week 4** | PR #7 | Add CI wiring gates | New PRs cannot repeat these mistakes |

---

## 8. How to Verify Each Fix

| Fix | Verification command / test |
|-----|----------------------------|
| Router registration | `curl -s https://$DOMAIN/api/v1/<route>` returns 200/401, not 404 |
| Celery module loaded | `docker logs sowknow4-celery-worker | grep "subscription_tasks"` |
| Beat task runs | Check worker logs at scheduled time; verify task ID appears in result backend |
| Prometheus scrape | `curl -s http://prometheus:9090/api/v1/targets` shows backend UP |
| HTTP metrics | `curl -s https://$DOMAIN/metrics | grep sowknow_http_requests_total` |
| Host cron | Run `scripts/monitor-alerts.sh` manually; should emit valid JSON |
| Compose topology | `docker-compose -f docker-compose.production.yml config` validates; deploy smoke test uploads a document |
| Role gating | Log in as non-admin; `/collections` behavior matches policy |
| Dead code deletion | Full test suite + build passes; no import errors in logs |
| CI gates | Open a test PR that adds an unwired router; gate fails |

---

## 9. Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Activating Celery modules floods workers | Deploy during low traffic; set rate limits on `subscription_tasks.send_payment_reminders` first. |
| Adding embed-server/rerank-server exceeds host resources | Run resource estimation on staging; scale workers horizontally only after baseline. |
| `setup_default_alerts()` creates noisy alerts | Tune thresholds in `monitoring.py` before enabling page/telegram integrations. |
| Deleting `main_minimal.py` loses monitoring endpoints | Port endpoints in PR #2 before deletion in PR #5. |
| Feature-flag changes hide live features | Coordinate with product; use phased rollout with explicit opt-in. |

---

## 10. Summary of What to Fix Now

If only one sprint is available, do **PR #1 + PR #3** first:

1. Register `pipeline_admin` and `reports` routers.
2. Add `subscription_tasks` and `health_report_tasks` to Celery `include=`.
3. Fix the two broken imports in `document_tasks.py` and `performance_service.py`.
4. Make `docker-compose.production.yml` the canonical complete topology.

These five changes restore the highest-impact disconnected features and prevent the deploy script from running a degraded stack.
