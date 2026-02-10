# Import all models for Alembic autogenerate
from app.models.base import Base
from app.models.user import User
from app.models.document import Document, DocumentTag, DocumentChunk
from app.models.chat import ChatSession, ChatMessage, LLMProvider, MessageRole
from app.models.processing import ProcessingQueue, TaskType, TaskStatus

__all__ = [
    "Base",
    "User",
    "Document",
    "DocumentTag",
    "DocumentChunk",
    "ChatSession",
    "ChatMessage",
    "LLMProvider",
    "MessageRole",
    "ProcessingQueue",
    "TaskType",
    "TaskStatus",
]
