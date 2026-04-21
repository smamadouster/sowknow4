import enum
import uuid

from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, String, Text, func

from app.models.base import Base, GUIDType


class SpaceBucket(enum.StrEnum):
    PUBLIC = "public"
    CONFIDENTIAL = "confidential"


class SpaceItemType(enum.StrEnum):
    DOCUMENT = "document"
    BOOKMARK = "bookmark"
    NOTE = "note"


class SpaceRuleType(enum.StrEnum):
    TAG = "tag"
    KEYWORD = "keyword"


class Space(Base):
    __tablename__ = "spaces"
    __table_args__ = ({"schema": "sowknow"},)

    id = Column(GUIDType(as_uuid=True), primary_key=True, default=uuid.uuid4, unique=True, nullable=False)
    user_id = Column(GUIDType(as_uuid=True), ForeignKey("sowknow.users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(512), nullable=False)
    description = Column(Text, nullable=True)
    icon = Column(String(64), nullable=True)
    bucket = Column(
        Enum(SpaceBucket, values_callable=lambda obj: [e.value for e in obj]),
        default=SpaceBucket.PUBLIC,
        nullable=False,
    )
    is_pinned = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class SpaceItem(Base):
    __tablename__ = "space_items"
    __table_args__ = ({"schema": "sowknow"},)

    id = Column(GUIDType(as_uuid=True), primary_key=True, default=uuid.uuid4, unique=True, nullable=False)
    space_id = Column(GUIDType(as_uuid=True), ForeignKey("sowknow.spaces.id", ondelete="CASCADE"), nullable=False, index=True)
    item_type = Column(
        Enum(SpaceItemType, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
    )
    document_id = Column(GUIDType(as_uuid=True), ForeignKey("sowknow.documents.id", ondelete="CASCADE"), nullable=True)
    bookmark_id = Column(GUIDType(as_uuid=True), ForeignKey("sowknow.bookmarks.id", ondelete="CASCADE"), nullable=True)
    note_id = Column(GUIDType(as_uuid=True), ForeignKey("sowknow.notes.id", ondelete="CASCADE"), nullable=True)
    added_by = Column(String(16), nullable=False, default="user")
    added_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    note = Column(Text, nullable=True)
    is_excluded = Column(Boolean, default=False, nullable=False)


class SpaceRule(Base):
    __tablename__ = "space_rules"
    __table_args__ = ({"schema": "sowknow"},)

    id = Column(GUIDType(as_uuid=True), primary_key=True, default=uuid.uuid4, unique=True, nullable=False)
    space_id = Column(GUIDType(as_uuid=True), ForeignKey("sowknow.spaces.id", ondelete="CASCADE"), nullable=False, index=True)
    rule_type = Column(
        Enum(SpaceRuleType, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
    )
    rule_value = Column(String(512), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
