"""
Knowledge Graph Models for Phase 3

Stores entities, relationships, and timelines extracted from documents
for graph-augmented retrieval and knowledge visualization.
"""
import uuid
import enum
from sqlalchemy import Column, String, Integer, Boolean, UUID, ForeignKey, Text, JSON, Index, Float, Date, Enum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from app.models.base import Base, TimestampMixin


class EntityType(str, enum.Enum):
    """Types of entities that can be extracted"""
    PERSON = "person"
    ORGANIZATION = "organization"
    LOCATION = "location"
    CONCEPT = "concept"
    EVENT = "event"
    DATE = "date"
    PRODUCT = "product"
    PROJECT = "project"
    OTHER = "other"


class RelationType(str, enum.Enum):
    """Types of relationships between entities"""
    WORKS_AT = "works_at"
    FOUNDED = "founded"
    CEO_OF = "ceo_of"
    EMPLOYEE_OF = "employee_of"
    CLIENT_OF = "client_of"
    PARTNER_OF = "partner_of"
    RELATED_TO = "related_to"
    MENTIONED_WITH = "mentioned_with"
    LOCATED_IN = "located_in"
    HAPPENED_ON = "happened_on"
    CREATED_ON = "created_on"
    REFERENCES = "references"
    PART_OF = "part_of"
    OWNED_BY = "owned_by"
    MEMBER_OF = "member_of"
    OTHER = "other"


class Entity(Base, TimestampMixin):
    """
    Extracted entity from documents

    Represents a person, organization, location, concept, etc.
    mentioned across documents.
    """
    __tablename__ = "entities"
    __table_args__ = {"schema": "sowknow"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, unique=True, nullable=False)

    # Entity identity
    name = Column(String(512), nullable=False, index=True)
    entity_type = Column(Enum(EntityType), nullable=False, index=True)
    canonical_id = Column(String(256), index=True)  # External ID (Wikidata, etc.)

    # Additional metadata
    aliases = Column(JSONB, default=list)  # Alternative names
    attributes = Column(JSONB, default=dict)  # Additional properties (birth_date, industry, etc.)
    confidence_score = Column(Integer, default=50)  # 0-100 confidence in extraction

    # Extraction metadata
    first_seen_at = Column(Date)
    last_seen_at = Column(Date)
    document_count = Column(Integer, default=0)  # Number of docs containing this entity
    relationship_count = Column(Integer, default=0)  # Number of relationships

    # Visualization data
    x_position = Column(Float)  # For graph visualization
    y_position = Column(Float)  # For graph visualization
    color = Column(String(7))  # Hex color for visualization

    # Relationships
    source_relationships = relationship("EntityRelationship", foreign_keys=[("source_id",)], back_populates="source_entity")
    target_relationships = relationship("EntityRelationship", foreign_keys=[("target_id",)], back_populates="target_entity")
    mentions = relationship("EntityMention", back_populates="entity")

    # Indexes
    __table_args__ = (
        Index("ix_entities_name", "name"),
        Index("ix_entities_type", "entity_type"),
        Index("ix_entities_name_type", "name", "entity_type"),
        {"schema": "sowknow"},
    )

    def __repr__(self):
        return f"<Entity {self.name} ({self.entity_type})>"


class EntityRelationship(Base, TimestampMixin):
    """
    Relationship between two entities

    Represents how entities are connected (e.g., person works at organization).
    """
    __tablename__ = "entity_relationships"
    __table_args__ = {"schema": "sowknow"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, unique=True, nullable=False)

    # Connected entities
    source_id = Column(UUID(as_uuid=True), ForeignKey("sowknow.entities.id", ondelete="CASCADE"), nullable=False, index=True)
    target_id = Column(UUID(as_uuid=True), ForeignKey("sowknow.entities.id", ondelete="CASCADE"), nullable=False, index=True)

    # Relationship type and properties
    relation_type = Column(Enum(RelationType), nullable=False, index=True)
    confidence_score = Column(Integer, default=50)  # 0-100
    attributes = Column(JSONB, default=dict)  # Additional properties (start_date, role, etc.)

    # Evidence
    document_count = Column(Integer, default=0)  # Number of docs supporting this relationship
    first_seen_at = Column(Date)
    last_seen_at = Column(Date)

    # Relationships
    source_entity = relationship("Entity", foreign_keys=[("source_id",)], back_populates="source_relationships")
    target_entity = relationship("Entity", foreign_keys=[("target_id",)], back_populates="target_relationships")

    # Indexes
    __table_args__ = (
        Index("ix_entity_relationships_source", "source_id"),
        Index("ix_entity_relationships_target", "target_id"),
        Index("ix_entity_relationships_type", "relation_type"),
        {"schema": "sowknow"},
    )

    def __repr__(self):
        return f"<EntityRelationship {self.source_id} -{self.relation_type}-> {self.target_id}>"


class EntityMention(Base, TimestampMixin):
    """
    Specific mention of an entity in a document

    Tracks where and how an entity appears in each document.
    """
    __tablename__ = "entity_mentions"
    __table_args__ = {"schema": "sowknow"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, unique=True, nullable=False)

    # References
    entity_id = Column(UUID(as_uuid=True), ForeignKey("sowknow.entities.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id = Column(UUID(as_uuid=True), ForeignKey("sowknow.documents.id", ondelete="CASCADE"), nullable=False, index=True)
    chunk_id = Column(UUID(as_uuid=True), ForeignKey("sowknow.document_chunks.id", ondelete="SET NULL"))

    # Mention details
    context_text = Column(Text)  # Surrounding text where entity was found
    page_number = Column(Integer)
    position_start = Column(Integer)  # Character position in text
    position_end = Column(Integer)
    confidence_score = Column(Integer, default=50)

    # Relationships
    entity = relationship("Entity", back_populates="mentions")

    # Indexes
    __table_args__ = (
        Index("ix_entity_mentions_entity", "entity_id"),
        Index("ix_entity_mentions_document", "document_id"),
        Index("ix_entity_mentions_entity_document", "entity_id", "document_id"),
        {"schema": "sowknow"},
    )

    def __repr__(self):
        return f"<EntityMention {self.entity_id} in {self.document_id}>"


class TimelineEvent(Base, TimestampMixin):
    """
    Timeline events for temporal reasoning

    Represents dated events extracted from documents for timeline
    visualization and evolution tracking.
    """
    __tablename__ = "timeline_events"
    __table_args__ = {"schema": "sowknow"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, unique=True, nullable=False)

    # Event identity
    title = Column(String(512), nullable=False)
    description = Column(Text)
    event_date = Column(Date, index=True)
    event_date_precision = Column(String(20))  # "exact", "approximate", "quarter", "year"

    # Related entities
    entity_ids = Column(JSONB, default=list)  # List of entity IDs involved

    # Source document
    document_id = Column(UUID(as_uuid=True), ForeignKey("sowknow.documents.id", ondelete="SET NULL"), index=True)

    # Classification
    event_type = Column(String(100))  # "founding", "merger", "appointment", "milestone", etc.
    importance = Column(Integer, default=50)  # 0-100

    # Visualization
    color = Column(String(7))

    # Indexes
    __table_args__ = (
        Index("ix_timeline_events_date", "event_date"),
        Index("ix_timeline_events_type", "event_type"),
        {"schema": "sowknow"},
    )

    def __repr__(self):
        return f"<TimelineEvent {self.title} ({self.event_date})>"
