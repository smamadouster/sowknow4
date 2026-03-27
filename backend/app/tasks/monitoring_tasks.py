"""
Memory monitoring Celery task.

Measures the current worker's RSS memory every 5 minutes and fires alerts
when thresholds are crossed.  Two thresholds are defined to match the
1280m container limit set in docker-compose:

    WARNING  — 1024 MB  (80% of 1280m container limit)
    CRITICAL — 1152 MB  (90% of 1280m container limit)

The beat schedule entry is injected into celery_app at module import time
so it is picked up by the Celery beat scheduler automatically.
"""

import asyncio
import logging

import psutil

from app.celery_app import celery_app
from app.services.alert_service import alert_service

logger = logging.getLogger(__name__)

# Memory thresholds in MB
_WARN_THRESHOLD_MB: int = 1024  # 80% of 1280m container limit
_CRIT_THRESHOLD_MB: int = 1152  # 90% of 1280m container limit


@celery_app.task(
    bind=True,
    name="app.tasks.monitoring_tasks.check_worker_memory",
    max_retries=0,  # monitoring tasks should not retry
    ignore_result=True,
)
def check_worker_memory(self) -> dict:
    """
    Sample the worker's current RSS memory and alert when thresholds are exceeded.

    Returns a dict with the measured RSS and the action taken.
    """
    process = psutil.Process()
    rss_bytes = process.memory_info().rss
    rss_mb = rss_bytes // (1024 * 1024)

    logger.info("check_worker_memory: RSS = %d MB", rss_mb)

    result = {"rss_mb": rss_mb, "action": "none"}

    if rss_mb >= _CRIT_THRESHOLD_MB:
        severity = "CRITICAL"
        title = "Celery worker memory CRITICAL"
        message = (
            f"Celery worker RSS is {rss_mb} MB -- exceeds the CRITICAL "
            f"threshold of {_CRIT_THRESHOLD_MB} MB "
            f"(container limit: 1280 MB).  Consider restarting the worker."
        )
        result["action"] = "critical_alert"
    elif rss_mb >= _WARN_THRESHOLD_MB:
        # Warning-level memory usage is logged but not sent to Telegram.
        # Guardian HC auto-healing will restart if it hits 90% of container limit.
        logger.warning(
            "Celery worker RSS is %d MB (WARNING threshold %d MB)",
            rss_mb, _WARN_THRESHOLD_MB,
        )
        result["action"] = "warning_logged"
        return result
    else:
        return result

    try:
        asyncio.run(
            alert_service.send_alert(
                message=message,
                severity=severity,
                title=title,
                metadata={
                    "rss_mb": rss_mb,
                    "warn_threshold_mb": _WARN_THRESHOLD_MB,
                    "crit_threshold_mb": _CRIT_THRESHOLD_MB,
                    "container_limit_mb": 1280,
                    "worker_hostname": self.request.hostname,
                },
            )
        )
    except Exception as exc:
        logger.error("check_worker_memory: failed to send alert: %s", exc)

    return result


# ---------------------------------------------------------------------------
# Inject beat schedule entry into the running celery_app configuration.
# This runs at module import time so celery_app.autodiscover_tasks() picks it up.
# ---------------------------------------------------------------------------

beat_schedule = {
    "check-worker-memory": {
        "task": "app.tasks.monitoring_tasks.check_worker_memory",
        "schedule": 300,  # every 5 minutes (300 seconds)
        "args": (),
    },
}

celery_app.conf.beat_schedule.update(beat_schedule)
