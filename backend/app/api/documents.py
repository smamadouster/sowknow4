"""
Document API endpoints for upload, list, get, update, and delete operations
"""
import os
import json
import logging
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query, Header, Request
from sqlalchemy.orm import Session
from typing import Optional, List
import uuid
import mimetypes
from datetime import datetime

logger = logging.getLogger(__name__)

from app.database import get_db
from app.models.user import User, UserRole
from app.models.document import Document, DocumentBucket, DocumentStatus, DocumentLanguage
from app.models.audit import AuditLog, AuditAction
from app.schemas.document import (
    DocumentCreate,
    DocumentResponse,
    DocumentListResponse,
    DocumentUploadResponse,
    DocumentUpdate,
)
from app.services.storage_service import storage_service
from app.api.deps import get_current_user, require_admin_only

router = APIRouter(prefix="/documents", tags=["documents"])

BOT_API_KEY = os.getenv("BOT_API_KEY", "")


def create_audit_log(
    db: Session,
    user_id: uuid.UUID,
    action: AuditAction,
    resource_type: str,
    resource_id: Optional[str] = None,
    details: Optional[dict] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None
):
    """Helper function to create audit log entries for document access"""
    try:
        audit_entry = AuditLog(
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=json.dumps(details) if details else None,
            ip_address=ip_address,
            user_agent=user_agent
        )
        db.add(audit_entry)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Audit logging failed: {str(e)}")

# Allowed file types and size limits
ALLOWED_EXTENSIONS = {
    ".pdf", ".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls",
    ".txt", ".md", ".json",
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".heic",
    ".mp4", ".avi", ".mov", ".mkv",
    ".epub"
}
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB


def get_file_extension(filename: str) -> str:
    """Get file extension from filename"""
    return "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def get_mime_type(filename: str) -> str:
    """Get MIME type for filename"""
    mime_type, _ = mimetypes.guess_type(filename)
    return mime_type or "application/octet-stream"


@router.post("/upload", response_model=DocumentUploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    bucket: str = Form("public"),
    title: Optional[str] = Form(None),
    x_bot_api_key: Optional[str] = Header(None, alias="X-Bot-Api-Key"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Upload a document to the specified bucket

    - **file**: The file to upload
    - **bucket**: Either "public" or "confidential" (admin/superuser only)
    - **title**: Optional title for the document

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
            raise HTTPException(status_code=401, detail="Bot API key not configured")
        if x_bot_api_key != BOT_API_KEY:
            logger.warning(f"Invalid Bot API Key. Received length: {len(x_bot_api_key)}, Expected length: {len(BOT_API_KEY)}")
            raise HTTPException(status_code=401, detail="Invalid Bot API Key")
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
                status_code=403,
                detail="Forbidden: Admin or Super User role required for confidential bucket uploads"
            )
        logger.info(f"Confidential upload authorized for {current_user.role.value}: {current_user.email}")
    else:
        # Public bucket: any valid user can upload (with or without bot API key)
        logger.info(f"Public upload authorized for {current_user.role.value}: {current_user.email}")

    if bucket not in ["public", "confidential"]:
        raise HTTPException(status_code=400, detail="Invalid bucket. Use 'public' or 'confidential'")

    # Validate file
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    file_extension = get_file_extension(file.filename)
    if file_extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"
        )

    # Read file content
    content = await file.read()

    # Check file size
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Maximum size: {MAX_FILE_SIZE // (1024*1024)}MB"
        )

    # Save file
    save_result = storage_service.save_file(
        file_content=content,
        original_filename=file.filename,
        bucket=bucket
    )

    # Detect language from metadata or default
    language = DocumentLanguage.UNKNOWN

    # Create document record
    document = Document(
        filename=save_result["filename"],
        original_filename=file.filename,
        file_path=save_result["file_path"],
        bucket=DocumentBucket(bucket),
        status=DocumentStatus.PROCESSING,
        size=save_result["size"],
        mime_type=get_mime_type(file.filename),
        language=language
    )

    db.add(document)
    db.commit()
    db.refresh(document)

    # Log confidential document upload
    if bucket == "confidential":
        create_audit_log(
            db=db,
            user_id=current_user.id,
            action=AuditAction.CONFIDENTIAL_UPLOADED,
            resource_type="document",
            resource_id=str(document.id),
            details={"filename": document.filename, "original_filename": file.filename}
        )

    # Trigger async processing
    try:
        from app.tasks.document_tasks import process_document
        process_document.delay(str(document.id))
    except Exception as e:
        logger.warning(f"Failed to queue document for processing: {e}")

    return DocumentUploadResponse(
        document_id=document.id,
        filename=document.filename,
        status=document.status,
        message="Document uploaded successfully and queued for processing"
    )


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    bucket: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List documents with pagination and filtering

    - Non-admin users only see public documents
    - Admin users see all documents unless bucket is specified
    """
    query = db.query(Document)

    # Apply bucket filter based on user role
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPERUSER]:
        # Non-admins and non-superusers only see public documents
        query = query.filter(Document.bucket == DocumentBucket.PUBLIC)
    elif bucket:
        # Admin can filter by bucket
        if bucket in ["public", "confidential"]:
            query = query.filter(Document.bucket == DocumentBucket(bucket))

    # Apply status filter
    if status:
        try:
            status_enum = DocumentStatus(status)
            query = query.filter(Document.status == status_enum)
        except ValueError:
            pass

    # Apply search filter
    if search:
        query = query.filter(Document.original_filename.ilike(f"%{search}%"))

    # Get total count
    total = query.count()

    # Apply pagination
    offset = (page - 1) * page_size
    documents = query.order_by(Document.created_at.desc()).offset(offset).limit(page_size).all()

    return DocumentListResponse(
        documents=[DocumentResponse.model_validate(doc) for doc in documents],
        total=total,
        page=page,
        page_size=page_size
    )


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get a specific document by ID

    SECURITY: Returns 404 (not 403) for confidential documents accessed by
    regular users to prevent document enumeration.
    """
    document = db.query(Document).filter(Document.id == document_id).first()

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    # Check access permission - return 404 for confidential docs to prevent enumeration
    if document.bucket == DocumentBucket.CONFIDENTIAL and current_user.role not in [UserRole.ADMIN, UserRole.SUPERUSER]:
        raise HTTPException(status_code=404, detail="Document not found")

    # Log confidential document access
    if document.bucket == DocumentBucket.CONFIDENTIAL:
        create_audit_log(
            db=db,
            user_id=current_user.id,
            action=AuditAction.CONFIDENTIAL_ACCESSED,
            resource_type="document",
            resource_id=str(document.id),
            details={"filename": document.filename, "action": "view"}
        )

    return DocumentResponse.model_validate(document)


