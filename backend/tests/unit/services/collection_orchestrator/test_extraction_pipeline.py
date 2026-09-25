"""FR4.1 extraction pipeline tests — context gating, confidence routing,
unit normalisation, conflict precedence, unparseable handling."""

import pytest
pytest.skip("Disabled during Ollama removal (Sep 4)", allow_module_level=True)

from datetime import datetime, timezone

from app.services.collection_orchestrator.extraction_pipeline import (
    ExtractionPipeline,
)


@pytest.fixture
def pipeline():
    return ExtractionPipeline()


def _item(item_id, mime="text/plain", item_type="txt", doc=None):
    return {
        "id": item_id,
        "document_id": doc or f"doc-{item_id}",
        "mime_type": mime,
        "item_type": item_type,
    }


class TestContextGating:
    def test_bare_number_rejected_as_noise(self, pipeline):
        out = pipeline.extract(
            [_item("a")],
            {"a": "The meeting had 42 attendees, 7 laptops and 999 chairs."},
        )
        assert out["facts"] == []
        assert out["low_confidence"] == []
        # No facts at all -> content yielded nothing (FR6.6)
        assert out["unparseable"] == ["a"]

    def test_generic_colon_label_accepted(self, pipeline):
        out = pipeline.extract([_item("a")], {"a": "Subscriptions: 340"})
        facts = [f for f in out["facts"] if f["value"] is not None]
        assert len(facts) == 1
        assert facts[0]["name"] == "subscriptions"
        assert facts[0]["value"] == 340.0
        assert facts[0]["confidence"] == 0.75

    def test_keyword_label_without_colon_accepted(self, pipeline):
        out = pipeline.extract(
            [_item("a")], {"a": "Total revenue reached 5400 last quarter."}
        )
        facts = [f for f in out["facts"] if f["value"] is not None]
        assert len(facts) == 1
        assert facts[0]["name"] == "revenue"
        assert facts[0]["value"] == 5400.0

    def test_label_does_not_cross_sentence_boundary(self, pipeline):
        out = pipeline.extract(
            [_item("a")],
            {"a": "Growth of 12.5% was recorded. Random 999 888 appeared."},
        )
        names = [f["name"] for f in out["facts"]]
        # "999 888" sits in a different sentence from "growth" -> dropped
        assert all(
            f["value"] != 999888.0 for f in out["facts"] if f["value"] is not None
        )
        assert "growth" in names  # the percent fact only

    def test_table_cell_confidence_09(self, pipeline):
        text = "| Metric | Value |\n|---|---|\n| Revenue | 4,200 |\n"
        out = pipeline.extract([_item("a")], {"a": text})
        facts = [f for f in out["facts"] if f["value"] is not None]
        assert len(facts) == 1
        assert facts[0]["name"] == "revenue"
        assert facts[0]["value"] == 4200.0
        assert facts[0]["confidence"] == 0.9
        assert facts[0]["origin"] == "table"

    def test_csv_period_column_annotates_rows(self, pipeline):
        text = "Year,Revenue EUR\n2022,1000\n2023,1200\n"
        out = pipeline.extract(
            [_item("a", mime="text/csv", item_type="csv")], {"a": text}
        )
        facts = [f for f in out["facts"] if f["value"] is not None]
        assert {(f["name"], f["value"], f["unit"], f["date"]) for f in facts} == {
            ("revenue", 1000.0, "EUR", "2022"),
            ("revenue", 1200.0, "EUR", "2023"),
        }
        # Distinct periods -> no false conflict between the two rows
        assert out["conflicts"] == []


