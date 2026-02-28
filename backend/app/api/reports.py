"""
API endpoints for asynchronous report generation.

POST /reports/generate   — queue a PDF/Excel report generation task
GET  /reports/status/{task_id} — poll task status
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, status

from app.api.deps import get_current_user
from app.models.user import User
from app.schemas.reports import GenerateReportRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reports", tags=["reports"])


@router.post("/generate", status_code=status.HTTP_202_ACCEPTED)
async def generate_report(
    request: GenerateReportRequest,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Queue an async report generation task.

    Returns HTTP 202 Accepted with a task_id and status_url for polling.
    """
    from app.tasks.report_tasks import generate_excel_export, generate_pdf_report

    task_fn = generate_excel_export if request.format == "excel" else generate_pdf_report

    task = task_fn.delay(
        report_type=request.report_type,
        filters=request.filters,
        user_id=str(current_user.id),
        output_filename=request.output_filename,
    )

    return {
        "task_id": task.id,
        "status": "processing",
        "status_url": f"/api/v1/reports/status/{task.id}",
        "message": f"Report generation queued (task_id={task.id})",
    }


@router.get("/status/{task_id}")
async def get_report_status(
    task_id: str,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """
    Poll the status of an async report generation task.
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
