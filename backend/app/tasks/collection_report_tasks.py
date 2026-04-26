"""
Celery tasks for asynchronous Collection Report generation.

Offloads PDF report generation from the HTTP worker to a background Celery
worker, preventing gateway timeouts for long-running LLM synthesis.
"""

import asyncio
import logging
from typing import Any

from celery import shared_task

from app.tasks.base import store_dlq_on_max_retries

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    name="app.tasks.collection_report_tasks.generate_collection_report",
    queue="celery",
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 1},
    retry_backoff=True,
    soft_time_limit=300,   # 5 min
    time_limit=600,        # 10 min
)
def generate_collection_report_task(
    self,
    collection_id: str,
    report_format: str,
    include_citations: bool,
    language: str,
    user_id: str,
) -> dict[str, Any]:
    """
    Generate a collection report asynchronously.

    Args:
        collection_id: UUID string of the collection to report on.
        report_format: Report length (short, standard, comprehensive).
        include_citations: Whether to include document references.
        language: Report language (en, fr).
        user_id: UUID string of the requesting user.

    Returns:
        Dictionary matching CollectionReportResponse fields.
    """
    from uuid import UUID

    from sqlalchemy import select

    from app.database import AsyncSessionLocal
    from app.models.user import User
    from app.services.report_service import ReportFormat as ReportFormatService
    from app.services.report_service import report_service

    async def _run() -> dict[str, Any]:
        async with AsyncSessionLocal() as db:
            user_uuid = UUID(user_id)
            user = (
                (await db.execute(select(User).where(User.id == user_uuid)))
                .scalar_one_or_none()
            )
            if not user:
                raise ValueError(f"User {user_id} not found")

            format_map = {
                "short": ReportFormatService.SHORT,
                "standard": ReportFormatService.STANDARD,
                "comprehensive": ReportFormatService.COMPREHENSIVE,
            }
            fmt = format_map.get(report_format, ReportFormatService.STANDARD)

            result = await report_service.generate_report(
                collection_id=UUID(collection_id),
                format=fmt,
                include_citations=include_citations,
                language=language,
                user=user,
                db=db,
            )

            # Audit log: confidential document access
            if result.get("has_confidential"):
                import json

                from app.models.audit import AuditAction, AuditLog

                audit_entry = AuditLog(
                    user_id=user_uuid,
                    action=AuditAction.CONFIDENTIAL_ACCESSED,
                    resource_type="report",
                    resource_id=collection_id,
                    details=json.dumps(
                        {
                            "format": report_format,
                            "language": language,
                            "action": "generate_report",
                            "has_confidential": True,
                        }
                    ),
                )
                db.add(audit_entry)
                await db.commit()
                logger.info(
                    "CONFIDENTIAL_ACCESSED: User %s generated report with confidential documents",
                    user.email,
                )

            return result

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.error("Collection report generation failed: %s", exc, exc_info=True)
        store_dlq_on_max_retries(
            self, exc, extra_metadata={"collection_id": collection_id, "user_id": user_id}
        )
        raise
