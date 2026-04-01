"""
Document API endpoints for upload, list, get, update, and delete operations
"""

import json
import logging
import mimetypes
import os
import uuid
from datetime import datetime
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

try:
    import magic as _magic

    _magic_available = True
except ImportError:
    _magic_available = False

logger = logging.getLogger(__name__)

from app.api.deps import get_current_user, require_admin_only
from app.database import get_db
from app.models.audit import AuditAction, AuditLog
from app.models.document import (
    Document,
    DocumentBucket,
    DocumentLanguage,
    DocumentStatus,
    DocumentTag,
)
from app.models.user import User, UserRole
from app.schemas.document import (
    BatchUploadResponse,
    DocumentListResponse,
    DocumentResponse,
    DocumentStatusResponse,
    DocumentUpdate,
    DocumentUploadResponse,
)
from app.services.deduplication_service import deduplication_service
from app.services.storage_service import storage_service

router = APIRouter(prefix="/documents", tags=["documents"])

BOT_API_KEY = os.getenv("BOT_API_KEY", "")


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


# Allowed file types and size limits
ALLOWED_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".doc",
    ".pptx",
    ".ppt",
    ".xlsx",
    ".xls",
    ".txt",
    ".md",
    ".json",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".bmp",
    ".heic",
    ".mp4",
    ".avi",
    ".mov",
    ".mkv",
    ".epub",
    ".csv",
    ".xml",
    ".tiff",
    ".tif",
}
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB
MAX_BATCH_SIZE = 500 * 1024 * 1024  # 500MB


def get_file_extension(filename: str) -> str:
    """Get file extension from filename"""
    return "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def get_mime_type(filename: str, content: bytes = b"") -> str:
    """Get MIME type using content-based detection (magic bytes) with filename fallback"""
    if content and _magic_available:
        try:
            detected = _magic.from_buffer(content, mime=True)
            if detected and detected != "application/octet-stream":
                return detected
        except Exception:
            pass
    mime_type, _ = mimetypes.guess_type(filename)
    return mime_type or "application/octet-stream"


# Map of allowed extensions to their expected MIME type prefixes for validation
_EXTENSION_MIME_PREFIXES: dict = {
    ".pdf": ["application/pdf"],
    ".docx": ["application/vnd.openxmlformats", "application/zip"],
    ".doc": ["application/msword", "application/vnd.ms"],
    ".pptx": ["application/vnd.openxmlformats", "application/zip"],
    ".ppt": ["application/vnd.ms-powerpoint", "application/vnd.ms"],
    ".xlsx": ["application/vnd.openxmlformats", "application/zip"],
    ".xls": ["application/vnd.ms-excel", "application/vnd.ms"],
    ".txt": ["text/"],
    ".md": ["text/"],
    ".json": ["application/json", "text/"],
    ".jpg": ["image/jpeg"],
    ".jpeg": ["image/jpeg"],
    ".png": ["image/png"],
    ".gif": ["image/gif"],
    ".bmp": ["image/bmp", "image/x-bmp", "image/x-ms-bmp"],
    ".heic": ["image/heic", "image/heif"],
    ".mp4": ["video/mp4"],
    ".avi": ["video/x-msvideo", "video/avi"],
    ".mov": ["video/quicktime"],
    ".mkv": ["video/x-matroska"],
    ".epub": ["application/epub+zip", "application/zip"],
    ".csv": ["text/csv", "text/", "application/csv"],
    ".xml": ["text/xml", "application/xml", "text/"],
    ".tiff": ["image/tiff"],
    ".tif": ["image/tiff"],
}


def validate_magic_bytes(filename: str, content: bytes) -> bool:
    """Validate file content matches extension using magic bytes. Returns True if valid."""
    if not content or not _magic_available:
        return True  # Fallback: allow if we can't check

    extension = get_file_extension(filename)
    allowed_prefixes = _EXTENSION_MIME_PREFIXES.get(extension)
    if not allowed_prefixes:
        return True  # Unknown extension map — extension check already handles this

    try:
        detected_mime = _magic.from_buffer(content[:8192], mime=True)
        return any(detected_mime.startswith(prefix) for prefix in allowed_prefixes)
    except Exception:
        return True  # Fail open on magic detection errors


