from datetime import datetime
from enum import StrEnum
from uuid import UUID
from pydantic import BaseModel, Field

from app.schemas.tag import TagCreate, TagResponse


class NoteBucket(StrEnum):
    PUBLIC = "public"
    CONFIDENTIAL = "confidential"


class NoteCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=512)
    content: str | None = Field(None)
    bucket: NoteBucket = Field(default=NoteBucket.PUBLIC)
    tags: list[TagCreate] = Field(default_factory=list)


class NoteUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=512)
    content: str | None = None
    bucket: NoteBucket | None = None
    tags: list[TagCreate] | None = None


class NoteResponse(BaseModel):
    id: UUID
    user_id: UUID
    title: str
    content: str | None
    bucket: NoteBucket
    tags: list[TagResponse] = []
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class NoteListResponse(BaseModel):
    notes: list[NoteResponse]
    total: int
    page: int
    page_size: int
