import uuid
from dataclasses import asdict

import pytest

from app.services.smart_folder.analysis import AnalysisResult
from app.services.smart_folder.report_generator import (
    CHARS_PER_TOKEN,
    REPORT_CONTEXT_BUDGET_TOKENS,
    ReportGeneratorService,
    GeneratedReport,
    _allocate_doc_text,
    _estimate_tokens,
)
from app.services.smart_folder.retrieval import RetrievedAsset, RetrievalContext


class TestReportGeneratorService:
    """Unit tests for ReportGeneratorService (post-processing logic)."""

    @pytest.fixture
    def generator(self):
        return ReportGeneratorService()

    @pytest.fixture
    def sample_assets(self):
        doc_id_1 = uuid.uuid4()
        doc_id_2 = uuid.uuid4()
        return [
            RetrievedAsset(
                document_id=doc_id_1,
                document_name="Statement 2024.pdf",
                document_bucket="public",
                chunk_text="Account opened in March 2010.",
                score=0.95,
                retrieval_source="hybrid_search",
            ),
            RetrievedAsset(
                document_id=doc_id_2,
                document_name="Email thread.pdf",
                document_bucket="public",
                chunk_text="Disputed charge in January 2022.",
                score=0.88,
                retrieval_source="mention",
            ),
        ]

    def test_build_context_string(self, generator, sample_assets):
        """Test that context string is assembled correctly."""
        retrieval = RetrievalContext(
            primary_assets=sample_assets,
            query_used="Bank A relationship",
        )
        analysis = AnalysisResult(
            milestones=[
                {"date": "2010-03-15", "title": "Account opened", "description": "Opened savings account"}
            ],
            patterns=[{"description": "Monthly fee deducted", "confidence": 80}],
            trends=[],
            issues=[{"description": "Disputed charge 2022", "confidence": 90}],
            learnings=[{"description": "Always confirm fees", "confidence": 100}],
        )

        context = generator._build_context_string(
            entity_name="Bank A",
            query_text="Tell me about Bank A",
            retrieval_context=retrieval,
            analysis_result=analysis,
        )

        assert "Bank A" in context
        assert "Account opened" in context
        assert "Monthly fee deducted" in context
        assert "Disputed charge 2022" in context

    def test_build_citation_index(self, generator, sample_assets):
        """Test citation index building from report text."""
        doc_id = sample_assets[0].document_id
        data = {
            "summary": f"Account opened in 2010 [{doc_id}].",
            "patterns": [f"Fee deducted [{doc_id}]."],
        }
        retrieval = RetrievalContext(primary_assets=sample_assets)

        citation_index, source_ids = generator._build_citation_index(data, retrieval)

        assert len(citation_index) == 1
        assert str(doc_id) in citation_index
        assert citation_index[str(doc_id)]["number"] == 1
        assert citation_index[str(doc_id)]["preview"] == "Account opened in March 2010."
        assert doc_id in source_ids

    def test_renumber_citations(self, generator, sample_assets):
        """Test that [AssetID] is replaced with [N]."""
        doc_id = sample_assets[0].document_id
        data = {
            "summary": f"Account opened [{doc_id}].",
        }
        citation_index = {
            str(doc_id): {"number": 1, "asset_id": str(doc_id), "preview": "..."},
        }

        result = generator._renumber_citations(data, citation_index)

        assert result["summary"] == "Account opened [1]."

    def test_fallback_report(self, generator):
        """Test fallback report generation on failure."""
        report = generator._fallback_report("Some raw error text")

        assert isinstance(report, GeneratedReport)
        assert "could not be fully generated" in report.summary
        assert report.raw_markdown == "Some raw error text"


class TestTokenEstimation:
    """Tests for _estimate_tokens heuristic (now delegates to token_utils)."""

    def test_empty_text(self):
        assert _estimate_tokens("") == 0

    def test_default_fallback(self):
        # Default language is "fr" → 3.2 chars/token
        text = "a" * 38
        assert _estimate_tokens(text) == int(38 / 3.2)

    def test_french_text(self):
        # French fallback ≈ 3.2 chars/token (default language)
        text = "Le rapide renard brun saute par-dessus le chien paresseux."
        tokens = _estimate_tokens(text)
        assert tokens > 0
        assert tokens == int(len(text) / 3.2)


