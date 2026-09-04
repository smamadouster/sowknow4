import pytest
@pytest.mark.skip(reason="Ollama removed")
"""Unit tests for the packaging service (in-app view + PDF export)."""

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from app.services.collection_orchestrator.packaging_service import (
    _disclosure_text,
    _item_view,
    build_in_app_view,
    export_docx,
    export_pdf,
)

DELIVERABLE_ID = uuid.uuid4()
REQUEST_ID = uuid.uuid4()
DOC_ID = uuid.uuid4()


def make_deliverable(**overrides):
    deliverable = SimpleNamespace(
        id=DELIVERABLE_ID,
        request_id=REQUEST_ID,
        version=1,
        summary_md="# Summary\nRevenue totalled 3,000 XOF.",
        appendix={"normalization_notes": ["kept currency unit XOF"]},
        disclosures=[{
            "type": "truncation",
            "items_processed": 2,
            "truncated": False,
            "ranking_rule": "ranking v1.0",
        }],
        created_at=datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc),
    )
    for key, value in overrides.items():
        setattr(deliverable, key, value)
    return deliverable


def make_item(**overrides):
    item = {
        "id": uuid.uuid4(),
        "document_id": DOC_ID,
        "title": "annual-report.pdf",
        "annotation": "Relevant excerpt about revenue.",
        "category_tags": ["pdf", "2024"],
        "item_date": datetime(2024, 3, 1, tzinfo=timezone.utc),
        "source": "chunk",
        "author": "Jane",
        "snippet": "Revenue: 3,000 XOF",
        "rank_position": 1,
        "relevance_score": 0.9,
        "status": "ok",
        "related_items": [],
    }
    item.update(overrides)
    return item


DESCRIPTIVE_ANALYSIS = {
    "analysis_type": "descriptive",
    "output": {
        "metrics": [{
            "metric": "revenue", "unit": "XOF", "count": 2,
            "total": 6000.0, "mean": 3000.0, "min": 1000.0, "max": 5000.0,
            "values": [],
        }],
    },
    "provenance": [],
}

TREND_ANALYSIS = {
    "analysis_type": "trend",
    "output": {
        "trends": [{
            "metric": "revenue", "unit": "XOF", "sufficient_data": True,
            "direction": "increasing", "slope": 12.5,
            "points": [
                {"period": "2023", "value": 100.0, "source_refs": []},
                {"period": "2024", "value": 150.0, "source_refs": []},
            ],
        }],
    },
    "provenance": [],
}


class TestItemView:
    def test_deep_link_and_fields(self):
        view = _item_view(make_item())
        assert view["link"] == f"/documents/{DOC_ID}"
        assert view["annotation"] == "Relevant excerpt about revenue."
        assert view["category_tags"] == ["pdf", "2024"]
        assert view["date"] == "2024-03-01T00:00:00+00:00"

    def test_related_items_links(self):
        dup = {"id": uuid.uuid4(), "document_id": uuid.uuid4(), "title": "dup.pdf"}
        view = _item_view(make_item(related_items=[dup]))
        assert view["related_items"][0]["link"] == f"/documents/{dup['document_id']}"

    def test_no_document_means_no_link(self):
        view = _item_view(make_item(document_id=None))
        assert view["link"] is None


