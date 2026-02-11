# Import all models for Alembic autogenerate
from app.models.base import Base
from app.models.user import User
from app.models.document import Document, DocumentTag, DocumentChunk
from app.models.chat import ChatSession, ChatMessage, LLMProvider, MessageRole
from app.models.processing import ProcessingQueue, TaskType, TaskStatus
from app.models.collection import (
    Collection,
    CollectionItem,
    CollectionChatSession,
    CollectionVisibility,
    CollectionType
)
from app.models.knowledge_graph import (
    Entity,
    EntityRelationship,
    EntityMention,
    TimelineEvent,
    EntityType,
    RelationType
)
from app.models.audit import AuditLog, AuditAction

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
    "Collection",
    "CollectionItem",
    "CollectionChatSession",
    "CollectionVisibility",
    "CollectionType",
    "Entity",
    "EntityRelationship",
    "EntityMention",
    "TimelineEvent",
    "EntityType",
    "RelationType",
    "AuditLog",
    "AuditAction",
]
