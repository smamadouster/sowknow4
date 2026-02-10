from pydantic import BaseModel, Field
from uuid import UUID
from typing import Optional, List


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000)
    limit: int = Field(default=10, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
    bucket: Optional[str] = None  # Filter by bucket (for admins)
    semantic_weight: float = Field(default=0.7, ge=0.0, le=1.0)  # Hybrid search weight


class SearchResultChunk(BaseModel):
    chunk_id: UUID
    document_id: UUID
    document_name: str
    document_bucket: str
    chunk_text: str
    chunk_index: int
    page_number: Optional[int] = None
    relevance_score: float
    semantic_score: float
    keyword_score: float


class SearchResponse(BaseModel):
    query: str
    results: List[SearchResultChunk]
    total: int
    llm_used: Optional[str] = None  # "kimi" or "ollama" if routing occurred
