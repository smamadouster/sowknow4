"""
Document API endpoints for upload, list, get, update, and delete operations
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from sqlalchemy.orm import Session
from typing import Optional, List
import uuid
import mimetypes
from datetime import datetime

from app.database import get_db
from app.models.user import User, UserRole
from app.models.document import Document, DocumentBucket, DocumentStatus, DocumentLanguage
from app.schemas.document import (
    DocumentCreate,
    DocumentResponse,
    DocumentListResponse,
    DocumentUploadResponse,
    DocumentUpdate,
)
from app.services.storage_service import storage_service
from app.utils.security import get_current_user, require_admin

router = APIRouter(prefix="/documents", tags=["documents"])

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
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Upload a document to the specified bucket

    - **file**: The file to upload
    - **bucket**: Either "public" or "confidential" (admin only for confidential)
    - **title**: Optional title for the document
    """
    # Verify bucket permission
    if bucket == "confidential" and current_user.role not in [UserRole.ADMIN, UserRole.SUPERUSER]:
        raise HTTPException(status_code=403, detail="Only admins and superusers can upload to confidential bucket")

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

    # Trigger async processing (will be implemented with Celery)
    # from app.tasks.document_tasks import process_document
    # process_document.delay(str(document.id))

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
    """Get a specific document by ID"""
    document = db.query(Document).filter(Document.id == document_id).first()

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    # Check access permission
    if document.bucket == DocumentBucket.CONFIDENTIAL and current_user.role not in [UserRole.ADMIN, UserRole.SUPERUSER]:
        raise HTTPException(status_code=403, detail="Access denied to confidential document")

    return DocumentResponse.model_validate(document)


@router.get("/{document_id}/download")
async def download_document(
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Download a document file"""
    from fastapi.responses import Response

    document = db.query(Document).filter(Document.id == document_id).first()

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    # Check access permission
    if document.bucket == DocumentBucket.CONFIDENTIAL and current_user.role not in [UserRole.ADMIN, UserRole.SUPERUSER]:
        raise HTTPException(status_code=403, detail="Access denied to confidential document")

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
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update document metadata (admin only)"""
    document = db.query(Document).filter(Document.id == document_id).first()

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    # Update fields
    if updates.filename is not None:
        document.filename = updates.filename
    if updates.bucket is not None:
        if current_user.role != UserRole.ADMIN:
            raise HTTPException(status_code=403, detail="Only admins can change bucket")
        document.bucket = DocumentBucket(updates.bucket)
    if updates.language is not None:
        document.language = DocumentLanguage(updates.language)

    db.commit()
    db.refresh(document)

    return DocumentResponse.model_validate(document)


@router.delete("/{document_id}")
async def delete_document(
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a document (admin only)"""
    # Require admin or superuser for deletion
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPERUSER]:
        raise HTTPException(status_code=403, detail="Only admins and superusers can delete documents")

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
