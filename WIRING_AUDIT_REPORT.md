# SOWKNOW Wiring Audit Report

**Date:** 2026-07-12
**Scope:** Full codebase (backend, frontend, infrastructure, metrics, workers)
**Auditor:** Kimi Code CLI
**Constraint:** This audit was performed on the development repository. Production nginx/application access logs are empty in this environment, so "live traffic" verification is based on static wiring analysis (Docker Compose, route registration, imports, Celery queues, startup sequence) rather than request-volume telemetry. Distinctions between "zero traffic" and "low traffic" could not be confirmed from logs. Multiple compose files and deploy scripts disagree on the production topology; findings note these conflicts where relevant.

---

## 1. Executive Summary

We found **a systemic wiring problem**. Dozens of modules, services, metrics, and routes are built and tested but not connected to the production request path. The most damaging pattern is not missing code — it is code that exists, is imported, and is even referenced by the UI, but is never registered in the live FastAPI application or the production Docker Compose.

### Headline numbers

| Category | Count | Estimated lines at risk |
|----------|-------|------------------------|
| A — Wiring bug (should be live) | 24 | ~5,700 lines built but unreachable |
| B — Dead code (safe to delete) | 26 | ~8,200 lines |
| C — Dormant by design (decision needed) | 15 | — |
| D — Redundant / consolidate | 8 | — |

### Top systemic patterns

1. **Router registration drift.** Several API modules are imported in `main.py` but never `include_router`-ed, and one router the dashboard actively calls is not imported at all.
2. **Celery module registration drift.** Tasks are scheduled or dispatched from API endpoints, but their modules are missing from `celery_app.conf.include`, so workers never load them.
3. **Two entrypoints, one live.** `main.py` runs in production; `main_minimal.py` is stale, has broken imports, and exposes endpoints (including monitoring) that are missing from production.
4. **Metrics theater.** `/metrics` is wired, ~25 metrics are registered, but almost none are updated and nothing scrapes the endpoint in production.
5. **Infrastructure with no traffic.** NATS client, Swarm v2, and several monitoring modules are initialized or present but have no production callers.
6. **Docker Compose and deploy-script drift.** `deploy-production.sh` uses `docker-compose.production.yml`, which is missing workers and services that exist in the committed `docker-compose.yml`.
7. **Host cron depends on unused entrypoint.** `monitor-alerts.sh` calls `/api/v1/monitoring/*` endpoints that only exist in `main_minimal.py`.
8. **Feature-flag config that no code reads.** Deploy scripts export `NEXT_PUBLIC_ENABLE_*` flags and `.env.example` documents thresholds that are hard-coded elsewhere.

### Highest-priority fixes

| # | Fix | File(s) | Impact | Effort |
|---|-----|---------|--------|--------|
| 1 | Register `pipeline_admin` router in `main.py` | `backend/app/main.py` | Dashboard pipeline UI works | 1 line |
| 2 | Register `reports` router in `main.py` | `backend/app/main.py` | Report generation API reachable | 1 line |
| 3 | Add missing Celery modules to `include=` | `backend/app/celery_app.py:35-50` | Scheduled/dispatched tasks actually run | 3 lines |
| 4 | Add monitoring endpoints to `main.py` | `backend/app/main.py`, `scripts/monitor-alerts.sh` | Host cron monitoring stops 404ing | small |
| 5 | Fix broken `metrics` import in document tasks | `backend/app/tasks/document_tasks.py:650` | Task-failure metric actually increments | 1 line |
| 6 | Fix broken `cache_monitor_service` import | `backend/app/services/performance_service.py:17` | Removes latent ImportError | 1 line |
| 7 | Add Prometheus service and scrape config | `docker-compose.yml`, `monitoring/prometheus.yml` | Metrics become visible | small |
| 8 | Call `setup_default_alerts()` in live app | `backend/app/main.py` lifespan | PRD alerts evaluate | small |
| 9 | Add per-stage pipeline workers / embed-server to canonical compose | `docker-compose.production.yml` | Document pipeline actually runs | significant |
| 10 | Pick one canonical production compose file | `docker-compose.production.yml`, `docker-compose.yml` | Eliminates deploy ambiguity | small |

---

## 2. Methodology & Constraints

### Step 1 — Map what is actually live

- **Production entrypoint:** `uvicorn app.main:app` (confirmed by `docker-compose.production.yml:120`).
- **Routers included in `main.py`:** `auth`, `admin`, `bookmarks`, `notes`, `spaces`, `documents`, `articles`, `collections`, `smart_folders`, `knowledge_graph`, `graph_rag`, `search_agent_router`, `search_suggest`, `search_feedback`, `chat`, `internal`, `tags`, `voice`, `health`, `status`, `subscriptions`, `tasks`, `push`.
- **Celery task modules included:** `document_tasks`, `anomaly_tasks`, `embedding_tasks`, `report_tasks`, `monitoring_tasks`, `article_tasks`, `voice_tasks`, `pipeline_tasks`, `pipeline_orchestrator`, `pipeline_sweeper`, `guardian_tasks`, `smart_folder_tasks`, `collection_report_tasks`, `task_alarm_tasks`.
- **Celery beat schedule:** daily-anomaly-report, pipeline-sweeper, cleanup-old-reports, smart-folder-auto-refresh, pipeline-daily-health-report, subscription-payment-reminders, task-alarm-checker.
- **Production compose ambiguity:** `deploy-production.sh` references `docker-compose.production.yml`, but a separate audit path found running containers reportedly using `/var/docker/sowknow4/docker-compose.yml` (full topology). `docker-compose.production.yml` is missing pipeline workers, embed-server, rerank-server, and Prometheus. This report treats the committed `docker-compose.yml` as the live topology where they conflict.
- **Production compose services (committed `docker-compose.yml`):** postgres, redis, backend, celery-light, celery-heavy, celery-entities, celery-articles, celery-collections, celery-beat, telegram-bot, frontend, embed-server, embed-server-2, rerank-server, nginx (profile-only), certbot (profile-only), prometheus (profile-only), guardian-hc (profile-only), vault (profile-only), ollama (profile-only).
- **Frontend reachable pages:** all pages in `frontend/app/[locale]/` are either linked in `Navigation.tsx` or are auth/offline pages.

### Step 2 — Find orphans

For each backend module we traced imports from `main.py`, routers, Celery tasks, and service-to-service calls. For the frontend we traced the navigation graph and component imports.

### Step 3 — Classify

- **A — Should be live (wiring bug):** intended for production, disconnected by a defect.
- **B — Dead code:** abandoned experiments, replaced implementations, unused modules.
- **C — Dormant by design:** feature-flagged or intentionally held; needs a go/no-go.
- **D — Redundant:** multiple implementations where one should survive.

### Constraints

- No live nginx/application logs were available (`logs/nginx/`, `logs/app/` are empty).
- We did not analyze test-only code unless it clearly revealed a production wiring defect.
- Some findings depend on which compose file is actually deployed. `deploy-production.sh` points to `docker-compose.production.yml`, but the committed `docker-compose.yml` appears to be the running topology; findings note both where they conflict.

---

## 3. Full Inventory

### Category A — Should be live (wiring bug)

#### A1. `pipeline_admin` router is not registered in production

