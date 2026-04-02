"""
Collection schemas for Smart Collections feature

These schemas define the API contract for creating, managing, and querying
Smart Collections - AI-generated document groups based on natural language.
"""

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


# Enums
class CollectionVisibility(StrEnum):
    PRIVATE = "private"
    SHARED = "shared"
    PUBLIC = "public"


class CollectionType(StrEnum):
    SMART = "smart"
    MANUAL = "manual"
    FOLDER = "folder"


# Intent Parsing Schemas
class ParsedIntentResponse(BaseModel):
    """Response from intent parsing"""

    query: str
    keywords: list[str] = []
    date_range: dict[str, Any] = {}
    entities: list[dict[str, str]] = []
    document_types: list[str] = []
    collection_name: str | None = None
    confidence: float = 0.0

    class Config:
        from_attributes = True


# Collection Schemas
class CollectionBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=512, description="Collection name")
    description: str | None = Field(None, description="Optional description")
    visibility: CollectionVisibility = Field(default=CollectionVisibility.PRIVATE)
    collection_type: CollectionType = Field(default=CollectionType.SMART)


class CollectionCreate(CollectionBase):
    query: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Natural language query to generate collection (up to 500 characters)",
    )
    save: bool = Field(default=True, description="Whether to save the collection")


class CollectionUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=512)
    description: str | None = None
    visibility: CollectionVisibility | None = None
    is_pinned: bool | None = None
    is_favorite: bool | None = None


class CollectionItemBase(BaseModel):
    document_id: UUID
    relevance_score: int = Field(default=50, ge=0, le=100)
    notes: str | None = None
    is_highlighted: bool = False


class CollectionItemCreate(CollectionItemBase):
    pass


class CollectionItemUpdate(BaseModel):
    relevance_score: int | None = Field(None, ge=0, le=100)
    notes: str | None = None
    is_highlighted: bool | None = None
    order_index: int | None = None


class CollectionItemResponse(BaseModel):
    id: UUID
    collection_id: UUID
    document_id: UUID
    relevance_score: int
    order_index: int
    notes: str | None = None
    is_highlighted: bool
    added_by: str | None = None
    added_reason: str | None = None
    created_at: datetime

    # Article info (set after ORM validation)
    article_id: str | None = None
    article_title: str | None = None
    article_summary: str | None = None

    # Include document summary (set after ORM validation)
    document: Any | None = None

    class Config:
        from_attributes = True


class CollectionResponse(BaseModel):
    id: UUID
    user_id: UUID
    name: str
    description: str | None = None
    collection_type: CollectionType
    visibility: CollectionVisibility
    query: str
    parsed_intent: dict[str, Any] | None = None
    ai_summary: str | None = None
    ai_keywords: list[str] | None = []
    ai_entities: list[Any] | None = []
    filter_criteria: dict[str, Any] | None = None
    document_count: int
    last_refreshed_at: str | None = None
    chat_session_id: UUID | None = None
    is_pinned: bool
    is_favorite: bool
    status: str = "ready"
    build_error: str | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CollectionDetailResponse(CollectionResponse):
    """Extended response with items"""

    items: list[CollectionItemResponse] = []


class CollectionListResponse(BaseModel):
    collections: list[CollectionResponse]
    total: int
    page: int
    page_size: int


class CollectionPreviewRequest(BaseModel):
    """Request to preview collection without saving"""

    query: str = Field(..., min_length=1, max_length=500, description="Natural language query (up to 500 characters)")


class CollectionPreviewResponse(BaseModel):
    """Preview of collection before saving"""

    intent: ParsedIntentResponse
    documents: list[dict[str, Any]] = []
    estimated_count: int = 0
    ai_summary: str | None = None
    suggested_name: str


# Collection Chat Schemas
class CollectionChatCreate(BaseModel):
    collection_id: UUID | None = None  # May be provided in path instead of body
    message: str = Field(..., min_length=1, description="User message")
    session_name: str | None = Field(None, description="Optional name for the Q&A session")


class CollectionChatResponse(BaseModel):
    session_id: UUID
    collection_id: UUID
    message_count: int
    llm_used: str
    response: str
    sources: list[dict[str, Any]] = []
    cache_hit: bool = False


# Bulk Operations
class CollectionBulkAddRequest(BaseModel):
    document_ids: list[UUID] = Field(..., min_length=1, description="List of document IDs to add")
    relevance_scores: list[int] | None = Field(None, description="Optional relevance scores for each document")


class CollectionBulkRemoveRequest(BaseModel):
    document_ids: list[UUID] = Field(..., min_length=1, description="List of document IDs to remove")


class CollectionRefreshRequest(BaseModel):
    """Request to refresh collection documents based on query"""

    include_new_documents: bool = True
    update_summary: bool = True


# Collection Statistics
class CollectionStatsResponse(BaseModel):
    total_collections: int
    pinned_collections: int
    favorite_collections: int
    total_documents_in_collections: int
    average_documents_per_collection: float
    collections_by_type: dict[str, int]
    recent_activity: list[dict[str, Any]]


# Smart Folder Generation
class SmartFolderGenerateRequest(BaseModel):
    topic: str = Field(..., min_length=1, description="Topic for smart folder")
    include_confidential: bool = Field(default=False, description="Include confidential documents (admin only)")
    style: str = Field(
        default="informative",
        description="Writing style: informative, creative, professional, casual",
    )
    length: str = Field(default="medium", description="Content length: short, medium, long")


class SmartFolderResponse(BaseModel):
    collection_id: UUID
    generated_content: str
    sources_used: list[dict[str, Any]]
    word_count: int
    llm_used: str


# Report Generation
class ReportFormat(StrEnum):
    SHORT = "short"
    STANDARD = "standard"
    COMPREHENSIVE = "comprehensive"


class CollectionReportRequest(BaseModel):
    collection_id: UUID
    format: ReportFormat = Field(default=ReportFormat.STANDARD)
    include_citations: bool = Field(default=True)
    language: str = Field(default="en", description="Report language: en or fr")


class CollectionReportResponse(BaseModel):
    report_id: UUID
    collection_id: UUID
    format: ReportFormat
    content: str
    citations: list[dict[str, Any]] = []
    generated_at: datetime
    file_url: str | None = None  # URL to download PDF report


class ExportFormat(StrEnum):
    PDF = "pdf"
    JSON = "json"


class CollectionExportResponse(BaseModel):
    """Response for collection export"""

    collection_id: UUID
    collection_name: str
    format: ExportFormat
    content: str | None = None
    file_url: str | None = None
    generated_at: datetime
    document_count: int
