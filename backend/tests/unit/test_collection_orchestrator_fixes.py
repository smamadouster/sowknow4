"""
Unit tests for the 2026-08-04 collection fixes:

- Focused retrieval query: build_confirmed_params derives ``search_query``
  from the parsed focus aspects / entities instead of the raw request
  sentence, and plan_searches uses it for the search calls.
- ZIP export: memo (md/pdf/docx) + the actual source files + index.json,
  with graceful skipping of missing/oversized files.
"""

import io
import json
import zipfile
from uuid import uuid4


class _FakeSession:
    """Minimal stand-in for a ClarificationSession row (JSONB columns only)."""

    def __init__(self, rounds, entities, analysis_types=None, assumptions=None):
        self.rounds = rounds
        self.extracted_entities = entities
        self.analysis_types = analysis_types or ["descriptive"]
        self.assumptions = assumptions or []


class TestFocusedSearchQuery:
    def _build(self, session):
        from app.services.collection_orchestrator.conversation_manager import (
            ConversationManager,
        )

        return ConversationManager().build_confirmed_params(session)

    def test_search_query_derived_from_focus_aspects(self):
        session = _FakeSession(
            rounds=[
                {
                    "round": 1,
                    "extraction": {
                        "focus_aspects": ["salaires", "rémunération"],
                        "time_range_start": None,
                        "time_range_end": None,
                    },
                    "answers": [],
                }
            ],
            entities=[],
        )
        params = self._build(session)
        assert params["search_query"] == "salaires rémunération"

    def test_search_query_falls_back_to_entity_names(self):
        session = _FakeSession(
            rounds=[
                {
                    "round": 1,
                    "extraction": {"focus_aspects": [], "time_range_start": None, "time_range_end": None},
                    "answers": [],
                }
            ],
            entities=[
                {
                    "name": "Jean Dupont",
                    "type": "person",
                    "canonical_id": "x",
                    "confidence": 1.0,
                    "status": "applied",
                    "raw_name": "Jean Dupont",
                }
            ],
        )
        params = self._build(session)
        assert params["search_query"] == "Jean Dupont"

    def test_search_query_none_when_nothing_to_derive(self):
        session = _FakeSession(
            rounds=[
                {
                    "round": 1,
                    "extraction": {"focus_aspects": [], "time_range_start": None, "time_range_end": None},
                    "answers": [],
                }
            ],
            entities=[],
        )
        params = self._build(session)
        assert params["search_query"] is None

    def test_plan_searches_uses_focused_search_query_not_raw_sentence(self):
        from app.services.collection_orchestrator.query_planner import plan_searches

        specs = plan_searches(
            {
                "query_text": "me réunir tous les dossiers concernants les salaires",
                "search_query": "salaires",
                "entities": [],
                "filters": {},
                "date_range": {},
            }
        )
        assert specs, "expected at least one spec"
        assert specs[0].query_text == "salaires"

    def test_plan_searches_falls_back_to_raw_query_text(self):
        from app.services.collection_orchestrator.query_planner import plan_searches

        specs = plan_searches(
            {
                "query_text": "me réunir tous les dossiers concernants les salaires",
                "search_query": None,
                "entities": [],
                "filters": {},
                "date_range": {},
            }
        )
        assert specs[0].query_text == "me réunir tous les dossiers concernants les salaires"


class _FakeDeliverable:
    summary_md = "# Memo\n\nUn test."
    id = "d1"
    request_id = "r1"
    version = 1
    created_at = None
    appendix = {}
    disclosures = []


class _FakeDoc:
    def __init__(self, path):
        self.file_path = path


def _view(doc_ids):
    return {
        "request_id": "r1",
        "deliverable_id": "d1",
        "version": 1,
        "summary_md": "# Memo",
        "items": [
            {
                "document_id": doc_id,
                "title": f"doc_{idx}.pdf",
                "relevance_score": 0.9 - idx * 0.1,
                "rank_position": idx + 1,
            }
            for idx, doc_id in enumerate(doc_ids)
        ],
        "appendix": {},
        "disclosures": [],
    }


class TestExportZip:
    def test_bundles_memo_files_and_index(self, tmp_path):
        from app.services.collection_orchestrator.packaging_service import export_zip

        src = tmp_path / "salaire_2024.pdf"
        src.write_bytes(b"%PDF-1.4 fake content")
        doc_id = str(uuid4())
        data = export_zip(_FakeDeliverable(), _view([doc_id]), {doc_id: _FakeDoc(str(src))})
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = zf.namelist()
            assert "memo.md" in names
            assert "memo.pdf" in names
            assert "index.json" in names
            assert any(n.startswith("source/") for n in names)
            index = json.loads(zf.read("index.json"))
            assert index["source_files"]["included"], "expected the source file"
            assert index["items"], "expected the item list"
            # python-docx is not installed in the unit-test venv, so memo.docx
            # is gracefully skipped — that is the intended fallback, not a bug.
            skipped_names = [s["name"] for s in index["source_files"]["skipped"]]
            assert set(skipped_names) <= {"memo.docx"}

    def test_skips_missing_source_file(self, tmp_path):
        from app.services.collection_orchestrator.packaging_service import export_zip

        doc_id = str(uuid4())
        missing = str(tmp_path / "nope.pdf")
        data = export_zip(_FakeDeliverable(), _view([doc_id]), {doc_id: _FakeDoc(missing)})
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            index = json.loads(zf.read("index.json"))
            assert index["source_files"]["included"] == []
            assert any("not found" in s["reason"] for s in index["source_files"]["skipped"])
            assert "memo.md" in zf.namelist()


class TestRichMemo:
    """2026-08-04 rich memo: source items feed the narrative, numbers stay
    grounded."""

    def test_summary_prompt_includes_source_items(self):
        from app.services.collection_orchestrator.summary_generator import SummaryGenerator

        gen = SummaryGenerator()
        messages = gen._build_messages(
            [{"statement": "total: 100", "source_refs": [{"document_id": "a"}]}],
            [],
            {"query_text": "salaires"},
            {},
            source_items=[
                {"title": "Doc A", "document_id": "a", "snippet": "Le total est 100 XOF."}
            ],
        )
        joined = messages[-1]["content"]
        assert 'kind="source_items"' in joined
        assert "Doc A" in joined

    def test_validator_accepts_source_cited_number(self):
        from app.services.collection_orchestrator.grounding_validator import GroundingValidator

        analyses = [{"output": {"total": 100}}]
        insights = [{"statement": "total 100", "source_refs": []}]
        source_refs = [{"title": "Salaire 2024.pdf", "document_id": "doc-1"}]
        md = "Le salaire total est 100 XOF ([source: Salaire 2024.pdf])."
        report = GroundingValidator().validate(md, analyses, insights, source_refs)
        assert report.passed, report.failed_claims

    def test_validator_still_strips_ungrounded_number(self):
        from app.services.collection_orchestrator.grounding_validator import GroundingValidator

        analyses = [{"output": {"total": 100}}]
        insights = [{"statement": "total 100", "source_refs": []}]
        # 999 is NOT in the computed set -> numeric failure, stripped.
        md = "Le montant est 999 XOF ([source: Salaire 2024.pdf])."
        report = GroundingValidator().validate(md, analyses, insights, [])
        assert not report.passed
        assert report.numeric_failures
