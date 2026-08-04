"""Celery task for Collection Orchestrator jobs.

Runs the full collection pipeline (retrieve → process → extract → analyse →
summarise → package) for one confirmed collection request, following the
collection_report_tasks.py idiom: async runner inside @shared_task with its
own AsyncSessionLocal. On failure the SmartFolder job_state is set to
"failed" with the error message and a failure audit event is written — no
autoretry (the job state machine, not Celery, is the source of truth).

FR6.4: when the failure cause is search-unavailability, the task schedules
its own retry with exponential backoff (60s, 120s, 240s, 480s, 900s — about
30 minutes total, well under the 1h cap). The retry count is recorded on
the SmartFolder checkpoint; PipelineRunner resumes from the checkpoint so
completed stages are never re-paid. When retries are exhausted the job is
left in its final (failed/abandoned) state with an explicit message.
"""

import asyncio
import logging
from typing import Any
from uuid import UUID

from celery import shared_task

logger = logging.getLogger(__name__)

# FR6.4 retry policy for search-unavailable failures.
RETRY_MAX = 5
RETRY_BASE_SECONDS = 60
RETRY_MAX_COUNTDOWN = 900  # 60+120+240+480+900 = 1800s total ≤ 1h cap

SEARCH_UNAVAILABLE_MARKER = "search unavailable"
ABANDONED_NOTE = "retries exhausted — job abandoned"


def is_search_unavailable(error: str | None) -> bool:
    """True when a failure message signals search-layer unavailability."""
    return SEARCH_UNAVAILABLE_MARKER in (error or "").lower()


def retry_countdown(retries_so_far: int) -> int | None:
    """Exponential backoff delay for the next retry, or None when the
    retry budget (RETRY_MAX) is exhausted."""
    if retries_so_far >= RETRY_MAX:
        return None
    return min(RETRY_BASE_SECONDS * (2 ** retries_so_far), RETRY_MAX_COUNTDOWN)


@shared_task(
    bind=True,
    name="app.tasks.collection_request_tasks.run_collection_request_task",
    queue="collections",
    soft_time_limit=300,   # 5 min
    time_limit=600,        # 10 min
)
def run_collection_request_task(
    self,
    smart_folder_id: str,
    user_id: str,
) -> dict[str, Any]:
    """Run the collection pipeline for one confirmed request.

    Args:
        smart_folder_id: UUID string of the SmartFolder (collection request).
        user_id: UUID string of the owning user.

    Returns:
        The PipelineRunner status dict.
    """
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from app.database import _async_db_url
    from app.models.smart_folder import CollectionJobState, SmartFolder
    from app.services.collection_orchestrator import audit_logger
    from app.services.collection_orchestrator.pipeline_runner import (
        TooManyJobsError,
        get_pipeline_runner,
    )

    async def _run() -> dict[str, Any]:
        engine = create_async_engine(_async_db_url, poolclass=NullPool)
        session_factory = async_sessionmaker(
            engine, expire_on_commit=False, class_=AsyncSession
        )
        try:
            return await _run_with_session(session_factory)
        finally:
            await engine.dispose()

    async def _run_with_session(session_factory) -> dict[str, Any]:
        async with session_factory() as db:
            try:
                return await get_pipeline_runner().run(
                    UUID(smart_folder_id), UUID(user_id), db
                )
            except Exception as exc:
                logger.error(
                    "Collection request %s failed: %s", smart_folder_id, exc,
                    exc_info=True,
                )
                # Best-effort failure persistence on a fresh session view.
                try:
                    await db.rollback()
                    sf = (
                        await db.execute(
                            select(SmartFolder).where(
                                SmartFolder.id == UUID(smart_folder_id)
                            )
                        )
                    ).scalar_one_or_none()
                    if sf is not None and sf.job_state not in (
                        CollectionJobState.COMPLETED.value,
                        CollectionJobState.FAILED.value,
                        CollectionJobState.CANCELLED.value,
                    ):
                        sf.job_state = CollectionJobState.FAILED.value
                        sf.error_message = str(exc)[:2000]
                        await audit_logger.log_event(
                            db,
                            request_id=sf.id,
                            user_id=UUID(user_id),
                            stage="retrieve",
                            action="job_failed",
                            status="failure",
                            detail={
                                "error": str(exc)[:500],
                                "too_many_jobs": isinstance(exc, TooManyJobsError),
                            },
                        )
                        await db.commit()
                except Exception as inner:  # pragma: no cover - defensive
                    logger.error(
                        "Failed to persist failure state for %s: %s",
                        smart_folder_id, inner,
                    )
                return {
                    "status": CollectionJobState.FAILED.value,
                    "smart_folder_id": smart_folder_id,
                    "error": str(exc)[:500],
                }

    result = asyncio.run(_run())

    # FR6.4: search-unavailable failures self-schedule a bounded retry with
    # exponential backoff; after RETRY_MAX attempts the job is abandoned.
    if result.get("status") == "failed" and is_search_unavailable(result.get("error")):
        countdown = _update_folder_after_failure(
            smart_folder_id, user_id, retries=self.request.retries
        )
        if countdown is not None:
            raise self.retry(countdown=countdown)
    return result


