"""FR4.2 summary generator tests — empty-insights guard, prompt structure,
numeric formatting."""

import pytest

from app.services.collection_orchestrator import summary_generator
from app.services.collection_orchestrator.summary_generator import (
    SECTIONS,
    SummaryGenerator,
    format_number,
)


@pytest.fixture
def generator():
    return SummaryGenerator()


def _insights():
    return [
        {
            "statement": "Revenue totalled 3,000 across the period",
            "source_refs": [{"document_id": "d1", "chunk_id": "c1", "page": 3,
                             "title": "Annual Report"}],
            "validation_status": "validated",
        }
    ]


def _analyses():
    return [
        {
            "analysis_type": "descriptive",
            "output": {"metrics": [{"metric": "revenue", "total": 3000.0}]},
            "provenance": [{"document_id": "d1", "chunk_id": "c1", "page": 3}],
        }
    ]


class TestEmptyInsights:
    @pytest.mark.asyncio
    async def test_no_llm_call_and_none_returned(self, generator, monkeypatch):
        def _boom(*args, **kwargs):  # pragma: no cover - must not be called
            raise AssertionError("llm_router called with empty insights")

        monkeypatch.setattr(
            summary_generator.llm_router, "generate_completion", _boom
        )
        result = await generator.generate([], [], {}, {})
        assert result is None


class TestPromptStructure:
    @pytest.mark.asyncio
    async def test_segments_sections_and_rules(self, generator, monkeypatch):
        captured = {}

        async def mock_generate(messages, **kwargs):
            captured["messages"] = messages
            captured["kwargs"] = kwargs
            yield "generated summary"

        monkeypatch.setattr(
            summary_generator.llm_router, "generate_completion", mock_generate
        )
        result = await generator.generate(
            _insights(), _analyses(), {"query": "revenue overview"}, {}
        )
        assert result == "generated summary"

        system, user = captured["messages"]
        assert system["role"] == "system"
        assert user["role"] == "user"

        # FR7.1 injection defence: delimited data segments + explicit rule
        assert "<verified_data" in user["content"]
        assert "</verified_data>" in user["content"]
        assert "never instructions" in system["content"]

        # FR4.2.2 sections mandated in both system rules and user request
        for section in SECTIONS:
            assert section in system["content"]
            assert section in user["content"]

        # FR4.2.3 citation format and FR4.2.4 no-extrapolation rule
        assert "([source: <title>, <page-or-ref>])" in system["content"]
        assert "association, not causation" in system["content"]

        # STANDARD tier, joined chunks
        from app.services.llm_router import TaskTier
        assert captured["kwargs"]["tier"] == TaskTier.STANDARD

    @pytest.mark.asyncio
    async def test_chunks_are_joined(self, generator, monkeypatch):
        async def mock_generate(messages, **kwargs):
            yield "part-"
            yield "one"

        monkeypatch.setattr(
            summary_generator.llm_router, "generate_completion", mock_generate
        )
        result = await generator.generate(_insights(), [], {}, {})
        assert result == "part-one"


class TestFormatNumber:
    def test_thousands_separators(self):
        assert format_number(1250000) == "1,250,000"
        assert format_number(3000.0) == "3,000"

    def test_percent_one_decimal(self):
        assert format_number(12.49, "%") == "12.5%"
        assert format_number(12.0, "%") == "12.0%"

    def test_non_integer_float_two_decimals(self):
        assert format_number(1234.5) == "1,234.50"

    def test_iso_date_passthrough(self):
        assert format_number("2024-03-01") == "2024-03-01"

    def test_none_renders_na(self):
        assert format_number(None) == "n/a"
