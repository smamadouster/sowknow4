"""
Celery application configuration for SOWKNOW async tasks
"""

import os

from celery import Celery
from celery.schedules import crontab
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Redis / broker configuration — sourced from authenticated settings.REDIS_URL
# ---------------------------------------------------------------------------

try:
    from app.core.config import settings as _settings

    REDIS_URL = _settings.REDIS_URL
except Exception:
    # Fallback: build URL from REDIS_PASSWORD with proper encoding
    from app.core.redis_url import safe_redis_url

    REDIS_URL = safe_redis_url()

# ---------------------------------------------------------------------------
# Create Celery app
# ---------------------------------------------------------------------------

celery_app = Celery(
    "sowknow",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=[
        "app.tasks.document_tasks",
        "app.tasks.anomaly_tasks",
        "app.tasks.embedding_tasks",
        "app.tasks.report_tasks",
        "app.tasks.monitoring_tasks",
        "app.tasks.article_tasks",
        "app.tasks.voice_tasks",
        "app.tasks.pipeline_tasks",
        "app.tasks.pipeline_orchestrator",
        "app.tasks.pipeline_sweeper",
        "app.tasks.guardian_tasks",
        "app.tasks.smart_folder_tasks",
        "app.tasks.collection_report_tasks",
    ],
)

# ---------------------------------------------------------------------------
# Celery configuration
# ---------------------------------------------------------------------------

# visibility_timeout must be > task_time_limit to prevent premature re-delivery
# Defaults: visibility_timeout = 7200 (2h), task_time_limit = 600 (10min) → 7200 > 600 ✓
visibility_timeout = int(os.getenv("CELERY_VISIBILITY_TIMEOUT", "7200"))  # 2 hours
task_time_limit = int(os.getenv("CELERY_TASK_TIME_LIMIT", "600"))  # 10 minutes
_visibility_timeout = visibility_timeout
_task_time_limit = task_time_limit

celery_app.conf.update(
    # Default concurrency — overridden per-worker via CLI flags in docker-compose.
    # celery-heavy uses --pool=threads --concurrency=3 (threads share one 1.3GB model).
    worker_concurrency=1,
    worker_max_tasks_per_child=30,
    worker_prefetch_multiplier=1,
    # Serialisation — JSON only; no binary serializers permitted
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Task routing — pipeline stage tasks get per-stage queues
    task_routes={
        # Pipeline stage tasks
        "pipeline.ocr_stage": {"queue": "pipeline.ocr"},
        "pipeline.chunk_stage": {"queue": "pipeline.chunk"},
        "pipeline.embed_stage": {"queue": "pipeline.embed"},
        "pipeline.index_stage": {"queue": "pipeline.index"},
        "pipeline.article_stage": {"queue": "pipeline.articles"},
        "pipeline.entity_stage": {"queue": "pipeline.entities"},
        "pipeline.finalize_stage": {"queue": "pipeline.index"},
        "pipeline.sweeper": {"queue": "scheduled"},
        # Existing routes
        "build_smart_collection": {"queue": "collections"},
        "app.tasks.document_tasks.*": {"queue": "document_processing"},
        "app.tasks.embedding_tasks.*": {"queue": "document_processing"},
        "app.tasks.article_tasks.*": {"queue": "document_processing"},
        "app.tasks.voice_tasks.*": {"queue": "document_processing"},
        "app.tasks.anomaly_tasks.*": {"queue": "scheduled"},
        "app.tasks.report_tasks.*": {"queue": "celery"},
    },
    # Result backend
    result_extended=True,
    result_expires=86400,  # 24 hours — document processing may be checked hours later
    # Reliability
    task_acks_late=True,
    # Rate limiting — disabled by default. Slow tasks (entity extraction, LLM
    # calls) are naturally throttled by their own execution time. A global
    # rate limit artificially starves fast pipeline stages (index, finalize)
    # and causes massive queue build-up.
    task_default_rate_limit=os.getenv("CELERY_RATE_LIMIT", None),
    # Task time limits (env-configurable)
    task_soft_time_limit=int(os.getenv("CELERY_SOFT_TIME_LIMIT", "300")),  # 5 min
    task_time_limit=_task_time_limit,
    # Broker connection — retry on startup to survive Redis restarts
    # (required explicitly before Celery 6 where the default changes)
    broker_connection_retry_on_startup=True,
    # Broker transport — visibility timeout must exceed task_time_limit
    broker_transport_options={
        "visibility_timeout": _visibility_timeout,
        "fanout_prefix": True,
        "fanout_patterns": True,
    },
    # Beat scheduler
    beat_schedule={
        "daily-anomaly-report": {
            "task": "app.tasks.anomaly_tasks.daily_anomaly_report",
            "schedule": crontab(hour=9, minute=0),  # 09:00 AM daily
            "args": (),
        },
        "pipeline-sweeper": {
            "task": "pipeline.sweeper",
            "schedule": 300,  # Every 5 minutes — replaces recover_stuck/recover_pending/fail_stuck
            "args": (),
        },
        "cleanup-old-reports": {
            "task": "app.tasks.report_tasks.cleanup_old_reports",
            "schedule": crontab(hour=2, minute=0),  # 02:00 AM daily
            "args": (7,),  # Keep reports for 7 days
        },
    },
)

# Auto-discover tasks
celery_app.autodiscover_tasks(["app.tasks"])

if __name__ == "__main__":
    celery_app.start()
