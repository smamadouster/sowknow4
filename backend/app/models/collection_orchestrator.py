"""Collection Orchestrator models.

Data-model foundation for the Collection Orchestrator module: clarification
sessions, query executions, source items with dedup/ACL stamps, annotations,
factsets, analysis results, insights, deliverables, and an append-only audit
trail. All tables hang off ``sowknow.smart_folders`` (the collection request).
"""

import uuid

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.models.base import Base, GUIDType, TimestampMixin


class ClarificationSession(Base, TimestampMixin):
    """Clarification rounds for a collection request."""

    __tablename__ = "clarification_sessions"
    __table_args__ = {"schema": "sowknow"}

    id = Column(
        GUIDType(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        unique=True,
        nullable=False,
    )
    request_id = Column(
        GUIDType(as_uuid=True),
        ForeignKey("sowknow.smart_folders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Each round: {questions: [], answers: [], timestamp: ...}
    rounds = Column(JSONB, default=list)

    # Each entity: {name, type, canonical_id, confidence}
    extracted_entities = Column(JSONB, default=list)

    # Extracted user intent
    extracted_intent = Column(String(100), nullable=True)

    # Intent → analysis type mapping (FR1.8)
    analysis_types = Column(JSONB, default=list)

    open_ambiguities = Column(JSONB, default=list)
    assumptions = Column(JSONB, default=list)

    # active / completed / abandoned
    status = Column(String(30), default="active")

    # Relationships
    request = relationship("SmartFolder")

    def __repr__(self) -> str:
        return f"<ClarificationSession {self.id} ({self.status})>"


class QueryExecution(Base, TimestampMixin):
    """A single retrieval call executed for a collection request."""

    __tablename__ = "query_executions"
    __table_args__ = {"schema": "sowknow"}

    id = Column(
        GUIDType(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        unique=True,
        nullable=False,
    )
    request_id = Column(
        GUIDType(as_uuid=True),
        ForeignKey("sowknow.smart_folders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Payload sent to the search service
    search_call_payload = Column(JSONB)

    started_at = Column(DateTime(timezone=True))
    duration_ms = Column(Integer)
    result_count = Column(Integer)

    # running / completed / failed
    status = Column(String(30))

    # Relationships
    request = relationship("SmartFolder")

    def __repr__(self) -> str:
        return f"<QueryExecution {self.id} ({self.status})>"


class SourceItem(Base, TimestampMixin):
    """A retrieved source item for a collection request.

    Carries the ACL bucket stamped at retrieval time (FR7.3), content hash
    and simhash for dedup, and a loose canonical link for near-duplicates.
    """

    __tablename__ = "source_items"
    __table_args__ = {"schema": "sowknow"}

    id = Column(
        GUIDType(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        unique=True,
        nullable=False,
    )
    request_id = Column(
        GUIDType(as_uuid=True),
        ForeignKey("sowknow.smart_folders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    execution_id = Column(
        GUIDType(as_uuid=True),
        ForeignKey("sowknow.query_executions.id", ondelete="CASCADE"),
        nullable=True,
    )

    # Loose link to documents — intentionally no FK constraint
    document_id = Column(GUIDType(as_uuid=True), nullable=True)

    uri = Column(String(1024))
    title = Column(String(512))
    item_type = Column(String(100))
    source = Column(String(100))
    author = Column(String(255), nullable=True)
    item_date = Column(DateTime(timezone=True), nullable=True)
    relevance_score = Column(Float, nullable=True)
    snippet = Column(Text, nullable=True)

    # ACL bucket stamped at retrieval time (FR7.3)
    acl_stamp = Column(String(20))

    # Dedup
    content_hash = Column(String(64), index=True)
    simhash = Column(String(32), nullable=True)

    # Self-reference to the canonical representative for near-dupes
    # (loose link, no FK constraint)
    canonical_id = Column(GUIDType(as_uuid=True), nullable=True)

    rank_position = Column(Integer)

    # ok / content_unavailable / trimmed
    status = Column(String(30), default="ok")

    # Relationships
    request = relationship("SmartFolder")
    execution = relationship("QueryExecution")
    annotations = relationship(
        "Annotation",
        back_populates="item",
        cascade="all, delete-orphan",
        order_by="Annotation.rank_position",
    )

    def __repr__(self) -> str:
        return f"<SourceItem {self.id} ({self.title!r})>"


class Annotation(Base, TimestampMixin):
    """An annotation extracted from a source item."""

    __tablename__ = "annotations"
    __table_args__ = {"schema": "sowknow"}

    id = Column(
        GUIDType(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        unique=True,
        nullable=False,
    )
    item_id = Column(
        GUIDType(as_uuid=True),
        ForeignKey("sowknow.source_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    annotation_text = Column(Text)
    evidence_offsets = Column(JSONB, default=list)
    category_tags = Column(JSONB, default=list)
    rank_position = Column(Integer)

    # Relationships
    item = relationship("SourceItem", back_populates="annotations")

    def __repr__(self) -> str:
        return f"<Annotation {self.id} ({self.item_id})>"


class FactSet(Base, TimestampMixin):
    """A versioned set of extracted facts for a collection request."""

    __tablename__ = "factsets"
    __table_args__ = {"schema": "sowknow"}

    id = Column(
        GUIDType(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        unique=True,
        nullable=False,
    )
    request_id = Column(
        GUIDType(as_uuid=True),
        ForeignKey("sowknow.smart_folders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    version = Column(Integer, default=1)

    # Each fact: {name, value, unit, date, source_ref{document_id, chunk_id, page}, confidence, origin}
    facts = Column(JSONB, default=list)
    normalization_notes = Column(JSONB, default=list)

    # Relationships
    request = relationship("SmartFolder")
    analyses = relationship(
        "AnalysisResult",
        back_populates="factset",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<FactSet v{self.version} ({self.request_id})>"


class AnalysisResult(Base, TimestampMixin):
    """Result of a deterministic analysis run over a factset."""

    __tablename__ = "analysis_results"
    __table_args__ = {"schema": "sowknow"}

    id = Column(
        GUIDType(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        unique=True,
        nullable=False,
    )
    factset_id = Column(
        GUIDType(as_uuid=True),
        ForeignKey("sowknow.factsets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # trend / anomaly / comparison / correlation / descriptive
    analysis_type = Column(String(50))

    inputs = Column(JSONB)
    output = Column(JSONB)
    thresholds_used = Column(JSONB)
    provenance = Column(JSONB, default=list)
    code_version = Column(String(50))

    # Relationships
    factset = relationship("FactSet", back_populates="analyses")
    insights = relationship(
        "Insight",
        back_populates="analysis",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<AnalysisResult {self.analysis_type} ({self.factset_id})>"


class Insight(Base, TimestampMixin):
    """A validated (or pending) insight derived from an analysis result."""

    __tablename__ = "insights"
    __table_args__ = {"schema": "sowknow"}

    id = Column(
        GUIDType(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        unique=True,
        nullable=False,
    )
    analysis_id = Column(
        GUIDType(as_uuid=True),
        ForeignKey("sowknow.analysis_results.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    statement = Column(Text)
    source_refs = Column(JSONB, default=list)

    # pending / validated / rejected
    validation_status = Column(String(30), default="pending")

    # Relationships
    analysis = relationship("AnalysisResult", back_populates="insights")

    def __repr__(self) -> str:
        return f"<Insight {self.id} ({self.validation_status})>"


class Deliverable(Base, TimestampMixin):
    """A versioned deliverable (summary + exports) for a collection request."""

    __tablename__ = "deliverables"
    __table_args__ = {"schema": "sowknow"}

    id = Column(
        GUIDType(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        unique=True,
        nullable=False,
    )
    request_id = Column(
        GUIDType(as_uuid=True),
        ForeignKey("sowknow.smart_folders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    version = Column(Integer, default=1)
    summary_md = Column(Text)
    item_list_ref = Column(String(1024), nullable=True)
    appendix = Column(JSONB, nullable=True)
    exports = Column(JSONB, default=list)

    # Truncation / conflict / removed-claims disclosures
    disclosures = Column(JSONB, default=list)

    # Relationships
    request = relationship("SmartFolder")

    def __repr__(self) -> str:
        return f"<Deliverable v{self.version} ({self.request_id})>"


class CollectionAuditEvent(Base):
    """Append-only audit event for a collection job (spec §2.7).

    No update semantics: rows are inserted once and never mutated, so this
    table carries its own ``timestamp`` column instead of TimestampMixin.
    """

    __tablename__ = "collection_audit_events"
    __table_args__ = {"schema": "sowknow"}

    id = Column(
        GUIDType(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        unique=True,
        nullable=False,
    )
    request_id = Column(
        GUIDType(as_uuid=True),
        ForeignKey("sowknow.smart_folders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    timestamp = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    user_id = Column(GUIDType(as_uuid=True), nullable=True)

    # clarify / plan / retrieve / process / extract / analyse / summarise /
    # validate / package / export
    stage = Column(String(30))
    action = Column(String(100))

    input_ref = Column(String(1024), nullable=True)
    output_ref = Column(String(1024), nullable=True)
    component_version = Column(String(100), nullable=True)
    duration_ms = Column(Integer, nullable=True)
    status = Column(String(30))
    detail = Column(JSONB, nullable=True)

    # Relationships
    request = relationship("SmartFolder")

    def __repr__(self) -> str:
        return f"<CollectionAuditEvent {self.stage}/{self.action} ({self.status})>"