- **What:** Pipeline status dashboard and bulk-retry endpoints (`/api/v1/admin/pipeline/status`, `/api/v1/admin/pipeline/retry-failed`).
- **Files:** `backend/app/api/pipeline_admin.py` (131 lines); missing from `backend/app/main.py`.
- **Evidence:** The frontend admin dashboard calls `/v1/admin/pipeline/status` and `/v1/admin/pipeline/retry-failed` (`frontend/lib/api.ts:1106-1130`). `pipeline_admin.py` exists but is only included in the unused `main_minimal.py`.
- **User/business impact:** Admin dashboard pipeline panel returns 404; operators cannot see queue depths or retry failed stages.
- **Effort to fix:** one-line.
- **Risk of activating:** low.
- **Priority score:** highest.
- **Fix:** Add to `backend/app/main.py`:
  ```python
  from app.api import pipeline_admin
  app.include_router(pipeline_admin.router, prefix="/api/v1")
  ```

#### A2. `reports` router is imported but never included

- **What:** Async PDF/Excel report generation endpoints (`POST /api/v1/reports/generate`, `GET /api/v1/reports/status/{task_id}`).
- **Files:** `backend/app/api/reports.py` (76 lines); imported in `backend/app/main.py:34` but not in `app.include_router(...)` list.
- **Evidence:** `main.py` imports `reports` alongside live routers, but the include list at lines 417-439 omits it.
- **User/business impact:** Report generation API is unreachable; report tasks in Celery are only triggerable internally.
- **Effort to fix:** one-line.
- **Risk of activating:** low.
- **Priority score:** highest.
- **Fix:** Add `app.include_router(reports.router, prefix="/api/v1")` in `backend/app/main.py` after line 439.

#### A3. `/metrics` endpoint has no scraper in production

- **What:** Prometheus metrics exporter at `/metrics` (`backend/app/main.py:470-478`).
- **Files:** `backend/app/main.py:470-478`, `monitoring/prometheus.yml`, `docker-compose.yml`, `docker-compose.production.yml`.
- **Evidence:** `prometheus.yml` defines scrape jobs, but neither the canonical `docker-compose.yml` (unless `monitoring` profile is enabled) nor `docker-compose.production.yml` runs a Prometheus service by default. Guardian health checks hit `/api/v1/health`, not `/metrics`.
- **User/business impact:** All instrumented metrics are collected but invisible; no dashboards or alerts can be built.
- **Effort to fix:** small.
- **Risk of activating:** low.
- **Priority score:** high.
- **Fix:** Add a `prometheus` service to the canonical compose file mounting `monitoring/prometheus.yml`; ensure `/metrics` is reachable internally.

#### A4. `track_http_request` decorator is defined but never applied

- **What:** HTTP request duration/count decorator in `backend/app/services/prometheus_metrics.py:386-419`.
- **Files:** `backend/app/services/prometheus_metrics.py:386-419`.
- **Evidence:** Grep shows zero usage outside definition. The decorator also hard-codes method/endpoint/status as `"unknown"`.
- **User/business impact:** `sowknow_http_requests_total` and `sowknow_http_request_duration_seconds` are empty.
- **Effort to fix:** small.
- **Risk of activating:** low.
- **Priority score:** high.
- **Fix:** Replace with a real FastAPI middleware that records actual method, path, and status; add it in `backend/app/main.py` after `ErrorRateMiddleware`.

#### A5. Most registered Prometheus metrics are never updated

- **What:** `setup_standard_metrics()` registers ~25 metrics (DB, queue, LLM tokens/retries/cost, cache, documents, system, users).
- **Files:** `backend/app/services/prometheus_metrics.py:262-384`.
- **Evidence:** Only `chat_service.py:381-535` updates `llm_request_duration` and `llm_request_total`. Queue depth, cache counters, document counters, memory/disk gauges, user gauges, etc. are never set.
- **User/business impact:** `/metrics` exports mostly zeroed metrics, giving a false sense of observability.
- **Effort to fix:** significant.
- **Risk of activating:** low.
- **Priority score:** medium.
- **Fix:** Add instrumentation hooks from Celery signals, `document_tasks.py`/`pipeline_tasks.py`, `cache_monitor.py`, `SystemMonitor`, and `llm_gateway.py`/`openrouter_service.py`.

#### A6. `document_tasks.py` references a non-existent `metrics` symbol, so task-failure counter never increments

- **What:** `from app.services.prometheus_metrics import metrics` at `backend/app/tasks/document_tasks.py:650`.
- **Files:** `backend/app/tasks/document_tasks.py:648-653`.
- **Evidence:** `prometheus_metrics.py` exports `get_metrics`, `PrometheusMetrics`, `Counter`, `Histogram`, etc., but no module-level `metrics` object. The call is wrapped in `try/except Exception: pass`, so it does not crash; it just silently fails to record the metric.
- **User/business impact:** Document-processing failure counts are under-reported in `/metrics`; operators lack signal on pipeline health.
- **Effort to fix:** one-line.
- **Risk of activating:** low.
- **Priority score:** high.
- **Fix:** Replace with `from app.services.prometheus_metrics import get_metrics` and increment a counter such as `get_metrics().counter("sowknow_task_failures_total", ...).inc()`.

#### A7. `performance_service.py` imports non-existent `cache_monitor_service`

- **What:** `from app.services.cache_monitor import cache_monitor_service` at `backend/app/services/performance_service.py:17`.
- **Files:** `backend/app/services/performance_service.py:17`, `backend/app/services/cache_monitor.py:374`.
- **Evidence:** `cache_monitor.py` exports `cache_monitor = CacheMonitor(...)` only.
- **User/business impact:** Any import of `performance_service.py` crashes. The module is currently unused, so it is latent breakage.
- **Effort to fix:** one-line.
- **Risk of activating:** low.
- **Priority score:** highest.
- **Fix:** Change import to `from app.services.cache_monitor import cache_monitor` and adjust method calls (`get_daily_stats`, `get_stats_summary`).

#### A8. `monitoring.py` default alerts are never set up in the live app

- **What:** `setup_default_alerts()` registers memory, disk, queue, cost, and 5xx-rate alerts.
- **Files:** `backend/app/services/monitoring.py:1055-1071`, `backend/app/main.py` lifespan.
- **Evidence:** `main_minimal.py:37` calls `setup_default_alerts()`; `main.py` lifespan does not.
- **User/business impact:** PRD-mandated alerts are registered but never evaluated in production.
- **Effort to fix:** small.
- **Risk of activating:** low.
- **Priority score:** high.
- **Fix:** Add `from app.services.monitoring import setup_default_alerts` and call `setup_default_alerts()` in `main.py` lifespan startup; wire alert evaluation into beat schedule or `/metrics` handler.

#### A9. Production Docker Compose omits embedding/reranking microservices and per-stage pipeline workers

