"""Tests for Smart Collections v2 pipeline."""

import pytest


class TestCollectionQueueRouting:
    """build_smart_collection must be routed to the collections queue."""

    def test_task_routed_to_collections_queue(self):
        from app.celery_app import celery_app

        routes = celery_app.conf.task_routes
        assert "build_smart_collection" in routes
        assert routes["build_smart_collection"]["queue"] == "collections"


class TestStage1Understand:
    """Stage 1: Intent parsing always uses MiniMax, never Ollama."""

    @pytest.mark.asyncio
    async def test_understand_uses_minimax_not_ollama(self):
        """Intent parsing must pass use_ollama=False."""
        from unittest.mock import AsyncMock, patch

        from app.services.collection_service import collection_service
        from app.services.intent_parser import ParsedIntent

        mock_intent = ParsedIntent(
            query="test", keywords=["test"], collection_name="Test", confidence=0.9,
        )
        with patch.object(
            collection_service.intent_parser, "parse_intent",
            new_callable=AsyncMock, return_value=mock_intent,
        ) as mock_parse:
            await collection_service._understand_query("Find financial documents")
            mock_parse.assert_called_once()
            assert mock_parse.call_args.kwargs.get("use_ollama") is False

    @pytest.mark.asyncio
    async def test_understand_retries_on_low_confidence(self):
        """If confidence < 0.5, must retry."""
        from unittest.mock import patch

        from app.services.collection_service import collection_service
        from app.services.intent_parser import ParsedIntent

        low = ParsedIntent(query="xyz", keywords=[], collection_name="", confidence=0.3)
        good = ParsedIntent(query="xyz", keywords=["xyz"], collection_name="XYZ", confidence=0.7)

        call_count = [0]

        async def _mock(*args, **kwargs):
            call_count[0] += 1
            return low if call_count[0] == 1 else good

        with patch.object(collection_service.intent_parser, "parse_intent", side_effect=_mock):
            intent, _ = await collection_service._understand_query("xyz")
            assert call_count[0] >= 2
            assert intent.confidence >= 0.5

    @pytest.mark.asyncio
    async def test_understand_entity_strategy(self):
        """Entities present -> entity_first strategy."""
        from unittest.mock import AsyncMock, patch

        from app.services.collection_service import collection_service
        from app.services.intent_parser import ParsedIntent

        intent = ParsedIntent(
            query="Ndakhte Mboup", keywords=["Ndakhte", "Mboup"],
            entities=[{"type": "person", "name": "Ndakhte Mboup"}],
            collection_name="Ndakhte Mboup", confidence=0.9,
        )
        with patch.object(collection_service.intent_parser, "parse_intent",
                          new_callable=AsyncMock, return_value=intent):
            _, strategy = await collection_service._understand_query("Ndakhte Mboup")
            assert strategy == "entity_first"

    @pytest.mark.asyncio
    async def test_understand_date_strategy(self):
        """Date range present -> date_filtered strategy."""
        from unittest.mock import AsyncMock, patch

        from app.services.collection_service import collection_service
        from app.services.intent_parser import ParsedIntent

        intent = ParsedIntent(
            query="docs from 2024", keywords=["docs"],
            date_range={"type": "this_year"}, collection_name="2024 Docs", confidence=0.9,
        )
        with patch.object(collection_service.intent_parser, "parse_intent",
                          new_callable=AsyncMock, return_value=intent):
            _, strategy = await collection_service._understand_query("docs from 2024")
            assert strategy == "date_filtered"

    @pytest.mark.asyncio
    async def test_understand_broad_strategy(self):
        """No entities, no date -> broad_hybrid strategy."""
        from unittest.mock import AsyncMock, patch

        from app.services.collection_service import collection_service
        from app.services.intent_parser import ParsedIntent

        intent = ParsedIntent(
            query="solar energy", keywords=["solar", "energy"],
            collection_name="Solar Energy", confidence=0.9,
        )
        with patch.object(collection_service.intent_parser, "parse_intent",
                          new_callable=AsyncMock, return_value=intent):
            _, strategy = await collection_service._understand_query("solar energy")
            assert strategy == "broad_hybrid"


