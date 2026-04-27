import json
from datetime import datetime, timezone

import pytest

from app.services.smart_folder.query_parser import QueryParserService, ParsedQuery


class TestQueryParserService:
    """Unit tests for QueryParserService."""

    @pytest.fixture
    def parser(self):
        return QueryParserService()

    @pytest.mark.asyncio
    async def test_parse_extracts_entity_and_relationship(self, monkeypatch, parser):
        """Test that parse correctly extracts entity and relationship type."""

        async def mock_generate(*args, **kwargs):
            yield json.dumps({
                "primary_entity": "Bank A",
                "relationship_type": "institutional",
                "temporal_scope_description": "all time",
                "time_range_start": None,
                "time_range_end": None,
                "focus_aspects": ["financial"],
            })

        monkeypatch.setattr(
            "app.services.smart_folder.query_parser.llm_router.generate_completion",
            mock_generate,
        )

        result = await parser.parse("Tell me about my relationship with Bank A")

        assert isinstance(result, ParsedQuery)
        assert result.primary_entity == "Bank A"
        assert result.relationship_type == "institutional"
        assert result.focus_aspects == ["financial"]
        assert result.temporal_scope_description == "all time"

    @pytest.mark.asyncio
    async def test_parse_handles_dates(self, monkeypatch, parser):
        """Test that parse correctly parses ISO date strings."""

        async def mock_generate(*args, **kwargs):
            yield json.dumps({
                "primary_entity": "Jane",
                "relationship_type": "personal",
                "temporal_scope_description": "2020-2023",
                "time_range_start": "2020-01-01T00:00:00Z",
                "time_range_end": "2023-12-31T23:59:59Z",
                "focus_aspects": [],
            })

        monkeypatch.setattr(
            "app.services.smart_folder.query_parser.llm_router.generate_completion",
            mock_generate,
        )

        result = await parser.parse("My friend Jane from 2020 to 2023")

        assert result.primary_entity == "Jane"
        assert result.relationship_type == "personal"
        assert result.time_range_start == datetime(2020, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        assert result.time_range_end == datetime(2023, 12, 31, 23, 59, 59, tzinfo=timezone.utc)

    @pytest.mark.asyncio
    async def test_parse_handles_invalid_json(self, monkeypatch, parser):
        """Test graceful handling of invalid LLM output."""

        async def mock_generate(*args, **kwargs):
            yield "not valid json"

        monkeypatch.setattr(
            "app.services.smart_folder.query_parser.llm_router.generate_completion",
            mock_generate,
        )

        result = await parser.parse("Some query")

        assert result.primary_entity is None
        assert result.raw_json is not None
        assert "error" in result.raw_json

    @pytest.mark.asyncio
    async def test_parse_strips_markdown_fences(self, monkeypatch, parser):
        """Test that markdown code fences are stripped from LLM output."""

        async def mock_generate(*args, **kwargs):
            yield '```json\n{"primary_entity": "X", "relationship_type": "general"}\n```'

        monkeypatch.setattr(
            "app.services.smart_folder.query_parser.llm_router.generate_completion",
            mock_generate,
        )

        result = await parser.parse("Test")

        assert result.primary_entity == "X"
        assert result.relationship_type == "general"
