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
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_superuser_or_admin
from app.database import get_db
from app.models.audit import AuditAction, AuditLog
from app.models.note import Note, NoteBucket
from app.models.smart_folder import SmartFolder, SmartFolderReport, SmartFolderStatus
from app.models.user import User
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
    current_user: User = Depends(require_superuser_or_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get a previously generated report (placeholder)."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Report history not yet implemented",
    )


# -----------------------------------------------------------------------------
# SSE Streaming endpoint for real-time generation progress
# -----------------------------------------------------------------------------

from fastapi.responses import StreamingResponse
import asyncio


@router.post("/stream")
async def stream_smart_folder_generation(
    request: SmartFolderGenerateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Stream Smart Folder generation progress via Server-Sent Events.

    Returns a stream of JSON events:
      - event: "step"     — { step, message, progress_percent }
      - event: "complete" — { smart_folder_id, report_id, report }
      - event: "error"    — { error }
    """
    from app.tasks.smart_folder_tasks import generate_smart_folder_v2_task
    from celery.result import AsyncResult
    from app.celery_app import celery_app

    include_confidential = current_user.can_access_confidential

    # Kick off the Celery task
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
            detail="Unable to queue generation task.",
        )

    task_id = task.id
    logger.info("SSE stream started for task %s user=%s", task_id, current_user.email)

    async def event_generator():
        steps = [
            ("parsing", "Understanding your request…", 10),
            ("resolving", "Finding the right entity…", 25),
            ("retrieving", "Searching your vault…", 40),
            ("analysing", "Extracting milestones & patterns…", 60),
            ("generating", "Writing your report…", 80),
        ]
        step_index = 0
        last_status = None

        for _ in range(120):  # Max ~3 minutes of polling
            result = AsyncResult(task_id, app=celery_app)

            if result.state == "PENDING":
                if step_index < len(steps):
                    step_key, message, pct = steps[step_index]
                    yield f'event: step\ndata: {{"step":"{step_key}","message":"{message}","progress_percent":{pct}}}\n\n'
                    step_index += 1
                await asyncio.sleep(1.5)
                continue

            if result.state == "SUCCESS":
                task_result = result.result or {}
                if task_result.get("status") == "completed":
                    sf_id = task_result.get("smart_folder_id")
                    report_id = task_result.get("report_id")
                    # Fetch full report from DB
                    report_data = None
                    if sf_id:
                        try:
                            sf_stmt = select(SmartFolder).where(
                                SmartFolder.id == UUID(sf_id),
                                SmartFolder.user_id == current_user.id,
                            )
                            sf_res = await db.execute(sf_stmt)
                            sf = sf_res.scalar_one_or_none()
                            if sf and sf.reports:
                                latest = sf.reports[0]
                                report_data = {
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

                    payload = json.dumps({
                        "smart_folder_id": sf_id,
                        "report_id": report_id,
                        "report": report_data,
                    })
                    yield f'event: complete\ndata: {payload}\n\n'
                else:
                    err = task_result.get("error", "Unknown error")
                    payload = json.dumps({"error": err})
                    yield f'event: error\ndata: {payload}\n\n'
                return

            if result.state == "FAILURE":
                payload = json.dumps({"error": str(result.info)})
                yield f'event: error\ndata: {payload}\n\n'
                return

            # Still running — advance steps based on time
            if step_index < len(steps):
                step_key, message, pct = steps[step_index]
                yield f'event: step\ndata: {{"step":"{step_key}","message":"{message}","progress_percent":{pct}}}\n\n'
                step_index += 1

            await asyncio.sleep(1.5)

        # Timeout fallback
        payload = json.dumps({"error": "Generation timed out. Please check status later."})
        yield f'event: error\ndata: {payload}\n\n'

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