@router.post("/upload", response_model=DocumentUploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    bucket: str = Form("public"),
    title: str | None = Form(None),
    tags: str | None = Form(None),
    x_bot_api_key: str | None = Header(None, alias="X-Bot-Api-Key"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentUploadResponse:
    """
    Upload a document to the specified bucket

    - **file**: The file to upload
    - **bucket**: Either "public" or "confidential" (admin/superuser only)
    - **title**: Optional title for the document
    - **tags**: Optional comma-separated tag names (e.g. "urgent,invoice")

    SECURITY: Role-based access control enforced for confidential uploads.
    - Public bucket: Any authenticated user can upload (with or without bot API key)
    - Confidential bucket: Only Admin and Super User roles can upload
    - Bot API key validation is performed but does NOT bypass role checks
    - Returns 403 Forbidden for unauthorized confidential upload attempts
    """
    # PRIORITY: Check user role FIRST (admin/superuser have full access)
    logger.info(f"Upload attempt: user={current_user.email}, role={current_user.role.value}, bucket={bucket}")
    logger.info(f"x_bot_api_key present: {bool(x_bot_api_key)}, BOT_API_KEY configured: {bool(BOT_API_KEY)}")

    # Validate bot API key if provided (used in conjunction with role checks)
    is_bot = False
    if x_bot_api_key:
        if not BOT_API_KEY:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bot API key not configured")
        if x_bot_api_key != BOT_API_KEY:
            logger.warning(
                f"Invalid Bot API Key. Received length: {len(x_bot_api_key)}, Expected length: {len(BOT_API_KEY)}"
            )
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Bot API Key")
        is_bot = True
        logger.info(f"Valid bot API key provided for user: {current_user.email}")

    # CRITICAL SECURITY CHECK: Validate role-based access for confidential bucket
    if bucket == "confidential":
        # Only Admin and Super User roles can upload to confidential bucket
        if current_user.role.value not in ["admin", "superuser"]:
            logger.warning(
                f"SECURITY: Blocked confidential upload attempt by user {current_user.email} "
                f"(role: {current_user.role.value}). Admin or Super User role required."
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: Admin or Super User role required for confidential bucket uploads",
            )
        logger.info(f"Confidential upload authorized for {current_user.role.value}: {current_user.email}")
    else:
        # Public bucket: any valid user can upload (with or without bot API key)
        logger.info(f"Public upload authorized for {current_user.role.value}: {current_user.email}")

    if bucket not in ["public", "confidential"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid bucket. Use 'public' or 'confidential'"
        )

    # Validate file
    if not file.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No filename provided")

    file_extension = get_file_extension(file.filename)
    if file_extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file type. Allowed: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    # Read file content
    content = await file.read()

    # Check file size
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File too large. Maximum size: {MAX_FILE_SIZE // (1024 * 1024)}MB",
        )

    # Validate magic bytes — reject files where content doesn't match declared extension
    if not validate_magic_bytes(file.filename, content):
        logger.warning(f"SECURITY: Magic byte mismatch for {file.filename} uploaded by {current_user.email}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File content does not match its extension. Upload rejected.",
        )

    # Step 1: Calculate file hash for deduplication
    file_hash = deduplication_service.calculate_hash(content)
    logger.info(f"Calculated hash for {file.filename}: {file_hash[:16]}...")

    # Step 2: Check for duplicates
    duplicate_doc = await deduplication_service.is_duplicate(
        file_hash=file_hash, filename=file.filename, size=len(content), db=db
    )

    if duplicate_doc:
        logger.info(f"Duplicate detected: {file.filename} matches document {duplicate_doc.id}")
        return DocumentUploadResponse(
            document_id=duplicate_doc.id,
            filename=duplicate_doc.filename,
            status=duplicate_doc.status,
            message="Document already exists (duplicate detected)",
        )

    # Step 3: Save file (only if not duplicate)
    save_result = storage_service.save_file(file_content=content, original_filename=file.filename, bucket=bucket)

    # Detect language from metadata or default
    language = DocumentLanguage.UNKNOWN

    # Create document record with PENDING status initially
    document = Document(
        filename=save_result["filename"],
        original_filename=file.filename,
        file_path=save_result["file_path"],
        bucket=DocumentBucket(bucket),
        status=DocumentStatus.PENDING,  # Set to PENDING until successfully queued
        size=save_result["size"],
        mime_type=get_mime_type(file.filename, content),
        language=language,
        uploaded_by=current_user.id,
    )

    db.add(document)
    await db.commit()
    await db.refresh(document)

    # Step 3b: Persist user-supplied tags (e.g. hashtags from Telegram caption)
    if tags:
        tag_names = [t.strip().lower() for t in tags.split(",") if t.strip()]
        for tag_name in tag_names:
            document_tag = DocumentTag(
                document_id=document.id,
                tag_name=tag_name,
                tag_type="user",
                auto_generated=False,
            )
            db.add(document_tag)
        if tag_names:
            await db.commit()
            logger.info(f"Added {len(tag_names)} user tag(s) to document {document.id}: {tag_names}")

    # Step 4: Register hash for future deduplication checks
    await deduplication_service.register_upload(
        file_hash=file_hash,
        filename=file.filename,
        size=len(content),
        document_id=str(document.id),
        db=db,
    )
    logger.info(f"Registered upload hash for document {document.id}")

    # Log confidential document upload
    if bucket == "confidential":
        await create_audit_log(
            db=db,
            user_id=current_user.id,
            action=AuditAction.CONFIDENTIAL_UPLOADED,
            resource_type="document",
            resource_id=str(document.id),
            details={"filename": document.filename, "original_filename": file.filename},
        )

    # Trigger async processing with proper state transitions
    try:
        from app.tasks.document_tasks import process_document

        task = process_document.delay(str(document.id))

        # Only set PROCESSING after successful queue
        document.status = DocumentStatus.PROCESSING
        document.document_metadata = document.document_metadata or {}
        document.document_metadata["celery_task_id"] = task.id
        await db.commit()

        logger.info(f"Document {document.id} queued successfully with task {task.id}")

        return DocumentUploadResponse(
            document_id=document.id,
            filename=document.filename,
            status=document.status,
            message="Document uploaded successfully and queued for processing",
        )

    except Exception as e:
        logger.error(f"Failed to queue document {document.id} for processing: {e}")

        # Set document status to ERROR on queue failure
        document.status = DocumentStatus.ERROR
        metadata = document.document_metadata or {}
        metadata["processing_error"] = f"Failed to queue for processing: {str(e)}"
        document.document_metadata = metadata
        await db.commit()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Document saved but failed to queue for processing: {str(e)}",
        )


class JournalEntryRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=10000)
    tags: list[str] = Field(default_factory=list)
    timestamp: str | None = None  # ISO format, defaults to now


