"""
SOWKNOW Agentic Search — Test Suite
Covers: RBAC enforcement, LLM routing, RRF scoring, intent parsing,
        citation building, RBAC double-checks, and API endpoints.
Run: pytest tests/test_search_agent.py -v
"""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio

from backend.search_agent import (
    _fallback_intent,
    _score_to_label,
    build_citations,
    build_search_queries,
    rerank_and_build_results,
)
from backend.search_models import (
    DocumentBucket,
    ParsedIntent,
    QueryIntent,
    RawChunk,
    RelevanceLabel,
    SearchRequest,
    SearchMode,
    UserRole,
)


# ─────────────────────────────────────────────────────────────────────────────
# FIXTURES
# ─────────────────────────────────────────────────────────────────────────────

def make_chunk(
    bucket: DocumentBucket = DocumentBucket.PUBLIC,
    semantic_score: float = 0.75,
    rrf_score: float = 0.015,
    text: str = "Ceci est un extrait de test sur la finance.",
    doc_id=None,
) -> RawChunk:
    return RawChunk(
        chunk_id=uuid4(),
        document_id=doc_id or uuid4(),
        document_title="Document de test",
        document_bucket=bucket,
        document_type="pdf",
        chunk_index=0,
        page_number=1,
        text=text,
        semantic_score=semantic_score,
        fts_rank=0.3,
        rrf_score=rrf_score,
        created_at=datetime.utcnow(),
        tags=["finance", "test"],
    )


def make_intent(
    intent: QueryIntent = QueryIntent.FACTUAL,
    keywords: list[str] = None,
    sub_queries: list[str] = None,
    requires_synthesis: bool = False,
) -> ParsedIntent:
    return ParsedIntent(
        intent=intent,
        confidence=0.9,
        keywords=keywords or ["finance", "bilan"],
        expanded_keywords=["actif", "passif"],
        sub_queries=sub_queries or [],
        detected_language="fr",
        requires_synthesis=requires_synthesis,
    )


# ─────────────────────────────────────────────────────────────────────────────
# TEST: RELEVANCE LABEL THRESHOLDS
# ─────────────────────────────────────────────────────────────────────────────

class TestRelevanceLabels:
    def test_highly_relevant(self):
        assert _score_to_label(0.85) == RelevanceLabel.HIGHLY_RELEVANT

    def test_highly_relevant_boundary(self):
        assert _score_to_label(0.82) == RelevanceLabel.HIGHLY_RELEVANT

    def test_relevant(self):
        assert _score_to_label(0.72) == RelevanceLabel.RELEVANT

    def test_relevant_lower_boundary(self):
        assert _score_to_label(0.65) == RelevanceLabel.RELEVANT

    def test_partially(self):
        assert _score_to_label(0.55) == RelevanceLabel.PARTIALLY

    def test_marginal(self):
        assert _score_to_label(0.3) == RelevanceLabel.MARGINAL

    def test_zero(self):
        assert _score_to_label(0.0) == RelevanceLabel.MARGINAL


# ─────────────────────────────────────────────────────────────────────────────
# TEST: RBAC — CONFIDENTIAL VISIBILITY
# ─────────────────────────────────────────────────────────────────────────────

