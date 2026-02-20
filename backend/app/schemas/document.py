from pydantic import BaseModel, Field, model_validator
from uuid import UUID
from datetime import datetime
from typing import Optional, List, Any
from enum import Enum


class DocumentBucket(str, Enum):
    PUBLIC = "public"
    CONFIDENTIAL = "confidential"


class DocumentStatus(str, Enum):
    PENDING = "pending"
    UPLOADING = "uploading"
    PROCESSING = "processing"
    INDEXED = "indexed"
    ERROR = "error"


class DocumentLanguage(str, Enum):
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
    filename: Optional[str] = None
    bucket: Optional[DocumentBucket] = None
    language: Optional[DocumentLanguage] = None


class DocumentResponse(BaseModel):
    id: UUID
    filename: str
    original_filename: str
    file_path: str
    bucket: DocumentBucket
    status: DocumentStatus
    size: int = Field(..., alias="file_size")
    mime_type: str
    language: Optional[DocumentLanguage] = None
    page_count: Optional[int] = None
    ocr_processed: bool = False
    embedding_generated: bool = False
    chunk_count: int = 0
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
        populate_by_name = True


class DocumentListResponse(BaseModel):
    documents: List[DocumentResponse]
    total: int
    page: int
    page_size: int


# Document Tag Schemas
class DocumentTagCreate(BaseModel):
    tag_name: str
    tag_type: Optional[str] = "topic"
    auto_generated: bool = False
    confidence_score: Optional[int] = None


class DocumentTagResponse(BaseModel):
    id: UUID
    document_id: UUID
    tag_name: str
    tag_type: Optional[str] = None
    auto_generated: bool = False
    confidence_score: Optional[int] = None
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
    token_count: Optional[int] = None
    page_number: Optional[int] = None

    class Config:
        from_attributes = True
