# Changelog

All notable changes to SOWKNOW are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased] — Celery Task Queue Remediation (Audit Report #8)

### Added

#### Dead Letter Queue (DLQ) — TASK 1.1
- `backend/app/models/failed_task.py` — `FailedCeleryTask` ORM model with full schema
- `backend/app/services/dlq_service.py` — `DeadLetterQueueService` with `store_failed_task` and `list_failed_tasks`
- `backend/app/api/admin.py` — `GET /admin/failed-tasks`, `DELETE /admin/failed-tasks/{id}`, `POST /admin/test-alert`
- Migration `007_add_failed_celery_tasks_dlq.py` — creates `failed_celery_tasks` table

#### Embedding Tasks Module — TASK 1.2 & 1.4
- `backend/app/tasks/embedding_tasks.py` — three dedicated Celery tasks:
  - `generate_embeddings_batch` — batch embedding with exponential backoff (max 3 retries)
  - `recompute_embeddings_for_document` — per-document recompute
  - `upgrade_embeddings_model` — bulk model migration
- All tasks use `@celery_app.task` decorator and are registered in `tasks/__init__.py`

#### Celery Worker Health Check — TASK 1.3
- `backend/app/api/health.py` — `GET /health/celery` (worker status, 503 on no workers) and `GET /health` (unified 5-component check: DB, Redis, Celery, disk, memory)
- `GET /health/celery` wired into `main.py`

#### Alert & Notification System — TASK 2.1
- `backend/app/services/alert_service.py` — `AlertService` with severity routing (CRITICAL → Telegram + Email, WARN → Email only)
- `backend/app/services/telegram_notifier.py` — Telegram Bot API integration
- `backend/app/services/email_notifier.py` — SendGrid email integration

#### Failure Callbacks — TASK 2.2
- `backend/app/tasks/base.py` — `base_task_failure_handler()` universal on_failure callback
- All tasks wired with `on_failure` callbacks that store to DLQ + fire alerts
- `on_process_document_failure` updates `doc.status = ERROR` and `doc.metadata['failure_reason']`
- Prometheus metrics incremented on task failure via `metrics.task_failures.labels(task_name=...).inc()`

#### Report Tasks — TASK 2.1
- `backend/app/tasks/report_tasks.py` — `generate_pdf_report`, `generate_excel_export`, `cleanup_old_reports`
- `backend/app/api/reports.py` — `POST /reports/generate` (202 Accepted), `GET /reports/status/{task_id}`

#### Batch Upload API — TASK 2.4
- `POST /documents/upload-batch` now returns `202 Accepted` with `batch_id`
- 20-file per-batch limit enforced
- `GET /documents/batch/{batch_id}/status` endpoint for progress tracking
- `BatchUploadResponse`, `BatchStatusResponse`, `ReprocessRequest` Pydantic schemas
- Migration `008_add_batch_id_to_documents.py` — adds `batch_id` column to documents
- `frontend/components/BatchUploader.tsx` — drag-and-drop batch upload component with progress bar

#### Full-Text Search — TASK 3
- Migration `009_add_fulltext_search.py` — PostgreSQL full-text search index

#### E2E & Unit Tests — TASK 2.3
- `tests/unit/tasks/test_dlq.py` — 3 DLQ unit tests (insert, error handling, pagination)
- `tests/unit/tasks/test_embedding_tasks.py` — 3 embedding task unit tests
- `tests/e2e/test_document_processing.py` — 4 E2E pipeline tests
- `tests/integration/test_batch_upload.py` — 3 batch upload integration tests
- `pytest.ini` — custom markers: `e2e`, `integration`, `unit`, `slow`
- `.github/workflows/ci.yml` — CI pipeline with unit + E2E + integration test jobs

### Changed

- `backend/app/celery_app.py` — `visibility_timeout = 7200` (2h) > `task_time_limit = 600` (10min) ✓
- `backend/app/tasks/document_tasks.py` — `max_retries=3` explicit; `on_failure` callbacks wired
- `backend/app/tasks/anomaly_tasks.py` — `on_failure` callback wired; alert severity routing
- `backend/.env.example` — added: `CELERY_VISIBILITY_TIMEOUT`, `CELERY_RATE_LIMIT`, `CELERY_MEMORY_WARNING_MB`, `REPORTS_DIR`, `TELEGRAM_ADMIN_CHAT_ID`, `SENDGRID_API_KEY`, `ALERT_FROM_EMAIL`, `ADMIN_EMAILS`
- `.env.example` (root) — mirrored Celery + alert env vars
- `setup.cfg` — flake8 config for black-compatible E203 ignore

### Fixed

- `batch-upload` endpoint now correctly returns HTTP 202 (was 200)
- `generate_embeddings` task was a stub — now fully implemented with `EmbeddingService`

---

## Earlier History

See git log for prior changes.