class TestConfidenceRouting:
    def test_ocr_facts_capped_and_routed_to_low_confidence(self, pipeline):
        out = pipeline.extract(
            [_item("img", mime="image/png", item_type="image")],
            {"img": "Revenue: 500 scanned figure"},
        )
        assert out["facts"] == []
        assert len(out["low_confidence"]) == 1
        fact = out["low_confidence"][0]
        assert fact["confidence"] == 0.6
        assert fact["origin"] == "ocr"

    def test_scanned_hint_also_capped(self, pipeline):
        out = pipeline.extract(
            [_item("s", mime="application/pdf", item_type="scanned_pdf")],
            {"s": "Headcount: 87"},
        )
        assert all(f["confidence"] <= 0.6 for f in out["low_confidence"])
        assert [f for f in out["facts"] if f["value"] is not None] == []

    def test_threshold_routing_respects_setting(self, pipeline):
        assert pipeline.confidence_threshold == 0.7
        out = pipeline.extract([_item("a")], {"a": "Revenue: 100"})
        # 0.75 >= 0.7 -> stays in facts (FR4.1.6)
        assert len(out["facts"]) == 1
        assert out["low_confidence"] == []


class TestUnitNormalisation:
    def test_thousands_separators_stripped_with_note(self, pipeline):
        out = pipeline.extract([_item("a")], {"a": "Revenue: 1,250,000"})
        fact = next(f for f in out["facts"] if f["value"] is not None)
        assert fact["value"] == 1250000.0
        assert any("stripped thousands separators" in n
                   for n in out["normalization_notes"])

    def test_percent_kept_on_0_100_base(self, pipeline):
        out = pipeline.extract([_item("a")], {"a": "Growth of 12.5% YoY."})
        fact = next(f for f in out["facts"] if f["value"] is not None)
        assert fact["unit"] == "%"
        assert fact["value"] == 12.5
        assert any("0-100 base" in n for n in out["normalization_notes"])

    def test_currency_code_kept_with_note(self, pipeline):
        out = pipeline.extract([_item("a")], {"a": "Total: 1,200 EUR"})
        fact = next(f for f in out["facts"] if f["value"] is not None)
        assert fact["unit"] == "EUR"
        assert fact["value"] == 1200.0
        assert any("kept currency unit EUR" in n
                   for n in out["normalization_notes"])

    def test_currency_symbol_mapped_to_code(self, pipeline):
        out = pipeline.extract([_item("a")], {"a": "Price: €42"})
        fact = next(f for f in out["facts"] if f["value"] is not None)
        assert fact["unit"] == "EUR"

    def test_fcfa_normalised_to_xof(self, pipeline):
        out = pipeline.extract([_item("a")], {"a": "Amount: 500 FCFA"})
        fact = next(f for f in out["facts"] if f["value"] is not None)
        assert fact["unit"] == "XOF"
        assert any("FCFA" in n for n in out["normalization_notes"])

    def test_mixed_currencies_flagged_never_converted(self, pipeline):
        items = [_item("a"), _item("b")]
        contents = {"a": "Revenue: 100 EUR", "b": "Revenue: 90 USD"}
        out = pipeline.extract(items, contents)
        assert any("mixed currencies" in n and "revenue" in n
                   for n in out["normalization_notes"])
        units = {f["unit"] for f in out["facts"] if f["name"] == "revenue"}
        assert units == {"EUR", "USD"}  # both kept, no conversion


