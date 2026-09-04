import pytest
@pytest.mark.skip(reason="Ollama removed")
"""Unit tests for query_planner (FR2.1/FR2.2/FR2.3) — pure, no I/O."""

from app.services.collection_orchestrator.query_planner import (
    MAX_PAGE_SIZE,
    SearchCallSpec,
    paginate,
    plan_searches,
)


def params(**overrides):
    base = {
        "query_text": "bank statements",
        "date_range": {"from": None, "to": None},
        "entities": [{"name": "Bank A", "type": "organization", "canonical_id": "1234", "confidence": 1.0}],
        "filters": {"doc_types": [], "tags": []},
        "sources": [],
        "analysis_types": ["descriptive"],
        "assumptions": [],
    }
    base.update(overrides)
    return base


class TestPlanSearches:
    def test_single_spec_without_doc_types(self):
        specs = plan_searches(params())
        assert len(specs) == 1
        spec = specs[0]
        assert spec.query_text == "bank statements"
        assert spec.doc_types == ()
        assert spec.limit == MAX_PAGE_SIZE
        assert spec.offset == 0

    def test_decomposition_per_doc_type(self):
        specs = plan_searches(params(filters={"doc_types": ["PDF", ".xlsx"], "tags": []}))
        assert len(specs) == 2
        assert {s.doc_types for s in specs} == {("pdf",), ("xlsx",)}
        # Same query, same offset — only the disjoint filter differs
        assert all(s.query_text == "bank statements" and s.offset == 0 for s in specs)

    def test_single_doc_type_not_decomposed(self):
        specs = plan_searches(params(filters={"doc_types": ["pdf"], "tags": []}))
        assert len(specs) == 1
        assert specs[0].doc_types == ("pdf",)

    def test_filters_carried_on_spec(self):
        specs = plan_searches(params(
            date_range={"from": "2020-01-01", "to": "2023-12-31"},
            filters={"doc_types": [], "tags": ["finance", "2021"]},
        ))
        spec = specs[0]
        assert spec.date_from == "2020-01-01"
        assert spec.date_to == "2023-12-31"
        assert spec.tags == ("finance", "2021")

    def test_query_falls_back_to_entity_names(self):
        specs = plan_searches(params(query_text=""))
        assert specs[0].query_text == "Bank A"

    def test_empty_query_and_entities_yields_no_specs(self):
        assert plan_searches(params(query_text="", entities=[])) == []

    def test_page_size_clamped_to_100(self):
        specs = plan_searches(params(), page_size=500)
        assert specs[0].limit == 100


class TestPaginate:
    def test_follow_up_pages(self):
        spec = SearchCallSpec(query_text="q", limit=100, offset=0)
        pages = paginate(spec, total=350, max_items=100000)
        assert [p.offset for p in pages] == [100, 200, 300]
        assert all(p.limit == 100 and p.query_text == "q" for p in pages)

    def test_no_pages_when_total_within_first_page(self):
        spec = SearchCallSpec(query_text="q", limit=100, offset=0)
        assert paginate(spec, total=100, max_items=100000) == []

    def test_hard_cap_stops_pagination(self):
        spec = SearchCallSpec(query_text="q", limit=100, offset=0)
        pages = paginate(spec, total=100000, max_items=250)
        assert [p.offset for p in pages] == [100, 200]

    def test_filters_preserved_on_follow_up_pages(self):
        spec = SearchCallSpec(
            query_text="q", doc_types=("pdf",), date_from="2020-01-01",
            date_to=None, tags=("finance",), limit=100, offset=0,
        )
        pages = paginate(spec, total=150, max_items=100000)
        assert pages[0].doc_types == ("pdf",)
        assert pages[0].tags == ("finance",)
        assert pages[0].date_from == "2020-01-01"