- **What:** `docker-compose.production.yml` has only one `celery-worker` consuming `-Q celery,document_processing,scheduled,collections`.
- **Files:** `docker-compose.production.yml:136-171`, `backend/app/celery_app.py:78-96`.
- **Evidence:** Celery routes tasks to `pipeline.ocr`, `pipeline.chunk`, `pipeline.embed`, `pipeline.index`, `pipeline.articles`, `pipeline.entities`. None of those queues are consumed in production. There is no `embed-server` or `rerank-server` service, and `EMBED_SERVER_URL`/`RERANK_SERVER_URL` are not set for backend/celery.
- **User/business impact:** Document processing pipeline may enqueue embedding/entity/article stages that never execute. Search reranking silently falls back to RRF-only.
- **Effort to fix:** significant.
- **Risk of activating:** medium (memory/CPU budget must be rechecked).
- **Priority score:** highest.
- **Fix:** Either add `embed-server`, `rerank-server`, and targeted Celery workers (as in `docker-compose.yml`), or document that production intentionally runs a degraded single-worker topology.

#### A10. NATS messaging client is initialized but has no production callers

- **What:** `main.py` lifespan calls `get_messaging_client()` and `close_messaging_client()`.
- **Files:** `backend/app/services/messaging/__init__.py` (171 lines), `backend/app/main.py:167-173,215-220`.
- **Evidence:** No production code publishes or subscribes to NATS subjects; the `swarm/v2/` package that depends on it is also unused.
- **User/business impact:** Startup/shutdown overhead and a dependency on an unused service.
- **Effort to fix:** small.
- **Risk of activating:** low.
- **Priority score:** medium.
- **Fix:** Remove NATS client initialization from `main.py` lifespan (and the `nats` dependency) unless a feature is planned to use it.

#### A11. Guardian health-check subsystem is not deployed

- **What:** `monitoring/guardian-hc/` is a complete health-check/runbook/agent subsystem.
- **Files:** `monitoring/guardian-hc/` (~1,500 lines), `monitoring/guardian-hc/guardian-hc.sowknow4.yml`.
- **Evidence:** No service in `docker-compose.production.yml` runs Guardian HC; no cron references it.
- **User/business impact:** Built-in self-healing checks and runbooks are not running.
- **Effort to fix:** small.
- **Risk of activating:** low.
- **Priority score:** medium.
- **Fix:** Add a `guardian-hc` service to compose or run it as a cron job; update `guardian-hc.sowknow4.yml` to match current service names.

#### A12. `NEXT_PUBLIC_ENABLE_*` feature flags are exported but never read

- **What:** Deploy script writes `NEXT_PUBLIC_ENABLE_KNOWLEDGE_GRAPH`, `NEXT_PUBLIC_ENABLE_SMART_COLLECTIONS`, `NEXT_PUBLIC_ENABLE_SMART_FOLDERS`, `NEXT_PUBLIC_ENABLE_MULTI_AGENT` to `frontend/.env.production`.
- **Files:** `scripts/deploy-production.sh:127-130`.
- **Evidence:** No frontend code reads these variables; pages and navigation links are unconditional.
- **User/business impact:** Feature gating does not work; features are always visible even when backend support is absent.
- **Effort to fix:** small.
- **Risk of activating:** low.
- **Priority score:** low.
- **Fix:** Either read these flags in `Navigation.tsx`/`page.tsx` to conditionally render features, or remove them from the deploy script.

#### A13. `cache_monitor` statistics are not surfaced to any dashboard

- **What:** `cache_monitor.py` records cache hits/misses and token savings.
- **Files:** `backend/app/services/cache_monitor.py`, `backend/app/api/admin.py`.
- **Evidence:** Data is consumed by `anomaly_tasks.py` and some services, but no admin endpoint exposes it.
- **User/business impact:** Operators cannot see cache effectiveness or cost savings.
- **Effort to fix:** small.
- **Risk of activating:** low.
- **Priority score:** medium.
- **Fix:** Add an admin endpoint (e.g., `/v1/admin/cache-stats`) returning `cache_monitor.get_stats_summary()`.

#### A14. `main_minimal.py` has broken imports

- **What:** `main_minimal.py` imports `search` and `multi_agent` modules that do not exist.
- **Files:** `backend/app/main_minimal.py:220-224`.
- **Evidence:** `backend/app/api/search.py` and `backend/app/api/multi_agent.py` are absent.
- **User/business impact:** `main_minimal.py` cannot start; it is a trap for anyone trying to use it.
- **Effort to fix:** small.
- **Risk of activating:** low.
- **Priority score:** low (file is already unused).
- **Fix:** Delete `main_minimal.py` (recommended) or fix imports.

#### A15. `subscription_tasks` module is scheduled but not loaded by Celery workers

- **What:** Daily subscription payment-reminder task.
- **Files:** `backend/app/tasks/subscription_tasks.py` (222 lines); `backend/app/celery_app.py:154` schedules it; module absent from `celery_app.py:35-50` `include` list.
- **Evidence:** Beat references `app.tasks.subscription_tasks.send_payment_reminders`, but the module is not in `include=`. `api/subscriptions.py` imports helper functions at request time, which does not register tasks in workers.
- **User/business impact:** Payment reminders never execute; beat logs "unknown task" errors.
- **Effort to fix:** one-line.
- **Risk of activating:** low.
- **Priority score:** highest.
- **Fix:** Add `"app.tasks.subscription_tasks"` to `celery_app.py:35-50` `include=[...]`.

#### A16. `health_report_tasks` module is scheduled but not loaded by Celery workers

- **What:** Daily pipeline health report email.
- **Files:** `backend/app/tasks/health_report_tasks.py` (264 lines); `backend/app/celery_app.py:149` schedules `pipeline.daily_health_report`; module absent from `include=`.
- **Evidence:** Same pattern as A15: decorated task in a module workers never import.
- **User/business impact:** 07:30 UTC pipeline health report is never sent.
- **Effort to fix:** one-line.
- **Risk of activating:** low.
- **Priority score:** highest.
- **Fix:** Add `"app.tasks.health_report_tasks"` to `celery_app.py:35-50` `include=[...]`.

#### A17. `auto_tagging_service` is built but never invoked

- **What:** LLM-based automatic document tagging on ingestion.
- **Files:** `backend/app/services/auto_tagging_service.py` (384 lines).
- **Evidence:** No production import of `auto_tagging_service`. E2E tests expect auto-tagging on upload, but the upload/document-processing pipeline never calls it.
- **User/business impact:** Documents are not auto-tagged; related e2e test fails; users miss AI-generated tags.
- **Effort to fix:** small.
- **Risk of activating:** medium (adds LLM cost per document; should be feature-flagged or async stage).
- **Priority score:** high.
- **Fix:** Call `auto_tagging_service.tag_document(document, extracted_text, db)` in `document_tasks.py:process_document` after text extraction, or add a dedicated `auto_tag` pipeline stage in `pipeline_tasks.py`.

#### A18. Host monitoring cron job calls endpoints missing from the live backend

- **What:** `scripts/monitor-alerts.sh` calls `/api/v1/monitoring/system`, `/api/v1/monitoring/queue`, `/api/v1/monitoring/alerts`.
- **Files:** `scripts/monitor-alerts.sh:49-99`, `backend/app/main.py`, `backend/app/main_minimal.py:328-520`.
- **Evidence:** Production runs `app.main:app`; these endpoints only exist in `main_minimal.py`. Live curl returns `{"detail":"Not Found"}`.
- **User/business impact:** Host-level resource/alert monitoring is blind; alerts never fire.
- **Effort to fix:** small.
- **Risk of activating:** low.
- **Priority score:** highest.
- **Fix:** Either add the monitoring endpoints to `main.py` (move them to `api/monitoring.py` and include the router), or switch production to a corrected entrypoint and update compose.

