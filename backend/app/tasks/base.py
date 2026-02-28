"""
Shared utilities for Celery tasks.

Provides:
  - log_task_memory:           Log current process RSS memory at a named stage.
  - store_dlq_on_max_retries:  Store a permanently failed task in the DLQ.
"""

import logging
import os
import traceback as _tb

logger = logging.getLogger(__name__)

# Memory threshold in MB — log a WARNING when exceeded
MEMORY_WARNING_THRESHOLD_MB = int(os.getenv("CELERY_MEMORY_WARNING_MB", "1400"))


def log_task_memory(task_name: str, stage: str) -> float:
    """
    Log the current process RSS memory and return MB used.

    Args:
        task_name: Name of the Celery task (for log context).
        stage:     Human-readable stage label (e.g. "start", "after_ocr").

    Returns:
        Current RSS memory in MB (0.0 if psutil is unavailable).
    """
    try:
        import psutil

        process = psutil.Process(os.getpid())
        memory_mb = process.memory_info().rss / 1024 / 1024

        if memory_mb > MEMORY_WARNING_THRESHOLD_MB:
            logger.warning(
                f"[MEMORY] {task_name} @ {stage}: {memory_mb:.1f} MB (above {MEMORY_WARNING_THRESHOLD_MB} MB threshold)"
            )
        else:
            logger.debug(f"[MEMORY] {task_name} @ {stage}: {memory_mb:.1f} MB")

        return memory_mb

    except ImportError:
        logger.debug(f"[MEMORY] {task_name} @ {stage}: psutil not available, skipping")
        return 0.0

    except Exception as exc:
        logger.debug(f"[MEMORY] {task_name} @ {stage}: error — {exc}")
        return 0.0


def base_task_failure_handler(
    task_self,
    exception: Exception,
    task_id: str,
    args: tuple,
    kwargs: dict,
    traceback,
    is_critical: bool = False,
    extra_metadata: dict | None = None,
) -> None:
    """
    Universal on_failure callback for Celery tasks.

    Stores the failed task in the Dead Letter Queue (DLQ) and optionally fires
    an alert via AlertService for critical failures.

    Usage — wire to a task via @task.on_failure or call directly from an
    on_failure callback function.
    """
    try:
        import traceback as _tb

        tb_str = _tb.format_exc()

        # 1. Store in DLQ
        from app.services.dlq_service import DeadLetterQueueService

        DeadLetterQueueService.store_failed_task(
            task_name=getattr(task_self, "name", str(type(task_self).__name__)),
            task_id=task_id or "unknown",
            args=tuple(args or ()),
            kwargs=dict(kwargs or {}),
            exception=exception,
            traceback_str=tb_str,
            retry_count=getattr(getattr(task_self, "request", None), "retries", 0),
            extra_metadata=extra_metadata or {},
        )

        # 2. Fire alert for critical tasks
        if is_critical:
            try:
                import asyncio

                from app.services.alert_service import alert_service

                coro = alert_service.send_alert(
                    message=f"Critical task failure: {str(exception)[:500]}",
                    severity="CRITICAL",
                    title=f"Task Failure: {getattr(task_self, 'name', 'unknown')}",
                    metadata=extra_metadata or {},
                )
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        loop.create_task(coro)
                    else:
                        loop.run_until_complete(coro)
                except RuntimeError:
                    asyncio.run(coro)
            except Exception as alert_err:
                logger.debug(f"base_task_failure_handler: alert skipped: {alert_err}")

    except Exception as handler_err:
        logger.error(f"base_task_failure_handler itself failed: {handler_err}")


def store_dlq_on_max_retries(
    task_self,
    exception: Exception,
    extra_metadata: dict | None = None,
) -> None:
    """
    Call from a task's except block to persist the failure in the DLQ once all
    retries are exhausted.

    Usage (inside a @shared_task(bind=True) except block):
        store_dlq_on_max_retries(self, exc, extra_metadata={"document_id": doc_id})

    For autoretry tasks:  checks self.request.retries >= self.max_retries.
    For manual retry tasks: call unconditionally from the permanent-failure branch.
    """
    try:
        max_retries = getattr(task_self, "max_retries", None)
        current_retries = getattr(task_self.request, "retries", 0)
        # Only store once all retries are exhausted (or for unconditional calls)
        if max_retries is not None and current_retries < max_retries:
            return

        from app.services.dlq_service import DeadLetterQueueService

        task_name = task_self.name or type(task_self).__name__
        task_id = getattr(task_self.request, "id", None) or "unknown"
        args = tuple(getattr(task_self.request, "args", ()) or ())
        kwargs = dict(getattr(task_self.request, "kwargs", {}) or {})

        DeadLetterQueueService.store_failed_task(
            task_name=task_name,
            task_id=task_id,
            args=args,
            kwargs=kwargs,
            exception=exception,
            traceback_str=_tb.format_exc(),
            retry_count=current_retries,
            extra_metadata=extra_metadata or {},
        )
    except Exception as dlq_err:
        logger.error(f"store_dlq_on_max_retries failed: {dlq_err}")
