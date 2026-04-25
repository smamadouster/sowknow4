from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field


class LLMProvider(StrEnum):
    MINIMAX = "minimax"
    KIMI = "kimi"
    OLLAMA = "ollama"
    OPENROUTER = "openrouter"


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


# Chat Session Schemas
class ChatSessionCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=512)
    document_scope: list[UUID] | None = None
    model_preference: str | None = None


class ChatSessionResponse(BaseModel):
    id: UUID
    user_id: UUID
    title: str
    document_scope: list[UUID] = []
    model_preference: str | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ChatSessionListResponse(BaseModel):
    sessions: list[ChatSessionResponse]
    total: int


# Chat Message Schemas
class SourceDocument(BaseModel):
    document_id: UUID
    document_name: str
    chunk_id: UUID
    chunk_text: str | None = None
    relevance_score: float


class ChatMessageCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=10000)


class ChatMessageResponse(BaseModel):
    id: UUID
    session_id: UUID
    role: MessageRole
    content: str
    llm_used: LLMProvider | None = None
    sources: list[SourceDocument] | None = None
    confidence_score: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class ChatMessageListResponse(BaseModel):
    messages: list[ChatMessageResponse]
    total: int


# Stream Response Schema
class ChatStreamChunk(BaseModel):
    type: str  # "token", "source", "error", "done"
    content: str | None = None
    sources: list[SourceDocument] | None = None
    llm_used: LLMProvider | None = None
    error: str | None = None
