import enum
import uuid

from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, String, Text, func

from app.models.base import Base, GUIDType


class TaskStatus(enum.StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TaskPriority(enum.StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TaskBucket(enum.StrEnum):
    PUBLIC = "public"
    CONFIDENTIAL = "confidential"


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = ({"schema": "sowknow"},)

    id = Column(GUIDType(as_uuid=True), primary_key=True, default=uuid.uuid4, unique=True, nullable=False)
    user_id = Column(GUIDType(as_uuid=True), ForeignKey("sowknow.users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(512), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(
        Enum(TaskStatus, values_callable=lambda obj: [e.value for e in obj]),
        default=TaskStatus.PENDING,
        nullable=False,
    )
    priority = Column(
        Enum(TaskPriority, values_callable=lambda obj: [e.value for e in obj]),
        default=TaskPriority.MEDIUM,
        nullable=False,
    )
    due_date = Column(DateTime(timezone=True), nullable=True)
    alarm_at = Column(DateTime(timezone=True), nullable=True)
    alarm_triggered = Column(Boolean, default=False, nullable=False)
    notes = Column(Text, nullable=True)
    bucket = Column(
        Enum(TaskBucket, values_callable=lambda obj: [e.value for e in obj]),
        default=TaskBucket.PUBLIC,
        nullable=False,
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
