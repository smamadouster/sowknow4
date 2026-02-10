"""
Collection schemas for Smart Collections feature

These schemas define the API contract for creating, managing, and querying
Smart Collections - AI-generated document groups based on natural language.
"""
from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum


# Enums
class CollectionVisibility(str, Enum):
    PRIVATE = "private"
    SHARED = "shared"
    PUBLIC = "public"


class CollectionType(str, Enum):
    SMART = "smart"
    MANUAL = "manual"
    FOLDER = "folder"


# Intent Parsing Schemas
class ParsedIntentResponse(BaseModel):
    """Response from intent parsing"""
    query: str
    keywords: List[str] = []
    date_range: Dict[str, Any] = {}
    entities: List[Dict[str, str]] = []
    document_types: List[str] = []
    collection_name: Optional[str] = None
    confidence: float = 0.0

    class Config:
        from_attributes = True


# Collection Schemas
class CollectionBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=512, description="Collection name")
    description: Optional[str] = Field(None, description="Optional description")
    visibility: CollectionVisibility = Field(default=CollectionVisibility.PRIVATE)
    collection_type: CollectionType = Field(default=CollectionType.SMART)


class CollectionCreate(CollectionBase):
    query: str = Field(..., min_length=1, description="Natural language query to generate collection")
    save: bool = Field(default=True, description="Whether to save the collection")


class CollectionUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=512)
    description: Optional[str] = None
    visibility: Optional[CollectionVisibility] = None
    is_pinned: Optional[bool] = None
    is_favorite: Optional[bool] = None


class CollectionItemBase(BaseModel):
    document_id: UUID
    relevance_score: int = Field(default=50, ge=0, le=100)
    notes: Optional[str] = None
    is_highlighted: bool = False


class CollectionItemCreate(CollectionItemBase):
    pass


class CollectionItemUpdate(BaseModel):
    relevance_score: Optional[int] = Field(None, ge=0, le=100)
    notes: Optional[str] = None
    is_highlighted: Optional[bool] = None
    order_index: Optional[int] = None


class CollectionItemResponse(BaseModel):
    id: UUID
    collection_id: UUID
    document_id: UUID
    relevance_score: int
    order_index: int
    notes: Optional[str] = None
    is_highlighted: bool
    added_by: Optional[str] = None
    added_reason: Optional[str] = None
    created_at: datetime

    # Include document summary
    document: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True


class CollectionResponse(BaseModel):
    id: UUID
    user_id: UUID
    name: str
    description: Optional[str] = None
    collection_type: CollectionType
    visibility: CollectionVisibility
    query: str
    parsed_intent: Dict[str, Any] = {}
    ai_summary: Optional[str] = None
    ai_keywords: List[str] = []
    ai_entities: List[Dict[str, str]] = []
    filter_criteria: Dict[str, Any] = {}
    document_count: int
    last_refreshed_at: Optional[str] = None
    chat_session_id: Optional[UUID] = None
    is_pinned: bool
    is_favorite: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CollectionDetailResponse(CollectionResponse):
    """Extended response with items"""
    items: List[CollectionItemResponse] = []


class CollectionListResponse(BaseModel):
    collections: List[CollectionResponse]
    total: int
    page: int
    page_size: int


class CollectionPreviewRequest(BaseModel):
    """Request to preview collection without saving"""
    query: str = Field(..., min_length=1, description="Natural language query")


class CollectionPreviewResponse(BaseModel):
    """Preview of collection before saving"""
    intent: ParsedIntentResponse
    documents: List[Dict[str, Any]] = []
    estimated_count: int = 0
    ai_summary: Optional[str] = None
    suggested_name: str


# Collection Chat Schemas
class CollectionChatCreate(BaseModel):
    collection_id: UUID
    message: str = Field(..., min_length=1, description="User message")
    session_name: Optional[str] = Field(None, description="Optional name for the Q&A session")


class CollectionChatResponse(BaseModel):
    session_id: UUID
    collection_id: UUID
    message_count: int
    llm_used: str
    response: str
    sources: List[Dict[str, Any]] = []
    cache_hit: bool = False


# Bulk Operations
class CollectionBulkAddRequest(BaseModel):
    document_ids: List[UUID] = Field(..., min_length=1, description="List of document IDs to add")
    relevance_scores: Optional[List[int]] = Field(None, description="Optional relevance scores for each document")


class CollectionBulkRemoveRequest(BaseModel):
    document_ids: List[UUID] = Field(..., min_length=1, description="List of document IDs to remove")


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
    collections_by_type: Dict[str, int]
    recent_activity: List[Dict[str, Any]]


# Smart Folder Generation
class SmartFolderGenerateRequest(BaseModel):
    topic: str = Field(..., min_length=1, description="Topic for smart folder")
    include_confidential: bool = Field(default=False, description="Include confidential documents (admin only)")
    style: str = Field(default="informative", description="Writing style: informative, creative, professional, casual")
    length: str = Field(default="medium", description="Content length: short, medium, long")


class SmartFolderResponse(BaseModel):
    collection_id: UUID
    generated_content: str
    sources_used: List[Dict[str, Any]]
    word_count: int
    llm_used: str


# Report Generation
class ReportFormat(str, Enum):
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
    citations: List[Dict[str, Any]] = []
    generated_at: datetime
    file_url: Optional[str] = None  # URL to download PDF report