#### A19. `monitor_resources.sh` reads 5xx rate from a non-existent container

- **What:** `scripts/monitor_resources.sh:84-106` looks for container `sowknow4-nginx`.
- **Files:** `scripts/monitor_resources.sh:84-106`, `docker-compose.yml:752-783`, `docker-compose.production.yml:240-272`.
- **Evidence:** The `nginx` service is gated behind profile `nginx` and not started in production (Caddy is the external proxy). `docker ps` shows no `sowknow4-nginx`.
- **User/business impact:** 5xx error-rate alert always reads 0, masking outages.
- **Effort to fix:** small.
- **Risk of activating:** low.
- **Priority score:** high.
- **Fix:** Change script to read from Caddy access logs (e.g., `/var/log/caddy/access.log`) or from backend `/metrics`/structured logs, or query the backend error-rate tracker.

#### A20. `monitoring_tasks.py` memory thresholds are wrong for actual containers

- **What:** Worker memory alert thresholds are hard-coded to 1024 MB warning / 1152 MB critical.
- **Files:** `backend/app/tasks/monitoring_tasks.py:26-27`, `docker-compose.yml:356-571`.
- **Evidence:** Thresholds assume a 1280 MB limit, but actual workers run with 3072–6144 MB limits.
- **User/business impact:** Workers can be under real memory pressure without triggering alerts.
- **Effort to fix:** small.
- **Risk of activating:** low.
- **Priority score:** medium.
- **Fix:** Derive thresholds from a `MEM_LIMIT_MB` or `CELERY_MEMORY_WARN_MB` env var set per worker in compose.

#### A21. Production compose file is incomplete and ambiguous

- **What:** `docker-compose.production.yml` (used by `deploy-production.sh`) lacks the pipeline workers, embed-server, rerank-server, and Prometheus services that exist in the committed `docker-compose.yml`.
- **Files:** `docker-compose.production.yml`, `docker-compose.yml`, `scripts/deploy-production.sh`.
- **Evidence:** `deploy-production.sh:136-144` runs `docker-compose -f docker-compose.production.yml up -d`. That file defines a single `celery-worker` consuming `-Q celery,document_processing,scheduled,collections`, missing all `pipeline.*` queues, and has no `embed-server`, `rerank-server`, or `prometheus` services. The committed `docker-compose.yml` contains the fuller topology but is not referenced by the deploy script.
- **User/business impact:** Deployments from `deploy-production.sh` run a degraded topology: document pipeline stages may never execute, embeddings/reranking are unavailable, and metrics are not scraped.
- **Effort to fix:** small.
- **Risk of activating:** high (changing production topology).
- **Priority score:** highest.
- **Fix:** Either (a) make `docker-compose.production.yml` the canonical complete topology by copying missing services/workers from `docker-compose.yml`, or (b) update `deploy-production.sh` to use `docker-compose.yml` and delete `docker-compose.production.yml`.

#### A22. `telegram-bot` container is expected by watchdog but not running

- **What:** `monitoring/guardian-hc/scripts/watchdog.sh` expects `sowknow4-telegram-bot` in `EXPECTED_CONTAINERS`.
- **Files:** `monitoring/guardian-hc/scripts/watchdog.sh:33`, `docker-compose.yml:688-724`.
- **Evidence:** `docker ps` shows no `sowknow4-telegram-bot`; the service is in compose but may not be started.
- **User/business impact:** Watchdog alerts every patrol cycle until the container is started or removed from the expected list.
- **Effort to fix:** small.
- **Risk of activating:** low.
- **Priority score:** medium.
- **Fix:** Either start `telegram-bot` or remove it from `EXPECTED_CONTAINERS`.

#### A23. `/collections` page has inconsistent role gating

- **What:** Navigation hides `/collections` behind admin/superuser, but the home page service grid exposes it unconditionally.
- **Files:** `frontend/components/Navigation.tsx:61-70`, `frontend/app/[locale]/page.tsx:72-83,217-253`, `frontend/app/[locale]/collections/page.tsx`.
- **Evidence:** `navItems` has `roles: ['admin','superuser']` for collections, but the service grid card has no role check. `CommandPalette.tsx` is just a `SearchModal` wrapper and does not expose `/collections`.
- **User/business impact:** Non-admin users can reach a feature the navigation says they should not see, or the navigation is wrong.
- **Effort to fix:** small.
- **Risk of activating:** low–medium.
- **Priority score:** high.
- **Fix:** Decide intended audience. If collections are for everyone, remove `roles` from Navigation. If admin-only, add a role guard to the home page service-grid card.

#### A24. Admin pages `/settings`, `/monitoring`, `/admin/search-debug` lack client role guards

- **What:** Only `/dashboard` redirects non-admins; other admin pages rely solely on backend authorization.
- **Files:** `frontend/app/[locale]/settings/page.tsx`, `frontend/app/[locale]/monitoring/page.tsx`, `frontend/app/[locale]/admin/search-debug/page.tsx`, contrast with `frontend/app/[locale]/dashboard/page.tsx:122-128`.
- **Evidence:** No client-side `useEffect` redirect in those pages.
- **User/business impact:** Unauthorized users could view admin UI if backend checks are missed; inconsistent security posture.
- **Effort to fix:** small.
- **Risk of activating:** medium if backend not enforcing; low otherwise.
- **Priority score:** medium-high.
- **Fix:** Add the same client guard from `dashboard/page.tsx` to each affected page.

---

### Category B — Dead code (safe to delete)

#### B1. `main_minimal.py` — unused alternative entrypoint

- **Files:** `backend/app/main_minimal.py` (580 lines).
- **Evidence:** Production compose uses `app.main:app`; no script/nginx references `main_minimal`.
- **Lines to remove:** 580.
- **Fix:** Delete after porting any missing wiring (e.g., monitoring status endpoints) to `main.py`.

#### B2. `backend/app/performance.py` — never imported

- **Files:** `backend/app/performance.py` (327 lines).
- **Evidence:** No production imports; only test files and its own `__main__` block reference it.
- **Lines to remove:** 327.
- **Fix:** Delete or call `apply_performance_tuning(engine)` from `main.py` lifespan.

#### B3. `backend/app/services/performance_service.py` — dead and broken

- **Files:** `backend/app/services/performance_service.py` (316 lines).
- **Evidence:** No production imports; has broken `cache_monitor_service` import.
- **Lines to remove:** 316.
- **Fix:** Delete (preferred) or fix import and wire to an admin/status endpoint.

#### B4. `backend/app/services/structured_logging.py` — defined but not wired

- **Files:** `backend/app/services/structured_logging.py` (382 lines).
- **Evidence:** No production code calls `setup_structured_logging`, `get_request_logger`, or `get_query_logger`.
- **Lines to remove:** 382.
- **Fix:** Delete or call `setup_structured_logging()` in `main.py` startup and add request-log middleware.

#### B5. `backend/app/services/spell_service.py` — unreferenced

