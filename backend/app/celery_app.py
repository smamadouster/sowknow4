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
    # Fallback for environments where config.py is not yet bootstrapped
    # (e.g., during Alembic migrations or bare-metal test runs).
    # REDIS_URL from env must already include credentials in this path.
    _raw = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    if not _raw.startswith(("redis://", "rediss://", "unix://")):
        raise ValueError(f"REDIS_URL must start with 'redis://', 'rediss://', or 'unix://'; got: {_raw!r}")
    REDIS_URL = _raw

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
    # Memory optimisation — concurrency MUST stay at 1 to prevent OOM from
    # fork-duplicating the 1.3 GB embedding model.  Matches docker-compose --concurrency=1.
    worker_concurrency=1,
    worker_max_tasks_per_child=50,
    worker_prefetch_multiplier=1,
    # Serialisation — JSON only; no binary serializers permitted
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Task routing
    task_routes={
        "app.tasks.document_tasks.*": {"queue": "document_processing"},
        "app.tasks.embedding_tasks.*": {"queue": "document_processing"},
        "app.tasks.anomaly_tasks.*": {"queue": "scheduled"},
        "app.tasks.report_tasks.*": {"queue": "celery"},
    },
    # Result backend
    result_extended=True,
    result_expires=3600,  # 1 hour
    # Reliability
    task_acks_late=True,
    # Rate limiting (env-configurable)
    task_default_rate_limit=os.getenv("CELERY_RATE_LIMIT", "10/m"),
    # Task time limits (env-configurable)
    task_soft_time_limit=int(os.getenv("CELERY_SOFT_TIME_LIMIT", "300")),  # 5 min
    task_time_limit=_task_time_limit,
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
        "recover-stuck-documents": {
            "task": "app.tasks.anomaly_tasks.recover_stuck_documents",
            "schedule": 600,  # Every 10 minutes (600 seconds)
            "args": (5,),  # Max 5 minutes in processing state before recovery
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
