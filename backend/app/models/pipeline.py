"""Pipeline stage tracking model for guaranteed document processing."""
import enum
import uuid

from sqlalchemy import Column, DateTime, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.sql import func

from app.models.base import Base, GUIDType, TimestampMixin


class StageEnum(enum.StrEnum):
    """Ordered pipeline stages. Every document follows this sequence."""
    UPLOADED = "uploaded"
    OCR = "ocr"
    CHUNKED = "chunked"
    EMBEDDED = "embedded"
    INDEXED = "indexed"
    ARTICLES = "articles"
    ENTITIES = "entities"
    ENRICHED = "enriched"

    def next_stage(self) -> "StageEnum | None":
        """Return the next stage in the pipeline, or None if terminal."""
        members = list(StageEnum)
        idx = members.index(self)
        if idx + 1 < len(members):
            return members[idx + 1]
        return None


class StageStatus(enum.StrEnum):
    """Status of a single pipeline stage."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


# Per-stage retry configuration
STAGE_RETRY_CONFIG = {
    StageEnum.OCR: {"max_attempts": 3, "backoff": [30, 60, 120], "soft_timeout": 300, "hard_timeout": 360},
    StageEnum.CHUNKED: {"max_attempts": 2, "backoff": [15, 30], "soft_timeout": 120, "hard_timeout": 180},
    StageEnum.EMBEDDED: {"max_attempts": 3, "backoff": [60, 120, 300], "soft_timeout": 1800, "hard_timeout": 1980},
    StageEnum.INDEXED: {"max_attempts": 2, "backoff": [15, 30], "soft_timeout": 120, "hard_timeout": 180},
    StageEnum.ARTICLES: {"max_attempts": 3, "backoff": [60, 120, 300], "soft_timeout": 600, "hard_timeout": 720},
    StageEnum.ENTITIES: {"max_attempts": 3, "backoff": [60, 120, 300], "soft_timeout": 600, "hard_timeout": 720},
}


class PipelineStage(Base, TimestampMixin):
    """Tracks individual stage completion for a document's processing pipeline."""
    __tablename__ = "pipeline_stages"
    __table_args__ = (
        Index("ix_pipeline_stages_doc_stage", "document_id", "stage", unique=True),
        Index("ix_pipeline_stages_status", "status"),
        Index("ix_pipeline_stages_stuck", "status", "started_at"),
        {"schema": "sowknow"},
    )

    id = Column(GUIDType(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False)
    document_id = Column(
        GUIDType(as_uuid=True),
        ForeignKey("sowknow.documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    stage = Column(
        Enum(StageEnum, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
    )
    status = Column(
        Enum(StageStatus, values_callable=lambda obj: [e.value for e in obj]),
        default=StageStatus.PENDING,
        nullable=False,
    )
    attempt = Column(Integer, default=0, nullable=False)
    max_attempts = Column(Integer, default=3, nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)
    worker_id = Column(String(255), nullable=True)

    def __init__(self, **kwargs):
        kwargs.setdefault("attempt", 0)
        kwargs.setdefault("max_attempts", 3)
        kwargs.setdefault("status", StageStatus.PENDING)
        super().__init__(**kwargs)

    def __repr__(self) -> str:
        return f"<PipelineStage {self.stage.name}:{self.status.name} doc={self.document_id}>"