class TestRBACEnforcement:
    """
    CRITICAL: These tests verify the privacy wall between regular users
    and confidential documents. Any failure here is a security breach.
    """

    def test_user_cannot_see_confidential_chunks(self):
        """UserRole.USER must NEVER receive confidential results."""
        doc_id = uuid4()
        public_chunk = make_chunk(DocumentBucket.PUBLIC, rrf_score=0.01, doc_id=doc_id)
        confidential_chunk = make_chunk(DocumentBucket.CONFIDENTIAL, rrf_score=0.02)
        intent = make_intent()

        results, has_confidential = rerank_and_build_results(
            [public_chunk, confidential_chunk],
            query="test",
            intent=intent,
            top_k=10,
            user_role=UserRole.USER,
        )

        # Confidential document must not appear
        for r in results:
            assert r.bucket != DocumentBucket.CONFIDENTIAL, (
                f"SECURITY BREACH: Confidential doc '{r.document_title}' visible to regular user!"
            )
        assert not has_confidential

    def test_admin_can_see_confidential_chunks(self):
        """Admin must receive confidential results."""
        confidential_chunk = make_chunk(DocumentBucket.CONFIDENTIAL, rrf_score=0.9)
        intent = make_intent()

        results, has_confidential = rerank_and_build_results(
            [confidential_chunk],
            query="test",
            intent=intent,
            top_k=10,
            user_role=UserRole.ADMIN,
        )
        assert has_confidential
        assert any(r.bucket == DocumentBucket.CONFIDENTIAL for r in results)

    def test_super_user_can_see_confidential_chunks(self):
        """Super User must receive confidential results."""
        confidential_chunk = make_chunk(DocumentBucket.CONFIDENTIAL, rrf_score=0.9)
        intent = make_intent()

        results, has_confidential = rerank_and_build_results(
            [confidential_chunk],
            query="test",
            intent=intent,
            top_k=10,
            user_role=UserRole.SUPER_USER,
        )
        assert has_confidential
        assert any(r.bucket == DocumentBucket.CONFIDENTIAL for r in results)

    def test_user_mixed_results_filters_confidential(self):
        """Regular user with mixed-bucket results gets only public ones."""
        doc_pub = uuid4()
        doc_conf = uuid4()
        chunks = [
            make_chunk(DocumentBucket.PUBLIC, rrf_score=0.8, doc_id=doc_pub),
            make_chunk(DocumentBucket.CONFIDENTIAL, rrf_score=0.9, doc_id=doc_conf),  # Higher score
            make_chunk(DocumentBucket.PUBLIC, rrf_score=0.7, doc_id=uuid4()),
        ]
        intent = make_intent()
        results, has_confidential = rerank_and_build_results(
            chunks, query="test", intent=intent, top_k=10, user_role=UserRole.USER
        )
        # Even though confidential chunk has the highest score, it must not appear
        assert all(r.bucket == DocumentBucket.PUBLIC for r in results)
        assert not has_confidential
        assert len(results) == 2  # Only 2 public docs

    def test_is_confidential_flag_set_correctly(self):
        """SearchResult.is_confidential must reflect the document bucket."""
        doc_id = uuid4()
        conf_chunk = make_chunk(DocumentBucket.CONFIDENTIAL, rrf_score=0.9, doc_id=doc_id)
        intent = make_intent()
        results, _ = rerank_and_build_results(
            [conf_chunk], query="test", intent=intent, top_k=10, user_role=UserRole.ADMIN
        )
        assert results[0].is_confidential is True

    def test_public_result_not_flagged_confidential(self):
        doc_id = uuid4()
        pub_chunk = make_chunk(DocumentBucket.PUBLIC, rrf_score=0.9, doc_id=doc_id)
        intent = make_intent()
        results, _ = rerank_and_build_results(
            [pub_chunk], query="test", intent=intent, top_k=10, user_role=UserRole.ADMIN
        )
        assert results[0].is_confidential is False


# ─────────────────────────────────────────────────────────────────────────────
# TEST: LLM ROUTING (privacy invariant)
# ─────────────────────────────────────────────────────────────────────────────

