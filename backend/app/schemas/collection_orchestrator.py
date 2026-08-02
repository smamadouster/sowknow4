"""Collection Orchestrator Pydantic schemas.

Defines the API contract for the Collection Orchestrator: request creation,
clarification answers, confirmation, and response shapes mirroring the
ORM models.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class CollectionRequestCreate(BaseModel):
    """Request to create a new collection job."""

    query: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Natural language collection request",
    )
    idempotency_key: str | None = Field(
        None,
        max_length=255,
        description="Client-supplied key to dedupe repeated submissions",
    )


class ClarificationAnswer(BaseModel):
    """Answers to a clarification round (or an explicit skip)."""

    answers: dict[str, Any] | list[Any] = Field(default_factory=dict)
    skip: bool = False


class ConfirmRequest(BaseModel):
    """Confirm the clarified parameters and start the collection job."""

    pass


# ---------------------------------------------------------------------------
# Endpoint response schemas (collection-requests router)
# ---------------------------------------------------------------------------

class ClarificationPayload(BaseModel):
    """The clarification round returned after creation / an answer."""

    questions: list[dict[str, Any]] = Field(default_factory=list)
    round: int = 1
    max_rounds: int = 3
    extracted: list[dict[str, Any]] = Field(default_factory=list)
    intent: str | None = None


class CollectionRequestCreated(BaseModel):
    """Response for POST /collection-requests (202)."""

    request_id: UUID
    clarification: ClarificationPayload


class ClarificationStepResponse(BaseModel):
    """Response for POST /collection-requests/{id}/clarify."""

    ready_to_confirm: bool = False
    questions: list[dict[str, Any]] = Field(default_factory=list)
    round: int = 1
    max_rounds: int = 3
    confirmation: dict[str, Any] | None = None


class ConfirmEnqueueResponse(BaseModel):
    """Response for POST /collection-requests/{id}/confirm (202)."""

    request_id: UUID
    task_id: str


class CollectionJobStatusResponse(BaseModel):
    """Response for GET /collection-requests/{id}/status."""

    request_id: UUID
    job_state: str | None = None
    checkpoint: dict[str, Any] | None = None
    error_message: str | None = None
    deliverable_id: UUID | None = None


# ---------------------------------------------------------------------------
# Response schemas (ORM-backed)
# ---------------------------------------------------------------------------

class CollectionRequestStatus(BaseModel):
    """Status of a collection job (backed by the SmartFolder row)."""

    id: UUID
    query_text: str
    job_state: str | None = None
    idempotency_key: str | None = None
    checkpoint: dict[str, Any] | None = None
    confirmed_params: dict[str, Any] | None = None
    celery_task_id: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ClarificationStateResponse(BaseModel):
    """Current state of a clarification session."""

    id: UUID
    request_id: UUID
    rounds: list[dict[str, Any]] = Field(default_factory=list)
    extracted_entities: list[dict[str, Any]] = Field(default_factory=list)
    extracted_intent: str | None = None
    analysis_types: list[dict[str, Any]] = Field(default_factory=list)
    open_ambiguities: list[dict[str, Any]] = Field(default_factory=list)
    assumptions: list[dict[str, Any]] = Field(default_factory=list)
    status: str = "active"
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SourceItemResponse(BaseModel):
    """A retrieved source item."""

    id: UUID
    request_id: UUID
    execution_id: UUID | None = None
    document_id: UUID | None = None
    uri: str | None = None
    title: str | None = None
    item_type: str | None = None
    source: str | None = None
    author: str | None = None
    item_date: datetime | None = None
    relevance_score: float | None = None
    snippet: str | None = None
    acl_stamp: str | None = None
    content_hash: str | None = None
    canonical_id: UUID | None = None
    rank_position: int | None = None
    status: str = "ok"
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AnnotationResponse(BaseModel):
    """An annotation extracted from a source item."""

    id: UUID
    item_id: UUID
    annotation_text: str | None = None
    evidence_offsets: list[dict[str, Any]] = Field(default_factory=list)
    category_tags: list[str] = Field(default_factory=list)
    rank_position: int | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DeliverableResponse(BaseModel):
    """A versioned deliverable for a collection request."""

    id: UUID
    request_id: UUID
    version: int = 1
    summary_md: str | None = None
    item_list_ref: str | None = None
    appendix: dict[str, Any] | None = None
    exports: list[dict[str, Any]] = Field(default_factory=list)
    disclosures: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AuditEventResponse(BaseModel):
    """An append-only audit event for a collection job."""

    id: UUID
    request_id: UUID
    timestamp: datetime
    user_id: UUID | None = None
    stage: str | None = None
    action: str | None = None
    input_ref: str | None = None
    output_ref: str | None = None
    component_version: str | None = None
    duration_ms: int | None = None
    status: str | None = None
    detail: dict[str, Any] | None = None

    model_config = ConfigDict(from_attributes=True)
