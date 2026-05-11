"""
Document API endpoints for list, get, update, delete, download, similar, and reprocess.

Upload and journal endpoints have been split into sub-routers:
  - documents_upload.py  → /upload, /upload-batch, /batch/{id}/status
  - documents_journal.py → /journal, /journal/voice
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin_only
from app.api.documents_common import create_audit_log
from app.api.documents_journal import router as journal_router
from app.api.documents_upload import router as upload_router
from app.database import get_db
from app.models.audit import AuditAction
from app.models.document import (
    Document,
    DocumentBucket,
    DocumentLanguage,
    DocumentStatus,
    DocumentTag,
)
from app.models.user import User, UserRole
from app.schemas.document import (
    DocumentListResponse,
    DocumentResponse,
    DocumentStatusResponse,
    DocumentUpdate,
)
from app.services.storage_service import storage_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])

# Include sub-routers for upload and journal endpoints
router.include_router(upload_router)
router.include_router(journal_router)


# ── CRUD Endpoints ──────────────────────────────────────────────────────────


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    bucket: str | None = Query(None),
    status: str | None = Query(None),
    search: str | None = Query(None),
    document_type: str | None = Query(None, description="Filter by document_type in metadata (e.g. 'journal')"),
    tag: str | None = Query(None, description="Filter by tag name"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentListResponse:
    """List documents with pagination and filtering."""
    stmt = select(Document)

    if current_user.role not in [UserRole.ADMIN, UserRole.SUPERUSER]:
        stmt = stmt.where(Document.bucket == DocumentBucket.PUBLIC)
    elif bucket:
        if bucket in ["public", "confidential"]:
            stmt = stmt.where(Document.bucket == DocumentBucket(bucket))

    if status:
        try:
            status_enum = DocumentStatus(status)
            stmt = stmt.where(Document.status == status_enum)
        except ValueError:
            pass

    if search:
        stmt = stmt.where(Document.original_filename.ilike(f"%{search}%"))

    if document_type:
        stmt = stmt.where(Document.document_metadata["document_type"].astext == document_type)

    if tag:
        stmt = stmt.where(
            Document.id.in_(select(DocumentTag.document_id).where(DocumentTag.tag_name == tag.strip().lower()))
        )

    count_result = await db.execute(select(func.count()).select_from(stmt.subquery()))
    total = count_result.scalar_one()

    offset = (page - 1) * page_size
    result = await db.execute(stmt.order_by(Document.created_at.desc()).offset(offset).limit(page_size))
    documents = result.scalars().all()

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
    """Get a specific document by ID."""
    db_result = await db.execute(select(Document).where(Document.id == document_id))
    document = db_result.scalar_one_or_none()

    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    if document.bucket == DocumentBucket.CONFIDENTIAL and current_user.role not in [
        UserRole.ADMIN,
        UserRole.SUPERUSER,
    ]:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

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
    """Get the processing status of a specific document."""
    from app.models.processing import ProcessingQueue

    db_result = await db.execute(select(Document).where(Document.id == document_id))
    document = db_result.scalar_one_or_none()

    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    if document.bucket == DocumentBucket.CONFIDENTIAL and current_user.role not in [
        UserRole.ADMIN,
        UserRole.SUPERUSER,
    ]:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    pq_result = await db.execute(select(ProcessingQueue).where(ProcessingQueue.document_id == document_id))
    processing_task = pq_result.scalar_one_or_none()

    error_message: str | None = None
    retry_count: int = 0
    processing_started_at = None

    if processing_task:
        error_message = processing_task.error_message
        retry_count = processing_task.retry_count or 0
        processing_started_at = processing_task.started_at

    doc_meta = document.document_metadata or {}
    if not error_message and doc_meta.get("processing_error"):
        error_message = doc_meta["processing_error"]

    if not error_message and document.pipeline_error:
        error_message = document.pipeline_error

    if not error_message:
        from app.models.pipeline import PipelineStage, StageStatus
        ps_result = await db.execute(
            select(PipelineStage)
            .where(
                PipelineStage.document_id == document_id,
                PipelineStage.status == StageStatus.FAILED,
            )
            .order_by(PipelineStage.updated_at.desc())
        )
        failed_stage = ps_result.scalars().first()
        if failed_stage and failed_stage.error_message:
            error_message = failed_stage.error_message

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
    """Download a document file."""
    db_result = await db.execute(select(Document).where(Document.id == document_id))
    document = db_result.scalar_one_or_none()

    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    if document.bucket == DocumentBucket.CONFIDENTIAL and current_user.role not in [
        UserRole.ADMIN,
        UserRole.SUPERUSER,
    ]:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    if document.bucket == DocumentBucket.CONFIDENTIAL:
        await create_audit_log(
            db=db,
            user_id=current_user.id,
            action=AuditAction.CONFIDENTIAL_ACCESSED,
            resource_type="document",
            resource_id=str(document.id),
            details={"filename": document.filename, "action": "download"},
        )

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
    """Update document metadata (admin only)."""
    db_result = await db.execute(select(Document).where(Document.id == document_id))
    document = db_result.scalar_one_or_none()

    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

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
    """Delete a document (admin only)."""
    db_result = await db.execute(select(Document).where(Document.id == document_id))
    document = db_result.scalar_one_or_none()

    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    storage_service.delete_file(filename=document.filename, bucket=document.bucket.value)
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
    """Return documents similar to the given document, ranked by embedding cosine similarity."""
    from app.services.similarity_service import similarity_service

    db_result = await db.execute(select(Document).where(Document.id == document_id))
    document = db_result.scalar_one_or_none()

    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

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


# ── Reprocessing ────────────────────────────────────────────────────────────


@router.post("/{document_id}/reprocess")
async def reprocess_document(
    document_id: uuid.UUID,
    force: bool = False,
    regenerate_embeddings: bool = True,
    reason: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Reprocess a document (e.g., after fixing errors or upgrading models)."""
    from app.tasks.document_tasks import process_document
    from app.tasks.embedding_tasks import recompute_embeddings_for_document

    db_result = await db.execute(select(Document).where(Document.id == document_id))
    document = db_result.scalar_one_or_none()
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

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

    # A document may be marked PROCESSING at the Document level while its
    # PipelineStage was reset to PENDING by the sweeper (e.g. after a worker
    # crash).  Allow reprocess when no stage is actually RUNNING.
    if document.status == DocumentStatus.PROCESSING:
        from app.models.pipeline import PipelineStage, StageStatus

        running_stage = await db.execute(
            select(PipelineStage).where(
                PipelineStage.document_id == document_id,
                PipelineStage.status == StageStatus.RUNNING,
            )
        )
        if running_stage.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Document is currently being processed. Wait for it to finish.",
            )

    document.status = DocumentStatus.PENDING
    document.pipeline_stage = "uploaded"
    meta = document.document_metadata or {}
    meta["reprocessed_at"] = datetime.utcnow().isoformat()
    meta["reprocess_reason"] = reason or "manual"
    meta["reprocess_by"] = str(current_user.id)
    document.document_metadata = meta
    await db.commit()

    if regenerate_embeddings:
        task = recompute_embeddings_for_document.delay(str(document_id))
        return {
            "document_id": str(document_id),
            "status": "pending",
            "task_id": task.id,
            "message": "Re-embedding queued successfully",
        }

    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    from app.tasks.pipeline_orchestrator import dispatch_document
    from app.tasks.pipeline_tasks import update_stage
    from app.models.pipeline import StageEnum, StageStatus

    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor(max_workers=1) as pool:
        # Reset pipeline tracking so the document starts fresh
        await loop.run_in_executor(
            pool, update_stage, str(document_id), StageEnum.UPLOADED, StageStatus.COMPLETED
        )
        dispatch_result = await loop.run_in_executor(pool, dispatch_document, str(document_id))

    if dispatch_result == "dispatched":
        document.status = DocumentStatus.PROCESSING
        document.pipeline_stage = "ocr"
    else:
        document.status = DocumentStatus.PENDING
        meta = document.document_metadata or {}
        meta["backpressure"] = dispatch_result
        document.document_metadata = meta
    await db.commit()

    return {
        "document_id": str(document_id),
        "status": document.status.value,
        "task_id": dispatch_result,
        "message": "Reprocessing queued successfully" if dispatch_result == "dispatched" else f"Pipeline backpressure: {dispatch_result}",
    }