@router.get("/{document_id}/download")
async def download_document(
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Download a document file

    SECURITY: Returns 404 (not 403) for confidential documents accessed by
    regular users to prevent document enumeration.
    """
    from fastapi.responses import Response

    document = db.query(Document).filter(Document.id == document_id).first()

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    # Check access permission - return 404 for confidential docs to prevent enumeration
    if document.bucket == DocumentBucket.CONFIDENTIAL and current_user.role not in [UserRole.ADMIN, UserRole.SUPERUSER]:
        raise HTTPException(status_code=404, detail="Document not found")

    # Log confidential document access
    if document.bucket == DocumentBucket.CONFIDENTIAL:
        create_audit_log(
            db=db,
            user_id=current_user.id,
            action=AuditAction.CONFIDENTIAL_ACCESSED,
            resource_type="document",
            resource_id=str(document.id),
            details={"filename": document.filename, "action": "download"}
        )

    # Get file content
    file_content = storage_service.get_file(
        filename=document.filename,
        bucket=document.bucket.value
    )

    if not file_content:
        raise HTTPException(status_code=404, detail="File not found")

    return Response(
        content=file_content,
        media_type=document.mime_type,
        headers={
            "Content-Disposition": f'attachment; filename="{document.original_filename}"'
        }
    )


@router.put("/{document_id}", response_model=DocumentResponse)
async def update_document(
    document_id: uuid.UUID,
    updates: DocumentUpdate,
    current_user: User = Depends(require_admin_only),
    db: Session = Depends(get_db)
):
    """
    Update document metadata (admin only)

    SECURITY: Admin-only operation. SuperUsers cannot modify documents.
    """
    document = db.query(Document).filter(Document.id == document_id).first()

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    # Update fields
    if updates.filename is not None:
        document.filename = updates.filename
    if updates.bucket is not None:
        document.bucket = DocumentBucket(updates.bucket)
    if updates.language is not None:
        document.language = DocumentLanguage(updates.language)

    db.commit()
    db.refresh(document)

    return DocumentResponse.model_validate(document)


@router.delete("/{document_id}")
async def delete_document(
    document_id: uuid.UUID,
    current_user: User = Depends(require_admin_only),
    db: Session = Depends(get_db)
):
    """
    Delete a document (admin only)

    SECURITY: Admin-only operation. SuperUsers cannot delete documents.
    """

    document = db.query(Document).filter(Document.id == document_id).first()

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    # Delete file from storage
    storage_service.delete_file(
        filename=document.filename,
        bucket=document.bucket.value
    )

    # Delete database record (cascade will handle tags, chunks, etc.)
    db.delete(document)
    db.commit()

    return {"message": "Document deleted successfully"}
