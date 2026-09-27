"""Smart Folders v2 API endpoints.

Provides endpoints for:
  - Generating Smart Folder reports (async via Celery)
  - Retrieving generated reports
  - Iterative refinement
  - Saving as Note
  - Legacy report generation (backward compatible)
"""

import json
import logging
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_superuser_or_admin
from app.database import get_db
from app.models.audit import AuditAction, AuditLog
from app.models.note import Note, NoteBucket
from app.models.smart_folder import SmartFolder, SmartFolderReport, SmartFolderStatus
from app.models.user import User, UserRole
from app.schemas.collection import (
    CollectionReportRequest,
    SmartFolderGenerateRequest as LegacySmartFolderGenerateRequest,
)
from app.schemas.smart_folder import (
    GenerationStatusResponse,
    SmartFolderGenerateRequest,
    SmartFolderRefineRequest,
    SmartFolderReportResponse,
    SmartFolderResponse,
    SmartFolderSaveRequest,
)

router = APIRouter(prefix="/smart-folders", tags=["smart-folders"])
logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

async def _create_audit_log(
    db: AsyncSession,
    user_id: UUID,
    action: AuditAction,
    resource_type: str,
    resource_id: str | None = None,
    details: dict | None = None,
) -> None:
    try:
        audit_entry = AuditLog(
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=json.dumps(details) if details else None,
        )
        db.add(audit_entry)
        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.error("Audit logging failed: %s", e)


def _report_to_response(report: SmartFolderReport) -> SmartFolderReportResponse:
    """Convert ORM report to Pydantic response."""
    return SmartFolderReportResponse(
        id=report.id,
        smart_folder_id=report.smart_folder_id,
        generated_content=report.generated_content or {},
        source_asset_ids=[UUID(aid) for aid in (report.source_asset_ids or [])],
        citation_index=report.citation_index or {},
        version=report.version,
        refinement_query=report.refinement_query,
        generator_version=report.generator_version,
        created_at=report.created_at,
        updated_at=report.updated_at,
    )


# -----------------------------------------------------------------------------
# v2 Endpoints — available to all authenticated users
# -----------------------------------------------------------------------------