class TestConflicts:
    def test_conflict_resolved_by_source_precedence(self, pipeline):
        items = [
            _item("csv", mime="text/csv", item_type="csv", doc="d-csv"),
            _item("pdf", mime="application/pdf", item_type="pdf", doc="d-pdf"),
        ]
        contents = {
            # Plain-text values in a .csv item (no table structure) and a
            # pdf item; same metric, same period, differing values.
            "csv": "System export. Revenue: 1000 for fiscal 2024.",
            "pdf": "Official report. Revenue: 1200 for fiscal 2024.",
        }
        out = pipeline.extract(items, contents)
        revenue = [f for f in out["facts"]
                   if f["name"] == "revenue" and f["value"] is not None]
        assert len(revenue) == 1
        assert revenue[0]["value"] == 1000.0  # csv/xlsx tier beats pdf
        assert len(out["conflicts"]) == 1
        conflict = out["conflicts"][0]
        assert conflict["winner"]["value"] == 1000.0
        assert conflict["loser"]["value"] == 1200.0
        assert conflict["winner"]["source_ref"]["document_id"] == "d-csv"
        assert conflict["loser"]["source_ref"]["document_id"] == "d-pdf"
        assert "source_precedence" in conflict["rule"]

    def test_conflict_never_silent(self, pipeline):
        items = [_item("a", doc="d1"), _item("b", doc="d2")]
        contents = {
            "a": "Headcount: 87 in 2024.",
            "b": "Headcount: 90 in 2024.",
        }
        out = pipeline.extract(items, contents)
        assert len(out["conflicts"]) == 1
        # Both source_refs disclosed for the deliverable appendix
        conflict = out["conflicts"][0]
        assert conflict["winner"]["source_ref"] != conflict["loser"]["source_ref"]

    def test_same_precedence_class_resolved_by_recency(self, pipeline):
        # pdf vs pdf: source precedence says nothing — the most recent
        # item_date wins, and the rule string says so (no double spaces).
        items = [
            {
                **_item("old", mime="application/pdf", item_type="pdf", doc="d-old"),
                "item_date": datetime(2023, 6, 1, tzinfo=timezone.utc),
            },
            {
                **_item("new", mime="application/pdf", item_type="pdf", doc="d-new"),
                "item_date": datetime(2024, 6, 1, tzinfo=timezone.utc),
            },
        ]
        contents = {
            "old": "Report. Revenue: 1000 for fiscal 2024.",
            "new": "Report. Revenue: 1200 for fiscal 2024.",
        }
        out = pipeline.extract(items, contents)
        assert len(out["conflicts"]) == 1
        conflict = out["conflicts"][0]
        assert conflict["winner"]["value"] == 1200.0  # newer item wins
        assert conflict["winner"]["source_ref"]["document_id"] == "d-new"
        assert conflict["rule"] == (
            "same source class 'application/pdf pdf': "
            "most recent item_date preferred"
        )
        assert "  " not in conflict["rule"]

    def test_same_class_rule_string_has_no_double_space_without_mime(self, pipeline):
        # The Phase-1 bug: "source_precedence:  pdf preferred over  pdf".
        items = [
            {
                **_item("a", mime="", item_type="pdf", doc="d1"),
                "item_date": datetime(2023, 1, 1, tzinfo=timezone.utc),
            },
            {
                **_item("b", mime="", item_type="pdf", doc="d2"),
                "item_date": datetime(2024, 1, 1, tzinfo=timezone.utc),
            },
        ]
        contents = {"a": "Revenue: 100 in 2024.", "b": "Revenue: 200 in 2024."}
        out = pipeline.extract(items, contents)
        conflict = out["conflicts"][0]
        assert "  " not in conflict["rule"]
        assert "'pdf'" in conflict["rule"]


class TestDatesAndUnparseable:
    def test_date_forms_extracted(self, pipeline):
        out = pipeline.extract(
            [_item("a")],
            {"a": "Filed 2024-03-12, signed 15/04/2024, dated March 2024."},
        )
        dates = {f["date"] for f in out["facts"] if f["name"] == "date"}
        assert "2024-03-12" in dates
        assert "2024-04-15" in dates
        assert "2024-03-01" in dates
        assert all(
            f["confidence"] == 0.8 for f in out["facts"] if f["name"] == "date"
        )

    def test_numeric_fact_picks_up_neighbouring_date(self, pipeline):
        out = pipeline.extract(
            [_item("a")], {"a": "Revenue: 5400 in 2023."}
        )
        fact = next(f for f in out["facts"] if f["value"] is not None)
        assert fact["date"] == "2023"

    def test_empty_content_is_unparseable(self, pipeline):
        out = pipeline.extract([_item("a"), _item("b")], {"a": "   ", "b": None})
        assert sorted(out["unparseable"]) == ["a", "b"]
        assert out["facts"] == []

    def test_chunk_dicts_with_page_and_id(self, pipeline):
        out = pipeline.extract(
            [_item("a", doc="d1")],
            {"a": [{"text": "Revenue: 100", "chunk_id": "c9", "page": 4}]},
        )
        fact = out["facts"][0]
        assert fact["source_ref"] == {
            "document_id": "d1", "chunk_id": "c9", "page": 4,
        }