- **Files:** `backend/app/services/spell_service.py` (106 lines).
- **Evidence:** No imports outside the file.
- **Lines to remove:** 106.
- **Fix:** Delete or wire into search query preprocessing.

#### B6. `backend/app/services/auto_tagging_service.py` — unreferenced

- **Files:** `backend/app/services/auto_tagging_service.py` (384 lines).
- **Evidence:** No production imports. `api/status.py` claims "Auto-Tagging" is implemented.
- **Lines to remove:** 384.
- **Fix:** Delete or call from document processing pipeline; update `status.py` accordingly.

#### B7. `backend/app/services/silent_agent_loop.py` — only self-referenced

- **Files:** `backend/app/services/silent_agent_loop.py` (363 lines).
- **Evidence:** Only its own docstring imports it.
- **Lines to remove:** 363.
- **Fix:** Delete unless planned.

#### B8. `backend/app/services/swarm/v2/` — unused package

- **Files:** `backend/app/services/swarm/v2/*.py` (~320 lines).
- **Evidence:** No imports outside the package. Depends on unused NATS client.
- **Lines to remove:** ~320.
- **Fix:** Delete `backend/app/services/swarm/` or move to archive branch.

#### B9. `backend/app/services/agents/agent_orchestrator.py` — not used by API

- **Files:** `backend/app/services/agents/agent_orchestrator.py` (17425 bytes, ~470 lines).
- **Evidence:** `search_agent_router.py` imports `search_agent.py` directly, not the orchestrator.
- **Lines to remove:** ~470.
- **Fix:** Delete or wire into `search_agent_router.py`.

#### B10. `minimax_service.py` and `kimi_service.py` — deprecated providers

- **Files:** `backend/app/services/minimax_service.py`, `backend/app/services/kimi_service.py`.
- **Evidence:** Imported only by `llm_router.py` fallback injection, but `llm_router.fallback_chains` lists only `openrouter` and `together`.
- **Lines to remove:** ~520.
- **Fix:** Delete files and remove fallback injection in `llm_router.py`.

#### B11. `backend/embed_server/main.py` default `EmbeddingService` may be unused in production

- **Files:** `backend/app/services/embedding_service.py` (410 lines).
- **Evidence:** Production backend uses `embed_client.py` (HTTP). The embed server uses `embedding_service.py` only as fallback when ONNX is not selected.
- **Lines to remove:** N/A (keep for embed-server fallback).
- **Fix:** Document that `embedding_service.py` is the embed-server fallback, not the backend local path.

#### B12. `backend/app/services/performance.py` archived Docker Compose files

- **Files:** `docker/archived-compose/docker-compose.production.yml`, `docker/archived-compose/docker-compose.simple.yml`, `docker/archived-compose/docker-compose.prebuilt.yml`.
- **Evidence:** `deploy-production.sh` uses the root `docker-compose.production.yml`.
- **Fix:** Move entire `docker/archived-compose/` to git archive or delete.

#### B13. `backend/app/services/_spreadsheet_extractor.py` — internal helper naming

- **Files:** `backend/app/services/_spreadsheet_extractor.py` (added 2026-07-01).
- **Evidence:** Prefixed with `_`; verify it is imported by `text_extractor.py` or pipeline tasks.
- **Fix:** If unused, delete. If used, leave as private helper.

#### B14. `backend/app/api/reports.py` schema may be unused

- **Files:** `backend/app/schemas/reports.py`.
- **Evidence:** Only referenced by `reports.py` router, which itself is unwired (A2).
- **Fix:** If A2 is fixed, keep; otherwise delete alongside A2.

#### B15. `backend/app/core/context.py` — read but not fully wired

- **Files:** `backend/app/core/context.py` (453 bytes).
- **Evidence:** Imported by `llm_gateway.py` for user context, but no middleware sets `current_user_id`/`current_user_role`.
- **Fix:** Either remove the contextvars or add middleware that sets them from the request.

#### B16. `backend/telegram_bot/` may be unmaintained

- **Files:** `backend/telegram_bot/`.
- **Evidence:** In compose but the bot logic was not verified to call current API routes. Deserves a focused audit.
- **Fix:** Audit separately; flag if commands reference removed endpoints.

#### B17. `frontend/components/BatchUploader.tsx` — dead component

- **Files:** `frontend/components/BatchUploader.tsx` (~208 lines).
- **Evidence:** No file in `frontend/app` or `frontend/components` imports it.
- **Lines to remove:** 208.
- **Fix:** Delete file; no callers to update.

#### B18. `deferred_query_service.py` — unused deferred-query feature

- **Files:** `backend/app/services/deferred_query_service.py` (220 lines).
- **Evidence:** Only self-referenced; no callers.
- **Lines to remove:** 220.
- **Fix:** Delete file.

#### B19. `tool_registry.py` — unused tool registry

- **Files:** `backend/app/services/tool_registry.py` (100 lines).
- **Evidence:** No callers; not wired to any LLM function-calling path.
- **Lines to remove:** 100.
- **Fix:** Delete file.

#### B20. Old anomaly recovery tasks superseded by pipeline sweeper

- **Files:** `backend/app/tasks/anomaly_tasks.py:495`, `:656`, `:878`.
- **Evidence:** `recover_stuck_documents`, `recover_pending_documents`, `fail_stuck_processing_documents` have no callers and are superseded by `pipeline_sweeper.py`.
- **Fix:** Delete these task definitions.

#### B21. Old monolithic document processing task

- **Files:** `backend/app/tasks/document_tasks.py:75`.
- **Evidence:** `process_document` only referenced in a docstring; replaced by `pipeline_orchestrator.dispatch_document`.
- **Fix:** Delete task or mark deprecated.

#### B22. Old entity extraction tasks

- **Files:** `backend/app/tasks/document_tasks.py:681`, `:770`.
- **Evidence:** `extract_entities_for_document` / `batch_extract_entities` replaced by `pipeline.entity_stage`.
- **Fix:** Delete tasks.

#### B23. Report generator tasks have no callers (unless reports router is wired)

- **Files:** `backend/app/tasks/report_tasks.py:34`, `:160`.
- **Evidence:** `generate_pdf_report`, `generate_excel_export` have no `.delay()` callers unless `reports.py` router is fixed (A2).
- **Fix:** If A2 is fixed, these become live; otherwise delete them.

#### B24. `guardian_tasks.guardian_ping` — unused

- **Files:** `backend/app/tasks/guardian_tasks.py:7`.
- **Evidence:** Only used in runbook examples; no operational scheduling.
- **Fix:** Delete file and remove from `celery_app.py:46`.

#### B25. Unused health/cost checks in anomaly tasks

- **Files:** `backend/app/tasks/anomaly_tasks.py:302`, `:452`.
- **Evidence:** `system_health_check`, `check_api_costs` defined but never scheduled/called.
- **Fix:** Delete or schedule in beat.

#### B26. Old pending reprocess task

- **Files:** `backend/app/tasks/document_tasks.py:885`.
- **Evidence:** `reprocess_pending_documents` has no callers.
- **Fix:** Delete.

#### B27. Old batch upload task

- **Files:** `backend/app/tasks/document_tasks.py:430`.
- **Evidence:** `process_batch_documents` has no callers.
- **Fix:** Delete.

