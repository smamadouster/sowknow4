"""Smart Folder v2 Pydantic schemas.

Defines the API contract for Smart Folder generation, retrieval,
refinement, and persistence.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.smart_folder import RelationshipType, SmartFolderStatus


# ---------------------------------------------------------------------------
# Smart Folder schemas
# ---------------------------------------------------------------------------

class SmartFolderBase(BaseModel):
    """Base fields for a Smart Folder."""

    name: str = Field(..., min_length=1, max_length=512)
    query_text: str = Field(..., min_length=1, description="Natural language query")
    entity_id: UUID | None = Field(None, description="Resolved entity ID")
    relationship_type: RelationshipType | None = Field(
        None, description="Detected relationship type"
    )
    time_range_start: datetime | None = Field(None)
    time_range_end: datetime | None = Field(None)
    focus_aspects: list[str] = Field(default_factory=list)


class SmartFolderCreate(SmartFolderBase):
    """Request to create a new Smart Folder."""

    pass


class SmartFolderUpdate(BaseModel):
    """Request to update a Smart Folder."""

    name: str | None = Field(None, min_length=1, max_length=512)
    query_text: str | None = Field(None, min_length=1)
    entity_id: UUID | None = None
    relationship_type: RelationshipType | None = None
    time_range_start: datetime | None = None
    time_range_end: datetime | None = None
    focus_aspects: list[str] | None = None
    status: SmartFolderStatus | None = None


class SmartFolderResponse(SmartFolderBase):
    """Response shape for a Smart Folder."""

    id: UUID
    user_id: UUID
    status: SmartFolderStatus
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class SmartFolderListResponse(BaseModel):
    """Paginated list of Smart Folders."""

    items: list[SmartFolderResponse]
    total: int
    page: int
    page_size: int


# ---------------------------------------------------------------------------
# Smart Folder Report schemas
# ---------------------------------------------------------------------------

class CitationEntry(BaseModel):
    """A single citation mapping [N] → source asset."""

    asset_id: UUID
    preview: str
    cell_ref: str | None = None  # For spreadsheet/PDF cell-level citations
    page_number: int | None = None


class ReportSection(BaseModel):
    """A section within the generated report."""

    section_type: str  # "title", "summary", "timeline", "patterns", "issues", "learnings", "recommendations"
    title: str
    content: str | list[dict[str, Any]] | None = None
    markdown: str | None = None


class GeneratedContent(BaseModel):
    """Structured generated report content."""

    title: str
    summary: str
    timeline: list[dict[str, Any]] = Field(default_factory=list)
    patterns: list[str] = Field(default_factory=list)
    trends: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    learnings: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    sections: list[ReportSection] = Field(default_factory=list)


class SmartFolderReportResponse(BaseModel):
    """Response shape for a generated Smart Folder report."""

    id: UUID
    smart_folder_id: UUID
    generated_content: GeneratedContent | dict[str, Any]
    source_asset_ids: list[UUID]
    citation_index: dict[str, CitationEntry]
    version: int
    refinement_query: str | None = None
    generator_version: str | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Request / Action schemas
# ---------------------------------------------------------------------------

class SmartFolderGenerateRequest(BaseModel):
    """Request to generate a new Smart Folder report."""

    query: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Natural language request, e.g. 'Tell me about my relationship with Bank A'",
    )
    include_confidential: bool = Field(
        default=False, description="Include confidential documents (admin only)"
    )


class SmartFolderRefineRequest(BaseModel):
    """Request to refine an existing Smart Folder report."""

    refinement_query: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Follow-up constraint, e.g. 'Only show disputes from 2020-2023'",
    )


class SmartFolderSaveRequest(BaseModel):
    """Request to save a Smart Folder as a permanent Note."""

    name: str | None = Field(None, description="Override the auto-generated name")


class GenerationStatusResponse(BaseModel):
    """Polling response for async generation tasks."""

    task_id: str
    status: str  # "pending", "retrieving", "analysing", "generating", "completed", "failed"
    progress_percent: int = 0
    message: str | None = None
    smart_folder_id: UUID | None = None
    report_id: UUID | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Milestone schemas
# ---------------------------------------------------------------------------

class MilestoneBase(BaseModel):
    """Base fields for a Milestone."""

    entity_id: UUID
    date: datetime | None = None
    date_precision: str = "exact"
    title: str = Field(..., min_length=1, max_length=512)
    description: str | None = None
    linked_asset_ids: list[UUID] = Field(default_factory=list)
    importance: int = Field(default=50, ge=0, le=100)
    extracted_by: str = "manual"
    confidence: int = Field(default=100, ge=0, le=100)


class MilestoneCreate(MilestoneBase):
    pass


class MilestoneResponse(MilestoneBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Pattern / Insight schemas
# ---------------------------------------------------------------------------

class PatternInsightBase(BaseModel):
    """Base fields for a Pattern / Insight."""

    entity_id: UUID
    insight_type: str  # "pattern", "trend", "issue", "learning"
    description: str = Field(..., min_length=1)
    linked_asset_ids: list[UUID] = Field(default_factory=list)
    confidence: int = Field(default=50, ge=0, le=100)
    time_range_start: datetime | None = None
    time_range_end: datetime | None = None
    extracted_by: str = "manual"
    trend_data: dict[str, Any] = Field(default_factory=dict)


class PatternInsightCreate(PatternInsightBase):
    pass


class PatternInsightResponse(PatternInsightBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
