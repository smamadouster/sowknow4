from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.tag import TagCreate, TagResponse


class TaskStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TaskPriority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TaskBucket(StrEnum):
    PUBLIC = "public"
    CONFIDENTIAL = "confidential"


class TaskCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=512)
    description: str | None = Field(None)
    status: TaskStatus = Field(default=TaskStatus.PENDING)
    priority: TaskPriority = Field(default=TaskPriority.MEDIUM)
    due_date: datetime | None = Field(None)
    alarm_at: datetime | None = Field(None)
    notes: str | None = Field(None)
    bucket: TaskBucket = Field(default=TaskBucket.PUBLIC)
    tags: list[TagCreate] = Field(default_factory=list)


class TaskUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=512)
    description: str | None = None
    status: TaskStatus | None = None
    priority: TaskPriority | None = None
    due_date: datetime | None = None
    alarm_at: datetime | None = None
    notes: str | None = None
    bucket: TaskBucket | None = None
    tags: list[TagCreate] | None = None


class TaskResponse(BaseModel):
    id: UUID
    user_id: UUID
    title: str
    description: str | None
    status: TaskStatus
    priority: TaskPriority
    due_date: datetime | None
    alarm_at: datetime | None
    alarm_triggered: bool
    notes: str | None
    bucket: TaskBucket
    tags: list[TagResponse] = []
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class TaskListResponse(BaseModel):
    tasks: list[TaskResponse]
    total: int
    page: int
    page_size: int