---

### Category C — Dormant by design (activation decision needed)

#### C1. Embedding implementations (3 variants)

- **What:** `embedding_service.py` (sentence-transformers), `embed_client.py` (HTTP to embed-server), `embedding_service_onnx.py` (ONNX/INT8).
- **Files:** `backend/app/services/embedding_service.py`, `backend/app/services/embed_client.py`, `backend/app/services/embedding_service_onnx.py`, `backend/embed_server/main.py`.
- **Current state:** Backend production code uses `embed_client.py`. Embed server picks ONNX if available, else sentence-transformers.
- **Decision:** Keep architecture; rename/document roles to avoid confusion.

#### C2. Search implementations (2 variants)

- **What:** `search_service.py` (HybridSearchService) and `search_agent.py` (agentic search).
- **Files:** `backend/app/services/search_service.py`, `backend/app/services/search_agent.py`, `backend/app/api/search_agent_router.py`.
- **Current state:** Both are live: `search_service.py` serves documents/graph/collections; `search_agent_router.py` serves agentic search.
- **Decision:** No action unless product wants to consolidate.

#### C3. OCR cloud provider (Tencent)

- **What:** `TENCENT_OCR_SECRET_ID`/`TENCENT_OCR_SECRET_KEY` in `.env.example`.
- **Files:** `.env.example:98-99`, `backend/app/services/ocr_service.py`.
- **Current state:** Variables are documented but not read in code.
- **Decision:** Remove from `.env.example` or implement high-fidelity cloud OCR.

#### C4. LLM fallback providers (Together, Ollama)

- **What:** `together_service.py` and `ollama_service.py` are wired into `llm_router.py` but require env vars not present in `.env.example`.
- **Files:** `backend/app/services/together_service.py`, `backend/app/services/ollama_service.py`, `backend/app/services/llm_router.py`.
- **Current state:** OpenRouter is primary; Together/Ollama fallbacks are dormant.
- **Decision:** Keep for resilience if keys will be configured; otherwise delete to simplify.

#### C5. Multi-agent search

- **What:** `status.py` lists "Multi-Agent Search" as ⏳ incomplete. `agent_orchestrator.py` exists but unwired.
- **Files:** `backend/app/api/status.py:117`, `backend/app/services/agents/agent_orchestrator.py`.
- **Decision:** Go/no-go on multi-agent search v2.

#### C6. Push notifications

- **What:** Backend API, service worker, and `AppHooks.tsx` auto-subscribe logic exist.
- **Files:** `backend/app/api/push.py`, `frontend/hooks/usePushNotifications.ts`, `frontend/worker/index.js`, `frontend/components/AppHooks.tsx`.
- **Current state:** Fully wired but gated by browser permission and VAPID keys.
- **Decision:** Verify VAPID keys are configured in production; consider making subscription explicit rather than auto.

#### C7. Subscriptions module

- **What:** `subscriptions.py` router and `subscription_tasks.py` are wired; frontend has a subscriptions page.
- **Files:** `backend/app/api/subscriptions.py`, `backend/app/tasks/subscription_tasks.py`, `frontend/app/[locale]/subscriptions/page.tsx`.
- **Current state:** UI page seems to mix "Mac app subscription bundle" localStorage with backend subscription records.
- **Decision:** Clarify whether this is a billing feature or a document-reminder feature.

#### C8. Upload pause toggle

- **What:** Admin can pause uploads via Redis key; automatic red-state throttling exists.
- **Files:** `backend/app/api/documents_common.py`, `backend/app/api/admin.py:1580-1624`.
- **Current state:** Wired in admin and upload path.
- **Decision:** Working as designed; verify dashboard exposes it.

#### C9. `backfill_tasks` are not registered in Celery

- **What:** Manual disaster-recovery tasks (`classify_and_recover_errors`, `reprocess_failed_documents`, `backfill_missing_embeddings`, etc.).
- **Files:** `backend/app/tasks/backfill_tasks.py` (377 lines).
- **Current state:** Module not in `celery_app.include`; only unit tests import it.
- **Decision:** Add to `include` for manual `celery call` use, or delete.

#### C10. Smart-folders fallback polling branch is unreachable

- **What:** Polling fallback in smart-folders page.
- **Files:** `frontend/app/[locale]/smart-folders/page.tsx:68,156-211`.
- **Current state:** `useFallbackPolling` is initialized to `false` and never set to `true`; SSE is the only active path.
- **Decision:** Wire `setUseFallbackPolling(true)` on SSE failure, or delete the fallback.

#### C11. `/verify-email/[token]` is email-only

- **What:** Email verification page.
- **Files:** `frontend/app/[locale]/verify-email/[token]/page.tsx`.
- **Current state:** No UI link targets it; intended to be opened from an email.
- **Decision:** Correct by design.

#### C12. `/offline` page is service-worker only

- **What:** Offline fallback page.
- **Files:** `frontend/app/[locale]/offline/page.tsx`, `frontend/next.config.js`, `frontend/public/fallback-*.js`.
- **Current state:** No UI link; PWA service worker maps offline requests here.
- **Decision:** Correct by design.

#### C13. `/api/health` Next.js route is unused by the UI

- **What:** Frontend API route for health probes.
- **Files:** `frontend/app/api/health/route.ts`.
- **Current state:** Monitoring page uses `/api/v1/health` (backend); no frontend fetch calls `/api/health`.
- **Decision:** Keep for infrastructure probes, or delete if redundant.

#### C14. Settings "System" tab is a stub

- **What:** Admin settings page section.
- **Files:** `frontend/app/[locale]/settings/page.tsx:240-262`.
- **Current state:** Tab renders placeholder cards with no controls or API calls.
- **Decision:** Implement backend endpoints and UI controls, or remove the tab.

#### C15. `space_tasks` module is intentionally held back

- **What:** Space rule sync task (`sync_space_rules_task`) in `backend/app/tasks/space_tasks.py`.
- **Files:** `backend/app/tasks/space_tasks.py` (41 lines); `backend/app/api/spaces.py:230-246`.
- **Current state:** The `/spaces/{id}/sync` endpoint imports the task inside `try/except ImportError` and returns HTTP 501 with the message "Sync task not yet available; sync will be available after Task 5". The module is not in `celery_app.include`, so this is a deliberate placeholder, not a silent failure.
- **Decision:** Go/no-go on space rule sync. If ready, add `"app.tasks.space_tasks"` to `celery_app.py:35-50` `include=[...]` and remove the `try/except ImportError` from `spaces.py`. If not ready, leave the 501 placeholder in place.

---

### Category D — Redundant / consolidate

#### D1. Three overlapping monitoring systems

- **What:** `monitoring.py` (CostTracker, QueueMonitor, SystemMonitor, AlertManager), `prometheus_metrics.py`, `rollback_monitor.py`.
- **Files:** `backend/app/services/monitoring.py`, `backend/app/services/prometheus_metrics.py`, `backend/app/services/rollback_monitor.py`.
- **Issue:** Costs tracked in `CostTracker`, latency/TTFT/cost in `rollback_monitor`, but Prometheus gauges stay at zero.
- **Fix:** Consolidate on Prometheus as canonical export; have `CostTracker` and `rollback_monitor` push to `get_metrics()`.

