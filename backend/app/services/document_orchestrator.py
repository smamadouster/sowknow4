"""
Document Orchestrator Service

Extracts the core document ingestion pipeline from api/documents.py,
reducing the API router's responsibility to HTTP concerns only
(validating, serializing, calling the orchestrator, returning responses).

This is Step 1 in decoupling the 1,441-line documents.py god-router.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditAction, AuditLog
from app.models.document import (
    Document,
    DocumentBucket,
    DocumentLanguage,
    DocumentStatus,
    DocumentTag,
)
from app.models.user import User, UserRole
from app.schemas.document import DocumentUploadResponse
from app.services.deduplication_service import deduplication_service
from app.services.storage_service import storage_service

logger = logging.getLogger(__name__)

# File upload constraints
ALLOWED_EXTENSIONS = {
    ".pdf", ".docx", ".txt", ".md", ".html", ".epub",
    ".jpg", ".jpeg", ".png", ".webp", ".tiff",
    ".mp3", ".wav", ".ogg", ".webm", ".m4a", ".flac", ".aac",
    ".mp4", ".mov", ".avi", ".mkv",
}
MAX_FILE_SIZE = 500 * 1024 * 1024  # 500 MB


def get_file_extension(filename: str) -> str:
    """Return lowercase extension including the dot."""
    return filename[filename.rfind("."):].lower() if "." in filename else ""


def get_mime_type(filename: str, content: bytes = b"") -> str:
    """Best-effort MIME type detection."""
    ext = get_file_extension(filename)
    mime_map = {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".txt": "text/plain",
        ".md": "text/markdown",
        ".html": "text/html",
        ".epub": "application/epub+zip",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".tiff": "image/tiff",
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".ogg": "audio/ogg",
        ".webm": "audio/webm",
        ".m4a": "audio/mp4",
        ".flac": "audio/flac",
        ".aac": "audio/aac",
        ".mp4": "video/mp4",
        ".mov": "video/quicktime",
        ".avi": "video/x-msvideo",
        ".mkv": "video/x-matroska",
    }
    return mime_map.get(ext, "application/octet-stream")


def validate_magic_bytes(filename: str, content: bytes) -> bool:
    """Validate that file content matches declared extension."""
    ext = get_file_extension(filename)
    magic = {
        ".pdf": (content[:4] == b"%PDF"),
        ".png": (content[:8] == b"\x89PNG\r\n\x1a\n"),
        ".jpg": (content[:3] == b"\xff\xd8\xff"),
        ".jpeg": (content[:3] == b"\xff\xd8\xff"),
        ".gif": (content[:6] in (b"GIF87a", b"GIF89a")),
        ".webp": (content[:4] == b"RIFF" and content[8:12] == b"WEBP"),
        ".zip": (content[:4] == b"PK\x03\x04"),  # docx, epub
        ".docx": (content[:4] == b"PK\x03\x04"),
        ".epub": (content[:4] == b"PK\x03\x04"),
        ".mp3": (content[:3] == b"ID3" or content[:2] == b"\xff\xfb"),
        ".wav": (content[:4] == b"RIFF" and content[8:12] == b"WAVE"),
    }
    # If no magic rule for this extension, allow it through
    return magic.get(ext, True)


class DocumentOrchestrator:
    """
    Encapsulates the document ingestion pipeline:
      validation → deduplication → storage → persistence → queueing.
    """

    async def ingest_document(
        self,
        *,
        file: UploadFile,
        bucket: str,
        title: str | None,
        tags: str | None,
        document_type: str | None,
        transcript: str | None,
        current_user: User,
        db: AsyncSession,
    ) -> DocumentUploadResponse:
        """
        Full upload pipeline.  Raises HTTPException on validation or processing failure.
        """
        # ── Role & bucket validation ──
        self._assert_bucket_access(bucket, current_user)

        # ── File validation ──
        content = await self._validate_file(file)

        # ── Deduplication ──
        file_hash = deduplication_service.calculate_hash(content)
        duplicate = await deduplication_service.is_duplicate(
            file_hash=file_hash, filename=file.filename, size=len(content), db=db
        )
        if duplicate:
            logger.info(f"Duplicate detected: {file.filename} → {duplicate.id}")
            return DocumentUploadResponse(
                document_id=duplicate.id,
                filename=duplicate.filename,
                status=duplicate.status,
                message="Document already exists (duplicate detected)",
            )

        # ── Storage ──
        save_result = storage_service.save_file(
            file_content=content, original_filename=file.filename, bucket=bucket
        )

        # ── Document record creation ──
        document = await self._create_document_record(
            file=file,
            content=content,
            save_result=save_result,
            bucket=bucket,
            document_type=document_type,
            transcript=transcript,
            current_user=current_user,
            db=db,
        )

        # ── Persist user tags ──
        if tags:
            await self._attach_user_tags(document, tags, db)

        # ── Register hash ──
        await deduplication_service.register_upload(
            file_hash=file_hash,
            filename=file.filename,
            size=len(content),
            document_id=str(document.id),
            db=db,
        )

        # ── Audit log for confidential uploads ──
        if bucket == "confidential":
            await self._log_confidential_upload(document, file.filename, current_user, db)

        # ── Voice transcription dispatch (async, non-blocking) ──
        await self._maybe_dispatch_voice_transcription(document, transcript)

        # ── Queue for pipeline processing ──
        return await self._queue_for_processing(document, db)

    # ───────────────────────────────────────────────────────────────
    # Internal helpers
    # ───────────────────────────────────────────────────────────────

    def _assert_bucket_access(self, bucket: str, current_user: User) -> None:
        if bucket not in ("public", "confidential"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid bucket. Use 'public' or 'confidential'",
            )
        if bucket == "confidential" and current_user.role.value not in ("admin", "superuser"):
            logger.warning(
                "SECURITY: Blocked confidential upload by %s (role=%s)",
                current_user.email,
                current_user.role.value,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: Admin or Super User role required for confidential bucket uploads",
            )

    async def _validate_file(self, file: UploadFile) -> bytes:
        if not file.filename:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="No filename provided"
            )
        ext = get_file_extension(file.filename)
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid file type. Allowed: {', '.join(ALLOWED_EXTENSIONS)}",
            )
        content = await file.read()
        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File too large. Maximum size: {MAX_FILE_SIZE // (1024 * 1024)}MB",
            )
        if not validate_magic_bytes(file.filename, content):
            logger.warning("SECURITY: Magic byte mismatch for %s", file.filename)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File content does not match its extension. Upload rejected.",
            )
        return content

    async def _create_document_record(
        self,
        *,
        file: UploadFile,
        content: bytes,
        save_result: dict[str, Any],
        bucket: str,
        document_type: str | None,
        transcript: str | None,
        current_user: User,
        db: AsyncSession,
    ) -> Document:
        if document_type == "journal" and bucket != "confidential":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Journal entries must use the confidential bucket",
            )

        document = Document(
            filename=save_result["filename"],
            original_filename=file.filename,
            file_path=save_result["file_path"],
            bucket=DocumentBucket(bucket),
            status=DocumentStatus.PENDING,
            size=save_result["size"],
            mime_type=get_mime_type(file.filename, content),
            language=DocumentLanguage.UNKNOWN,
            uploaded_by=current_user.id,
        )

        metadata: dict[str, Any] = {}
        if document_type:
            metadata["document_type"] = document_type
            if document_type == "journal":
                metadata["journal_timestamp"] = datetime.now(UTC).isoformat()
        if transcript:
            metadata["extracted_text"] = transcript
            document.ocr_processed = True
            # Write transcript to sidecar .txt for indexing
            txt_path = save_result["file_path"] + ".txt"
            try:
                with open(txt_path, "w", encoding="utf-8") as f:
                    f.write(transcript)
                logger.info("Wrote voice transcript to %s", txt_path)
            except Exception as exc:
                logger.warning("Failed to write transcript file: %s", exc)

        if metadata:
            document.document_metadata = metadata

        db.add(document)
        await db.commit()
        await db.refresh(document)
        return document

    async def _attach_user_tags(
        self, document: Document, tags: str, db: AsyncSession
    ) -> None:
        tag_names = [t.strip().lower() for t in tags.split(",") if t.strip()]
        for name in tag_names:
            db.add(
                DocumentTag(
                    document_id=document.id,
                    tag_name=name,
                    tag_type="user",
                    auto_generated=False,
                )
            )
        if tag_names:
            await db.commit()
            logger.info("Added %d user tag(s) to document %s", len(tag_names), document.id)

    async def _log_confidential_upload(
        self,
        document: Document,
        original_filename: str,
        current_user: User,
        db: AsyncSession,
    ) -> None:
        audit = AuditLog(
            user_id=current_user.id,
            action=AuditAction.CONFIDENTIAL_UPLOADED,
            resource_type="document",
            resource_id=str(document.id),
            details={"filename": document.filename, "original_filename": original_filename},
            created_at=datetime.now(UTC),
        )
        db.add(audit)
        await db.commit()

    async def _maybe_dispatch_voice_transcription(
        self, document: Document, transcript: str | None
    ) -> None:
        audio_extensions = {".ogg", ".webm", ".wav", ".mp3", ".m4a", ".flac", ".aac"}
        ext = get_file_extension(document.original_filename or document.filename)
        if ext in audio_extensions and not transcript:
            try:
                from app.tasks.voice_tasks import transcribe_voice_note

                transcribe_voice_note.delay(
                    audio_file_path=document.file_path,
                    document_id=str(document.id),
                )
                logger.info("Dispatched voice transcription for document %s", document.id)
            except Exception as exc:
                logger.warning("Failed to dispatch voice transcription: %s", exc)

    async def _queue_for_processing(
        self, document: Document, db: AsyncSession
    ) -> DocumentUploadResponse:
        try:
            import asyncio
            from concurrent.futures import ThreadPoolExecutor

            from app.models.pipeline import StageEnum, StageStatus
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
                message = "Document uploaded successfully and queued for processing"
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


# Singleton instance
document_orchestrator = DocumentOrchestrator()
