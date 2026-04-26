"""
Celery tasks for asynchronous Smart Folder generation.

Offloads the long-running LLM + DB workflow from the HTTP worker to a
background Celery worker, preventing gateway timeouts and connection-pool
exhaustion.
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
    name="app.tasks.smart_folder_tasks.generate_smart_folder",
    queue="collections",
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 1},
    retry_backoff=True,
    soft_time_limit=300,   # 5 min
    time_limit=600,        # 10 min
)
def generate_smart_folder_task(
    self,
    topic: str,
    style: str,
    length: str,
    include_confidential: bool,
    user_id: str,
) -> dict[str, Any]:
    """
    Generate a Smart Folder asynchronously.

    Args:
        topic: Subject to generate content about.
        style: Writing style (informative, creative, professional, casual).
        length: Content length (short, medium, long).
        include_confidential: Whether to include confidential documents.
        user_id: UUID string of the requesting user.

    Returns:
        Dictionary with collection_id, generated_content, sources, etc.
    """
    from sqlalchemy import select

    from app.database import AsyncSessionLocal
    from app.models.user import User
    from app.services.smart_folder_service import smart_folder_service

    async def _run() -> dict[str, Any]:
        async with AsyncSessionLocal() as db:
            # Fetch user
            user_uuid = uuid.UUID(user_id)
            user = (
                (await db.execute(select(User).where(User.id == user_uuid)))
                .scalar_one_or_none()
            )
            if not user:
                raise ValueError(f"User {user_id} not found")

            # Generate smart folder
            result = await smart_folder_service.generate_smart_folder(
                topic=topic,
                style=style,
                length=length,
                include_confidential=include_confidential,
                user=user,
                db=db,
            )

            # Audit log: confidential document access
            if include_confidential and result.get("sources_used"):
                import json

                from app.models.audit import AuditAction, AuditLog

                confidential_docs = [
                    {"id": src.get("id"), "filename": src.get("filename")}
                    for src in result["sources_used"]
                    if src.get("bucket") == "confidential"
                ]
                if confidential_docs:
                    audit_entry = AuditLog(
                        user_id=user_uuid,
                        action=AuditAction.CONFIDENTIAL_ACCESSED,
                        resource_type="smart_folder",
                        resource_id=str(result.get("collection_id", "unknown")),
                        details=json.dumps(
                            {
                                "topic": topic,
                                "confidential_document_count": len(confidential_docs),
                                "confidential_documents": confidential_docs,
                                "action": "generate_smart_folder",
                            }
                        ),
                    )
                    db.add(audit_entry)
                    await db.commit()
                    logger.info(
                        "CONFIDENTIAL_ACCESSED: User %s accessed confidential documents in smart folder generation",
                        user.email,
                    )

            return result

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.error("Smart folder generation failed: %s", exc, exc_info=True)
        store_dlq_on_max_retries(self, exc, extra_metadata={"topic": topic, "user_id": user_id})
        raise