class TestAllocateDocText:
    """Tests for dynamic context budget allocation."""

    def test_even_split_across_docs(self):
        """Budget is divided evenly; each doc gets the same share."""
        docs = [
            {"document_id": "d1", "full_text": "a" * 10_000},
            {"document_id": "d2", "full_text": "b" * 10_000},
        ]
        budget_tokens = 1_000  # → 500 tokens each → 1750 chars each
        result = _allocate_doc_text(docs, budget_tokens)

        expected_chars = int(500 * CHARS_PER_TOKEN)
        assert result["d1"] == "a" * expected_chars
        assert result["d2"] == "b" * expected_chars

    def test_short_text_not_padded(self):
        """Docs shorter than their share are returned unchanged."""
        docs = [
            {"document_id": "d1", "full_text": "short"},
            {"document_id": "d2", "full_text": "x" * 10_000},
        ]
        result = _allocate_doc_text(docs, 1_000)

        assert result["d1"] == "short"
        assert len(result["d2"]) > len(result["d1"])

    def test_max_chars_per_doc_cap(self):
        """Optional max_chars_per_doc caps individual allocations."""
        docs = [
            {"document_id": "d1", "full_text": "a" * 50_000},
        ]
        budget_tokens = 10_000  # Would allow 35K chars without cap
        result = _allocate_doc_text(docs, budget_tokens, max_chars_per_doc=1_000)

        assert len(result["d1"]) == 1_000

    def test_empty_docs_list(self):
        assert _allocate_doc_text([], 1_000) == {}

    def test_many_docs_scales_down(self):
        """With many docs, per-doc share shrinks so total stays in budget."""
        docs = [{"document_id": f"d{i}", "full_text": "x" * 50_000} for i in range(50)]
        budget_tokens = 50_000
        result = _allocate_doc_text(docs, budget_tokens)

        total_chars = sum(len(t) for t in result.values())
        total_tokens = int(total_chars / CHARS_PER_TOKEN)
        # Allow small rounding slack (one doc's worth)
        assert total_tokens <= budget_tokens + (budget_tokens // len(docs))


class TestBuildContextStringBudgeting:
    """Tests that _build_context_string respects dynamic budgets."""

    @pytest.fixture
    def generator(self):
        return ReportGeneratorService()

    def test_direct_docs_budgeted(self, generator):
        """Direct evidence texts should be truncated according to the token budget."""
        # Use text large enough that it MUST be truncated even with only 2 docs
        # (2 docs × 28K tokens = 56K tokens total → 28K tokens each → 98K chars)
        # We use 150K chars so truncation definitely happens.
        docs = [
            {"document_id": "d1", "full_text": "A" * 150_000, "title": "Doc 1"},
            {"document_id": "d2", "full_text": "B" * 150_000, "title": "Doc 2"},
        ]
        retrieval = RetrievalContext(primary_assets=[])
        analysis = AnalysisResult()

        context = generator._build_context_string(
            entity_name="Test",
            query_text="query",
            retrieval_context=retrieval,
            analysis_result=analysis,
            full_documents=docs,
        )

        # Neither doc should appear in full
        assert "A" * 150_000 not in context
        assert "B" * 150_000 not in context
        # But both should appear
        assert "Doc 1" in context
        assert "Doc 2" in context

    def test_contextual_docs_budgeted(self, generator):
        """Contextual evidence texts should also be truncated."""
        # 1 contextual doc gets 24K tokens = 84K chars; use 150K to force truncation
        doc_id = uuid.UUID("12345678-1234-1234-1234-123456789abc")
        docs = [
            {"document_id": str(doc_id), "full_text": "X" * 150_000, "title": "Ctx 1"},
        ]
        # Force contextual by using a relation_path that does NOT start with "direct"
        asset = RetrievedAsset(
            document_id=doc_id,
            document_name="Ctx 1",
            document_bucket="public",
            chunk_text="...",
            score=0.5,
            retrieval_source="cooccurrence",
            relation_path="cooccurrence:subject",
        )
        retrieval = RetrievalContext(related_assets=[asset])
        analysis = AnalysisResult()

        context = generator._build_context_string(
            entity_name="Test",
            query_text="query",
            retrieval_context=retrieval,
            analysis_result=analysis,
            full_documents=docs,
        )

        assert "X" * 150_000 not in context
        assert "Ctx 1" in context
        assert "CONTEXTUAL EVIDENCE" in context

    def test_total_context_under_budget(self, generator):
        """The assembled context (excluding analysis tables) should stay under budget."""
        docs = [{"document_id": f"d{i}", "full_text": "x" * 30_000, "title": f"Doc {i}"}
                for i in range(25)]
        retrieval = RetrievalContext(primary_assets=[])
        analysis = AnalysisResult()

        context = generator._build_context_string(
            entity_name="Test",
            query_text="query",
            retrieval_context=retrieval,
            analysis_result=analysis,
            full_documents=docs,
        )

        # Budget = 100K tokens; we reserve 20% for non-doc content, so docs
        # should consume at most 80K tokens.
        doc_text = context.split("Instructions: Generate")[0]
        doc_tokens = _estimate_tokens(doc_text)
        assert doc_tokens <= int(REPORT_CONTEXT_BUDGET_TOKENS * 0.8) + 1000  # slack for headers
