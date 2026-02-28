# Schemas initialization
from app.schemas.token import Token, TokenPayload
from app.schemas.user import UserCreate, UserInDB, UserPublic, UserRole

# Document schemas - check if they exist first
try:
    from app.schemas.document import (
        DocumentChunkResponse,
        DocumentCreate,
        DocumentListResponse,
        DocumentResponse,
        DocumentTagCreate,
        DocumentTagResponse,
        DocumentUpdate,
        DocumentUploadResponse,
    )

    _document_schemas = [
        "DocumentCreate",
        "DocumentUpdate",
        "DocumentResponse",
        "DocumentListResponse",
        "DocumentUploadResponse",
        "DocumentTagCreate",
        "DocumentTagResponse",
        "DocumentChunkResponse",
    ]
except ImportError:
    _document_schemas = []

# Chat schemas - check if they exist
try:
    from app.schemas.chat import (
        ChatMessageCreate,
        ChatMessageListResponse,
        ChatMessageResponse,
        ChatSessionCreate,
        ChatSessionListResponse,
        ChatSessionResponse,
        ChatStreamChunk,
        LLMProvider,
        MessageRole,
    )

    _chat_schemas = [
        "ChatSessionCreate",
        "ChatSessionResponse",
        "ChatSessionListResponse",
        "ChatMessageCreate",
        "ChatMessageResponse",
        "ChatMessageListResponse",
        "ChatStreamChunk",
        "LLMProvider",
        "MessageRole",
    ]
except ImportError:
    _chat_schemas = []

# Search schemas - check if they exist
try:
    from app.schemas.search import SearchRequest, SearchResponse, SearchResultChunk

    _search_schemas = ["SearchRequest", "SearchResponse", "SearchResultChunk"]
except ImportError:
    _search_schemas = []

# Admin schemas - check if they exist
try:
    from app.schemas.admin import (
        AnomalyBucketResponse,
        AnomalyDocument,
        DashboardResponse,
        QueueStats,
        SystemStats,
    )

    _admin_schemas = [
        "SystemStats",
        "QueueStats",
        "AnomalyDocument",
        "AnomalyBucketResponse",
        "DashboardResponse",
    ]
except ImportError:
    _admin_schemas = []

# Collection schemas - check if they exist
try:
    from app.schemas.collection import (
        CollectionBulkAddRequest,
        CollectionBulkRemoveRequest,
        CollectionChatCreate,
        CollectionChatResponse,
        CollectionCreate,
        CollectionDetailResponse,
        CollectionItemCreate,
        CollectionItemResponse,
        CollectionItemUpdate,
        CollectionListResponse,
        CollectionPreviewRequest,
        CollectionPreviewResponse,
        CollectionRefreshRequest,
        CollectionReportRequest,
        CollectionReportResponse,
        CollectionResponse,
        CollectionStatsResponse,
        CollectionType,
        CollectionUpdate,
        CollectionVisibility,
        ParsedIntentResponse,
        ReportFormat,
        SmartFolderGenerateRequest,
        SmartFolderResponse,
    )

    _collection_schemas = [
        "ParsedIntentResponse",
        "CollectionCreate",
        "CollectionUpdate",
        "CollectionResponse",
        "CollectionDetailResponse",
        "CollectionListResponse",
        "CollectionPreviewRequest",
        "CollectionPreviewResponse",
        "CollectionItemCreate",
        "CollectionItemUpdate",
        "CollectionItemResponse",
        "CollectionChatCreate",
        "CollectionChatResponse",
        "CollectionBulkAddRequest",
        "CollectionBulkRemoveRequest",
        "CollectionRefreshRequest",
        "CollectionStatsResponse",
        "SmartFolderGenerateRequest",
        "SmartFolderResponse",
        "ReportFormat",
        "CollectionReportRequest",
        "CollectionReportResponse",
        "CollectionVisibility",
        "CollectionType",
    ]
except ImportError:
    _collection_schemas = []

from app.schemas.pagination import (
    CursorPaginatedResponse,
    CursorPaginationParams,
    PaginatedResponse,
    PaginationParams,
    decode_cursor,
    encode_cursor,
)

__all__ = [
    "UserCreate",
    "UserPublic",
    "UserInDB",
    "UserRole",
    "Token",
    "TokenPayload",
    "PaginationParams",
    "PaginatedResponse",
    "CursorPaginationParams",
    "CursorPaginatedResponse",
    "encode_cursor",
    "decode_cursor",
    *_document_schemas,
    *_chat_schemas,
    *_search_schemas,
    *_admin_schemas,
    *_collection_schemas,
]
