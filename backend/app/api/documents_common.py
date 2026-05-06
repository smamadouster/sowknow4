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

# Allowed file types and size limits
ALLOWED_EXTENSIONS = {
    ".pdf", ".docx", ".doc", ".pptx", ".ppsx", ".ppt", ".xlsx", ".xls",
    ".txt", ".md", ".json", ".jpg", ".jpeg", ".png", ".gif", ".bmp",
    ".heic", ".mp4", ".avi", ".mov", ".mkv", ".mp3", ".wav", ".ogg",
    ".flac", ".aac", ".wma", ".m4a", ".webm", ".epub", ".csv", ".xml",
    ".html", ".htm", ".tiff", ".tif", ".rtf", ".zip", ".xmind", ".msg",
}
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB
MAX_BATCH_SIZE = 500 * 1024 * 1024  # 500MB

# Concurrency limiter: cap simultaneous uploads to prevent starving other endpoints
_upload_semaphore = asyncio.Semaphore(3)


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


def get_file_extension(filename: str) -> str:
    """Extract lowercase file extension including the dot."""
    return filename[filename.rfind("."):].lower() if "." in filename else ""


def get_mime_type(filename: str, content: bytes = b"") -> str:
    """Best-effort MIME type detection from filename and optional magic bytes."""
    ext = get_file_extension(filename)
    mime_map = {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".doc": "application/msword",
        ".txt": "text/plain",
        ".md": "text/markdown",
        ".html": "text/html",
        ".htm": "text/html",
        ".epub": "application/epub+zip",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
        ".tiff": "image/tiff",
        ".tif": "image/tiff",
        ".heic": "image/heic",
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".ogg": "audio/ogg",
        ".flac": "audio/flac",
        ".aac": "audio/aac",
        ".wma": "audio/x-ms-wma",
        ".m4a": "audio/mp4",
        ".webm": "audio/webm",
        ".mp4": "video/mp4",
        ".avi": "video/x-msvideo",
        ".mov": "video/quicktime",
        ".mkv": "video/x-matroska",
        ".csv": "text/csv",
        ".json": "application/json",
        ".xml": "application/xml",
        ".zip": "application/zip",
        ".rtf": "application/rtf",
    }
    if mime_map.get(ext):
        return mime_map[ext]
    guessed = mimetypes.guess_type(filename)[0]
    return guessed or "application/octet-stream"


def validate_magic_bytes(filename: str, content: bytes) -> bool:
    """Validate that file content matches declared extension via magic bytes."""
    ext = get_file_extension(filename)
    magic_signatures = {
        ".pdf": (content[:4] == b"%PDF"),
        ".png": (content[:8] == b"\x89PNG\r\n\x1a\n"),
        ".jpg": (content[:3] == b"\xff\xd8\xff"),
        ".jpeg": (content[:3] == b"\xff\xd8\xff"),
        ".gif": (content[:6] in (b"GIF87a", b"GIF89a")),
        ".webp": (content[:4] == b"RIFF" and content[8:12] == b"WEBP"),
        ".zip": (content[:4] == b"PK\x03\x04"),
        ".docx": (content[:4] == b"PK\x03\x04"),
        ".pptx": (content[:4] == b"PK\x03\x04"),
        ".xlsx": (content[:4] == b"PK\x03\x04"),
        ".epub": (content[:4] == b"PK\x03\x04"),
        ".mp3": (content[:3] == b"ID3" or content[:2] == b"\xff\xfb"),
        ".wav": (content[:4] == b"RIFF" and content[8:12] == b"WAVE"),
    }
    return magic_signatures.get(ext, True)


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
