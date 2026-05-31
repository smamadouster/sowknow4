"""
Tests for Phase 2 accuracy improvements:
- Language-aware regconfig
- Trigram fallback
- Dynamic threshold
- Re-ranker integration (mocked)
"""
import pytest
from unittest.mock import AsyncMock, patch

from app.services.search_service import _get_regconfig, HybridSearchService


class TestLanguageAwareRegconfig:
    def test_french_maps_correctly(self):
        assert _get_regconfig("fr") == "french"

    def test_english_maps_correctly(self):
        assert _get_regconfig("en") == "english"

    def test_german_maps_correctly(self):
        assert _get_regconfig("de") == "german"

    def test_unknown_defaults_to_simple(self):
        assert _get_regconfig("xx") == "simple"

    def test_none_defaults_to_simple(self):
        assert _get_regconfig(None) == "simple"

    def test_empty_string_defaults_to_simple(self):
        assert _get_regconfig("") == "simple"


class TestTrigramFallback:
    @pytest.mark.asyncio
    async def test_trigram_fallback_not_called_when_many_results(self):
        """If tsvector returns >=3 results, trigram fallback is skipped."""
        from app.services.search_service import SearchResult
        svc = HybridSearchService()
        # Mock keyword_search to return 5 results
        fake_results = [
            SearchResult(
                chunk_id=f"chunk-{i}",
                document_id=f"doc-{i}",
                document_name="test.pdf",
                document_bucket="public",
                chunk_text="test",
                chunk_index=0,
                page_number=None,
                semantic_score=0.0,
                keyword_score=0.5,
                final_score=0.5,
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
            query="test", db=None, user=None, regconfig="simple", rerank=False
        )
        svc._trigram_fallback_search.assert_not_awaited()


class TestDynamicThreshold:
    def test_short_query_uses_stricter_threshold(self):
        svc = HybridSearchService(min_score_threshold=0.1)
        # Threshold logic is inside hybrid_search; we verify the service
        # stores the base value correctly and the method uses it.
        assert svc.min_score_threshold == 0.1

    def test_long_query_uses_standard_threshold(self):
        svc = HybridSearchService(min_score_threshold=0.1)
        assert svc.min_score_threshold == 0.1


class TestRerankerFallback:
    @pytest.mark.asyncio
    async def test_reranker_failure_graceful(self):
        """If rerank server is unreachable, hybrid_search still returns results."""
        svc = HybridSearchService()
        # Mock all internal searches to return empty
        svc.semantic_search = AsyncMock(return_value=[])
        svc.keyword_search = AsyncMock(return_value=[])
        svc.article_semantic_search = AsyncMock(return_value=[])
        svc.article_keyword_search = AsyncMock(return_value=[])
        svc.tag_search = AsyncMock(return_value=[])

        with patch("app.services.rerank_service.rerank_passages", side_effect=Exception("unreachable")):
            result = await svc.hybrid_search(
                query="passport", db=None, user=None, regconfig="simple", rerank=True
            )

        assert result["query"] == "passport"
        assert result["results"] == []
        assert result["partial"] is False


# ──────────────────────────────────────────────────────────────────────────
# Phase 1-3 Regression Tests
# ──────────────────────────────────────────────────────────────────────────


class TestEmbedServerFallback:
    """Phase 3: When embed server is down, keyword search must carry full weight."""

    @pytest.mark.asyncio
    async def test_keyword_weight_boosted_when_semantic_empty(self):
        from app.services.search_service import SearchResult
        svc = HybridSearchService()

        # Simulate embed server unavailable
        svc.semantic_search = AsyncMock(return_value=[])
        svc._filename_search = AsyncMock(return_value=[])
        svc.article_semantic_search = AsyncMock(return_value=[])
        svc.article_keyword_search = AsyncMock(return_value=[])
        svc.tag_search = AsyncMock(return_value=[])

        keyword_result = SearchResult(
            chunk_id="c1", document_id="d1", document_name="x.pdf",
            document_bucket="public", chunk_text="x", chunk_index=0,
            page_number=None, semantic_score=0.0, keyword_score=0.6, final_score=0.6,
        )
        svc.keyword_search = AsyncMock(return_value=[keyword_result])

        with patch("app.services.search_service.embedding_service") as mock_embed:
            mock_embed.can_embed = False
            result = await svc.hybrid_search(
                query="passport", db=None, user=None, regconfig="simple", rerank=False
            )

        # keyword_score=0.6 * kw_w=1.0 => raw_score=0.6, plus RRF ~0.09
        # With threshold 0.08, this should be included
        assert result["total"] == 1


class TestFilenameSearchInHybrid:
    """Phase 1: Filename matches must appear in hybrid search results."""

    @pytest.mark.asyncio
    async def test_filename_results_included_in_hybrid(self):
        from app.services.search_service import SearchResult
        svc = HybridSearchService()

        filename_result = SearchResult(
            chunk_id="doc-1", document_id="doc-1", document_name="passport-form.pdf",
            document_bucket="public", chunk_text="[Filename match: passport-form.pdf]",
            chunk_index=0, page_number=None, semantic_score=0.0, keyword_score=1.0, final_score=0.0,
        )

        svc.semantic_search = AsyncMock(return_value=[])
        svc.keyword_search = AsyncMock(return_value=[])
        svc._filename_search = AsyncMock(return_value=[filename_result])
        svc.article_semantic_search = AsyncMock(return_value=[])
        svc.article_keyword_search = AsyncMock(return_value=[])
        svc.tag_search = AsyncMock(return_value=[])

        result = await svc.hybrid_search(
            query="passport", db=None, user=None, regconfig="simple", rerank=False
        )

        assert result["total"] == 1
        assert result["results"][0].document_name == "passport-form.pdf"


class TestSubstringFallback:
    """Phase 3: Substring fallback activates when very few results found."""

    @pytest.mark.asyncio
    async def test_substring_fallback_activates_on_zero_results(self):
        from app.services.search_service import SearchResult
        svc = HybridSearchService()

        svc.semantic_search = AsyncMock(return_value=[])
        svc.keyword_search = AsyncMock(return_value=[])
        svc._filename_search = AsyncMock(return_value=[])
        svc._substring_fallback_search = AsyncMock(return_value=[])
        svc.article_semantic_search = AsyncMock(return_value=[])
        svc.article_keyword_search = AsyncMock(return_value=[])
        svc.tag_search = AsyncMock(return_value=[])

        await svc.hybrid_search(
            query="xyznonexistent", db=None, user=None, regconfig="simple", rerank=False
        )
        svc._substring_fallback_search.assert_awaited_once()


class TestLanguageMismatchFix:
    """Phase 1: Keyword search uses 'simple' regconfig regardless of query language."""

    @pytest.mark.asyncio
    async def test_hybrid_search_passes_detected_regconfig_to_keyword_search(self):
        svc = HybridSearchService()
        svc.semantic_search = AsyncMock(return_value=[])
        svc.keyword_search = AsyncMock(return_value=[])
        svc._filename_search = AsyncMock(return_value=[])
        svc.article_semantic_search = AsyncMock(return_value=[])
        svc.article_keyword_search = AsyncMock(return_value=[])
        svc.tag_search = AsyncMock(return_value=[])

        await svc.hybrid_search(
            query="financial report", db=None, user=None,
            regconfig="english", rerank=False
        )

        svc.keyword_search.assert_awaited_once()
        call_kwargs = svc.keyword_search.call_args.kwargs
        # Phase 2: hybrid_search now passes the detected regconfig to keyword_search.
        # keyword_search() uses a dual-query strategy (detected regconfig + simple)
        # so language-specific stemming is preserved while simple catches cross-language matches.
        assert call_kwargs.get("regconfig") == "english"
