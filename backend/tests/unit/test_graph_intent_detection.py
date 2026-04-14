"""
Unit tests for graph traversal intent detection in ResearcherAgent.
No database required.
"""

import pytest
from app.services.agents.researcher_agent import ResearcherAgent


@pytest.fixture
def agent():
    return ResearcherAgent()


# ── _is_graph_traversal_query ──────────────────────────────────────────────

class TestIsGraphTraversalQuery:

    # English patterns
    def test_en_link_between(self, agent):
        assert agent._is_graph_traversal_query("Is there a link between salary and revenue?")

    def test_en_connection_between(self, agent):
        assert agent._is_graph_traversal_query("Is there a connection between the CEO and the company?")

    def test_en_what_connects(self, agent):
        assert agent._is_graph_traversal_query("What connects employee costs to net income?")

    def test_en_path_between(self, agent):
        assert agent._is_graph_traversal_query("Find the path between depreciation and equity")

    def test_en_relationship_between(self, agent):
        assert agent._is_graph_traversal_query("What is the relationship between assets and liabilities?")

    def test_en_show_path(self, agent):
        assert agent._is_graph_traversal_query("Show path between interest paid and operating result")

    # French patterns
    def test_fr_lien_entre(self, agent):
        assert agent._is_graph_traversal_query("y a-t-il un lien entre le salaire et le chiffre d'affaires?")

    def test_fr_rapport_entre(self, agent):
        assert agent._is_graph_traversal_query("quel est le rapport entre les dettes et les actifs?")

    def test_fr_qu_est_ce_qui_relie(self, agent):
        assert agent._is_graph_traversal_query("qu'est-ce qui relie la masse salariale au résultat?")

    # Negative cases — regular RAG queries must NOT match
    def test_no_match_simple_search(self, agent):
        assert not agent._is_graph_traversal_query("Show me documents about employee salaries")

    def test_no_match_summary(self, agent):
        assert not agent._is_graph_traversal_query("Summarize last year's financial results")

    def test_no_match_date_query(self, agent):
        assert not agent._is_graph_traversal_query("What happened in Q3 2023?")

    def test_no_match_empty(self, agent):
        assert not agent._is_graph_traversal_query("")


# ── _extract_traversal_pair ────────────────────────────────────────────────

class TestExtractTraversalPair:

    def test_en_between_and(self, agent):
        pair = agent._extract_traversal_pair("Is there a link between salary and revenue?")
        assert pair is not None
        assert pair[0].lower() == "salary"
        assert pair[1].lower() == "revenue"

    def test_en_multiword_entities(self, agent):
        pair = agent._extract_traversal_pair(
            "What connects employee benefits and net operating income?"
        )
        assert pair is not None
        assert "employee benefits" in pair[0].lower()
        assert "net operating income" in pair[1].lower()

    def test_fr_entre_et(self, agent):
        pair = agent._extract_traversal_pair(
            "y a-t-il un lien entre le salaire et le résultat net?"
        )
        assert pair is not None
        # "le salaire" — tolerate the article being captured
        assert "salaire" in pair[0].lower()
        assert "résultat net" in pair[1].lower()

    def test_no_and_returns_none(self, agent):
        # Query mentions only one entity — cannot extract a pair
        pair = agent._extract_traversal_pair("What is the revenue?")
        assert pair is None

    def test_strips_whitespace(self, agent):
        pair = agent._extract_traversal_pair("path between  depreciation  and  equity ")
        assert pair is not None
        assert pair[0] == "depreciation"
        assert pair[1] == "equity"
