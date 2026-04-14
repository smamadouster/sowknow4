"""
SOWKNOW Knowledge Graph — Schema Models
========================================
Node types, edge types, and Pydantic models for the graph layer.
Designed for PostgreSQL storage (no Neo4j dependency).
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# ── Node types ────────────────────────────────────────────────────────

class NodeType(str, enum.Enum):
    """Every entity extracted from the corpus maps to exactly one type."""

    PERSON = "person"
    ORGANIZATION = "organization"
    DOCUMENT = "document"
    FINANCIAL_METRIC = "financial_metric"
    CONCEPT = "concept"
    LOCATION = "location"
    DATE_REF = "date_ref"          # a referenced time period, not ingestion date
    AMOUNT = "amount"              # a concrete monetary value
    ACCOUNT_LINE = "account_line"  # balance-sheet / income-statement line item


# ── Edge types ────────────────────────────────────────────────────────

class EdgeType(str, enum.Enum):
    """
    Relationship types between nodes.
    Split into EXTRACTED (from NER / rules) and INFERRED (LLM or computation).
    """

    # --- Extracted (directly from document content) ---
    MENTIONED_IN = "mentioned_in"          # entity ↔ document
    RELATED_TO = "related_to"              # generic co-occurrence
    AUTHORED_BY = "authored_by"            # document → person
    BELONGS_TO = "belongs_to"              # person → organization
    LOCATED_IN = "located_in"             # entity → location
    RECORDED_IN = "recorded_in"            # metric/amount → date_ref

    # --- Financial domain (rule-based) ---
    COMPONENT_OF = "component_of"          # line item → aggregate
    LINE_ITEM_IN = "line_item_in"          # metric → financial statement
    DERIVED_FROM = "derived_from"          # metric A computed from metric B
    IMPACTS = "impacts"                    # cost line ↔ revenue line (same statement)
    PAID_BY = "paid_by"                    # amount → organization
    RECEIVED_BY = "received_by"            # amount → organization

    # --- Inferred (LLM-assisted or computed) ---
    SYNONYM_OF = "synonym_of"             # entity aliases after resolution
    CAUSES = "causes"                      # causal relationship (LLM-inferred)
    PRECEDES = "precedes"                  # temporal ordering
    CONTRADICTS = "contradicts"            # conflicting information across docs


class ExtractionMethod(str, enum.Enum):
    """How an edge was created — critical for confidence scoring."""

    NER = "ner"                  # spaCy / NER pipeline
    RULE_BASED = "rule_based"    # domain rules (financial, etc.)
    LLM_INFERRED = "llm_inferred"  # Kimi 2.5 relationship extraction
    EMBEDDING_SIMILARITY = "embedding_similarity"  # cosine > threshold
    MANUAL = "manual"            # curator-supplied


# ── Pydantic models ──────────────────────────────────────────────────

class GraphNode(BaseModel):
    """A single entity in the knowledge graph."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    canonical_name: str            # normalised, lowercased label
    aliases: list[str] = Field(default_factory=list)  # all surface forms seen
    node_type: NodeType
    language: str = "fr"           # iso-639-1 of the primary surface form
    metadata: dict = Field(default_factory=dict)
    embedding: Optional[list[float]] = None   # 1024-dim from multilingual-e5-large
    bucket: str = "public"         # "public" | "confidential"
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        use_enum_values = True


class GraphEdge(BaseModel):
    """A directed relationship between two nodes."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_id: str
    target_id: str
    edge_type: EdgeType
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    extraction_method: ExtractionMethod
    source_document_id: Optional[str] = None   # which doc produced this edge
    source_chunk_id: Optional[str] = None       # which chunk specifically
    metadata: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        use_enum_values = True


class PathResult(BaseModel):
    """A single traversal path returned by the graph search."""

    nodes: list[GraphNode]
    edges: list[GraphEdge]
    hop_count: int
    min_confidence: float          # weakest link in the chain
    supporting_document_ids: list[str]

    @property
    def summary(self) -> str:
        """Human-readable path representation."""
        parts = []
        for i, node in enumerate(self.nodes):
            parts.append(node.canonical_name)
            if i < len(self.edges):
                parts.append(f"--[{self.edges[i].edge_type}]-->")
        return " ".join(parts)


class ConnectionQuery(BaseModel):
    """User request: 'find connections between X and Y'."""

    start_entity: str              # natural-language name
    end_entity: str
    max_depth: int = Field(default=5, le=7)
    min_confidence: float = Field(default=0.3, ge=0.0, le=1.0)
    include_confidential: bool = False   # requires admin role