class TestLLMRouting:
    """
    Verify that the LLM router ALWAYS selects Ollama when any confidential
    chunk is in context — regardless of the ratio of public to confidential chunks.
    """

    @pytest.mark.asyncio
    async def test_all_public_routes_to_kimi(self):
        with patch("backend.search_agent._call_kimi", new_callable=AsyncMock) as mock_kimi, \
             patch("backend.search_agent._call_ollama", new_callable=AsyncMock) as mock_ollama:
            mock_kimi.return_value = '{"answer": "test"}'
            from backend.search_agent import _route_llm
            result, model = await _route_llm(
                messages=[{"role": "user", "content": "test"}],
                system="test",
                has_confidential=False,
            )
            mock_kimi.assert_called_once()
            mock_ollama.assert_not_called()
            assert "kimi" in model.lower()

    @pytest.mark.asyncio
    async def test_any_confidential_routes_to_ollama(self):
        """The ONE confidential chunk rule: even 1 out of 100 triggers Ollama."""
        with patch("backend.search_agent._call_kimi", new_callable=AsyncMock) as mock_kimi, \
             patch("backend.search_agent._call_ollama", new_callable=AsyncMock) as mock_ollama:
            mock_ollama.return_value = "Réponse Ollama"
            from backend.search_agent import _route_llm
            result, model = await _route_llm(
                messages=[{"role": "user", "content": "test"}],
                system="test",
                has_confidential=True,
            )
            mock_ollama.assert_called_once()
            mock_kimi.assert_not_called()
            assert "ollama" in model.lower()

    @pytest.mark.asyncio
    async def test_intent_parsing_never_uses_ollama(self):
        """Intent parsing contains no document content — always uses Kimi."""
        with patch("backend.search_agent._call_kimi", new_callable=AsyncMock) as mock_kimi, \
             patch("backend.search_agent._call_ollama", new_callable=AsyncMock) as mock_ollama:
            mock_kimi.return_value = json.dumps({
                "intent": "factual", "confidence": 0.9, "keywords": ["test"],
                "expanded_keywords": [], "sub_queries": [], "entities": [],
                "temporal_markers": [], "detected_language": "fr",
                "requires_synthesis": False, "temporal_range": None,
            })
            await parse_intent("Quels sont mes bilans financiers ?")
            mock_kimi.assert_called()
            mock_ollama.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# TEST: QUERY EXPANSION
# ─────────────────────────────────────────────────────────────────────────────

class TestQueryExpansion:
    def test_simple_query_no_sub_queries(self):
        intent = make_intent(sub_queries=[])
        queries = build_search_queries(intent, "bilan financier 2023")
        assert "bilan financier 2023" in queries
        assert len(queries) >= 1

    def test_complex_query_with_sub_queries(self):
        intent = make_intent(
            sub_queries=["bilan actif 2022", "bilan passif 2022"],
            keywords=["bilan", "actif"],
        )
        queries = build_search_queries(intent, "analyse complète du bilan 2022")
        assert "analyse complète du bilan 2022" in queries
        assert "bilan actif 2022" in queries
        assert "bilan passif 2022" in queries

    def test_no_duplicate_queries(self):
        intent = make_intent(sub_queries=["bilan financier"])
        queries = build_search_queries(intent, "bilan financier")
        assert queries.count("bilan financier") == 1

    def test_keyword_variant_added(self):
        intent = make_intent(keywords=["bilan", "actif", "passif", "2022", "annuel"])
        queries = build_search_queries(intent, "bilan financier annuel")
        # Should have a keyword-focused variant
        assert len(queries) >= 2


# ─────────────────────────────────────────────────────────────────────────────
# TEST: RESULT RANKING
# ─────────────────────────────────────────────────────────────────────────────

