"""
Celery application configuration for SOWKNOW async tasks
"""
from celery import Celery
import os
from dotenv import load_dotenv

load_dotenv()

# Redis configuration
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Create Celery app
celery_app = Celery(
    "sowknow",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=[
        "app.tasks.document_tasks",
        "app.tasks.anomaly_tasks",
    ]
)

# Celery configuration
celery_app.conf.update(
    # Task settings
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,

    # Task routing
    task_routes={
        "app.tasks.document_tasks.*": {"queue": "document_processing"},
        "app.tasks.anomaly_tasks.*": {"queue": "scheduled"},
    },

    # Task result backend
    result_extended=True,
    result_expires=3600,  # 1 hour

    # Retry settings
    task_acks_late=True,
    worker_prefetch_multiplier=1,

    # Rate limiting
    task_default_rate_limit="10/m",

    # Task time limits
    task_soft_time_limit=300,  # 5 minutes
    task_time_limit=600,  # 10 minutes

    # Beat scheduler configuration
    beat_schedule={
        "daily-anomaly-report": {
            "task": "app.tasks.anomaly_tasks.daily_anomaly_report",
            "schedule": 86400.0,  # Daily (24 hours)
            "args": (),
        },
    },
)

# Auto-discover tasks
celery_app.autodiscover_tasks(["app.tasks"])

if __name__ == "__main__":
    celery_app.start()
