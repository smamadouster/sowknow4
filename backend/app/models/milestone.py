"""Milestone model for Smart Folder v2.

A Milestone is a significant dated event linked to one or more entities
(e.g., "Opened account with Bank A – 15 Mar 2010").
"""

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.models.base import Base, GUIDType, TimestampMixin


class Milestone(Base, TimestampMixin):
    """A significant dated event linked to an entity and source assets."""

    __tablename__ = "milestones"
    __table_args__ = (
        Index("ix_milestones_entity_id", "entity_id"),
        Index("ix_milestones_date", "date"),
        Index("ix_milestones_entity_date", "entity_id", "date"),
        {"schema": "sowknow"},
    )

    id = Column(
        GUIDType(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        unique=True,
        nullable=False,
    )
    entity_id = Column(
        GUIDType(as_uuid=True),
        ForeignKey("sowknow.entities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # The milestone date (may be approximate)
    date = Column(DateTime(timezone=True), nullable=True, index=True)
    date_precision = Column(
        String(20),
        nullable=True,
        default="exact",
    )  # "exact", "approximate", "quarter", "year"

    # Content
    title = Column(String(512), nullable=False)
    description = Column(Text, nullable=True)

    # Source asset references (list of document IDs)
    linked_asset_ids = Column(JSONB, default=list)

    # Importance score (0-100)
    importance = Column(Integer, default=50)

    # Extraction metadata
    extracted_by = Column(
        String(50),
        nullable=True,
        default="manual",
    )  # "manual", "llm", "rule"
    confidence = Column(Integer, default=100)  # 0-100

    # Relationships
    entity = relationship("Entity", back_populates="milestones")

    def __repr__(self) -> str:
        return f"<Milestone {self.title} ({self.date})>"
