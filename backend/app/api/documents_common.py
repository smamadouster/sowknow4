"""
Shared utilities for document API routers.

Extracted from documents.py to enable sub-router splitting without circular imports.
"""

import asyncio
import json
import logging
import os
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditAction, AuditLog
from app.models.document import Document, DocumentBucket, DocumentLanguage, DocumentStatus
from app.schemas.document import DocumentUploadResponse
from app.models.user import User, UserRole

logger = logging.getLogger(__name__)

BOT_API_KEY = os.getenv("BOT_API_KEY", "")

# Validation constants and helpers are owned by
# app.services.document_orchestrator (single source of truth) and re-exported
# here so existing imports from documents_common keep working.
from app.services.document_orchestrator import (  # noqa: E402,F401
    ALLOWED_EXTENSIONS,
    MAX_FILE_SIZE,
    get_file_extension,
    get_mime_type,
    validate_magic_bytes,
)

MAX_BATCH_SIZE = 500 * 1024 * 1024  # 500MB

# Concurrency limiter: cap simultaneous uploads to prevent starving other endpoints
_upload_semaphore = asyncio.Semaphore(3)

# Redis key for admin upload pause toggle
_UPLOAD_PAUSE_KEY = "pipeline:uploads:paused"


def _get_redis_client() -> Any | None:
    """Best-effort Redis client for upload-pause checks."""
    try:
        import redis
        from app.core.redis_url import safe_redis_url
        return redis.from_url(safe_redis_url(), socket_timeout=2)
    except Exception:
        return None


def is_upload_paused() -> tuple[bool, str]:
    """Check whether uploads are currently paused.

    Returns (paused: bool, reason: str).
    Priority:
      1. Admin manual pause (Redis key)
      2. Automatic red-state throttling (pipeline health)

    NOTE: uses a synchronous Redis client — call through
    is_upload_paused_async() from async request handlers.
    """
    # 1. Manual admin pause
    r = _get_redis_client()
    if r is not None:
        try:
            if r.get(_UPLOAD_PAUSE_KEY):
                return True, "Uploads are paused by an administrator"
        except Exception:
            pass

    # 2. Automatic red-state throttling
    try:
        from app.tasks.pipeline_orchestrator import MAX_TOTAL_QUEUE_DEPTH
        if r is not None:
            total_depth = 0
            for q in [
                "pipeline.ocr", "pipeline.chunk", "pipeline.embed",
                "pipeline.index", "pipeline.articles", "pipeline.entities",
            ]:
                try:
                    total_depth += r.llen(q)
                except Exception:
                    pass
            if total_depth > MAX_TOTAL_QUEUE_DEPTH:
                return True, "Pipeline is critically backlogged — uploads temporarily paused"
    except Exception:
        pass

    return False, ""


async def is_upload_paused_async() -> tuple[bool, str]:
    """Async wrapper for is_upload_paused — the sync Redis call must not
    block the event loop in request handlers."""
    return await asyncio.to_thread(is_upload_paused)


def set_upload_paused(paused: bool) -> None:
    """Toggle the admin upload-pause flag in Redis."""
    r = _get_redis_client()
    if r is None:
        raise RuntimeError("Redis is not available")
    if paused:
        r.set(_UPLOAD_PAUSE_KEY, "1")
    else:
        r.delete(_UPLOAD_PAUSE_KEY)


async def create_audit_log(
    db: AsyncSession,
    user_id: uuid.UUID,
    action: AuditAction,
    resource_type: str,
    resource_id: str | None = None,
    details: dict | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> None:
    """Helper function to create audit log entries for document access"""
    try:
        audit_entry = AuditLog(
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=json.dumps(details) if details else None,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        db.add(audit_entry)
        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.error(f"Audit logging failed: {str(e)}")


class JournalEntryRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=10000)
    tags: list[str] = Field(default_factory=list)
    timestamp: str | None = None  # ISO format, defaults to now


async def _queue_document_for_processing(
    document: "Document",
    db: AsyncSession,
    success_message: str = "Document uploaded successfully and queued for processing",
) -> "DocumentUploadResponse":
    """Queue a persisted document for pipeline processing and return the response."""
    try:
        import asyncio
        from concurrent.futures import ThreadPoolExecutor

        from app.models.pipeline import StageEnum, StageStatus
        from app.schemas.document import DocumentUploadResponse
        from app.tasks.pipeline_orchestrator import dispatch_document
        from app.tasks.pipeline_tasks import update_stage

        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=1) as pool:
            await loop.run_in_executor(
                pool, update_stage, str(document.id), StageEnum.UPLOADED, StageStatus.COMPLETED
            )
            result = await loop.run_in_executor(pool, dispatch_document, str(document.id))

        if result == "dispatched":
            document.status = DocumentStatus.PROCESSING
            document.pipeline_stage = "ocr"
            message = success_message
        else:
            document.status = DocumentStatus.PENDING
            document.pipeline_stage = "uploaded"
            document.document_metadata = {
                **(document.document_metadata or {}),
                "backpressure": result,
            }
            message = "Document queued, processing will start when capacity is available"

        await db.commit()
        logger.info("Document %s pipeline %s", document.id, result)
        return DocumentUploadResponse(
            document_id=document.id,
            filename=document.filename,
            status=document.status,
            message=message,
        )
    except Exception as exc:
        logger.error("Failed to queue document %s: %s", document.id, exc)
        document.status = DocumentStatus.ERROR
        document.pipeline_stage = "failed"
        document.pipeline_error = str(exc)[:500]
        document.document_metadata = {
            **(document.document_metadata or {}),
            "processing_error": f"Failed to queue: {exc}",
        }
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Document saved but failed to queue for processing: {exc}",
        )