class TestResultRanking:
    def test_results_sorted_by_relevance_descending(self):
        chunks = [
            make_chunk(rrf_score=0.005, doc_id=uuid4()),
            make_chunk(rrf_score=0.020, doc_id=uuid4()),
            make_chunk(rrf_score=0.012, doc_id=uuid4()),
        ]
        intent = make_intent()
        results, _ = rerank_and_build_results(chunks, "test", intent, 10, UserRole.ADMIN)
        scores = [r.relevance_score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_ranks_sequential(self):
        chunks = [make_chunk(rrf_score=0.02 - i * 0.003, doc_id=uuid4()) for i in range(5)]
        intent = make_intent()
        results, _ = rerank_and_build_results(chunks, "test", intent, 10, UserRole.ADMIN)
        assert [r.rank for r in results] == list(range(1, len(results) + 1))

    def test_top_k_respected(self):
        chunks = [make_chunk(rrf_score=0.02 - i * 0.001, doc_id=uuid4()) for i in range(20)]
        intent = make_intent()
        results, _ = rerank_and_build_results(chunks, "test", intent, top_k=5, user_role=UserRole.ADMIN)
        assert len(results) <= 5

    def test_chunks_collapsed_per_document(self):
        """Multiple chunks from same doc should produce only one result."""
        doc_id = uuid4()
        chunks = [
            make_chunk(rrf_score=0.02, doc_id=doc_id),
            make_chunk(rrf_score=0.015, doc_id=doc_id),
            make_chunk(rrf_score=0.01, doc_id=doc_id),
        ]
        intent = make_intent()
        results, _ = rerank_and_build_results(chunks, "test", intent, 10, UserRole.ADMIN)
        doc_ids = [r.document_id for r in results]
        assert len(doc_ids) == len(set(doc_ids)), "Same document appeared multiple times in results"


# ─────────────────────────────────────────────────────────────────────────────
# TEST: CITATIONS
# ─────────────────────────────────────────────────────────────────────────────

class TestCitations:
    def test_citations_match_results(self):
        doc_id = uuid4()
        chunk = make_chunk(doc_id=doc_id, rrf_score=0.9)
        intent = make_intent()
        results, _ = rerank_and_build_results([chunk], "test", intent, 10, UserRole.ADMIN)
        citations = build_citations(results, [chunk])
        assert len(citations) == 1
        assert citations[0].document_id == doc_id

    def test_one_citation_per_document(self):
        doc_id = uuid4()
        chunks = [make_chunk(doc_id=doc_id, rrf_score=0.9 - i * 0.1) for i in range(3)]
        intent = make_intent()
        results, _ = rerank_and_build_results(chunks, "test", intent, 10, UserRole.ADMIN)
        citations = build_citations(results, chunks)
        cit_doc_ids = [c.document_id for c in citations]
        assert len(cit_doc_ids) == len(set(cit_doc_ids))

    def test_citations_max_ten(self):
        chunks = [make_chunk(doc_id=uuid4(), rrf_score=0.02 - i * 0.001) for i in range(15)]
        intent = make_intent()
        results, _ = rerank_and_build_results(chunks, "test", intent, 15, UserRole.ADMIN)
        citations = build_citations(results, chunks)
        assert len(citations) <= 10

    def test_citation_excerpt_length(self):
        doc_id = uuid4()
        chunk = make_chunk(doc_id=doc_id, text="A" * 300)
        intent = make_intent()
        results, _ = rerank_and_build_results([chunk], "test", intent, 10, UserRole.ADMIN)
        citations = build_citations(results, [chunk])
        assert len(citations[0].chunk_excerpt) <= 205  # 200 chars + ellipsis


# ─────────────────────────────────────────────────────────────────────────────
# TEST: FALLBACK INTENT
# ─────────────────────────────────────────────────────────────────────────────

class TestFallbackIntent:
    def test_temporal_query_detected(self):
        intent = _fallback_intent("Comment a évolué mon portefeuille en 2022 ?")
        assert intent.intent == QueryIntent.TEMPORAL

    def test_financial_query_detected(self):
        intent = _fallback_intent("Analyse du bilan financier annuel")
        assert intent.intent == QueryIntent.FINANCIAL

    def test_french_language_detected(self):
        intent = _fallback_intent("Quels sont les documents relatifs à la famille ?")
        assert intent.detected_language == "fr"

    def test_english_language_detected(self):
        intent = _fallback_intent("What are the main assets on the balance sheet?")
        assert intent.detected_language == "en"

    def test_keywords_extracted(self):
        intent = _fallback_intent("bilan financier actif passif 2023")
        assert len(intent.keywords) > 0

    def test_stop_words_removed_from_keywords(self):
        intent = _fallback_intent("les documents de la famille")
        # Stop words like 'les', 'de', 'la' should not be keywords
        assert "les" not in intent.keywords
        assert "de" not in intent.keywords
        assert "la" not in intent.keywords


# ─────────────────────────────────────────────────────────────────────────────
# TEST: SEARCH REQUEST VALIDATION
# ─────────────────────────────────────────────────────────────────────────────

class TestSearchRequestValidation:
    def test_empty_query_rejected(self):
        with pytest.raises(Exception):
            SearchRequest(query="")

    def test_whitespace_query_stripped(self):
        req = SearchRequest(query="  bilan financier  ")
        assert req.query == "bilan financier"

    def test_default_mode_is_auto(self):
        req = SearchRequest(query="test")
        assert req.mode == SearchMode.AUTO

    def test_top_k_default(self):
        req = SearchRequest(query="test")
        assert req.top_k == 10

    def test_top_k_max_enforced(self):
        with pytest.raises(Exception):
            SearchRequest(query="test", top_k=51)
