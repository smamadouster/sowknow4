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
