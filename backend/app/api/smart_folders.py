"""
Smart Folders and Reports API endpoints

Provides endpoints for generating AI content from documents and
creating professional PDF reports from collections.
"""

import json
import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_superuser_or_admin
from app.database import get_db
from app.models.audit import AuditAction, AuditLog
from app.models.user import User
from app.schemas.collection import (
    CollectionReportRequest,
    SmartFolderGenerateRequest,
)

router = APIRouter(prefix="/smart-folders", tags=["smart-folders"])
logger = logging.getLogger(__name__)


async def create_audit_log(
    db: AsyncSession,
    user_id: UUID,
    action: AuditAction,
    resource_type: str,
    resource_id: str | None = None,
    details: dict | None = None,
) -> None:
    """Helper function to create audit log entries for confidential access"""
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
        logger.error(f"Audit logging failed: {str(e)}")


@router.post("/generate")
async def generate_smart_folder(
    request: SmartFolderGenerateRequest,
    current_user: User = Depends(require_superuser_or_admin),
) -> dict[str, Any]:
    """
    Queue a Smart Folder generation task

    Enqueues an asynchronous Celery task that will:
      1. Search for relevant documents
      2. Generate AI content via MiniMax/OpenRouter
      3. Create a new Collection of type FOLDER

    Returns immediately with a task_id. Poll GET /generate/status/{task_id}
    to retrieve the result.

    - **topic**: The subject to generate content about
    - **style**: Writing style (informative, creative, professional, casual)
    - **length**: Content length (short, medium, long)
    """
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
        logger.error(
            "Failed to queue smart folder generation: %s",
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to queue generation task. Please try again later.",
        )

    logger.info(
        "Smart folder generation queued | task_id=%s user=%s topic=%s",
        task.id,
        current_user.email,
        request.topic,
    )

    return {
        "task_id": task.id,
        "status": "pending",
        "status_url": f"/api/v1/smart-folders/generate/status/{task.id}",
        "message": f"Smart folder generation queued (task_id={task.id})",
    }


@router.get("/generate/status/{task_id}")
async def get_smart_folder_status(
    task_id: str,
    current_user: User = Depends(require_superuser_or_admin),
) -> dict[str, Any]:
    """
    Poll the status of an async Smart Folder generation task.

    States:
      - **pending**:   Task is still in the queue or being processed.
      - **completed**: Task finished successfully — `result` contains the
                       SmartFolderResponse payload.
      - **failed**:    Task raised an exception — `error` contains details.
    """
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


@router.post("/reports/generate")
async def generate_collection_report(
    request: CollectionReportRequest,
    current_user: User = Depends(require_superuser_or_admin),
) -> dict[str, Any]:
    """
    Queue a Collection Report generation task

    Enqueues an asynchronous Celery task that will generate a professional
    PDF report from the specified collection.

    Returns immediately with a task_id. Poll GET /reports/status/{task_id}
    to retrieve the result.

    - **collection_id**: The collection to generate report from
    - **format**: Report length (short, standard, comprehensive)
    - **include_citations**: Include document references
    - **language**: Report language (en, fr)
    """
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
        logger.error(
            "Failed to queue collection report generation: %s",
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to queue report generation. Please try again later.",
        )

    logger.info(
        "Collection report generation queued | task_id=%s user=%s collection=%s",
        task.id,
        current_user.email,
        request.collection_id,
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
    """
    Poll the status of an async Collection Report generation task.

    States:
      - **pending**:   Task is still in the queue or being processed.
      - **completed**: Task finished successfully — `result` contains the
                       CollectionReportResponse payload.
      - **failed**:    Task raised an exception — `error` contains details.
    """
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
async def get_report_templates(current_user: User = Depends(require_superuser_or_admin)) -> dict[str, Any]:
    """Get available report templates and formats"""
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
        "languages": [{"value": "en", "name": "English"}, {"value": "fr", "name": "Français"}],
        "style_options": [
            {"value": "informative", "name": "Informative", "description": "Educational, clear explanations"},
            {"value": "creative", "name": "Creative", "description": "Engaging, vivid language"},
            {"value": "professional", "name": "Professional", "description": "Formal business tone"},
            {"value": "casual", "name": "Casual", "description": "Friendly, conversational"},
        ],
    }


@router.get("/reports/{report_id}")
async def get_report(
    report_id: UUID, current_user: User = Depends(require_superuser_or_admin), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Get a previously generated report"""
    # In a real implementation, this would fetch from a reports table
    # For now, return a placeholder
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Report history not yet implemented")