@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def create_smart_folder(
    request: SmartFolderGenerateRequest,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Queue a new Smart Folder v2 generation.

    Accepts a natural-language query, enqueues an async Celery task that runs
    the full pipeline (parse → resolve → retrieve → analyse → generate).

    Returns a task_id for polling.
    """
    from app.tasks.smart_folder_tasks import generate_smart_folder_v2_task

    include_confidential = current_user.can_access_confidential

    try:
        task = generate_smart_folder_v2_task.delay(
            query=request.query,
            include_confidential=include_confidential,
            user_id=str(current_user.id),
        )
    except Exception as exc:
        logger.error("Failed to queue smart folder v2 generation: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to queue generation task. Please try again later.",
        )

    logger.info(
        "Smart folder v2 generation queued | task_id=%s user=%s query=%s",
        task.id,
        current_user.email,
        request.query,
    )

    return {
        "task_id": task.id,
        "status": "pending",
        "status_url": f"/api/v1/smart-folders/generate/status/{task.id}",
        "message": f"Smart Folder generation queued (task_id={task.id})",
    }


@router.get("/{smart_folder_id}")
async def get_smart_folder(
    smart_folder_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Retrieve a Smart Folder and its latest report."""
    stmt = select(SmartFolder).where(
        SmartFolder.id == smart_folder_id,
        SmartFolder.user_id == current_user.id,
    )
    result = await db.execute(stmt)
    sf = result.scalar_one_or_none()

    if not sf:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Smart Folder not found")

    latest_report = None
    if sf.reports:
        latest_report = _report_to_response(sf.reports[0])

    return {
        "smart_folder": SmartFolderResponse.model_validate(sf),
        "latest_report": latest_report,
    }


@router.delete("/{smart_folder_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_smart_folder(
    smart_folder_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a Smart Folder and its reports (ORM cascade) plus any
    collection-request artifacts sharing the row (FK cascade).

    Idempotent: deleting an already-deleted folder returns 204. An active
    generation/collection job is revoked before deletion.
    """
    result = await db.execute(select(SmartFolder).where(SmartFolder.id == smart_folder_id))
    sf = result.scalar_one_or_none()
    if sf is None:
        return None  # idempotent: already gone
    if sf.user_id != current_user.id:
        # Exists but owned by someone else — 404 without leaking existence.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Smart Folder not found")

    task_id = getattr(sf, "celery_task_id", None)
    job_state = getattr(sf, "job_state", None)
    if task_id and job_state not in ("completed", "failed", "cancelled"):
        try:
            from app.celery_app import celery_app

            celery_app.control.revoke(task_id, terminate=True)
        except Exception as exc:
            logger.warning("Celery revoke failed for task %s: %s", task_id, exc)

    await _create_audit_log(
        db,
        current_user.id,
        AuditAction.SYSTEM_ACTION,
        "smart_folder",
        str(sf.id),
        {"action": "delete", "name": (sf.name or "")[:100]},
    )
    await db.delete(sf)
    await db.commit()
    return None


@router.post("/{smart_folder_id}/refresh", status_code=status.HTTP_202_ACCEPTED)
async def refresh_smart_folder(
    smart_folder_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Refresh an existing Smart Folder by re-running generation with the same query.

    Creates a new report version while preserving the Smart Folder identity.
    """
    from app.tasks.smart_folder_tasks import generate_smart_folder_v2_task

    # Load existing Smart Folder
    stmt = select(SmartFolder).where(
        SmartFolder.id == smart_folder_id,
        SmartFolder.user_id == current_user.id,
    )
    result = await db.execute(stmt)
    sf = result.scalar_one_or_none()

    if not sf:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Smart Folder not found",
        )

    include_confidential = current_user.can_access_confidential

    try:
        task = generate_smart_folder_v2_task.delay(
            query=sf.query_text,
            include_confidential=include_confidential,
            user_id=str(current_user.id),
            smart_folder_id=str(smart_folder_id),
        )
    except Exception as exc:
        logger.error("Failed to queue smart folder refresh: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to queue refresh task. Please try again later.",
        )

    logger.info(
        "Smart folder refresh queued | task_id=%s user=%s sf_id=%s",
        task.id,
        current_user.email,
        smart_folder_id,
    )

    return {
        "task_id": task.id,
        "status": "pending",
        "status_url": f"/api/v1/smart-folders/generate/status/{task.id}",
        "message": f"Smart Folder refresh queued (task_id={task.id})",
    }


@router.post("/{smart_folder_id}/refine", status_code=status.HTTP_202_ACCEPTED)
async def refine_smart_folder(
    smart_folder_id: UUID,
    request: SmartFolderRefineRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Refine an existing Smart Folder with a follow-up query.

    Re-runs retrieval and generation with the new constraint while
    preserving the original entity context.
    """
    from app.tasks.smart_folder_tasks import generate_smart_folder_v2_task

    stmt = select(SmartFolder).where(
        SmartFolder.id == smart_folder_id,
        SmartFolder.user_id == current_user.id,
    )
    result = await db.execute(stmt)
    sf = result.scalar_one_or_none()

    if not sf:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Smart Folder not found")

    include_confidential = current_user.can_access_confidential
    combined_query = f"{sf.query_text} | Refinement: {request.refinement_query}"

    try:
        task = generate_smart_folder_v2_task.delay(
            query=combined_query,
            include_confidential=include_confidential,
            user_id=str(current_user.id),
            smart_folder_id=str(smart_folder_id),
            refinement_query=request.refinement_query,
        )
    except Exception as exc:
        logger.error("Failed to queue smart folder refinement: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to queue refinement task. Please try again later.",
        )

    logger.info(
        "Smart folder refinement queued | task_id=%s user=%s sf=%s refinement=%s",
        task.id,
        current_user.email,
        smart_folder_id,
        request.refinement_query,
    )

    return {
        "task_id": task.id,
        "status": "pending",
        "status_url": f"/api/v1/smart-folders/generate/status/{task.id}",
        "message": f"Refinement queued (task_id={task.id})",
    }


@router.post("/{smart_folder_id}/save")
async def save_smart_folder_as_note(
    smart_folder_id: UUID,
    request: SmartFolderSaveRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Save a Smart Folder report as a permanent Note."""
    stmt = select(SmartFolder).where(
        SmartFolder.id == smart_folder_id,
        SmartFolder.user_id == current_user.id,
    )
    result = await db.execute(stmt)
    sf = result.scalar_one_or_none()

    if not sf:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Smart Folder not found")

    if not sf.reports:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No report generated yet for this Smart Folder",
        )

    latest_report = sf.reports[0]
    content = latest_report.generated_content or {}
    markdown = content.get("raw_markdown", "") or json.dumps(content, indent=2)

    note = Note(
        user_id=current_user.id,
        title=request.name or sf.name or "Smart Folder Report",
        content=markdown,
        bucket=NoteBucket.PRIVATE,
    )
    db.add(note)
    await db.commit()
    await db.refresh(note)

    logger.info(
        "Smart folder saved as note | note_id=%s user=%s sf=%s",
        note.id,
        current_user.email,
        smart_folder_id,
    )

    return {
        "note_id": str(note.id),
        "title": note.title,
        "smart_folder_id": str(sf.id),
        "message": "Smart Folder saved as Note successfully",
    }


@router.get("/{smart_folder_id}/status")
async def get_smart_folder_db_status(
    smart_folder_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GenerationStatusResponse:
    """Get the current generation status from the database."""
    stmt = select(SmartFolder).where(
        SmartFolder.id == smart_folder_id,
        SmartFolder.user_id == current_user.id,
    )
    result = await db.execute(stmt)
    sf = result.scalar_one_or_none()

    if not sf:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Smart Folder not found")

    progress = 0
    message = None
    if sf.status == SmartFolderStatus.DRAFT:
        progress = 0
        message = "Waiting to start..."
    elif sf.status == SmartFolderStatus.GENERATING:
        progress = 50
        message = "Generating report..."
    elif sf.status == SmartFolderStatus.READY:
        progress = 100
        message = "Report ready"
    elif sf.status == SmartFolderStatus.FAILED:
        progress = 0
        message = sf.error_message or "Generation failed"

    latest_report_id = sf.reports[0].id if sf.reports else None

    return GenerationStatusResponse(
        task_id="",  # DB status doesn't map to a single Celery task
        status=sf.status.value,
        progress_percent=progress,
        message=message,
        smart_folder_id=sf.id,
        report_id=latest_report_id,
        error=sf.error_message,
    )


# -----------------------------------------------------------------------------
# Celery task status polling (shared by v1 and v2)
# -----------------------------------------------------------------------------

@router.get("/generate/status/{task_id}")
async def get_generation_task_status(
    task_id: str,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Poll the status of an async generation Celery task."""
    from celery.result import AsyncResult

    from app.celery_app import celery_app

    result = AsyncResult(task_id, app=celery_app)

    if result.state == "PENDING":
        return {"task_id": task_id, "status": "pending", "result": None}
    if result.state == "SUCCESS":
        return {"task_id": task_id, "status": "completed", "result": result.result}
    if result.state == "FAILURE":
        return {
            "task_id": task_id,
            "status": "failed",
            "error": str(result.info),
        }

    return {"task_id": task_id, "status": result.state.lower(), "result": None}


# -----------------------------------------------------------------------------
# Legacy endpoints (backward compatibility — admin/superuser only)
# -----------------------------------------------------------------------------

@router.post("/generate")
async def generate_smart_folder_legacy(
    request: LegacySmartFolderGenerateRequest,
    current_user: User = Depends(require_superuser_or_admin),
) -> dict[str, Any]:
    """Legacy Smart Folder generation endpoint (v1)."""
    from app.tasks.smart_folder_tasks import generate_smart_folder_task

    include_confidential = current_user.can_access_confidential

    try:
        task = generate_smart_folder_task.delay(
            topic=request.topic,
            style=request.style,
            length=request.length,
            include_confidential=include_confidential,
            user_id=str(current_user.id),
        )
    except Exception as exc:
        logger.error("Failed to queue legacy smart folder generation: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to queue generation task. Please try again later.",
        )

    return {
        "task_id": task.id,
        "status": "pending",
        "status_url": f"/api/v1/smart-folders/generate/status/{task.id}",
        "message": f"Smart folder generation queued (task_id={task.id})",
    }


@router.post("/reports/generate")
async def generate_collection_report(
    request: CollectionReportRequest,
    current_user: User = Depends(require_superuser_or_admin),
) -> dict[str, Any]:
    """Queue a Collection Report generation task."""
    from app.tasks.collection_report_tasks import generate_collection_report_task

    try:
        task = generate_collection_report_task.delay(
            collection_id=str(request.collection_id),
            report_format=request.format.value,
            include_citations=request.include_citations,
            language=request.language,
            user_id=str(current_user.id),
        )
    except Exception as exc:
        logger.error("Failed to queue collection report generation: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to queue report generation. Please try again later.",
        )

    return {
        "task_id": task.id,
        "status": "pending",
        "status_url": f"/api/v1/smart-folders/reports/status/{task.id}",
        "message": f"Report generation queued (task_id={task.id})",
    }


@router.get("/reports/status/{task_id}")
async def get_collection_report_status(
    task_id: str,
    current_user: User = Depends(require_superuser_or_admin),
) -> dict[str, Any]:
    """Poll the status of an async Collection Report generation task."""
    from celery.result import AsyncResult

    from app.celery_app import celery_app

    result = AsyncResult(task_id, app=celery_app)

    if result.state == "PENDING":
        return {"task_id": task_id, "status": "pending", "result": None}
    if result.state == "SUCCESS":
        return {"task_id": task_id, "status": "completed", "result": result.result}
    if result.state == "FAILURE":
        return {
            "task_id": task_id,
            "status": "failed",
            "error": str(result.info),
        }

    return {"task_id": task_id, "status": result.state.lower(), "result": None}


@router.get("/reports/templates")
async def get_report_templates(
    current_user: User = Depends(require_superuser_or_admin),
) -> dict[str, Any]:
    """Get available report templates and formats."""
    return {
        "formats": [
            {
                "value": "short",
                "name": "Short",
                "description": "1-2 pages, executive summary style",
                "sections": ["Executive Summary", "Key Findings", "Recommendations"],
                "typical_length": "300-500 words",
            },
            {
                "value": "standard",
                "name": "Standard",
                "description": "3-5 pages, balanced overview",
                "sections": [
                    "Executive Summary",
                    "Introduction",
                    "Analysis",
                    "Key Findings",
                    "Recommendations",
                    "Conclusion",
                ],
                "typical_length": "800-1500 words",
            },
            {
                "value": "comprehensive",
                "name": "Comprehensive",
                "description": "6-10 pages, in-depth analysis",
                "sections": [
                    "Executive Summary",
                    "Introduction",
                    "Background",
                    "Detailed Analysis",
                    "Key Findings",
                    "Supporting Evidence",
                    "Recommendations",
                    "Implementation Notes",
                    "Conclusion",
                    "Appendices",
                ],
                "typical_length": "2000-4000 words",
            },
        ],
        "languages": [
            {"value": "en", "name": "English"},
            {"value": "fr", "name": "Français"},
        ],
        "style_options": [
            {"value": "informative", "name": "Informative", "description": "Educational, clear explanations"},
            {"value": "creative", "name": "Creative", "description": "Engaging, vivid language"},
            {"value": "professional", "name": "Professional", "description": "Formal business tone"},
            {"value": "casual", "name": "Casual", "description": "Friendly, conversational"},
        ],
    }


@router.get("/reports/{report_id}")
async def get_report(
    report_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SmartFolderReportResponse:
    """Get a previously generated report.

    Available to the report's owner; admins/superusers may read any report.
    """
    result = await db.execute(
        select(SmartFolderReport, SmartFolder)
        .join(SmartFolder, SmartFolderReport.smart_folder_id == SmartFolder.id)
        .where(SmartFolderReport.id == report_id)
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Report not found",
        )
    report, folder = row
    is_admin = current_user.role in (UserRole.ADMIN, UserRole.SUPERUSER)
    if folder.user_id != current_user.id and not is_admin:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Report not found",
        )
    return _report_to_response(report)


# -----------------------------------------------------------------------------
# SSE Streaming endpoint for real-time generation progress
# -----------------------------------------------------------------------------

import asyncio

from fastapi.responses import StreamingResponse


@router.post("/stream")
async def stream_smart_folder_generation(
    request: SmartFolderGenerateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Stream Smart Folder generation progress via Server-Sent Events.

    Progress is real: the Celery task publishes pipeline events to a Redis
    pub/sub channel, and this endpoint subscribes to that channel (BEFORE the
    task is dispatched — pub/sub is fire-and-forget) and forwards events to
    the browser. A Celery ``AsyncResult`` poll is kept as a safety net so the
    stream still terminates if pub/sub drops or the task finishes before the
    subscription is established.

    Returns a stream of JSON events:
      - event: "step"     — { step, message, progress_percent }
      - event: "complete" — { smart_folder_id, report_id, report }
      - event: "error"    — { error }
    """
    from celery.result import AsyncResult

    from app.celery_app import celery_app
    from app.services.smart_folder.progress import channel_for
    from app.tasks.smart_folder_tasks import generate_smart_folder_v2_task

    include_confidential = current_user.can_access_confidential

    # Mint the stream key up front so the subscriber is attached before the
    # task starts publishing (Redis pub/sub delivers only to current subscribers).
    stream_key = uuid4().hex
    channel = channel_for(stream_key)

    # Attach the pub/sub subscriber BEFORE dispatching so no event is lost.
    redis_client = None
    pubsub = None
    try:
        import redis.asyncio as aioredis

        from app.core.redis_url import safe_redis_url

        redis_client = aioredis.from_url(
            safe_redis_url(),
            decode_responses=True,
            socket_timeout=5,
            socket_connect_timeout=5,
        )
        pubsub = redis_client.pubsub()
        await pubsub.subscribe(channel)
    except Exception as exc:
        logger.warning(
            "Pub/sub subscribe failed for %s (%s); falling back to AsyncResult polling",
            stream_key,
            exc,
        )
        pubsub = None

    # Kick off the Celery task (after subscribing).
    try:
        task = generate_smart_folder_v2_task.delay(
            query=request.query,
            include_confidential=include_confidential,
            user_id=str(current_user.id),
            stream_key=stream_key,
        )
    except Exception as exc:
        logger.error("Failed to queue smart folder v2 generation: %s", exc, exc_info=True)
        if pubsub is not None:
            try:
                await pubsub.unsubscribe(channel)
                await pubsub.aclose()
            except Exception:
                pass
        if redis_client is not None:
            try:
                await redis_client.aclose()
            except Exception:
                pass
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to queue generation task.",
        )

    task_id = task.id
    logger.info(
        "SSE stream started | task=%s stream=%s user=%s",
        task_id,
        stream_key,
        current_user.email,
    )

    async def _fetch_report(sf_id: str) -> dict[str, Any] | None:
        """Read the latest report for a finished Smart Folder."""
        try:
            sf_stmt = select(SmartFolder).where(
                SmartFolder.id == UUID(sf_id),
                SmartFolder.user_id == current_user.id,
            )
            sf_res = await db.execute(sf_stmt)
            sf = sf_res.scalar_one_or_none()
            if sf and sf.reports:
                latest = sf.reports[0]
                return {
                    "title": latest.generated_content.get("title", ""),
                    "summary": latest.generated_content.get("summary", ""),
                    "timeline": latest.generated_content.get("timeline", []),
                    "patterns": latest.generated_content.get("patterns", []),
                    "trends": latest.generated_content.get("trends", []),
                    "issues": latest.generated_content.get("issues", []),
                    "learnings": latest.generated_content.get("learnings", []),
                    "recommendations": latest.generated_content.get("recommendations", []),
                    "raw_markdown": latest.generated_content.get("raw_markdown", ""),
                    "citation_index": latest.citation_index,
                    "source_asset_ids": latest.source_asset_ids,
                }
        except Exception as exc:
            logger.warning("Failed to fetch report for SSE: %s", exc)
        return None

    async def event_generator():
        try:
            loop = asyncio.get_running_loop()
            deadline = loop.time() + 300  # 5 min safety ceiling

            while True:
                # 1) Drain real progress events from Redis pub/sub.
                if pubsub is not None:
                    try:
                        msg = await pubsub.get_message(
                            ignore_subscribe_messages=True, timeout=0.1
                        )
                    except Exception as exc:
                        logger.debug("Pub/sub read failed: %s", exc)
                        pubsub = None  # drop pub/sub; rely on AsyncResult polling
                        msg = None

                    if msg and msg.get("type") == "message":
                        try:
                            event = json.loads(msg.get("data", "{}"))
                        except Exception:
                            event = {}

                        etype = event.get("event")
                        if etype == "step":
                            yield (
                                "event: step\ndata: "
                                + json.dumps(
                                    {
                                        "step": event.get("step"),
                                        "message": event.get("message"),
                                        "progress_percent": event.get("progress_percent"),
                                    }
                                )
                                + "\n\n"
                            )
                            continue
                        if etype == "complete":
                            sf_id = event.get("smart_folder_id")
                            report_id = event.get("report_id")
                            report_data = await _fetch_report(sf_id) if sf_id else None
                            yield (
                                "event: complete\ndata: "
                                + json.dumps(
                                    {
                                        "smart_folder_id": sf_id,
                                        "report_id": report_id,
                                        "report": report_data,
                                    }
                                )
                                + "\n\n"
                            )
                            return
                        if etype == "error":
                            yield (
                                "event: error\ndata: "
                                + json.dumps({"error": event.get("error", "Generation failed")})
                                + "\n\n"
                            )
                            return

                # 2) Safety net: Celery AsyncResult state.
                result = AsyncResult(task_id, app=celery_app)
                if result.state == "SUCCESS":
                    task_result = result.result or {}
                    if task_result.get("status") == "completed":
                        sf_id = task_result.get("smart_folder_id")
                        report_id = task_result.get("report_id")
                        report_data = await _fetch_report(sf_id) if sf_id else None
                        yield (
                            "event: complete\ndata: "
                            + json.dumps(
                                {
                                    "smart_folder_id": sf_id,
                                    "report_id": report_id,
                                    "report": report_data,
                                }
                            )
                            + "\n\n"
                        )
                    else:
                        yield (
                            "event: error\ndata: "
                            + json.dumps({"error": task_result.get("error", "Unknown error")})
                            + "\n\n"
                        )
                    return
                if result.state == "FAILURE":
                    yield (
                        "event: error\ndata: "
                        + json.dumps({"error": str(result.info)})
                        + "\n\n"
                    )
                    return

                if loop.time() > deadline:
                    yield (
                        "event: error\ndata: "
                        + json.dumps({"error": "Generation timed out. Please check status later."})
                        + "\n\n"
                    )
                    return

                await asyncio.sleep(0.5)
        finally:
            if pubsub is not None:
                try:
                    await pubsub.unsubscribe(channel)
                    await pubsub.aclose()
                except Exception:
                    pass
            if redis_client is not None:
                try:
                    await redis_client.aclose()
                except Exception:
                    pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
