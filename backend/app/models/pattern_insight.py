"""Pattern / Insight model for Smart Folder v2.

Captures recurring behaviours, directional trends, documented issues,
and user-recorded learnings linked to entities.
"""

import enum
import uuid

from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, String, Text, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.models.base import Base, GUIDType, TimestampMixin


class PatternInsightType(enum.StrEnum):
    """Types of pattern / insight that can be recorded."""

    PATTERN = "pattern"  # Recurring behaviour or theme
    TREND = "trend"  # Directional change over time
    ISSUE = "issue"  # Documented problem or complaint
    LEARNING = "learning"  # User-written or auto-extracted takeaway


class PatternInsight(Base, TimestampMixin):
    """A pattern, trend, issue, or learning linked to an entity."""

    __tablename__ = "pattern_insights"
    __table_args__ = (
        Index("ix_pattern_insights_entity_id", "entity_id"),
        Index("ix_pattern_insights_type", "insight_type"),
        Index("ix_pattern_insights_entity_type", "entity_id", "insight_type"),
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

    insight_type = Column(
        Enum(PatternInsightType, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
        index=True,
    )

    description = Column(Text, nullable=False)

    # Source asset references (list of document IDs)
    linked_asset_ids = Column(JSONB, default=list)

    # Confidence in the insight (0-100)
    confidence = Column(Integer, default=50)

    # Temporal scope (optional)
    time_range_start = Column(DateTime(timezone=True), nullable=True)
    time_range_end = Column(DateTime(timezone=True), nullable=True)

    # Extraction metadata
    extracted_by = Column(
        String(50),
        nullable=True,
        default="manual",
    )  # "manual", "llm", "rule"

    # For numeric trends: optional structured data
    trend_data = Column(JSONB, default=dict)  # e.g., { "values": [...], "labels": [...] }

    # Relationships
    entity = relationship("Entity", back_populates="pattern_insights")

    def __repr__(self) -> str:
        return f"<PatternInsight {self.insight_type}: {self.description[:50]}...>"
