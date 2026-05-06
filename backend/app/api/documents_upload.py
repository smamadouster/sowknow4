"""
Upload endpoints for single and batch document ingestion.

Split from documents.py to reduce the god-router surface area.
"""

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.documents_common import (
    ALLOWED_EXTENSIONS,
    BOT_API_KEY,
    MAX_BATCH_SIZE,
    MAX_FILE_SIZE,
    _upload_semaphore,
    create_audit_log,
    get_file_extension,
    get_mime_type,
    validate_magic_bytes,
    _queue_document_for_processing,
)
from app.database import get_db
from app.models.audit import AuditAction
from app.models.document import Document, DocumentBucket, DocumentLanguage, DocumentStatus
from app.models.user import User
from app.schemas.document import BatchUploadResponse, DocumentUploadResponse
from app.services.deduplication_service import deduplication_service
from app.services.document_orchestrator import document_orchestrator
from app.services.storage_service import storage_service

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/upload", response_model=DocumentUploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    bucket: str = Form("public"),
    title: str | None = Form(None),
    tags: str | None = Form(None),
    document_type: str | None = Form(None),
    transcript: str | None = Form(None),
    x_bot_api_key: str | None = Header(None, alias="X-Bot-Api-Key"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentUploadResponse:
    """Upload a document to the specified bucket."""
    if _upload_semaphore._value == 0:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Too many uploads in progress. Please retry shortly.",
        )
    async with _upload_semaphore:
        return await _do_upload_document(
            file=file, bucket=bucket, title=title, tags=tags,
            document_type=document_type, transcript=transcript,
            x_bot_api_key=x_bot_api_key, current_user=current_user, db=db,
        )


async def _do_upload_document(
    file: UploadFile,
    bucket: str,
    title: str | None,
    tags: str | None,
    document_type: str | None,
    transcript: str | None,
    x_bot_api_key: str | None,
    current_user: User,
    db: AsyncSession,
) -> DocumentUploadResponse:
    """Internal upload handler — delegates to DocumentOrchestrator."""
    if x_bot_api_key:
        if not BOT_API_KEY:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bot API key not configured")
        if x_bot_api_key != BOT_API_KEY:
            logger.warning(
                "Invalid Bot API Key. Received length: %d, Expected length: %d",
                len(x_bot_api_key),
                len(BOT_API_KEY),
            )
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Bot API Key")
        logger.info("Valid bot API key provided for user: %s", current_user.email)

    return await document_orchestrator.ingest_document(
        file=file,
        bucket=bucket,
        title=title,
        tags=tags,
        document_type=document_type,
        transcript=transcript,
        current_user=current_user,
        db=db,
    )


async def process_single_file_upload(
    file: UploadFile,
    bucket: str,
    current_user: User,
    db: AsyncSession,
    batch_id: str | None = None,
) -> tuple[DocumentUploadResponse | None, str | None]:
    """Helper function to process a single file upload within a batch."""
    try:
        if not file.filename:
            return None, "No filename provided"

        file_extension = get_file_extension(file.filename)
        if file_extension not in ALLOWED_EXTENSIONS:
            return None, f"Invalid file type: {file_extension}"

        content = await file.read()

        if len(content) > MAX_FILE_SIZE:
            return (
                None,
                f"File {file.filename} exceeds maximum size of {MAX_FILE_SIZE // (1024 * 1024)}MB",
            )

        if not validate_magic_bytes(file.filename, content):
            logger.warning(
                "SECURITY: Magic byte mismatch for %s in batch upload by %s",
                file.filename,
                current_user.email,
            )
            return None, f"File content does not match its extension: {file.filename}"

        file_hash = deduplication_service.calculate_hash(content)

        duplicate_doc = await deduplication_service.is_duplicate(
            file_hash=file_hash, filename=file.filename, size=len(content), db=db
        )

        if duplicate_doc:
            return DocumentUploadResponse(
                document_id=duplicate_doc.id,
                filename=duplicate_doc.filename,
                status=duplicate_doc.status,
                message="Document already exists (duplicate detected)",
            ), None

        save_result = storage_service.save_file(
            file_content=content, original_filename=file.filename, bucket=bucket
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
            batch_id=batch_id,
        )

        db.add(document)
        await db.commit()
        await db.refresh(document)

        await deduplication_service.register_upload(
            file_hash=file_hash,
            filename=file.filename,
            size=len(content),
            document_id=str(document.id),
            db=db,
        )

        if bucket == "confidential":
            await create_audit_log(
                db=db,
                user_id=current_user.id,
                action=AuditAction.CONFIDENTIAL_UPLOADED,
                resource_type="document",
                resource_id=str(document.id),
                details={"filename": document.filename, "original_filename": file.filename},
            )

        response = await _queue_document_for_processing(document, db)
        return response, None

    except Exception as exc:
        logger.error("Error processing file %s: %s", file.filename, exc)
        return None, f"Error processing file {file.filename}: {exc}"


