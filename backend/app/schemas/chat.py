from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime
from typing import Optional, List
from enum import Enum


class LLMProvider(str, Enum):
    KIMI = "kimi"
    OLLAMA = "ollama"


class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


# Chat Session Schemas
class ChatSessionCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=512)
    document_scope: Optional[List[UUID]] = None
    model_preference: Optional[str] = None


class ChatSessionResponse(BaseModel):
    id: UUID
    user_id: UUID
    title: str
    document_scope: List[UUID] = []
    model_preference: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ChatSessionListResponse(BaseModel):
    sessions: List[ChatSessionResponse]
    total: int


# Chat Message Schemas
class SourceDocument(BaseModel):
    document_id: UUID
    document_name: str
    chunk_id: UUID
    chunk_text: str
    relevance_score: float


class ChatMessageCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=10000)


class ChatMessageResponse(BaseModel):
    id: UUID
    session_id: UUID
    role: MessageRole
    content: str
    llm_used: Optional[LLMProvider] = None
    sources: Optional[List[SourceDocument]] = None
    confidence_score: Optional[int] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ChatMessageListResponse(BaseModel):
    messages: List[ChatMessageResponse]
    total: int


# Stream Response Schema
class ChatStreamChunk(BaseModel):
    type: str  # "token", "source", "error", "done"
    content: Optional[str] = None
    sources: Optional[List[SourceDocument]] = None
    llm_used: Optional[LLMProvider] = None
    error: Optional[str] = None
