from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.tag import TagResponse


class SpaceBucket(StrEnum):
    PUBLIC = "public"
    CONFIDENTIAL = "confidential"


class SpaceItemType(StrEnum):
    DOCUMENT = "document"
    BOOKMARK = "bookmark"
    NOTE = "note"


class SpaceRuleType(StrEnum):
    TAG = "tag"
    KEYWORD = "keyword"


# --- Space ---

class SpaceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=512)
    description: str | None = None
    icon: str | None = Field(None, max_length=64)
    bucket: SpaceBucket = Field(default=SpaceBucket.PUBLIC)


class SpaceUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=512)
    description: str | None = None
    icon: str | None = None
    bucket: SpaceBucket | None = None
    is_pinned: bool | None = None


class SpaceItemResponse(BaseModel):
    id: UUID
    space_id: UUID
    item_type: SpaceItemType
    document_id: UUID | None
    bookmark_id: UUID | None
    note_id: UUID | None
    added_by: str
    added_at: datetime
    note: str | None
    is_excluded: bool
    # Denormalized item info for display
    item_title: str | None = None
    item_url: str | None = None
    item_tags: list[TagResponse] = []

    class Config:
        from_attributes = True


class SpaceRuleResponse(BaseModel):
    id: UUID
    space_id: UUID
    rule_type: SpaceRuleType
    rule_value: str
    is_active: bool
    match_count: int = 0
    created_at: datetime

    class Config:
        from_attributes = True


class SpaceResponse(BaseModel):
    id: UUID
    user_id: UUID
    name: str
    description: str | None
    icon: str | None
    bucket: SpaceBucket
    is_pinned: bool
    item_count: int = 0
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class SpaceDetailResponse(SpaceResponse):
    items: list[SpaceItemResponse] = []
    rules: list[SpaceRuleResponse] = []


class SpaceListResponse(BaseModel):
    spaces: list[SpaceResponse]
    total: int
    page: int
    page_size: int


# --- SpaceItem ---

class SpaceItemAdd(BaseModel):
    item_type: SpaceItemType
    item_id: UUID
    note: str | None = None


# --- SpaceRule ---

class SpaceRuleCreate(BaseModel):
    rule_type: SpaceRuleType
    rule_value: str = Field(..., min_length=1, max_length=512)


class SpaceRuleUpdate(BaseModel):
    rule_value: str | None = Field(None, min_length=1, max_length=512)
    is_active: bool | None = None
