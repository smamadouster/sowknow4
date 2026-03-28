"""
SOWKNOW Agentic Search — Pydantic Models & Enums
All data contracts for the search pipeline, API, and agent state.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


# ─────────────────────────────────────────────────────────────────────────────
# ENUMS
# ─────────────────────────────────────────────────────────────────────────────

class QueryIntent(str, Enum):
    """Classified intent of the incoming user query."""
    FACTUAL        = "factual"         # What is X? Who is Y?
    TEMPORAL       = "temporal"        # How has X evolved? What did I write in 2020?
    COMPARATIVE    = "comparative"     # Compare X vs Y
    SYNTHESIS      = "synthesis"       # What insights do I have about X across all docs?
    FINANCIAL      = "financial"       # Balance sheets, assets, trends
    CROSS_REF      = "cross_reference" # Show everything related to X
    EXPLORATORY    = "exploratory"     # Tell me about X (broad)
    ENTITY_SEARCH  = "entity_search"   # Find docs mentioning person/org/place
    PROCEDURAL     = "procedural"      # How do I / steps to
    UNKNOWN        = "unknown"


class RelevanceLabel(str, Enum):
    HIGHLY_RELEVANT  = "highly_relevant"   # Score >= 0.82
    RELEVANT         = "relevant"          # Score >= 0.65
    PARTIALLY        = "partially"         # Score >= 0.45
    MARGINAL         = "marginal"          # Score < 0.45


class DocumentBucket(str, Enum):
    PUBLIC       = "public"
    CONFIDENTIAL = "confidential"


class UserRole(str, Enum):
    ADMIN      = "admin"
    SUPER_USER = "super_user"
    USER       = "user"


class SearchMode(str, Enum):
    FAST    = "fast"    # Single-pass hybrid search, no agent reasoning
    DEEP    = "deep"    # Full agentic pipeline with decomposition + synthesis
    AUTO    = "auto"    # Agent decides based on query complexity


# ─────────────────────────────────────────────────────────────────────────────
# REQUEST
# ─────────────────────────────────────────────────────────────────────────────

class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000, description="User's natural-language query")
    mode: SearchMode = SearchMode.AUTO
    top_k: int = Field(default=10, ge=1, le=50)
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    filter_tags: list[str] = Field(default_factory=list)
    filter_doc_types: list[str] = Field(default_factory=list)
    scope_document_ids: list[UUID] = Field(default_factory=list, description="Restrict search to specific docs")
    language: Optional[str] = Field(default=None, description="Force response language: 'fr' or 'en'")
    include_suggestions: bool = True

    @field_validator("query")
    @classmethod
    def strip_query(cls, v: str) -> str:
        return v.strip()


# ─────────────────────────────────────────────────────────────────────────────
# AGENT INTERNAL STATE
# ─────────────────────────────────────────────────────────────────────────────

class ParsedIntent(BaseModel):
    intent: QueryIntent
    confidence: float = Field(ge=0.0, le=1.0)
    entities: list[str] = Field(default_factory=list, description="Extracted named entities")
    temporal_markers: list[str] = Field(default_factory=list, description="Date/period references")
    keywords: list[str] = Field(default_factory=list, description="Core search keywords")
    expanded_keywords: list[str] = Field(default_factory=list, description="Synonyms and related terms")
    sub_queries: list[str] = Field(default_factory=list, description="Decomposed sub-queries for complex intent")
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
    semantic_score: float = Field(ge=0.0, le=1.0)
    fts_rank: float = Field(ge=0.0)
    rrf_score: float = Field(ge=0.0, description="Reciprocal Rank Fusion combined score")
    created_at: datetime
    tags: list[str] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# RESPONSE MODELS
# ─────────────────────────────────────────────────────────────────────────────

class Citation(BaseModel):
    document_id: UUID
    document_title: str
    document_type: str
    bucket: DocumentBucket
    page_number: Optional[int]
    chunk_excerpt: str = Field(description="Short excerpt (max 200 chars) supporting the answer")
    relevance_score: float


class SearchResult(BaseModel):
    rank: int
    document_id: UUID
    document_title: str
    document_type: str
    bucket: DocumentBucket
    relevance_label: RelevanceLabel
    relevance_score: float = Field(ge=0.0, le=1.0, description="Normalized 0-1 score")
    excerpt: str = Field(description="Most relevant passage from the document (max 400 chars)")
    highlights: list[str] = Field(default_factory=list, description="Key sentences highlighted")
    tags: list[str] = Field(default_factory=list)
    page_number: Optional[int] = None
    document_date: Optional[datetime] = None
    match_reason: str = Field(description="Human-readable explanation of why this matched")
    is_confidential: bool = False


class SearchSuggestion(BaseModel):
    suggestion_type: str = Field(description="'related_query' | 'refine' | 'expand' | 'temporal'")
    text: str
    rationale: str


class AgentTrace(BaseModel):
    """Debug/audit trace of the agent's reasoning steps."""
    intent_detected: QueryIntent
    intent_confidence: float
    sub_queries_used: list[str]
    total_chunks_retrieved: int
    chunks_after_reranking: int
    llm_model_used: str
    processing_time_ms: int
    confidential_results_count: int
    synthesis_performed: bool


class SearchResponse(BaseModel):
    query: str
    parsed_intent: QueryIntent
    answer_synthesis: Optional[str] = Field(
        default=None,
        description="LLM-generated direct answer synthesizing the top results. Present for DEEP/AUTO mode on complex queries."
    )
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
