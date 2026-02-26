"""
Standardized pagination schemas (T05 + T09)

PaginationParams / PaginatedResponse for offset-based pagination.
CursorPaginationParams / CursorPaginatedResponse for cursor-based pagination.
"""
import base64
import json
from typing import Generic, List, Optional, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Offset-based pagination (T05)
# ---------------------------------------------------------------------------

class PaginationParams(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


class PaginatedResponse(BaseModel, Generic[T]):
    items: List[T]
    total: int
    page: int
    page_size: int
    has_more: bool

    @classmethod
    def create(
        cls,
        items: List[T],
        total: int,
        page: int,
        page_size: int,
    ) -> "PaginatedResponse[T]":
        return cls(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            has_more=(page * page_size) < total,
        )


# ---------------------------------------------------------------------------
# Cursor-based pagination (T09)
# ---------------------------------------------------------------------------

class CursorPaginationParams(BaseModel):
    cursor: Optional[str] = None
    limit: int = Field(default=20, ge=1, le=100)


class CursorPaginatedResponse(BaseModel, Generic[T]):
    items: List[T]
    next_cursor: Optional[str]
    has_more: bool


def encode_cursor(data: dict) -> str:
    """Encode a dict into a URL-safe base64 cursor string."""
    return base64.urlsafe_b64encode(json.dumps(data).encode()).decode()


def decode_cursor(cursor: str) -> dict:
    """Decode a cursor string back into a dict."""
    return json.loads(base64.urlsafe_b64decode(cursor.encode()))
