"""
SOWKNOW Agentic Search — Pydantic Models & Enums
All data contracts for the search pipeline, API, and agent state.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.models.document import DocumentBucket
from app.models.user import UserRole


class QueryIntent(str, Enum):
    FACTUAL = "factual"
    TEMPORAL = "temporal"
    COMPARATIVE = "comparative"
    SYNTHESIS = "synthesis"
    FINANCIAL = "financial"
    CROSS_REF = "cross_reference"
    EXPLORATORY = "exploratory"
    ENTITY_SEARCH = "entity_search"
    PROCEDURAL = "procedural"
    UNKNOWN = "unknown"


class RelevanceLabel(str, Enum):
    HIGHLY_RELEVANT = "highly_relevant"
    RELEVANT = "relevant"
    PARTIALLY = "partially"
    MARGINAL = "marginal"


class SearchMode(str, Enum):
    FAST = "fast"
    DEEP = "deep"
    AUTO = "auto"


class AgenticSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000)
    mode: SearchMode = SearchMode.AUTO
    top_k: int = Field(default=10, ge=1, le=50)
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    filter_tags: list[str] = Field(default_factory=list)
    filter_doc_types: list[str] = Field(default_factory=list)
    scope_document_ids: list[UUID] = Field(default_factory=list)
    language: Optional[str] = Field(default=None)
    include_suggestions: bool = True
    journal_only: bool = False

    @field_validator("query")
    @classmethod
    def strip_query(cls, v: str) -> str:
        return v.strip()


class ParsedIntent(BaseModel):
    intent: QueryIntent
    confidence: float = Field(ge=0.0, le=1.0)
    entities: list[str] = Field(default_factory=list)
    temporal_markers: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    expanded_keywords: list[str] = Field(default_factory=list)
    sub_queries: list[str] = Field(default_factory=list)
    detected_language: str = "fr"
    requires_synthesis: bool = False
    temporal_range: Optional[dict[str, Any]] = None


class RawChunk(BaseModel):
    chunk_id: UUID
    document_id: UUID
    document_title: str
    document_bucket: DocumentBucket
    document_type: str
    chunk_index: int
    page_number: Optional[int]
    text: str
    semantic_score: float = 0.0
    fts_rank: float = 0.0
    rrf_score: float = 0.0
    created_at: Optional[datetime] = None
    tags: list[str] = Field(default_factory=list)


class Citation(BaseModel):
    document_id: UUID
    document_title: str
    document_type: str
    bucket: DocumentBucket
    page_number: Optional[int]
    chunk_excerpt: str
    relevance_score: float


class SearchResult(BaseModel):
    rank: int
    document_id: UUID
    document_title: str
    document_type: str
    bucket: DocumentBucket
    relevance_label: RelevanceLabel
    relevance_score: float = Field(ge=0.0, le=1.0)
    excerpt: str
    highlights: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    page_number: Optional[int] = None
    document_date: Optional[datetime] = None
    match_reason: str
    is_confidential: bool = False


class SearchSuggestion(BaseModel):
    suggestion_type: str
    text: str
    rationale: str


class AgentTrace(BaseModel):
    intent_detected: QueryIntent
    intent_confidence: float
    sub_queries_used: list[str]
    total_chunks_retrieved: int
    chunks_after_reranking: int
    llm_model_used: str
    processing_time_ms: int
    confidential_results_count: int
    synthesis_performed: bool


class AgenticSearchResponse(BaseModel):
    query: str
    parsed_intent: QueryIntent
    answer_synthesis: Optional[str] = None
    answer_language: str = "fr"
    results: list[SearchResult]
    citations: list[Citation]
    suggestions: list[SearchSuggestion] = Field(default_factory=list)
    total_found: int
    has_confidential_results: bool = False
    llm_model_used: Optional[str] = None
    agent_trace: Optional[AgentTrace] = None
    search_time_ms: int
    performed_at: datetime = Field(default_factory=datetime.utcnow)
