import enum
import uuid

from sqlalchemy import Boolean, Column, DateTime, Enum, Index, Integer, String, func

from app.models.base import Base, GUIDType


class TagType(enum.StrEnum):
    TOPIC = "topic"
    ENTITY = "entity"
    PROJECT = "project"
    IMPORTANCE = "importance"
    CUSTOM = "custom"


class TargetType(enum.StrEnum):
    DOCUMENT = "document"
    BOOKMARK = "bookmark"
    NOTE = "note"
    SPACE = "space"


class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = (
        Index("ix_tags_target", "target_type", "target_id"),
        Index("ix_tags_name", "tag_name"),
        Index("ix_tags_type_name", "tag_type", "tag_name"),
        {"schema": "sowknow"},
    )

    id = Column(GUIDType(as_uuid=True), primary_key=True, default=uuid.uuid4, unique=True, nullable=False)
    tag_name = Column(String(255), nullable=False, index=True)
    tag_type = Column(
        Enum(TagType, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
        default=TagType.CUSTOM,
    )
    target_type = Column(
        Enum(TargetType, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
    )
    target_id = Column(GUIDType(as_uuid=True), nullable=False)
    auto_generated = Column(Boolean, default=False, nullable=False)
    confidence_score = Column(Integer, default=0, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