#### D2. Two LLM abstraction layers

- **What:** `llm_gateway.py` (facade) and `llm_router.py` (provider selection/fallback).
- **Files:** `backend/app/services/llm_gateway.py`, `backend/app/services/llm_router.py`.
- **Issue:** Most consumers use `llm_gateway`; some smart-folder agents use `llm_router` directly.
- **Fix:** Route all consumers through `llm_gateway`; document the single path.

#### D3. Two FastAPI entrypoints

- **What:** `main.py` and `main_minimal.py`.
- **Files:** `backend/app/main.py`, `backend/app/main_minimal.py`.
- **Issue:** `main_minimal.py` is stale and has broken imports.
- **Fix:** Delete `main_minimal.py` after merging any valuable endpoints (monitoring status) into `main.py`.

#### D4. Two health check implementations

- **What:** `main.py` root `/health` vs. `health_router` `/api/v1/health`.
- **Files:** `backend/app/main.py`, `backend/app/api/health.py`.
- **Issue:** Both exist; nginx sends `/health` to backend root, but the frontend monitoring page calls `/api/v1/health`.
- **Fix:** Keep `/api/v1/health` as canonical; remove root `/health` from `main.py` or make it redirect.

#### D5. Two pipeline diagnostics endpoints

- **What:** `/api/v1/admin/pipeline/diagnostics` in `admin.py` and `/api/v1/admin/pipeline/status` in `pipeline_admin.py`.
- **Files:** `backend/app/api/admin.py:1329`, `backend/app/api/pipeline_admin.py`.
- **Issue:** Overlap in queue/worker/stage reporting.
- **Fix:** Merge into one admin pipeline router after registering it (A1).

#### D6. Inline API base URLs vs. central `lib/api.ts`

- **What:** Multiple pages redefine `const API_BASE = process.env.NEXT_PUBLIC_API_URL || '/api'` instead of using `frontend/lib/api.ts`.
- **Files:** `frontend/app/[locale]/login/page.tsx`, `register/page.tsx`, `verify-email/[token]/page.tsx`, `settings/page.tsx`, `documents/[id]/page.tsx`, `documents/page.tsx`, `chat/page.tsx`, `collections/page.tsx`, `collections/[id]/page.tsx`.
- **Issue:** Inconsistent CSRF/header handling, harder environment changes, larger bundle. `collections/page.tsx` even imports `{ api }` and then dynamically imports it again.
- **Fix:** Refactor pages to import the singleton `api` client from `frontend/lib/api.ts`.

#### D7. `MobileSheet` and `MobileBottomSheet` are near-duplicates

- **What:** Two mobile bottom-sheet components.
- **Files:** `frontend/components/mobile/MobileSheet.tsx` (~133 lines), `frontend/components/mobile/MobileBottomSheet.tsx` (~125 lines).
- **Issue:** Both implement touch-drag dismissal, backdrop tap, body scroll lock, Escape handling, and animated layout. Only prop differences (`headerActions`/`footer` vs `heightPercent`).
- **Fix:** Consolidate into one component with optional props.

#### D8. Duplicate `ChunkingService` implementation

- **What:** `ChunkingService` exists inside `embedding_service.py` and as standalone `chunking_service.py`.
- **Files:** `backend/app/services/embedding_service.py` (~line 319), `backend/app/services/chunking_service.py`.
- **Issue:** Live tasks import `chunking_service.py`. The copy in `embedding_service.py` is never imported.
- **Fix:** Remove `ChunkingService` from `embedding_service.py`; import from `chunking_service.py` if needed.

---

## 4. Top 10 Quick Wins

Ranked by impact × effort × risk.

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
| 9 | Add Prometheus service to compose | A | `docker-compose.yml`, `monitoring/prometheus.yml` | Add service + mount config | small | low | Metrics visible |
| 10 | Fix `/collections` role gating inconsistency | A | `frontend/components/Navigation.tsx`, `frontend/app/[locale]/page.tsx` | Unify role check | small | low | Consistent UX/permissions |

**Runners-up:** Wire HTTP request metrics middleware (A4); add cache stats admin endpoint (A13); delete `main_minimal.py` (B1/D3); remove NATS init from lifespan (A10).

---

## 5. Deletion Candidates

Safe to remove unless a pending feature needs them. Estimated line-count reduction: **~8,200 lines**.

| Module / directory | Lines | Why delete | Notes |
|--------------------|-------|------------|-------|
| `backend/app/main_minimal.py` | 580 | Unused; broken imports | Port monitoring endpoints first |
| `backend/app/performance.py` | 327 | Never imported | Or wire it intentionally |
| `backend/app/services/performance_service.py` | 316 | Unused + broken import | See A7 |
| `backend/app/services/structured_logging.py` | 382 | Never wired | Or add structured logging |
| `backend/app/services/spell_service.py` | 106 | No callers | — |
| `backend/app/services/auto_tagging_service.py` | 384 | Built but not invoked | See A18; update `status.py` if deleted |
| `backend/app/services/silent_agent_loop.py` | 363 | No callers | — |
| `backend/app/services/deferred_query_service.py` | 220 | No callers | — |
| `backend/app/services/tool_registry.py` | 100 | No callers | — |
| `backend/app/services/swarm/v2/` | ~320 | No callers | Includes NATS-only code |
| `backend/app/services/agents/` package | ~2,200 | Router bypasses orchestrator | Decide on multi-agent v2 first |
| `backend/app/services/minimax_service.py` | ~280 | Deprecated | Remove from `llm_router.py` too |
| `backend/app/services/kimi_service.py` | ~290 | Deprecated | Remove from `llm_router.py` too |
| `frontend/components/BatchUploader.tsx` | 208 | No imports | — |
| `docker/archived-compose/` | ~700 | Superseded by root compose | Historical configs |
| Old tasks in `document_tasks.py` / `anomaly_tasks.py` | ~500 | Replaced by pipeline sweeper/stages | Remove individually |
| `backend/app/tasks/guardian_tasks.py` | small | No operational scheduling | Remove from `celery_app.py:46` too |
| `backend/app/api/reports.py` + schema | 76 + small | Only if A2 rejected | Otherwise keep |

---

## 6. Activation Decisions Needed

| Item | Question | Recommended owner |
|------|----------|-------------------|
| Multi-agent search | Wire `agent_orchestrator.py` or delete it? | Engineering lead |
| Auto-tagging | Add to document pipeline or remove from status page? | Product |
| Together/Ollama fallback | Configure keys or remove fallback code? | Platform |
| Tencent OCR | Implement high-fidelity mode or remove config? | Product |
| Guardian HC | Deploy as service/cron or archive? | SRE |
| Push notifications | Keep auto-subscribe or make explicit? | Product |
| Subscriptions page | Billing feature or local reminder? | Product |
| ONNX embedding | Make default in embed server or keep sentence-transformers fallback? | ML/Platform |
| Space rule sync | Add `space_tasks` to Celery or remove the sync endpoint? | Engineering |
| Backfill tasks | Register `backfill_tasks` in Celery or delete? | Engineering |
| Smart-folders polling fallback | Wire on SSE failure or delete? | Engineering |
| Settings "System" tab | Implement controls or remove? | Product |
| Prometheus scraper | Enable `monitoring` profile or remove config? | SRE |
| nginx/certbot/Ollama/Vault profiles | Keep for dev or delete? | Platform |

