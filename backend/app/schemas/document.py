from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field


class DocumentBucket(StrEnum):
    PUBLIC = "public"
    CONFIDENTIAL = "confidential"


class DocumentStatus(StrEnum):
    PENDING = "pending"
    UPLOADING = "uploading"
    PROCESSING = "processing"
    INDEXED = "indexed"
    ERROR = "error"


class DocumentLanguage(StrEnum):
    FRENCH = "fr"
    ENGLISH = "en"
    MULTILINGUAL = "multi"
    UNKNOWN = "unknown"


# Document Schemas
class DocumentBase(BaseModel):
    filename: str
    original_filename: str
    bucket: DocumentBucket = DocumentBucket.PUBLIC


class DocumentCreate(DocumentBase):
    pass


class DocumentUpdate(BaseModel):
    filename: str | None = None
    bucket: DocumentBucket | None = None
    language: DocumentLanguage | None = None


class DocumentResponse(BaseModel):
    id: UUID
    filename: str
    original_filename: str
    file_path: str
    bucket: DocumentBucket
    status: DocumentStatus
    size: int = Field(..., alias="file_size")
    mime_type: str
    language: DocumentLanguage | None = None
    page_count: int | None = None
    ocr_processed: bool = False
    embedding_generated: bool = False
    chunk_count: int = 0
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
        populate_by_name = True


class DocumentListResponse(BaseModel):
    documents: list[DocumentResponse]
    total: int
    page: int
    page_size: int


# Document Tag Schemas
class DocumentTagCreate(BaseModel):
    tag_name: str
    tag_type: str | None = "topic"
    auto_generated: bool = False
    confidence_score: int | None = None


class DocumentTagResponse(BaseModel):
    id: UUID
    document_id: UUID
    tag_name: str
    tag_type: str | None = None
    auto_generated: bool = False
    confidence_score: int | None = None
    created_at: datetime

    class Config:
        from_attributes = True


# Upload Schemas
class DocumentUploadResponse(BaseModel):
    document_id: UUID
    filename: str
    status: DocumentStatus
    message: str = "Document uploaded successfully"


# Chunk Schemas
class DocumentChunkResponse(BaseModel):
    id: UUID
    document_id: UUID
    chunk_index: int
    chunk_text: str
    token_count: int | None = None
    page_number: int | None = None

    class Config:
        from_attributes = True


# Document Status Schema
class DocumentStatusResponse(BaseModel):
    document_id: UUID
    status: DocumentStatus
    error_message: str | None = None
    retry_count: int = 0
    processing_started_at: datetime | None = None
    last_error_at: datetime | None = None


# Batch Upload Schemas
class BatchUploadResponse(BaseModel):
    batch_id: str | None = None
    total_files: int
    successful: int
    failed: int
    documents: list[DocumentUploadResponse]
    errors: list[str]
    total_size_bytes: int
    batch_limit_exceeded: bool = False
    message: str = "Batch upload processed"


class BatchStatusResponse(BaseModel):
    """Response for GET /documents/batch/{batch_id}/status."""

    batch_id: str
    total_documents: int
    completed: int
    processing: int
    failed: int
    progress_percentage: float


class ReprocessRequest(BaseModel):
    """Request body for POST /documents/{document_id}/reprocess."""

    force: bool = False
    regenerate_embeddings: bool = True
    reason: str | None = None
