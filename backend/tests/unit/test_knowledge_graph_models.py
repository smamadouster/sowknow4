"""
Unit tests for knowledge graph Pydantic models.
No database or network required.
"""

import pytest
from datetime import datetime

from app.services.knowledge_graph.models import (
    ConnectionQuery,
    EdgeType,
    ExtractionMethod,
    GraphEdge,
    GraphNode,
    NodeType,
    PathResult,
)


class TestNodeType:
    def test_all_values_are_strings(self):
        for member in NodeType:
            assert isinstance(member.value, str)

    def test_financial_types_present(self):
        assert NodeType.ACCOUNT_LINE in NodeType
        assert NodeType.AMOUNT in NodeType
        assert NodeType.FINANCIAL_METRIC in NodeType

    def test_core_types_present(self):
        assert NodeType.PERSON in NodeType
        assert NodeType.ORGANIZATION in NodeType
        assert NodeType.DOCUMENT in NodeType


class TestEdgeType:
    def test_financial_edges_present(self):
        assert EdgeType.COMPONENT_OF in EdgeType
        assert EdgeType.IMPACTS in EdgeType
        assert EdgeType.DERIVED_FROM in EdgeType
        assert EdgeType.LINE_ITEM_IN in EdgeType

    def test_extraction_edges_present(self):
        assert EdgeType.MENTIONED_IN in EdgeType
        assert EdgeType.RELATED_TO in EdgeType

    def test_inferred_edges_present(self):
        assert EdgeType.CAUSES in EdgeType
        assert EdgeType.CONTRADICTS in EdgeType


class TestGraphNode:
    def test_defaults(self):
        node = GraphNode(canonical_name="test entity", node_type=NodeType.CONCEPT)
        assert node.language == "fr"
        assert node.bucket == "public"
        assert node.aliases == []
        assert node.metadata == {}
        assert node.embedding is None
        assert len(node.id) == 36  # UUID format

    def test_custom_values(self):
        node = GraphNode(
            canonical_name="chiffre d'affaires",
            node_type=NodeType.ACCOUNT_LINE,
            bucket="confidential",
            aliases=["CA", "turnover"],
        )
        assert node.bucket == "confidential"
        assert "CA" in node.aliases

    def test_unique_ids(self):
        n1 = GraphNode(canonical_name="a", node_type=NodeType.CONCEPT)
        n2 = GraphNode(canonical_name="b", node_type=NodeType.CONCEPT)
        assert n1.id != n2.id


class TestGraphEdge:
    def test_defaults(self):
        edge = GraphEdge(
            source_id="aaa",
            target_id="bbb",
            edge_type=EdgeType.RELATED_TO,
            extraction_method=ExtractionMethod.NER,
        )
        assert edge.confidence == 0.5
        assert edge.source_document_id is None

    def test_confidence_bounds(self):
        with pytest.raises(Exception):
            GraphEdge(
                source_id="a", target_id="b",
                edge_type=EdgeType.RELATED_TO,
                extraction_method=ExtractionMethod.NER,
                confidence=1.5,  # out of range
            )

    def test_confidence_zero_allowed(self):
        edge = GraphEdge(
            source_id="a", target_id="b",
            edge_type=EdgeType.IMPACTS,
            extraction_method=ExtractionMethod.RULE_BASED,
            confidence=0.0,
        )
        assert edge.confidence == 0.0


class TestPathResult:
    def _make_node(self, name: str) -> GraphNode:
        return GraphNode(canonical_name=name, node_type=NodeType.CONCEPT)

    def _make_edge(self, etype: EdgeType) -> GraphEdge:
        return GraphEdge(
            source_id="a", target_id="b",
            edge_type=etype,
            extraction_method=ExtractionMethod.NER,
        )

    def test_summary_single_hop(self):
        n1 = self._make_node("salaire")
        n2 = self._make_node("résultat net")
        e = self._make_edge(EdgeType.IMPACTS)
        path = PathResult(
            nodes=[n1, n2],
            edges=[e],
            hop_count=1,
            min_confidence=0.7,
            supporting_document_ids=[],
        )
        assert "salaire" in path.summary
        assert "résultat net" in path.summary
        assert "impacts" in path.summary

    def test_summary_no_edges(self):
        n = self._make_node("test")
        path = PathResult(
            nodes=[n], edges=[], hop_count=0, min_confidence=1.0,
            supporting_document_ids=[],
        )
        assert path.summary == "test"


class TestConnectionQuery:
    def test_defaults(self):
        q = ConnectionQuery(start_entity="salaire", end_entity="résultat")
        assert q.max_depth == 5
        assert q.min_confidence == 0.3
        assert q.include_confidential is False

    def test_max_depth_capped(self):
        with pytest.raises(Exception):
            ConnectionQuery(
                start_entity="a", end_entity="b", max_depth=8  # le=7
            )

    def test_min_confidence_bounds(self):
        with pytest.raises(Exception):
            ConnectionQuery(
                start_entity="a", end_entity="b", min_confidence=1.5
            )
