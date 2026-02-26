"""
DeferredQuery SQLAlchemy model.

Used when Ollama is unavailable and a confidential query cannot be answered
immediately.  The query is persisted and retried once Ollama recovers.
"""

import enum
from datetime import datetime

from sqlalchemy import Column, Integer, Text, DateTime, Enum as SAEnum, JSON
from sqlalchemy.dialects.postgresql import UUID as PGUUID
import uuid

from app.models.base import Base


class QueryStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"


class DeferredQuery(Base):
    """
    A confidential query that could not be answered immediately because
    Ollama was unavailable.  The worker picks it up and processes it
    once the service recovers, or expires after 24 hours.
    """

    __tablename__ = "deferred_queries"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(PGUUID(as_uuid=True), nullable=False, index=True)
    session_id = Column(PGUUID(as_uuid=True), nullable=True, index=True)

    # Query content
    query_text = Column(Text, nullable=False)
    document_ids = Column(JSON, nullable=True)  # list[str] of referenced document UUIDs
    context_chunks = Column(JSON, nullable=True)  # retrieved chunks (serialised)
    system_prompt = Column(Text, nullable=True)

    # Processing state
    status = Column(
        SAEnum(QueryStatus, name="querystatus"),
        nullable=False,
        default=QueryStatus.PENDING,
        index=True,
    )
    retry_count = Column(Integer, nullable=False, default=0)
    max_retries = Column(Integer, nullable=False, default=3)

    # Result (populated on COMPLETED)
    response_text = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)

    # Timestamps — query expires and is cleaned up after 24 hours
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)  # created_at + timedelta(hours=24)

    def __repr__(self) -> str:
        return f"<DeferredQuery id={self.id} status={self.status} retries={self.retry_count}>"