class TestStage2GatherAndVerify:
    """Stage 2: Articles-first search with quality gates and retry."""

    @pytest.mark.asyncio
    async def test_gather_calls_article_searches(self):
        """Must call both article search methods."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from app.services.collection_service import collection_service
        from app.services.intent_parser import ParsedIntent

        intent = ParsedIntent(query="solar", keywords=["solar"], collection_name="Solar", confidence=0.9)

        with patch.object(collection_service.search_service, "article_semantic_search",
                          new_callable=AsyncMock, return_value=[]) as mock_as, \
             patch.object(collection_service.search_service, "article_keyword_search",
                          new_callable=AsyncMock, return_value=[]) as mock_ak, \
             patch.object(collection_service.search_service, "semantic_search",
                          new_callable=AsyncMock, return_value=[]), \
             patch.object(collection_service.search_service, "keyword_search",
                          new_callable=AsyncMock, return_value=[]), \
             patch.object(collection_service.search_service, "tag_search",
                          new_callable=AsyncMock, return_value=[]):
            await collection_service._gather_and_verify(intent, "broad_hybrid", MagicMock(), MagicMock())
            mock_as.assert_called()
            mock_ak.assert_called()

    @pytest.mark.asyncio
    async def test_gather_retries_on_few_results(self):
        """If < 3 results, must retry with broader search."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from app.services.collection_service import collection_service
        from app.services.intent_parser import ParsedIntent

        intent = ParsedIntent(query="rare topic", keywords=["rare"], collection_name="Rare", confidence=0.9)
        call_count = [0]

        async def _count(*a, **k):
            call_count[0] += 1
            return []

        with patch.object(collection_service.search_service, "article_semantic_search",
                          new_callable=AsyncMock, side_effect=_count), \
             patch.object(collection_service.search_service, "article_keyword_search",
                          new_callable=AsyncMock, return_value=[]), \
             patch.object(collection_service.search_service, "semantic_search",
                          new_callable=AsyncMock, return_value=[]), \
             patch.object(collection_service.search_service, "keyword_search",
                          new_callable=AsyncMock, return_value=[]), \
             patch.object(collection_service.search_service, "tag_search",
                          new_callable=AsyncMock, return_value=[]):
            await collection_service._gather_and_verify(intent, "broad_hybrid", MagicMock(), MagicMock())
            assert call_count[0] >= 2, "Should retry on few results"

    @pytest.mark.asyncio
    async def test_gather_prefers_articles_over_chunks(self):
        """Same document: article result should win over chunk result."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from app.services.collection_service import collection_service
        from app.services.intent_parser import ParsedIntent

        article_r = MagicMock()
        article_r.document_id = "doc-1"
        article_r.article_id = "art-1"
        article_r.article_title = "Solar Report"
        article_r.article_summary = "Analysis of solar..."
        article_r.document_name = "solar.pdf"
        article_r.final_score = 0.8
        article_r.semantic_score = 0.8
        article_r.keyword_score = 0
        article_r.result_type = "article"

        chunk_r = MagicMock()
        chunk_r.document_id = "doc-1"
        chunk_r.article_id = None
        chunk_r.article_title = None
        chunk_r.article_summary = None
        chunk_r.document_name = "solar.pdf"
        chunk_r.final_score = 0.9
        chunk_r.semantic_score = 0.9
        chunk_r.keyword_score = 0
        chunk_r.result_type = "chunk"

        extra1 = MagicMock(document_id="doc-2", article_id=None, article_title=None,
                          article_summary=None, document_name="b.pdf", final_score=0.5,
                          semantic_score=0.5, keyword_score=0, result_type="chunk")
        extra2 = MagicMock(document_id="doc-3", article_id=None, article_title=None,
                          article_summary=None, document_name="c.pdf", final_score=0.4,
                          semantic_score=0.4, keyword_score=0, result_type="chunk")

        intent = ParsedIntent(query="solar", keywords=["solar"], collection_name="Solar", confidence=0.9)

        with patch.object(collection_service.search_service, "article_semantic_search",
                          new_callable=AsyncMock, return_value=[article_r]), \
             patch.object(collection_service.search_service, "article_keyword_search",
                          new_callable=AsyncMock, return_value=[]), \
             patch.object(collection_service.search_service, "semantic_search",
                          new_callable=AsyncMock, return_value=[chunk_r]), \
             patch.object(collection_service.search_service, "keyword_search",
                          new_callable=AsyncMock, return_value=[extra1, extra2]), \
             patch.object(collection_service.search_service, "tag_search",
                          new_callable=AsyncMock, return_value=[]):
            results = await collection_service._gather_and_verify(intent, "broad_hybrid", MagicMock(), MagicMock())

        # doc-1 should appear once with article preferred
        doc1_results = [r for r in results if r["document_id"] == "doc-1"]
        assert len(doc1_results) == 1
        assert doc1_results[0]["article_id"] == "art-1"
