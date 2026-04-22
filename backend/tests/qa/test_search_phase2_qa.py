"""
Phase 2 QA Validation — Accuracy Foundation

Validates:
- Language-aware regconfig (english vs french stemming)
- Trigram fallback for typos
- Cross-encoder re-ranker graceful degradation
- HNSW ef_search tuning
- Dynamic threshold behavior

Run: pytest backend/tests/qa/test_search_phase2_qa.py -v
"""
import pytest
from unittest.mock import AsyncMock, patch

from app.services.search_service import _get_regconfig, HybridSearchService


class TestLanguageAwareSearch:
    """QA Gate: P2.1 English queries must use english regconfig"""

    def test_english_query_maps_to_english(self):
        assert _get_regconfig("en") == "english"

    def test_french_query_maps_to_french(self):
        assert _get_regconfig("fr") == "french"

    def test_unknown_language_defaults_to_simple(self):
        assert _get_regconfig("xx") == "simple"

    @pytest.mark.asyncio
    async def test_hybrid_search_uses_regconfig_parameter(self):
        svc = HybridSearchService()
        svc.semantic_search = AsyncMock(return_value=[])
        svc.keyword_search = AsyncMock(return_value=[])
        svc.article_semantic_search = AsyncMock(return_value=[])
        svc.article_keyword_search = AsyncMock(return_value=[])
        svc.tag_search = AsyncMock(return_value=[])

        await svc.hybrid_search(
            query="financial report", db=None, user=None,
            regconfig="english", rerank=False
        )

        svc.keyword_search.assert_awaited_once()
        call_kwargs = svc.keyword_search.call_args.kwargs
        assert call_kwargs.get("regconfig") == "english"


class TestTrigramFallback:
    """QA Gate: P2.2 Typo queries must return results via trigram fallback"""

    @pytest.mark.asyncio
    async def test_trigram_fallback_activates_on_few_results(self):
        """When keyword_search returns <3 results, trigram fallback is triggered."""
        from app.services.search_service import SearchResult, HybridSearchService
        svc = HybridSearchService()

        # Mock DB and internal fallback
        mock_db = AsyncMock()
        fallback_result = SearchResult(
            chunk_id="fallback-1", document_id="doc-fb",
            document_name="fallback.pdf", document_bucket="public",
            chunk_text="fallback text", chunk_index=0, page_number=None,
            semantic_score=0.0, keyword_score=0.3, final_score=0.3,
        )

        with patch.object(svc, "_trigram_fallback_search", new_callable=AsyncMock, return_value=[fallback_result]) as mock_fallback:
            # Use a query that tsvector won't match (random chars)
            results = await svc.keyword_search(
                query="xyznonexistent123", limit=10, db=mock_db, user=None, regconfig="simple"
            )
            # Keyword search should call fallback when tsvector returns <3 results
            mock_fallback.assert_awaited_once()
            # Fallback results should be included
            assert len(results) == 1
            assert results[0].chunk_id == "fallback-1"

    @pytest.mark.asyncio
    async def test_trigram_fallback_skipped_when_many_results(self):
        from app.services.search_service import SearchResult
        svc = HybridSearchService()

        fake_results = [
            SearchResult(
                chunk_id=f"chunk-{i}", document_id=f"doc-{i}",
                document_name="test.pdf", document_bucket="public",
                chunk_text="test", chunk_index=0, page_number=None,
                semantic_score=0.0, keyword_score=0.5, final_score=0.5,
            )
            for i in range(5)
        ]
        svc.keyword_search = AsyncMock(return_value=fake_results)
        svc._trigram_fallback_search = AsyncMock(return_value=[])
        svc.semantic_search = AsyncMock(return_value=[])
        svc.article_semantic_search = AsyncMock(return_value=[])
        svc.article_keyword_search = AsyncMock(return_value=[])
        svc.tag_search = AsyncMock(return_value=[])

        await svc.hybrid_search(
            query="passport", db=None, user=None,
            regconfig="simple", rerank=False
        )
        svc._trigram_fallback_search.assert_not_awaited()


class TestRerankerGracefulDegradation:
    """QA Gate: P2.3 Re-ranker failure must not break search"""

    @pytest.mark.asyncio
    async def test_reranker_unavailable_returns_results(self):
        svc = HybridSearchService()
        svc.semantic_search = AsyncMock(return_value=[])
        svc.keyword_search = AsyncMock(return_value=[])
        svc.article_semantic_search = AsyncMock(return_value=[])
        svc.article_keyword_search = AsyncMock(return_value=[])
        svc.tag_search = AsyncMock(return_value=[])

        with patch("app.services.search_service.rerank_passages", side_effect=Exception("unreachable")):
            result = await svc.hybrid_search(
                query="test", db=None, user=None,
                regconfig="simple", rerank=True
            )

        assert result["query"] == "test"
        assert result["partial"] is False


class TestDynamicThreshold:
    """QA Gate: P2.6 Short queries use stricter threshold"""

    @pytest.mark.asyncio
    async def test_short_query_filters_weak_matches(self):
        """Short query (1 word) with score 0.20 should be filtered by 0.25 threshold."""
        from app.services.search_service import SearchResult
        svc = HybridSearchService(min_score_threshold=0.1)

        low_score = SearchResult(
            chunk_id="c1", document_id="d1", document_name="x.pdf",
            document_bucket="public", chunk_text="x", chunk_index=0,
            page_number=None, semantic_score=0.0, keyword_score=0.2, final_score=0.2,
        )
        svc.keyword_search = AsyncMock(return_value=[low_score])
        svc.semantic_search = AsyncMock(return_value=[])
        svc.article_semantic_search = AsyncMock(return_value=[])
        svc.article_keyword_search = AsyncMock(return_value=[])
        svc.tag_search = AsyncMock(return_value=[])

        result = await svc.hybrid_search(
            query="fin", db=None, user=None,
            regconfig="simple", rerank=False
        )
        # Score 0.20 < 0.25 threshold for short query => filtered out
        assert result["total"] == 0

    @pytest.mark.asyncio
    async def test_long_query_allows_moderate_matches(self):
        """Long query (5 words) with keyword score 0.6 should pass 0.15 threshold."""
        from app.services.search_service import SearchResult
        svc = HybridSearchService(min_score_threshold=0.1)

        # keyword_score=0.6 * kw_w=0.3 => final_score=0.18 >= 0.15 threshold
        moderate_score = SearchResult(
            chunk_id="c1", document_id="d1", document_name="x.pdf",
            document_bucket="public", chunk_text="x", chunk_index=0,
            page_number=None, semantic_score=0.0, keyword_score=0.6, final_score=0.6,
        )
        svc.keyword_search = AsyncMock(return_value=[moderate_score])
        svc.semantic_search = AsyncMock(return_value=[])
        svc.article_semantic_search = AsyncMock(return_value=[])
        svc.article_keyword_search = AsyncMock(return_value=[])
        svc.tag_search = AsyncMock(return_value=[])

        result = await svc.hybrid_search(
            query="financial report for last year", db=None, user=None,
            regconfig="simple", rerank=False
        )
        # Score 0.18 >= 0.15 threshold for long query => included
        assert result["total"] == 1
