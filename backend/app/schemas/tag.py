from datetime import datetime
from enum import StrEnum
from uuid import UUID
from pydantic import BaseModel, Field


class TagType(StrEnum):
    TOPIC = "topic"
    ENTITY = "entity"
    PROJECT = "project"
    IMPORTANCE = "importance"
    CUSTOM = "custom"


class TargetType(StrEnum):
    DOCUMENT = "document"
    BOOKMARK = "bookmark"
    NOTE = "note"
    SPACE = "space"


class TagCreate(BaseModel):
    tag_name: str = Field(..., min_length=1, max_length=255)
    tag_type: TagType = Field(default=TagType.CUSTOM)


class TagResponse(BaseModel):
    id: UUID
    tag_name: str
    tag_type: TagType
    target_type: TargetType
    target_id: UUID
    auto_generated: bool
    confidence_score: int | None
    created_at: datetime

    class Config:
        from_attributes = True


class TagListResponse(BaseModel):
    tags: list[TagResponse]
