"""
Dead Letter Queue service — persists permanently failed Celery tasks.
"""

from __future__ import annotations

import logging
import traceback as tb
from typing import Any, Optional

logger = logging.getLogger(__name__)


class DeadLetterQueueService:
    """Store failed tasks in the DLQ table for later inspection / replay."""

    @staticmethod
    def store_failed_task(
        task_name: str,
        task_id: str,
        args: tuple,
        kwargs: dict,
        exception: Exception,
        traceback_str: Optional[str] = None,
        retry_count: int = 0,
        extra_metadata: Optional[dict] = None,
    ) -> Optional[Any]:
        """
        Persist a permanently failed task to the dead letter queue.

        Args:
            task_name:      Celery task name (e.g. "app.tasks.document_tasks.process_document")
            task_id:        Celery task UUID string
            args:           Positional arguments the task was called with
            kwargs:         Keyword arguments the task was called with
            exception:      The exception that caused the failure
            traceback_str:  Formatted traceback string (optional)
            retry_count:    Number of retry attempts before permanent failure
            extra_metadata: Additional context (document_id, user_id, …)

        Returns:
            The persisted FailedCeleryTask ORM object, or None on storage error.
        """
        from app.database import SessionLocal
        from app.models.failed_task import FailedCeleryTask

        db = SessionLocal()
        try:
            # Safely serialise args/kwargs — they must be JSON-compatible
            safe_args: Any = None
            safe_kwargs: Any = None
            try:
                import json

                safe_args = json.loads(json.dumps(list(args), default=str))
                safe_kwargs = json.loads(json.dumps(kwargs, default=str))
            except Exception:
                safe_args = [str(a) for a in args]
                safe_kwargs = {k: str(v) for k, v in kwargs.items()}

            record = FailedCeleryTask(
                task_name=task_name,
                task_id=task_id,
                args=safe_args,
                kwargs=safe_kwargs,
                exception_type=type(exception).__name__,
                exception_message=str(exception)[:2000],
                traceback=traceback_str or tb.format_exc(),
                retry_count=retry_count,
                task_metadata=extra_metadata or {},
            )
            db.add(record)
            db.commit()
            db.refresh(record)
            logger.info(
                f"DLQ: stored failed task {task_name} (task_id={task_id}, "
                f"retries={retry_count})"
            )

            # Fire async alert (best-effort; don't block if event loop unavailable)
            try:
                import asyncio
                from app.services.alert_service import alert_service

                coro = alert_service.send_task_failure_alert(
                    task_name=task_name,
                    task_id=task_id,
                    exception=str(exception),
                    retry_count=retry_count,
                    extra_metadata=extra_metadata,
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
                logger.debug(f"DLQ: alert dispatch skipped: {alert_err}")

            return record

        except Exception as store_err:
            db.rollback()
            # DLQ storage must never crash the caller
            logger.error(
                f"DLQ: failed to store task {task_name} ({task_id}): {store_err}"
            )
            return None

        finally:
            db.close()

    @staticmethod
    def list_failed_tasks(
        page: int = 1,
        page_size: int = 50,
        task_name_filter: Optional[str] = None,
    ) -> dict:
        """
        Retrieve paginated failed tasks.

        Returns:
            {
                "items": [...],
                "total": int,
                "page": int,
                "page_size": int,
            }
        """
        from app.database import SessionLocal
        from app.models.failed_task import FailedCeleryTask
        from sqlalchemy import desc

        db = SessionLocal()
        try:
            query = db.query(FailedCeleryTask)
            if task_name_filter:
                query = query.filter(
                    FailedCeleryTask.task_name.ilike(f"%{task_name_filter}%")
                )

            total = query.count()
            items = (
                query.order_by(desc(FailedCeleryTask.failed_at))
                .offset((page - 1) * page_size)
                .limit(page_size)
                .all()
            )

            return {
                "items": items,
                "total": total,
                "page": page,
                "page_size": page_size,
            }

        finally:
            db.close()