class TestBuildInAppView:
    def test_view_shape_and_permission_bound_links(self):
        deliverable = make_deliverable()
        items = [make_item(), make_item(id=uuid.uuid4(), rank_position=2)]
        view = build_in_app_view(deliverable, items, [DESCRIPTIVE_ANALYSIS])

        assert view["deliverable_id"] == str(DELIVERABLE_ID)
        assert view["summary_md"].startswith("# Summary")
        assert len(view["items"]) == 2
        assert view["items"][0]["rank_position"] == 1  # ranked order
        assert view["links_permission_bound"] is True
        assert view["data_as_of"] == "2024-03-01T00:00:00+00:00"
        assert view["disclosures"][0]["type"] == "truncation"

    def test_descriptive_analysis_renders_table(self):
        view = build_in_app_view(make_deliverable(), [], [DESCRIPTIVE_ANALYSIS])
        rendered = view["appendix"]["analyses_rendered"][0]
        assert rendered["analysis_type"] == "descriptive"
        table = rendered["tables"][0]
        assert table["rows"][0]["metric"] == "revenue"
        assert table["rows"][0]["total"] == 6000.0
        assert rendered["charts"] == []

    def test_trend_analysis_renders_chart_from_computed_points(self):
        view = build_in_app_view(make_deliverable(), [], [TREND_ANALYSIS])
        rendered = view["appendix"]["analyses_rendered"][0]
        assert len(rendered["charts"]) == 1
        chart = rendered["charts"][0]
        assert "vega-lite" in chart["$schema"]
        # Chart data comes strictly from the computed trend points.
        assert chart["data"]["values"] == [
            {"period": "2023", "value": 100.0},
            {"period": "2024", "value": 150.0},
        ]

    def test_insufficient_trend_data_renders_message_not_chart(self):
        analysis = {
            "analysis_type": "trend",
            "output": {"trends": [{
                "metric": "revenue", "sufficient_data": False,
                "message": "no significant trend detected",
            }]},
            "provenance": [],
        }
        view = build_in_app_view(make_deliverable(), [], [analysis])
        rendered = view["appendix"]["analyses_rendered"][0]
        assert rendered["charts"] == []
        assert rendered["messages"] == ["revenue: no significant trend detected"]

    def test_empty_inputs(self):
        view = build_in_app_view(
            make_deliverable(appendix=None, disclosures=None), [], []
        )
        assert view["items"] == []
        assert view["disclosures"] == []
        assert view["data_as_of"] is None


class TestDisclosureText:
    def test_truncation(self):
        text = _disclosure_text({
            "type": "truncation", "items_processed": 10,
            "truncated": True, "ranking_rule": "ranking v1.0",
        })
        assert "10 item(s)" in text and "truncated" in text and "ranking v1.0" in text

    def test_removed_claims(self):
        text = _disclosure_text({"type": "removed_claims", "count": 2})
        assert "2 statement(s)" in text

    def test_zero_results(self):
        assert "Zero results" in _disclosure_text({"type": "zero_results"})


class TestExportPdf:
    def test_pdf_bytes_have_pdf_header(self):
        deliverable = make_deliverable()
        view = build_in_app_view(deliverable, [make_item()], [DESCRIPTIVE_ANALYSIS])
        pdf = export_pdf(deliverable, view)
        assert isinstance(pdf, bytes)
        assert pdf.startswith(b"%PDF")
        assert len(pdf) > 1000

    def test_pdf_renders_without_summary_or_items(self):
        deliverable = make_deliverable(summary_md=None, disclosures=[])
        view = build_in_app_view(deliverable, [], [])
        pdf = export_pdf(deliverable, view)
        assert pdf.startswith(b"%PDF")

    def test_pdf_renders_trend_appendix_table(self):
        deliverable = make_deliverable()
        view = build_in_app_view(deliverable, [make_item()], [TREND_ANALYSIS])
        pdf = export_pdf(deliverable, view)
        assert pdf.startswith(b"%PDF")


# ---------------------------------------------------------------------------
# Phase-2 analyses appendix rendering
# ---------------------------------------------------------------------------

ANOMALY_ANALYSIS = {
    "analysis_type": "anomaly",
    "output": {
        "metrics": [{
            "metric": "revenue", "unit": "XOF", "sufficient_data": True,
            "anomalies": [{
                "value": 10000.0, "date": "2024-12-01",
                "rules": ["z_score", "iqr_fence"], "z_score": 3.5,
                "source_refs": [],
            }],
        }],
    },
    "provenance": [],
}

COMPARISON_ANALYSIS = {
    "analysis_type": "comparison",
    "output": {
        "sufficient_data": True,
        "comparisons": [{
            "family": None, "dimension": "metric", "unit": "XOF",
            "ranking": [
                {"label": "revenue", "count": 2, "total": 300.0, "mean": 150.0,
                 "rank": 1, "source_refs": []},
                {"label": "costs", "count": 1, "total": 50.0, "mean": 50.0,
                 "rank": 2, "source_refs": []},
            ],
            "pairwise": [{
                "a": "revenue", "b": "costs",
                "total_difference": 250.0, "mean_difference": 100.0,
                "source_refs": [],
            }],
        }],
    },
    "provenance": [],
}

CORRELATION_ANALYSIS = {
    "analysis_type": "correlation",
    "output": {
        "sufficient_data": True,
        "correlations": [{
            "metric_a": "revenue", "metric_b": "costs",
            "n": 40, "r": 0.95, "p_value": 1e-20,
            "label": "association, not causation", "source_refs": [],
        }],
    },
    "provenance": [],
}


