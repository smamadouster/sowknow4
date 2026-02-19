"""
Collection models for Smart Collections feature

Users can create collections from natural language queries that gather
related documents. Collections support AI summaries, follow-up Q&A, and
can be saved for later reference.
"""
import uuid
import enum
from sqlalchemy import Column, String, Integer, Boolean, ForeignKey, Text, JSON, Index, event, Enum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from app.models.base import Base, TimestampMixin, GUIDType


class CollectionVisibility(str, enum.Enum):
    """Collection visibility settings"""
    PRIVATE = "private"           # Only owner can see
    SHARED = "shared"             # Owner + SuperUsers can see
    PUBLIC = "public"             # Everyone can see (with role restrictions)


class CollectionType(str, enum.Enum):
    """Types of collections"""
    SMART = "smart"               # AI-generated from natural language query
    MANUAL = "manual"             # Manually curated by user
    FOLDER = "folder"             # Smart Folder with generated content


class Collection(Base, TimestampMixin):
    """
    Smart Collection model for organizing documents based on natural language queries

    A collection represents a set of documents gathered by a query, with optional
    AI-generated summary and metadata. Collections support follow-up Q&A sessions.
    """
    __tablename__ = "collections"
    __table_args__ = {"schema": "sowknow"}

    id = Column(GUIDType(as_uuid=True), primary_key=True, default=uuid.uuid4, unique=True, nullable=False)

    # Owner
    user_id = Column(GUIDType(as_uuid=True), ForeignKey("sowknow.users.id", ondelete="CASCADE"), nullable=False, index=True)

    # Basic info
    name = Column(String(512), nullable=False, index=True)
    description = Column(Text)  # Optional description

    # Collection type and visibility
    collection_type = Column(Enum(CollectionType, values_callable=lambda obj: [e.value for e in obj]), default=CollectionType.SMART, nullable=False)
    visibility = Column(Enum(CollectionVisibility, values_callable=lambda obj: [e.value for e in obj]), default=CollectionVisibility.PRIVATE, nullable=False, index=True)

    # Query that generated this collection
    query = Column(Text, nullable=False)  # Original natural language query
    parsed_intent = Column(JSONB)  # Stored parsed intent for re-querying

    # AI-generated content
    ai_summary = Column(Text)  # AI-generated summary of the collection
    ai_keywords = Column(JSONB, default=list)  # Extracted keywords
    ai_entities = Column(JSONB, default=list)  # Extracted entities

    # Document filtering criteria (for re-gathering)
    filter_criteria = Column(JSONB, default=dict)  # Stored search filters

    # Statistics
    document_count = Column(Integer, default=0)  # Number of documents in collection
    last_refreshed_at = Column(String)  # ISO timestamp of last document refresh

    # Follow-up chat context
    chat_session_id = Column(GUIDType(as_uuid=True), ForeignKey("sowknow.chat_sessions.id", ondelete="SET NULL"))

    # Cache key for Gemini context caching (for cost optimization)
    cache_key = Column(String(256))

    # Pinned collections stay at top and get better cache treatment
    is_pinned = Column(Boolean, default=False, index=True)
    is_favorite = Column(Boolean, default=False, index=True)

    # Confidential flag for RBAC
    is_confidential = Column(Boolean, default=False, nullable=False, index=True)

    # Relationships
    user = relationship("User", back_populates="collections")
    chat_session = relationship("ChatSession")  # No back_populates - ChatSession doesn't reference Collection directly
    items = relationship("CollectionItem", back_populates="collection", cascade="all, delete-orphan")

    # Indexes
    __table_args__ = (
        Index("ix_collections_user_id", "user_id"),
        Index("ix_collections_visibility_pinned", "visibility", "is_pinned"),
        Index("ix_collections_created_at", "created_at"),
        Index("ix_collections_type", "collection_type"),
        {"schema": "sowknow"},
    )

    def __repr__(self):
        return f"<Collection {self.name} ({self.collection_type})>"


class CollectionItem(Base, TimestampMixin):
    """
    Individual documents within a collection

    Represents the relationship between a collection and a document,
    with optional metadata like relevance score and notes.
    """
    __tablename__ = "collection_items"
    __table_args__ = {"schema": "sowknow"}

    id = Column(GUIDType(as_uuid=True), primary_key=True, default=uuid.uuid4, unique=True, nullable=False)
    collection_id = Column(GUIDType(as_uuid=True), ForeignKey("sowknow.collections.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id = Column(GUIDType(as_uuid=True), ForeignKey("sowknow.documents.id", ondelete="CASCADE"), nullable=False, index=True)

    # Relevance and ordering
    relevance_score = Column(Integer, default=50)  # 0-100 relevance score
    order_index = Column(Integer, default=0)  # For custom ordering

    # User annotations
    notes = Column(Text)  # User notes on this document in context of collection
    is_highlighted = Column(Boolean, default=False)  # Highlighted by user

    # Metadata
    added_by = Column(String(256))  # "ai" or user email/ID
    added_reason = Column(Text)  # Why this doc was added (AI explanation)

    # Relationships
    collection = relationship("Collection", back_populates="items")
    document = relationship("Document")

    # Unique constraint to prevent duplicate items
    __table_args__ = (
        Index("ix_collection_items_collection_id", "collection_id"),
        Index("ix_collection_items_document_id", "document_id"),
        Index("ix_collection_items_relevance", "collection_id", "relevance_score"),
        {"schema": "sowknow"},
    )

    def __repr__(self):
        return f"<CollectionItem {self.collection_id}/{self.document_id}>"


class CollectionChatSession(Base, TimestampMixin):
    """
    Follow-up Q&A sessions scoped to a specific collection

    These sessions use context caching for cost efficiency and maintain
    conversation history within the collection's document context.
    """
    __tablename__ = "collection_chat_sessions"
    __table_args__ = {"schema": "sowknow"}

    id = Column(GUIDType(as_uuid=True), primary_key=True, default=uuid.uuid4, unique=True, nullable=False)
    collection_id = Column(GUIDType(as_uuid=True), ForeignKey("sowknow.collections.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(GUIDType(as_uuid=True), ForeignKey("sowknow.users.id", ondelete="CASCADE"), nullable=False, index=True)

    # Session metadata
    session_name = Column(String(512))  # Optional name for the Q&A session
    message_count = Column(Integer, default=0)

    # LLM usage tracking
    llm_used = Column(String(50))  # "gemini" or "ollama"
    total_tokens_used = Column(Integer, default=0)
    cache_hits = Column(Integer, default=0)

    # Relationships
    collection = relationship("Collection")
    user = relationship("User")

    __table_args__ = (
        Index("ix_collection_chat_sessions_collection_id", "collection_id"),
        Index("ix_collection_chat_sessions_user_id", "user_id"),
        {"schema": "sowknow"},
    )

    def __repr__(self):
        return f"<CollectionChatSession {self.collection_id}>"

# Set up defaults for test instances
@event.listens_for(Collection, 'init', propagate=True)
def _collection_init(target, args, kwargs):
    """Set default values for boolean fields when creating instances"""
    kwargs.setdefault('is_pinned', False)
    kwargs.setdefault('is_favorite', False)
    kwargs.setdefault('is_confidential', False)
    kwargs.setdefault('document_count', 0)
    kwargs.setdefault('ai_keywords', [])
    kwargs.setdefault('ai_entities', [])
    kwargs.setdefault('filter_criteria', {})
