# Schemas initialization
from app.schemas.user import UserCreate, UserPublic, UserInDB, UserRole
from app.schemas.token import Token, TokenPayload

# Document schemas - check if they exist first
try:
    from app.schemas.document import (
        DocumentCreate,
        DocumentUpdate,
        DocumentResponse,
        DocumentListResponse,
        DocumentUploadResponse,
        DocumentTagCreate,
        DocumentTagResponse,
        DocumentChunkResponse,
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
        ChatSessionCreate,
        ChatSessionResponse,
        ChatSessionListResponse,
        ChatMessageCreate,
        ChatMessageResponse,
        ChatMessageListResponse,
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
        SystemStats,
        QueueStats,
        AnomalyDocument,
        AnomalyBucketResponse,
        DashboardResponse,
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

__all__ = [
    "UserCreate",
    "UserPublic",
    "UserInDB",
    "UserRole",
    "Token",
    "TokenPayload",
    *_document_schemas,
    *_chat_schemas,
    *_search_schemas,
    *_admin_schemas,
]
