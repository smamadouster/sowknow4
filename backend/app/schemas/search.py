from uuid import UUID

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000)
    limit: int = Field(default=10, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
    bucket: str | None = None  # Filter by bucket (for admins)
    semantic_weight: float = Field(default=0.7, ge=0.0, le=1.0)  # Hybrid search weight


class SearchResultChunk(BaseModel):
    chunk_id: UUID
    document_id: UUID
    document_name: str
    document_bucket: str
    chunk_text: str
    chunk_index: int
    page_number: int | None = None
    relevance_score: float
    semantic_score: float
    keyword_score: float


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResultChunk]
    total: int
    llm_used: str | None = None  # "kimi" or "ollama" if routing occurred
    partial: bool = False  # True when results are incomplete due to timeout
    warning: str | None = None  # Human-readable reason when partial=True
    next_cursor: str | None = None  # Cursor for next page (T09)
