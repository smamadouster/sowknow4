"""Celery tasks for asynchronous Smart Folder v2 generation.

Runs the agentic pipeline: query parser → planner → skill executor →
synthesizer, persisting results as SmartFolder + SmartFolderReport.
"""

import asyncio
import logging
import uuid
from typing import Any

from celery import shared_task

from app.tasks.base import store_dlq_on_max_retries

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    name="app.tasks.smart_folder_tasks.generate_smart_folder_v2",
    queue="collections",
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 1},
    retry_backoff=True,
    soft_time_limit=300,   # 5 min
    time_limit=600,        # 10 min
)
def generate_smart_folder_v2_task(
    self,
    query: str,
    include_confidential: bool,
    user_id: str,
    smart_folder_id: str | None = None,
    refinement_query: str | None = None,
) -> dict[str, Any]:
    """Generate a Smart Folder v2 report asynchronously via the agentic pipeline.

    Args:
        query: Natural language request.
        include_confidential: Whether to include confidential documents.
        user_id: UUID string of the requesting user.
        smart_folder_id: If refining, the existing SmartFolder ID.
        refinement_query: Follow-up constraint if this is a refinement.

    Returns:
        Dictionary with smart_folder_id, report_id, status, and result payload.
    """
    from sqlalchemy import select

    from app.database import AsyncSessionLocal
    from app.models.audit import AuditAction, AuditLog
    from app.models.smart_folder import SmartFolder, SmartFolderStatus
    from app.models.user import User
    from app.services.smart_folder.agent_runner import agent_runner

    async def _run() -> dict[str, Any]:
        async with AsyncSessionLocal() as db:
            user_uuid = uuid.UUID(user_id)
            user = (
                (await db.execute(select(User).where(User.id == user_uuid)))
                .scalar_one_or_none()
            )
            if not user:
                raise ValueError(f"User {user_id} not found")

            # Load or create SmartFolder
            if smart_folder_id:
                sf_stmt = select(SmartFolder).where(
                    SmartFolder.id == uuid.UUID(smart_folder_id),
                    SmartFolder.user_id == user_uuid,
                )
                sf_result = await db.execute(sf_stmt)
                smart_folder = sf_result.scalar_one_or_none()
                if not smart_folder:
                    raise ValueError(f"SmartFolder {smart_folder_id} not found")
            else:
                smart_folder = SmartFolder(
                    user_id=user_uuid,
                    name=query[:120],
                    query_text=query,
                    status=SmartFolderStatus.GENERATING,
                )
                db.add(smart_folder)
                await db.commit()
                await db.refresh(smart_folder)

            try:
                # Run the agentic pipeline
                result = await agent_runner.run(
                    db=db,
                    user=user,
                    query=query,
                    smart_folder=smart_folder,
                    refinement_query=refinement_query,
                )

                # Audit: confidential access
                if include_confidential and result.get("status") == "completed":
                    # Retrieve source assets from report
                    report_id = result.get("report_id")
                    if report_id:
                        from app.models.smart_folder import SmartFolderReport
                        r_stmt = select(SmartFolderReport).where(SmartFolderReport.id == uuid.UUID(report_id))
                        r_result = await db.execute(r_stmt)
                        report = r_result.scalar_one_or_none()
                        if report and report.source_asset_ids:
                            from app.models.document import Document
                            d_stmt = select(Document.id, Document.bucket, Document.original_filename).where(
                                Document.id.in_([uuid.UUID(aid) for aid in report.source_asset_ids])
                            )
                            d_result = await db.execute(d_stmt)
                            conf_docs = [
                                {"id": str(row[0]), "name": row[2]}
                                for row in d_result.all()
                                if row[1] and row[1].value == "confidential"
                            ]
                            if conf_docs:
                                audit_entry = AuditLog(
                                    user_id=user_uuid,
                                    action=AuditAction.CONFIDENTIAL_ACCESSED,
                                    resource_type="smart_folder",
                                    resource_id=str(smart_folder.id),
                                    details={
                                        "query": query,
                                        "refinement": refinement_query,
                                        "confidential_document_count": len(conf_docs),
                                        "confidential_documents": conf_docs,
                                        "action": "generate_smart_folder_v2",
                                    },
                                )
                                db.add(audit_entry)
                                await db.commit()

                return result

            except Exception as exc:
                smart_folder.status = SmartFolderStatus.FAILED
                smart_folder.error_message = str(exc)
                await db.commit()
                raise

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.error("Smart folder v2 generation failed: %s", exc, exc_info=True)
        store_dlq_on_max_retries(self, exc, extra_metadata={"query": query, "user_id": user_id})
        raise


# Legacy task kept for backward compatibility
@shared_task(
    bind=True,
    name="app.tasks.smart_folder_tasks.generate_smart_folder",
    queue="collections",
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 1},
    retry_backoff=True,
    soft_time_limit=300,
    time_limit=600,
)
def generate_smart_folder_task(
    self,
    topic: str,
    style: str,
    length: str,
    include_confidential: bool,
    user_id: str,
) -> dict[str, Any]:
    """Legacy Smart Folder generation task (v1)."""
    import asyncio

    from sqlalchemy import select

    from app.database import AsyncSessionLocal
    from app.models.user import User
    from app.services.smart_folder_service import smart_folder_service

    async def _run() -> dict[str, Any]:
        async with AsyncSessionLocal() as db:
            user_uuid = uuid.UUID(user_id)
            user = (
                (await db.execute(select(User).where(User.id == user_uuid)))
                .scalar_one_or_none()
            )
            if not user:
                raise ValueError(f"User {user_id} not found")

            result = await smart_folder_service.generate_smart_folder(
                topic=topic,
                style=style,
                length=length,
                include_confidential=include_confidential,
                user=user,
                db=db,
            )
            return result

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.error("Legacy smart folder generation failed: %s", exc, exc_info=True)
        store_dlq_on_max_retries(self, exc, extra_metadata={"topic": topic, "user_id": user_id})
        raise
