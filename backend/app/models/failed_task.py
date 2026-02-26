"""
Dead Letter Queue model for permanently failed Celery tasks
"""

from sqlalchemy import Column, String, Integer, Text, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
import uuid

from app.models.base import Base, TimestampMixin, GUIDType


class FailedCeleryTask(Base, TimestampMixin):
    """
    Dead Letter Queue — stores tasks that failed after exhausting all retries.

    This table acts as an audit trail and forensic tool.  Admin staff can
    inspect failed tasks, understand root causes, and optionally replay them.
    """

    __tablename__ = "failed_celery_tasks"
    __table_args__ = {"schema": "sowknow"}

    id = Column(
        GUIDType(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    task_name = Column(String(256), nullable=False, index=True)
    task_id = Column(String(256), nullable=False, unique=True, index=True)
    # JSON-encoded args / kwargs kept as Text to handle arbitrary payloads
    args = Column(JSONB, nullable=True)
    kwargs = Column(JSONB, nullable=True)
    exception_type = Column(String(256), nullable=True)
    exception_message = Column(Text, nullable=True)
    traceback = Column(Text, nullable=True)
    retry_count = Column(Integer, nullable=False, default=0)
    # Extra context: document_id, user_id, etc.
    task_metadata = Column("metadata", JSONB, nullable=True, server_default="{}")
    failed_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
