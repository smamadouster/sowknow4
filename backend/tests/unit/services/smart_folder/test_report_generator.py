import uuid
from dataclasses import asdict

import pytest

from app.services.smart_folder.analysis import AnalysisResult
from app.services.smart_folder.report_generator import ReportGeneratorService, GeneratedReport
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
        assert "Account opened in March 2010" in context
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