MAX_FILES_PER_BATCH = 20


@router.post("/upload-batch", response_model=BatchUploadResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_batch_documents(
    files: list[UploadFile] = File(...),
    bucket: str = Form("public"),
    x_bot_api_key: str | None = Header(None, alias="X-Bot-Api-Key"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BatchUploadResponse:
    """Upload multiple documents in a single request (batch upload)."""
    logger.info(
        "Batch upload attempt: user=%s, role=%s, bucket=%s",
        current_user.email,
        current_user.role.value,
        bucket,
    )

    if x_bot_api_key:
        if not BOT_API_KEY:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bot API key not configured")
        if x_bot_api_key != BOT_API_KEY:
            logger.warning("Invalid Bot API Key")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Bot API Key")

    if bucket == "confidential":
        if current_user.role.value not in ["admin", "superuser"]:
            logger.warning(
                "SECURITY: Blocked confidential batch upload by user %s (role: %s)",
                current_user.email,
                current_user.role.value,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: Admin or Super User role required for confidential bucket uploads",
            )

    if bucket not in ["public", "confidential"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid bucket. Use 'public' or 'confidential'"
        )

    if not files:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No files provided")

    if len(files) > MAX_FILES_PER_BATCH:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Too many files: maximum {MAX_FILES_PER_BATCH} files per batch upload",
        )

    total_size = 0
    file_sizes: dict[str, int] = {}

    for file in files:
        if file.filename:
            content = await file.read()
            file_sizes[file.filename] = len(content)
            total_size += len(content)
            await file.seek(0)

    logger.info(
        "Batch upload: %d files, total size: %d bytes (%.2fMB)",
        len(files),
        total_size,
        total_size / (1024 * 1024),
    )

    if total_size > MAX_BATCH_SIZE:
        logger.warning(
            "Batch upload rejected: total size %d bytes (%.2fMB) exceeds limit of %d bytes (%dMB)",
            total_size,
            total_size / (1024 * 1024),
            MAX_BATCH_SIZE,
            int(MAX_BATCH_SIZE / (1024 * 1024)),
        )
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"Batch total size exceeds limit. "
                f"Received: {total_size / (1024 * 1024):.2f}MB, "
                f"Limit: {int(MAX_BATCH_SIZE / (1024 * 1024))}MB."
            ),
        )

    successful_docs: list[DocumentUploadResponse] = []
    errors: list[str] = []
    successful_count = 0
    failed_count = 0
    batch_id = str(uuid.uuid4())

    for file in files:
        async with _upload_semaphore:
            doc_response, error = await process_single_file_upload(
                file=file, bucket=bucket, current_user=current_user, db=db, batch_id=batch_id
            )

        if doc_response:
            successful_docs.append(doc_response)
            successful_count += 1
        else:
            errors.append(error)
            failed_count += 1

    return BatchUploadResponse(
        batch_id=batch_id,
        total_files=len(files),
        successful=successful_count,
        failed=failed_count,
        documents=successful_docs,
        errors=errors,
        total_size_bytes=total_size,
        batch_limit_exceeded=False,
        message=f"Batch upload completed: {successful_count} successful, {failed_count} failed",
    )


@router.get("/batch/{batch_id}/status")
async def get_batch_status(
    batch_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get the status of a batch upload by batch ID."""
    from sqlalchemy import func, select

    from app.models.document import Document

    stmt = (
        select(
            Document.status,
            func.count(Document.id).label("count"),
        )
        .where(Document.batch_id == batch_id)
        .group_by(Document.status)
    )
    result = await db.execute(stmt)
    rows = result.all()

    status_counts = {row.status.value: row.count for row in rows}
    total = sum(status_counts.values())

    return {
        "batch_id": batch_id,
        "total_documents": total,
        "status_breakdown": status_counts,
        "is_complete": status_counts.get("pending", 0) == 0 and total > 0,
    }