---

## 7. Root Cause Analysis

### Recurring patterns

1. **Router registration is manual and error-prone.** `main.py` imports many modules but the `include_router` list is separate; routers are dropped.
2. **Celery `include=` list is not kept in sync with the beat schedule and API dispatches.** `subscription_tasks` and `health_report_tasks` are scheduled but not loaded by workers. `space_tasks` is intentionally held back behind a 501 placeholder.
3. **Alternative entrypoints are left to rot.** `main_minimal.py` was kept as a fallback but is now broken, creating confusion and duplicated wiring.
4. **Metrics are added without a scraper or updater.** `/metrics` and `prometheus_metrics.py` look complete but have no consumer and few producers.
5. **Docker Compose and deploy-script drift.** `deploy-production.sh` uses `docker-compose.production.yml`, which is a stripped-down topology missing pipeline workers, embed-server, rerank-server, and Prometheus, while the committed `docker-compose.yml` contains the fuller topology.
6. **Host-level monitoring depends on backend endpoints that only exist in the unused entrypoint.** `monitor-alerts.sh` calls `/api/v1/monitoring/*`, which are only in `main_minimal.py`.
7. **Feature flags are set in env but not read in code.** `NEXT_PUBLIC_ENABLE_*` and several `.env.example` variables are documentation-only.
8. **No CI gate for wiring completeness.** Nothing verifies that every imported router is included, every scheduled task has a worker queue, every env var is read, or that cron scripts hit valid endpoints.

### What is missing from the development process

- A **wiring completeness check** in CI.
- A **single source of truth** for routers, task modules, beat schedule, and compose services.
- A **post-merge verification step** that starts the production compose and asserts key endpoints return 200.
- **Code review checklist** item: "Is every new route/service/metric actually wired to live traffic?"

---

## 8. Process Recommendations

### 8.1 PR template additions

Add this section to every PR:

```markdown
### Wiring checklist
- [ ] New API routers are registered in `backend/app/main.py`
- [ ] New Celery task modules are added to `backend/app/celery_app.py` `include`
- [ ] New beat-scheduled tasks are in a module listed in `celery_app.py` `include`
- [ ] New `.delay()` calls dispatch tasks in modules listed in `celery_app.py` `include`
- [ ] New Celery tasks route to a queue consumed by a worker in the canonical compose file
- [ ] New cron/script HTTP calls hit endpoints registered in `backend/app/main.py`
- [ ] New metrics are both produced (in code) and scraped (compose/config)
- [ ] New env vars are read in code and documented in `.env.example`
- [ ] Frontend pages/components are linked from `Navigation.tsx` or reachable route
- [ ] Feature flags are read in code, not just exported by deploy scripts
```

### 8.2 Code review checklist

- For every new service: **who calls it in a production path?**
- For every new route: **is it included in `main.py` and reachable through nginx?**
- For every new Celery task: **is its module in `celery_app.py` `include` and its queue consumed by a worker?**
- For every new beat schedule entry: **does the referenced module appear in `celery_app.py` `include`?**
- For every new cron/script HTTP call: **does the endpoint exist in `main.py`?**
- For every new metric: **is there a scraper and a dashboard/alarm consumer?**
- For every env var: **grep for it in application code.**

### 8.3 CI/CD gates

1. **Wiring linter.** A script that fails if:
   - Any file in `backend/app/api/` defines a router but is not included in `main.py`.
   - Any task name referenced in the Celery `beat_schedule` is not in a module listed in `celery_app.conf.include`.
   - Any task `.delay()` call in API code is not in a module listed in `celery_app.conf.include`.
   - Any task module in `celery_app.py` is not consumed by at least one worker queue in production compose.
   - Any env var in `.env.example` is not referenced in application code.
2. **Cron script validator.** Parse `scripts/*.sh` for `curl` targets and verify each path exists in the live FastAPI OpenAPI schema.
3. **Startup smoke test.** Build and start the canonical production compose in CI, then:
   - `GET /api/v1/health` → 200
   - `GET /metrics` → 200
   - For every router, hit a representative endpoint.
4. **Metrics scrape test.** Run a Prometheus container in CI that scrapes `/metrics` and asserts expected metrics are non-zero after a synthetic request.

### 8.4 Operational hygiene

- Delete `main_minimal.py` and archived compose files.
- Maintain a **live service registry** markdown file listing routers, workers, cron jobs, feature flags, and metrics owners.
- Run this wiring audit quarterly.

---

## 9. Appendix: Verified Live Paths

The following major subsystems are confirmed wired to production user requests:

| Subsystem | Entry point | Note |
|-----------|-------------|------|
| Auth | `backend/app/api/auth.py` → `main.py` | Live |
| Documents (CRUD, upload, journal) | `backend/app/api/documents.py` (includes upload/journal sub-routers) | Live |
| Search | `backend/app/api/search_agent_router.py` | Live |
| Search suggest/feedback | `backend/app/api/search_suggest.py`, `search_feedback.py` | Live |
| Collections / Smart Folders | `backend/app/api/collections.py`, `smart_folders.py` | Live |
| Chat | `backend/app/api/chat.py` | Live |
| Bookmarks / Notes / Spaces / Tasks | `backend/app/api/bookmarks.py`, `notes.py`, `spaces.py`, `tasks.py` | Live |
| Knowledge Graph / Graph-RAG | `backend/app/api/knowledge_graph.py`, `graph_rag.py` | Live |
| Admin users/stats/anomalies/pipeline diagnostics | `backend/app/api/admin.py` | Mostly live; pipeline status/retry missing (A1) |
| Health / Status / Rollback | `backend/app/api/health.py`, `status.py` | Live |
| Push subscriptions | `backend/app/api/push.py` | Live (permission-gated) |
| Subscriptions | `backend/app/api/subscriptions.py` | Live |
| Document processing pipeline | `backend/app/tasks/pipeline_tasks.py` etc. | Tasks defined, but per-stage queues need workers in some compose files (A9, A21) |
| Celery beat schedule | `backend/app/celery_app.py` | Live; some scheduled modules not loaded by workers (A15, A16) |

---

## 10. Next Steps

1. **Immediately fix Category A one-liners** (A1, A2, A6, A7, A15, A16, A4, A12, A23, A24) in a single PR.
2. **Restore host monitoring** (A18, A19, A20) by adding monitoring endpoints to `main.py` and fixing `monitor_resources.sh`.
3. **Fix deployment tooling** (A21) — choose one canonical compose file and update `deploy-production.sh` to use it.
4. **Add Prometheus service and request metrics middleware** (A3, A5, A11) in a follow-up PR.
5. **Resolve production compose topology** (A9) with platform/SRE to decide whether to add embed-server/rerank-server and pipeline workers.
6. **Decide on auto-tagging** (A17) — wire it or remove it from `status.py`.
7. **Schedule deletion PR** for Category B items after product sign-off on C1-C15.
8. **Implement CI wiring linter and cron validator** to prevent recurrence.