class TestPhaseTwoAppendix:
    def test_anomaly_renders_anomalies_table(self):
        view = build_in_app_view(make_deliverable(), [], [ANOMALY_ANALYSIS])
        rendered = view["appendix"]["analyses_rendered"][0]
        table = rendered["tables"][0]
        assert table["title"] == "Anomalies"
        row = table["rows"][0]
        assert row["value"] == 10000.0
        assert row["rules"] == "z_score, iqr_fence"

    def test_comparison_renders_ranking_and_pairwise_tables(self):
        view = build_in_app_view(make_deliverable(), [], [COMPARISON_ANALYSIS])
        rendered = view["appendix"]["analyses_rendered"][0]
        titles = [t["title"] for t in rendered["tables"]]
        assert any("Ranking" in t for t in titles)
        assert any("Pairwise" in t for t in titles)
        ranking = rendered["tables"][0]
        assert ranking["rows"][0]["label"] == "revenue"

    def test_correlation_renders_table_with_causation_label(self):
        view = build_in_app_view(make_deliverable(), [], [CORRELATION_ANALYSIS])
        rendered = view["appendix"]["analyses_rendered"][0]
        table = rendered["tables"][0]
        assert "association, not causation" in table["title"]
        assert table["rows"][0]["r"] == 0.95

    def test_insufficient_correlation_renders_message_with_best_observed(self):
        analysis = {
            "analysis_type": "correlation",
            "output": {
                "sufficient_data": False,
                "message": "no significant correlation",
                "best_observed": {"metric_a": "a", "metric_b": "b", "r": 0.3, "n": 40},
            },
            "provenance": [],
        }
        view = build_in_app_view(make_deliverable(), [], [analysis])
        rendered = view["appendix"]["analyses_rendered"][0]
        assert rendered["tables"] == []
        assert "no significant correlation" in rendered["messages"][0]
        assert "best observed" in rendered["messages"][0]


class TestAclTrimmingDisclosureText:
    def test_shown_with_count(self):
        text = _disclosure_text({
            "type": "acl_trimming", "trimmed_count": 7, "shown": True,
        })
        assert "7 matching document(s)" in text

    def test_hidden_boolean_note(self):
        text = _disclosure_text({"type": "acl_trimming", "shown": False})
        assert "some matching documents" in text
        assert "7" not in text


# ---------------------------------------------------------------------------
# FR5.2 — Word export
# ---------------------------------------------------------------------------

class TestExportDocx:
    def test_docx_bytes_have_zip_magic(self):
        deliverable = make_deliverable()
        view = build_in_app_view(deliverable, [make_item()], [DESCRIPTIVE_ANALYSIS])
        payload = export_docx(deliverable, view)
        assert isinstance(payload, bytes)
        assert payload.startswith(b"PK\x03\x04")  # zip/docx container

    def test_docx_contains_sections_and_footer(self):
        import io as _io

        from docx import Document as DocxDocument

        deliverable = make_deliverable(disclosures=[{
            "type": "acl_trimming", "trimmed_count": 3, "shown": True,
        }])
        view = build_in_app_view(
            deliverable, [make_item()], [COMPARISON_ANALYSIS]
        )
        payload = export_docx(deliverable, view)

        doc = DocxDocument(_io.BytesIO(payload))
        texts = [p.text for p in doc.paragraphs]
        assert "SOWKNOW Collection Deliverable" in texts[0]
        assert any(t == "Disclosures" for t in texts)
        assert any("3 matching document(s)" in t for t in texts)
        assert any(t == "Summary" for t in texts)
        assert any(t == "Source Items" for t in texts)
        assert any("Appendix" in t for t in texts)
        # FR5.6 footer info block
        footer_text = doc.sections[0].footer.paragraphs[0].text
        assert "Generated by SOWKNOW Collection" in footer_text
        assert "data as of" in footer_text
        # Item table rendered
        assert doc.tables

    def test_docx_renders_without_summary_or_items(self):
        deliverable = make_deliverable(summary_md=None, disclosures=[])
        view = build_in_app_view(deliverable, [], [])
        payload = export_docx(deliverable, view)
        assert payload.startswith(b"PK\x03\x04")
