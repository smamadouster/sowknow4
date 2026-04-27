# Import all models for Alembic autogenerate
from app.models.article import Article, ArticleStatus
from app.models.audit import AuditAction, AuditLog
from app.models.base import Base
from app.models.bookmark import Bookmark, BookmarkBucket  # noqa: F401
from app.models.chat import ChatMessage, ChatSession, LLMProvider, MessageRole
from app.models.collection import (
    Collection,
    CollectionChatSession,
    CollectionItem,
    CollectionType,
    CollectionVisibility,
)
from app.models.document import Document, DocumentChunk, DocumentTag
from app.models.failed_task import FailedCeleryTask
from app.models.knowledge_graph import (
    Entity,
    EntityMention,
    EntityRelationship,
    EntityType,
    RelationType,
    TimelineEvent,
)
from app.models.milestone import Milestone
from app.models.pattern_insight import PatternInsight, PatternInsightType
from app.models.smart_folder import (
    RelationshipType,
    SmartFolder,
    SmartFolderReport,
    SmartFolderStatus,
)
from app.models.note import Note, NoteBucket  # noqa: F401
from app.models.note_audio import NoteAudio  # noqa: F401
from app.models.pipeline import PipelineStage, StageEnum, StageStatus
from app.models.processing import ProcessingQueue, TaskStatus, TaskType
from app.models.space import Space, SpaceBucket, SpaceItem, SpaceItemType, SpaceRule, SpaceRuleType  # noqa: F401
from app.models.tag import Tag, TagType, TargetType  # noqa: F401
from app.models.user import User

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
    "Milestone",
    "PatternInsight",
    "PatternInsightType",
    "SmartFolder",
    "SmartFolderReport",
    "SmartFolderStatus",
    "RelationshipType",
    "AuditLog",
    "AuditAction",
    "FailedCeleryTask",
    "Article",
    "ArticleStatus",
    "Tag",
    "TagType",
    "TargetType",
    "Bookmark",
    "BookmarkBucket",
    "Note",
    "NoteBucket",
    "NoteAudio",
    "Space",
    "SpaceBucket",
    "SpaceItem",
    "SpaceItemType",
    "SpaceRule",
    "SpaceRuleType",
    "PipelineStage",
    "StageEnum",
    "StageStatus",
]