@router.post("/journal", response_model=DocumentUploadResponse)
async def create_journal_entry(
    entry: JournalEntryRequest,
    x_bot_api_key: str | None = Header(None, alias="X-Bot-Api-Key"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentUploadResponse:
    """Create a text-only journal entry in the confidential bucket."""
    # Only admin/superuser can create journal entries (confidential bucket)
    if current_user.role.value not in ["admin", "superuser"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin or Super User role required for journal entries",
        )

    # Validate bot API key if provided
    if x_bot_api_key:
        if not BOT_API_KEY or x_bot_api_key != BOT_API_KEY:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Bot API Key")

    # Save text as a .txt file
    from datetime import datetime as dt

    timestamp = entry.timestamp or dt.utcnow().isoformat()
    content = entry.text.encode("utf-8")
    filename = f"journal_{dt.utcnow().strftime('%Y%m%d_%H%M%S')}.txt"

    save_result = storage_service.save_file(
        file_content=content, original_filename=filename, bucket="confidential"
    )

    document = Document(
        filename=save_result["filename"],
        original_filename=filename,
        file_path=save_result["file_path"],
        bucket=DocumentBucket.CONFIDENTIAL,
        status=DocumentStatus.PENDING,
        size=save_result["size"],
        mime_type="text/plain",
        language=DocumentLanguage.UNKNOWN,
        uploaded_by=current_user.id,
        document_metadata={
            "document_type": "journal",
            "journal_timestamp": timestamp,
            "journal_text": entry.text[:500],  # Preview in metadata
        },
    )

    db.add(document)
    await db.commit()
    await db.refresh(document)

    # Add user tags
    for tag_name in entry.tags:
        tag = DocumentTag(
            document_id=document.id,
            tag_name=tag_name.strip().lower(),
            tag_type="user",
            auto_generated=False,
        )
        db.add(tag)
    if entry.tags:
        await db.commit()

    # Log confidential upload
    await create_audit_log(
        db=db,
        user_id=current_user.id,
        action=AuditAction.CONFIDENTIAL_UPLOADED,
        resource_type="journal_entry",
        resource_id=str(document.id),
        details={"filename": filename, "type": "journal"},
    )

    # Trigger processing
    try:
        from app.tasks.document_tasks import process_document

        task = process_document.delay(str(document.id))
        document.status = DocumentStatus.PROCESSING
        document.document_metadata = {
            **document.document_metadata,
            "celery_task_id": task.id,
        }
        await db.commit()

        return DocumentUploadResponse(
            document_id=document.id,
            filename=document.filename,
            status=document.status,
            message="Journal entry created and queued for processing",
        )
    except Exception as e:
        logger.error(f"Failed to queue journal entry {document.id}: {e}")
        document.status = DocumentStatus.ERROR
        document.document_metadata = {
            **document.document_metadata,
            "processing_error": str(e),
        }
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Journal entry saved but processing failed: {str(e)}",
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
            logger.warning(f"SECURITY: Magic byte mismatch for {file.filename} in batch upload by {current_user.email}")
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

        save_result = storage_service.save_file(file_content=content, original_filename=file.filename, bucket=bucket)

        language = DocumentLanguage.UNKNOWN

        document = Document(
            filename=save_result["filename"],
            original_filename=file.filename,
            file_path=save_result["file_path"],
            bucket=DocumentBucket(bucket),
            status=DocumentStatus.PENDING,
            size=save_result["size"],
            mime_type=get_mime_type(file.filename, content),
            language=language,
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
                details={
                    "filename": document.filename,
                    "original_filename": file.filename,
                },
            )

        try:
            from app.tasks.document_tasks import process_document

            task = process_document.delay(str(document.id))
            document.status = DocumentStatus.PROCESSING
            document.document_metadata = document.document_metadata or {}
            document.document_metadata["celery_task_id"] = task.id
            await db.commit()
            logger.info(f"Document {document.id} queued successfully with task {task.id}")
        except Exception as e:
            logger.error(f"Failed to queue document {document.id} for processing: {e}")
            document.status = DocumentStatus.ERROR
            metadata = document.document_metadata or {}
            metadata["processing_error"] = f"Failed to queue for processing: {str(e)}"
            document.document_metadata = metadata
            await db.commit()

        return DocumentUploadResponse(
            document_id=document.id,
            filename=document.filename,
            status=document.status,
            message="Document uploaded successfully and queued for processing",
        ), None

    except Exception as e:
        logger.error(f"Error processing file {file.filename}: {str(e)}")
        return None, f"Error processing file {file.filename}: {str(e)}"


MAX_FILES_PER_BATCH = 20


@router.post("/upload-batch", response_model=BatchUploadResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_batch_documents(
    files: list[UploadFile] = File(...),
    bucket: str = Form("public"),
    x_bot_api_key: str | None = Header(None, alias="X-Bot-Api-Key"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BatchUploadResponse:
    """
    Upload multiple documents in a single request (batch upload)

    - **files**: List of files to upload (multipart form)
    - **bucket**: Either "public" or "confidential" (admin/superuser only)

    SECURITY: Total batch size limit is 500MB.
    - If total size exceeds 500MB, entire batch is rejected with HTTP 413
    - Individual file size limit remains 100MB per file
    - Role-based access control enforced for confidential bucket
    """
    logger.info(f"Batch upload attempt: user={current_user.email}, role={current_user.role.value}, bucket={bucket}")

    is_bot = False
    if x_bot_api_key:
        if not BOT_API_KEY:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bot API key not configured")
        if x_bot_api_key != BOT_API_KEY:
            logger.warning("Invalid Bot API Key")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Bot API Key")
        is_bot = True

    if bucket == "confidential":
        if current_user.role.value not in ["admin", "superuser"]:
            logger.warning(
                f"SECURITY: Blocked confidential batch upload by user {current_user.email} "
                f"(role: {current_user.role.value})"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: Admin or Super User role required for confidential bucket uploads",
            )
    else:
        logger.info(f"Public batch upload authorized for {current_user.role.value}: {current_user.email}")

    if bucket not in ["public", "confidential"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid bucket. Use 'public' or 'confidential'"
        )

    if not files:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No files provided")

    if len(files) > MAX_FILES_PER_BATCH:  # max 20 files per batch
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Too many files: maximum {MAX_FILES_PER_BATCH} files per batch upload",
        )

    total_size = 0
    file_sizes = {}

    for file in files:
        if file.filename:
            content = await file.read()
            file_sizes[file.filename] = len(content)
            total_size += len(content)
            await file.seek(0)

    logger.info(
        f"Batch upload: {len(files)} files, total size: {total_size} bytes ({total_size / (1024 * 1024):.2f}MB)"
    )

    if total_size > MAX_BATCH_SIZE:
        logger.warning(
            f"Batch upload rejected: total size {total_size} bytes ({total_size / (1024 * 1024):.2f}MB) "
            f"exceeds limit of {MAX_BATCH_SIZE} bytes ({MAX_BATCH_SIZE / (1024 * 1024)}MB)"
        )
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"Batch total size exceeds limit. "
                f"Received: {total_size / (1024 * 1024):.2f}MB, "
                f"Limit: {int(MAX_BATCH_SIZE / (1024 * 1024))}MB. "
                f"Please reduce the number or size of files in your batch."
            ),
        )

    successful_docs = []
    errors = []
    successful_count = 0
    failed_count = 0

    # Generate a unique batch ID that groups all uploads in this request
    batch_id = str(uuid.uuid4())

    for file in files:
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
    """
    Get processing status for all documents in a batch upload.

    Returns aggregate progress and per-document statuses.
    """
    result = await db.execute(
        select(Document).where(
            Document.batch_id == batch_id,
            Document.uploaded_by == current_user.id,
        )
    )
    documents = result.scalars().all()

    if not documents:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Batch not found")

    from collections import Counter

    status_counts: Counter = Counter(doc.status.value for doc in documents)
    total = len(documents)
    completed = status_counts.get("indexed", 0)
    progress = round(completed / total * 100, 1) if total else 0.0

    return {
        "batch_id": batch_id,
        "total_documents": total,
        "completed": completed,
        "processing": status_counts.get("processing", 0) + status_counts.get("pending", 0),
        "failed": status_counts.get("error", 0),
        "progress_percentage": progress,
        "documents": [
            {
                "id": str(doc.id),
                "filename": doc.filename,
                "status": doc.status.value,
            }
            for doc in documents
        ],
    }


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    bucket: str | None = Query(None),
    status: str | None = Query(None),
    search: str | None = Query(None),
    document_type: str | None = Query(None, description="Filter by document_type in metadata (e.g. 'journal')"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentListResponse:
    """
    List documents with pagination and filtering

    - Non-admin users only see public documents
    - Admin users see all documents unless bucket is specified
    """
    stmt = select(Document)

    # Apply bucket filter based on user role
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPERUSER]:
        # Non-admins and non-superusers only see public documents
        stmt = stmt.where(Document.bucket == DocumentBucket.PUBLIC)
    elif bucket:
        # Admin can filter by bucket
        if bucket in ["public", "confidential"]:
            stmt = stmt.where(Document.bucket == DocumentBucket(bucket))

    # Apply status filter
    if status:
        try:
            status_enum = DocumentStatus(status)
            stmt = stmt.where(Document.status == status_enum)
        except ValueError:
            pass

    # Apply search filter
    if search:
        stmt = stmt.where(Document.original_filename.ilike(f"%{search}%"))

    # Apply document_type metadata filter
    if document_type:
        stmt = stmt.where(
            Document.document_metadata["document_type"].astext == document_type
        )

    # Get total count
    count_result = await db.execute(select(func.count()).select_from(stmt.subquery()))
    total = count_result.scalar_one()

    # Apply pagination
    offset = (page - 1) * page_size
    result = await db.execute(stmt.order_by(Document.created_at.desc()).offset(offset).limit(page_size))
    documents = result.scalars().all()

    # Audit: log a summary entry when admin/superuser receives confidential documents
    if current_user.role in [UserRole.ADMIN, UserRole.SUPERUSER]:
        confidential_docs = [d for d in documents if d.bucket == DocumentBucket.CONFIDENTIAL]
        if confidential_docs:
            await create_audit_log(
                db=db,
                user_id=current_user.id,
                action=AuditAction.CONFIDENTIAL_ACCESSED,
                resource_type="document_list",
                resource_id=None,
                details={
                    "action": "list",
                    "confidential_count": len(confidential_docs),
                    "confidential_ids": [str(d.id) for d in confidential_docs],
                    "page": page,
                    "bucket_filter": bucket,
                },
            )

    return DocumentListResponse(
        documents=[DocumentResponse.model_validate(doc) for doc in documents],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentResponse:
    """
    Get a specific document by ID

    SECURITY: Returns 404 (not 403) for confidential documents accessed by
    regular users to prevent document enumeration.
    """
    db_result = await db.execute(select(Document).where(Document.id == document_id))
    document = db_result.scalar_one_or_none()

    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    # Check access permission - return 404 for confidential docs to prevent enumeration
    if document.bucket == DocumentBucket.CONFIDENTIAL and current_user.role not in [
        UserRole.ADMIN,
        UserRole.SUPERUSER,
    ]:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    # Log confidential document access
    if document.bucket == DocumentBucket.CONFIDENTIAL:
        await create_audit_log(
            db=db,
            user_id=current_user.id,
            action=AuditAction.CONFIDENTIAL_ACCESSED,
            resource_type="document",
            resource_id=str(document.id),
            details={"filename": document.filename, "action": "view"},
        )

    return DocumentResponse.model_validate(document)


@router.get("/{document_id}/status", response_model=DocumentStatusResponse)
async def get_document_status(
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentStatusResponse:
    """
    Get the processing status of a specific document.

    Returns status, error message and retry count from the processing queue.
    SECURITY: Returns 404 (not 403) for confidential documents to prevent enumeration.
    """
    from app.models.processing import ProcessingQueue

    db_result = await db.execute(select(Document).where(Document.id == document_id))
    document = db_result.scalar_one_or_none()

    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    # Confidential visibility: same rule as get_document
    if document.bucket == DocumentBucket.CONFIDENTIAL and current_user.role not in [
        UserRole.ADMIN,
        UserRole.SUPERUSER,
    ]:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    # Pull processing details from ProcessingQueue if available
    pq_result = await db.execute(select(ProcessingQueue).where(ProcessingQueue.document_id == document_id))
    processing_task = pq_result.scalar_one_or_none()

    error_message: str | None = None
    retry_count: int = 0
    processing_started_at = None

    if processing_task:
        error_message = processing_task.error_message
        retry_count = processing_task.retry_count or 0
        processing_started_at = processing_task.started_at

    # Also surface error stored directly in document metadata
    doc_meta = document.document_metadata or {}
    if not error_message and doc_meta.get("processing_error"):
        error_message = doc_meta["processing_error"]

    last_error_at = None
    if doc_meta.get("last_error_at"):
        try:
            last_error_at = datetime.fromisoformat(doc_meta["last_error_at"])
        except (ValueError, TypeError):
            pass

    return DocumentStatusResponse(
        document_id=document.id,
        status=document.status,
        error_message=error_message,
        retry_count=retry_count,
        processing_started_at=processing_started_at,
        last_error_at=last_error_at,
    )


@router.get("/{document_id}/download")
async def download_document(
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """
    Download a document file

    SECURITY: Returns 404 (not 403) for confidential documents accessed by
    regular users to prevent document enumeration.
    """
    db_result = await db.execute(select(Document).where(Document.id == document_id))
    document = db_result.scalar_one_or_none()

    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    # Check access permission - return 404 for confidential docs to prevent enumeration
    if document.bucket == DocumentBucket.CONFIDENTIAL and current_user.role not in [
        UserRole.ADMIN,
        UserRole.SUPERUSER,
    ]:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    # Log confidential document access
    if document.bucket == DocumentBucket.CONFIDENTIAL:
        await create_audit_log(
            db=db,
            user_id=current_user.id,
            action=AuditAction.CONFIDENTIAL_ACCESSED,
            resource_type="document",
            resource_id=str(document.id),
            details={"filename": document.filename, "action": "download"},
        )

    # Get file content
    file_content = storage_service.get_file(filename=document.filename, bucket=document.bucket.value)

    if not file_content:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")

    return Response(
        content=file_content,
        media_type=document.mime_type,
        headers={"Content-Disposition": f'attachment; filename="{document.original_filename}"'},
    )


@router.put("/{document_id}", response_model=DocumentResponse)
async def update_document(
    document_id: uuid.UUID,
    updates: DocumentUpdate,
    current_user: User = Depends(require_admin_only),
    db: AsyncSession = Depends(get_db),
) -> DocumentResponse:
    """
    Update document metadata (admin only)

    SECURITY: Admin-only operation. SuperUsers cannot modify documents.
    """
    db_result = await db.execute(select(Document).where(Document.id == document_id))
    document = db_result.scalar_one_or_none()

    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    # Update fields
    if updates.filename is not None:
        document.filename = updates.filename
    if updates.bucket is not None:
        document.bucket = DocumentBucket(updates.bucket)
    if updates.language is not None:
        document.language = DocumentLanguage(updates.language)

    await db.commit()
    await db.refresh(document)

    return DocumentResponse.model_validate(document)


@router.delete("/{document_id}")
async def delete_document(
    document_id: uuid.UUID,
    current_user: User = Depends(require_admin_only),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """
    Delete a document (admin only)

    SECURITY: Admin-only operation. SuperUsers cannot delete documents.
    """

    db_result = await db.execute(select(Document).where(Document.id == document_id))
    document = db_result.scalar_one_or_none()

    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    # Delete file from storage
    storage_service.delete_file(filename=document.filename, bucket=document.bucket.value)

    # Delete database record (cascade will handle tags, chunks, etc.)
    await db.delete(document)
    await db.commit()

    return {"message": "Document deleted successfully"}


@router.get("/{document_id}/similar")
async def get_similar_documents(
    document_id: uuid.UUID,
    limit: int = Query(default=6, ge=1, le=20),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Return documents similar to the given document, ranked by embedding cosine similarity.

    SECURITY:
    - Regular users only see results from the public bucket.
    - Admin/SuperUser see results across all buckets.
    - Returns 404 if the source document doesn't exist or is inaccessible.
    - Returns an empty list (not an error) when the document has no embeddings yet.
    """
    from app.services.similarity_service import similarity_service

    db_result = await db.execute(select(Document).where(Document.id == document_id))
    document = db_result.scalar_one_or_none()

    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    # Regular users cannot access confidential source documents
    if document.bucket == DocumentBucket.CONFIDENTIAL and current_user.role not in [
        UserRole.ADMIN,
        UserRole.SUPERUSER,
    ]:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    results = await similarity_service.find_similar_to_document(
        document_id=str(document_id),
        user=current_user,
        db=db,
        limit=limit,
    )

    return {"similar": results, "total": len(results)}


# ---------------------------------------------------------------------------
# Document Reprocessing
# ---------------------------------------------------------------------------


@router.post("/{document_id}/reprocess")
async def reprocess_document(
    document_id: uuid.UUID,
    force: bool = False,
    regenerate_embeddings: bool = True,
    reason: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Reprocess a document (e.g., after fixing errors or upgrading models).

    Args:
        document_id:           Document UUID.
        force:                 Allow reprocessing even if status=INDEXED.
        regenerate_embeddings: Whether to regenerate embeddings (default True).
        reason:                Optional reason string stored in metadata.

    Returns:
        {
            "document_id": str,
            "status": "PENDING",
            "task_id": str,
            "message": str
        }
    """
    from app.tasks.document_tasks import process_document
    from app.tasks.embedding_tasks import recompute_embeddings_for_document

    db_result = await db.execute(select(Document).where(Document.id == document_id))
    document = db_result.scalar_one_or_none()
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    # Confidential docs: only admin/superuser can trigger reprocessing
    if document.bucket == DocumentBucket.CONFIDENTIAL and current_user.role not in [
        UserRole.ADMIN,
        UserRole.SUPERUSER,
    ]:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    if document.status == DocumentStatus.INDEXED and not force:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Document already indexed. Pass force=true to reprocess.",
        )

    if document.status == DocumentStatus.PROCESSING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Document is currently being processed. Wait for it to finish.",
        )

    # Update document status and metadata
    document.status = DocumentStatus.PENDING
    meta = document.document_metadata or {}
    meta["reprocessed_at"] = datetime.utcnow().isoformat()
    meta["reprocess_reason"] = reason or "manual"
    meta["reprocess_by"] = str(current_user.id)
    document.document_metadata = meta
    await db.commit()

    # Queue appropriate task
    if regenerate_embeddings:
        task = recompute_embeddings_for_document.delay(str(document_id))
    else:
        task = process_document.delay(str(document_id), "full_pipeline")

    return {
        "document_id": str(document_id),
        "status": "pending",
        "task_id": task.id,
        "message": "Reprocessing queued successfully",
    }
