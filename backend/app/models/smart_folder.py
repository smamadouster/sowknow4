"""Smart Folder v2 models.

A SmartFolder represents a saved natural-language query configuration.
A SmartFolderReport is a generated output (transient or persisted) that
answers the query with structured analysis, citations, and rich content.
"""

import enum
import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.models.base import Base, GUIDType, TimestampMixin


class SmartFolderStatus(enum.StrEnum):
    """Status of a smart folder generation pipeline."""

    DRAFT = "draft"
    GENERATING = "generating"
    READY = "ready"
    FAILED = "failed"


class RelationshipType(enum.StrEnum):
    """Detected relationship type for tone adaptation."""

    PERSONAL = "personal"
    PROFESSIONAL = "professional"
    INSTITUTIONAL = "institutional"
    PROJECT = "project"
    GENERAL = "general"


class SmartFolder(Base, TimestampMixin):
    """A saved Smart Folder query configuration.

    Stores the original natural-language request, resolved entity,
    relationship type, and any user-defined constraints.
    """

    __tablename__ = "smart_folders"
    __table_args__ = {"schema": "sowknow"}

    id = Column(
        GUIDType(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        unique=True,
        nullable=False,
    )
    user_id = Column(
        GUIDType(as_uuid=True),
        ForeignKey("sowknow.users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Display name (auto-generated or user-edited)
    name = Column(String(512), nullable=False, default="")

    # Original natural-language query
    query_text = Column(Text, nullable=False)

    # Resolved entity (optional — may be unresolved / multi-entity)
    entity_id = Column(
        GUIDType(as_uuid=True),
        ForeignKey("sowknow.entities.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Detected relationship type for tone adaptation
    relationship_type = Column(
        String(50),
        nullable=True,
    )

    # Temporal scope (optional)
    time_range_start = Column(DateTime(timezone=True), nullable=True)
    time_range_end = Column(DateTime(timezone=True), nullable=True)

    # Focus aspects extracted from query (e.g., ["financial", "legal"])
    focus_aspects = Column(JSONB, default=list)

    # Pipeline status
    status = Column(
        String(50),
        default=SmartFolderStatus.DRAFT.value,
        nullable=False,
        index=True,
    )

    # Error message if generation failed
    error_message = Column(Text, nullable=True)

    # Relationships
    user = relationship("User", back_populates="smart_folders")
    entity = relationship("Entity", back_populates="smart_folders")
    reports = relationship(
        "SmartFolderReport",
        back_populates="smart_folder",
        cascade="all, delete-orphan",
        order_by="SmartFolderReport.version.desc()",
    )

    def __repr__(self) -> str:
        return f"<SmartFolder {self.name} ({self.status})>"


class SmartFolderReport(Base, TimestampMixin):
    """A generated Smart Folder report.

    Stores the structured output, source asset references, citation index,
    and any refinement query that produced this version.
    """

    __tablename__ = "smart_folder_reports"
    __table_args__ = {"schema": "sowknow"}

    id = Column(
        GUIDType(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        unique=True,
        nullable=False,
    )
    smart_folder_id = Column(
        GUIDType(as_uuid=True),
        ForeignKey("sowknow.smart_folders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Structured generated content (JSON matching the PRD report schema)
    generated_content = Column(JSONB, nullable=False, default=dict)

    # Ordered list of source asset IDs used in the report
    source_asset_ids = Column(JSONB, default=list)

    # Citation index: { "1": { "asset_id": "...", "preview": "...", "cell_ref": "..." }, ... }
    citation_index = Column(JSONB, default=dict)

    # Version number (increments on each regeneration)
    version = Column(Integer, default=1, nullable=False)

    # If this report was produced by a refinement query, store it here
    refinement_query = Column(Text, nullable=True)

    # Which LLM / pipeline produced this report
    generator_version = Column(String(50), nullable=True)

    # Relationships
    smart_folder = relationship("SmartFolder", back_populates="reports")

    def __repr__(self) -> str:
        return f"<SmartFolderReport v{self.version} ({self.smart_folder_id})>"
