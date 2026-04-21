from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.tag import TagCreate, TagResponse


class BookmarkBucket(StrEnum):
    PUBLIC = "public"
    CONFIDENTIAL = "confidential"


class BookmarkCreate(BaseModel):
    url: str = Field(..., min_length=1, max_length=2048)
    title: str | None = Field(None, max_length=512)
    description: str | None = Field(None)
    bucket: BookmarkBucket = Field(default=BookmarkBucket.PUBLIC)
    tags: list[TagCreate] = Field(..., min_length=1)


class BookmarkUpdate(BaseModel):
    title: str | None = Field(None, max_length=512)
    description: str | None = None
    bucket: BookmarkBucket | None = None
    tags: list[TagCreate] | None = None


class BookmarkResponse(BaseModel):
    id: UUID
    user_id: UUID
    url: str
    title: str
    description: str | None
    favicon_url: str | None
    bucket: BookmarkBucket
    tags: list[TagResponse] = []
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class BookmarkListResponse(BaseModel):
    bookmarks: list[BookmarkResponse]
    total: int
    page: int
    page_size: int