def _update_folder_after_failure(
    smart_folder_id: str,
    user_id: str,
    *,
    retries: int,
) -> dict[str, Any] | None:
    """FR6.4: decide the post-failure action for a search-unavailable job.

    Returns the retry countdown in seconds (job re-queued, checkpoint
    updated) or None when retries are exhausted (job marked abandoned).
    No-op for non-search-unavailable failures (returns None without
    touching the folder — caller distinguishes via is_search_unavailable).
    """

    async def _update(action: str, countdown: int | None) -> None:
        from sqlalchemy import select

        from app.database import AsyncSessionLocal
        from app.models.smart_folder import CollectionJobState, SmartFolder
        from app.services.collection_orchestrator import audit_logger

        async with AsyncSessionLocal() as db:
            sf = (
                await db.execute(
                    select(SmartFolder).where(
                        SmartFolder.id == UUID(smart_folder_id)
                    )
                )
            ).scalar_one_or_none()
            if sf is None:
                return
            checkpoint = dict(sf.checkpoint or {})
            if action == "retry":
                checkpoint["retry_count"] = retries + 1
                sf.checkpoint = checkpoint
                # Back to queued so the SSE stream shows a truthful state
                # while the retry waits; the runner resumes from checkpoint.
                sf.job_state = CollectionJobState.QUEUED.value
                detail = {"retry_count": retries + 1, "countdown": countdown}
            else:
                checkpoint["retry_count"] = retries
                sf.checkpoint = checkpoint
                sf.job_state = CollectionJobState.FAILED.value
                sf.error_message = (
                    f"{(sf.error_message or 'search unavailable')} "
                    f"— {ABANDONED_NOTE}"
                )[:2000]
                detail = {"retry_count": retries}
            await audit_logger.log_event(
                db,
                request_id=sf.id,
                user_id=UUID(user_id),
                stage="retrieve",
                action=(
                    "job_retry_scheduled" if action == "retry"
                    else "job_abandoned"
                ),
                status="failure" if action == "abandon" else "success",
                detail=detail,
            )
            await db.commit()

    countdown = retry_countdown(retries)
    if countdown is not None:
        asyncio.run(_update("retry", countdown))
        return countdown
    asyncio.run(_update("abandon", None))
    return None


@shared_task(
    name="app.tasks.collection_request_tasks.purge_collection_audit_events_task",
    queue="scheduled",  # light queue — a single bounded DELETE
    soft_time_limit=120,
    time_limit=300,
)
def purge_collection_audit_events_task() -> dict[str, Any]:
    """FR8.4 retention: delete collection audit events older than
    ``settings.COLLECTION_AUDIT_RETENTION_DAYS`` (default 7 years).

    Beat-scheduled daily (see celery_app.py ``collection-audit-retention``);
    can equally be driven from cron via
    ``celery -A app.celery_app call app.tasks.collection_request_tasks.purge_collection_audit_events_task``.
    """
    from app.database import AsyncSessionLocal
    from app.services.collection_orchestrator.audit_logger import (
        purge_expired_audit_events,
    )

    async def _purge() -> int:
        async with AsyncSessionLocal() as db:
            return await purge_expired_audit_events(db)

    deleted = asyncio.run(_purge())
    logger.info("Collection audit retention purge deleted %d event(s)", deleted)
    return {"deleted": deleted}
