import pytest
@pytest.mark.skip(reason="Ollama removed")
"""Unit tests for PipelineRunner — all services and DB mocked."""

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.collection_orchestrator import (
    AnalysisResult,
    Annotation,
    Deliverable,
    FactSet,
    Insight,
    QueryExecution,
    SourceItem,
)
from app.services.collection_orchestrator.pipeline_runner import (
    PipelineRunner,
    TooManyJobsError,
)
from app.services.collection_orchestrator.search_adapter import SearchUnavailableError

USER_ID = uuid.uuid4()
FOLDER_ID = uuid.uuid4()
DOC_ID_1 = uuid.uuid4()
DOC_ID_2 = uuid.uuid4()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def one(value):
    mock = MagicMock()
    mock.scalar_one_or_none.return_value = value
    return mock


def many(values):
    mock = MagicMock()
    mock.scalars.return_value.all.return_value = values
    return mock


def first(value):
    mock = MagicMock()
    mock.scalars.return_value.first.return_value = value
    return mock


def count(value):
    mock = MagicMock()
    mock.scalar_one.return_value = value
    return mock


def make_folder(**overrides):
    folder = SimpleNamespace(
        id=FOLDER_ID,
        user_id=USER_ID,
        query_text="revenue of Bank A in 2024",
        job_state="queued",
        confirmed_params={
            "date_range": {"from": "2024-01-01", "to": "2024-12-31"},
            "entities": [{"name": "Bank A", "type": "organization"}],
            "filters": {"doc_types": [], "tags": []},
            "sources": [],
            "analysis_types": ["descriptive"],
            "assumptions": [],
        },
        celery_task_id="task-1",
        error_message=None,
        checkpoint=None,
    )
    for key, value in overrides.items():
        setattr(folder, key, value)
    return folder


def make_item(doc_id=DOC_ID_1, snippet="Revenue: 1,200 XOF in 2024", score=0.8):
    return {
        "document_id": str(doc_id),
        "chunk_id": str(uuid.uuid4()),
        "uri": f"/data/{str(doc_id)[:4]}.pdf",
        "title": f"doc-{str(doc_id)[:4]}.pdf",
        "item_type": "pdf",
        "source": "chunk",
        "author": None,
        "item_date": datetime(2024, 3, 1, tzinfo=timezone.utc),
        "relevance_score": score,
        "snippet": snippet,
        "acl_stamp": "public",
        "page_number": 1,
        "status": "ok",
    }


def make_row(item):
    return SimpleNamespace(
        id=uuid.uuid4(),
        document_id=uuid.UUID(item["document_id"]),
        snippet=item["snippet"],
        content_hash=None,
        simhash=None,
        canonical_id=None,
        rank_position=None,
        relevance_score=item["relevance_score"],
        status="ok",
    )


def make_execution(status="completed", error=None, result_count=2):
    return {
        "request_id": str(FOLDER_ID),
        "search_call_payload": {"query_text": "q", "limit": 100, "offset": 0},
        "started_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "duration_ms": 42,
        "result_count": result_count,
        "status": status,
        "error": error,
    }


def make_db(responses, folder=None):
    """AsyncMock db; ``responses`` is the ordered list of execute() results."""
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=list(responses))
    db.state_history = []
    real_commit = AsyncMock(
        side_effect=lambda: db.state_history.append(folder.job_state) if folder else None
    )
    db.commit = real_commit
    return db


def make_runner(items, executions, *, extraction=None, analyses=None,
                summary_md="# Summary\nTotal 3,000 XOF.", removed=None):
    adapter = MagicMock()
    adapter.execute_plan = AsyncMock(return_value=(items, executions))
    adapter.last_run_meta = {"truncated": False, "cache_hit": False, "total_items": len(items)}

    processor = MagicMock()

    def _dedup(all_items):
        for index, item in enumerate(all_items):
            item["content_hash"] = f"hash{index}"
            item["simhash"] = f"{index:016x}"
        return list(all_items), {}

    processor.dedup = MagicMock(side_effect=_dedup)

    async def _rank(ranked_items, query, **kwargs):
        for position, item in enumerate(ranked_items, start=1):
            item["rank_position"] = position
            item["ranking_detail"] = {"version": "1.0", "final_score": 1.0 - position * 0.1}
        return ranked_items

    processor.rank = AsyncMock(side_effect=_rank)

    async def _annotate(ranked_items, confirmed_params, user, **kwargs):
        return [
            {
                "item_index": i,
                "annotation_text": f"annotation {i}",
                "category_tags": ["pdf", "2024"],
                "evidence_offsets": [],
                "rank_position": item.get("rank_position"),
            }
            for i, item in enumerate(ranked_items)
        ]

    processor.annotate = AsyncMock(side_effect=_annotate)

    extractor = MagicMock()
    extractor.extract = MagicMock(return_value=extraction or {
        "facts": [{
            "name": "revenue", "value": 3000.0, "unit": "XOF", "date": "2024",
            "source_ref": {"document_id": str(DOC_ID_1), "chunk_id": None, "page": 1},
            "confidence": 0.9, "origin": "table", "raw": "3000",
        }],
        "low_confidence": [],
        "unparseable": [],
        "normalization_notes": ["kept currency unit XOF"],
        "conflicts": [],
    })

    engine = MagicMock()
    engine.run = MagicMock(return_value=analyses if analyses is not None else [{
        "analysis_type": "descriptive",
        "inputs": {"fact_count": 1, "metrics": ["revenue"]},
        "output": {
            "metrics": [{
                "metric": "revenue", "unit": "XOF", "count": 1,
                "total": 3000.0, "mean": 3000.0, "min": 3000.0, "max": 3000.0,
                "values": [{"value": 3000.0, "date": "2024",
                            "source_refs": [{"document_id": str(DOC_ID_1)}]}],
            }],
        },
        "thresholds_used": {},
        "provenance": [{"document_id": str(DOC_ID_1)}],
        "code_version": "1.0.0",
    }])

    summariser = MagicMock()
    summariser.generate = AsyncMock(return_value=summary_md)

    validator = MagicMock()
    validator.validate_with_regeneration = AsyncMock(return_value=(
        summary_md,
        SimpleNamespace(passed=True, checked_claims=1, failed_claims=[], numeric_failures=[]),
        removed or [],
    ))

    runner = PipelineRunner(
        search_adapter=adapter,
        result_processor=processor,
        extraction_pipeline=extractor,
        analysis_engine=engine,
        summary_generator=summariser,
        grounding_validator=validator,
    )
    return runner


def added_of_type(db, model):
    return [
        call.args[0]
        for call in db.add.call_args_list
        if isinstance(call.args[0], model)
    ]


def standard_responses(folder, user, rows):
    """Execute-result sequence for a full happy-path run."""
    return [
        one(folder), count(0), one(user), many(rows),
        count(None),  # FR5.5: next-deliverable-version probe at packaging
    ]


USER = SimpleNamespace(id=USER_ID, email="u@example.com")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestHappyPath:
    @pytest.mark.asyncio
    async def test_full_run_completes_and_persists_everything(self):
        items = [make_item(), make_item(DOC_ID_2, "Costs: 500 EUR in 2024", 0.7)]
        rows = [make_row(it) for it in items]
        executions = [make_execution()]
        folder = make_folder()
        db = make_db(standard_responses(folder, USER, rows), folder)

        runner = make_runner(items, executions)
        result = await runner.run(FOLDER_ID, USER_ID, db)

        assert result["status"] == "completed"
        assert folder.job_state == "completed"
        assert len(added_of_type(db, QueryExecution)) == 1
        assert len(added_of_type(db, SourceItem)) == 2
        assert len(added_of_type(db, FactSet)) == 1
        assert len(added_of_type(db, AnalysisResult)) == 1
        assert len(added_of_type(db, Insight)) == 1
        assert len(added_of_type(db, Annotation)) == 2
        deliverables = added_of_type(db, Deliverable)
        assert len(deliverables) == 1
        assert deliverables[0].summary_md == "# Summary\nTotal 3,000 XOF."
        assert deliverables[0].item_list_ref == f"api://collection-requests/{FOLDER_ID}/items"
        assert result["deliverable_id"] == str(deliverables[0].id)

    @pytest.mark.asyncio
    async def test_job_state_transitions_in_order(self):
        items = [make_item()]
        rows = [make_row(items[0])]
        folder = make_folder()
        db = make_db(standard_responses(folder, USER, rows), folder)

        runner = make_runner(items, [make_execution()])
        await runner.run(FOLDER_ID, USER_ID, db)

        # Committed states must walk the pipeline in order.
        assert db.state_history == [
            "searching",     # retrieve start
            "processing",    # retrieve done
            "analysing",     # process done
            "analysing",     # extract done
            "summarising",   # analyse done
            "packaging",     # summarise done
            "completed",     # package done
        ]

    @pytest.mark.asyncio
    async def test_checkpoint_records_last_stage(self):
        items = [make_item()]
        rows = [make_row(items[0])]
        folder = make_folder()
        db = make_db(standard_responses(folder, USER, rows), folder)

        runner = make_runner(items, [make_execution()])
        await runner.run(FOLDER_ID, USER_ID, db)

        assert folder.checkpoint["last_stage"] == "package"
        assert "deliverable_id" in folder.checkpoint["stage_outputs_refs"]

    @pytest.mark.asyncio
    async def test_rank_positions_and_scores_persisted(self):
        items = [make_item(), make_item(DOC_ID_2, "Costs: 500 EUR", 0.6)]
        rows = [make_row(it) for it in items]
        folder = make_folder()
        db = make_db(standard_responses(folder, USER, rows), folder)

        runner = make_runner(items, [make_execution()])
        await runner.run(FOLDER_ID, USER_ID, db)

        assert rows[0].rank_position == 1
        assert rows[1].rank_position == 2
        assert rows[0].relevance_score == pytest.approx(0.9)
        assert rows[0].content_hash == "hash0"


class TestRetrieveFailures:
    @pytest.mark.asyncio
    async def test_search_unavailable_marks_job_failed(self):
        folder = make_folder()
        db = make_db([one(folder), count(0), one(USER), first(None)], folder)

        runner = make_runner([], [])
        runner.search_adapter.execute_plan = AsyncMock(
            side_effect=SearchUnavailableError("all specs failed")
        )
        result = await runner.run(FOLDER_ID, USER_ID, db)

        assert folder.job_state == "failed"
        assert "all specs failed" in folder.error_message
        assert result["status"] == "failed"
        assert not added_of_type(db, Deliverable)

    @pytest.mark.asyncio
    async def test_partial_spec_failure_records_degraded_disclosure(self):
        items = [make_item()]
        rows = [make_row(items[0])]
        executions = [make_execution(), make_execution(status="failed", error="timeout")]
        folder = make_folder()
        db = make_db(standard_responses(folder, USER, rows), folder)

        runner = make_runner(items, executions)
        await runner.run(FOLDER_ID, USER_ID, db)

        deliverable = added_of_type(db, Deliverable)[0]
        degraded = [d for d in deliverable.disclosures if d["type"] == "degraded_sources"]
        assert degraded and degraded[0]["failed_queries"][0]["error"] == "timeout"
        # Failed execution rows are persisted too (payload carries the error).
        executions_rows = added_of_type(db, QueryExecution)
        assert any(e.status == "failed" for e in executions_rows)


class TestZeroResult:
    @pytest.mark.asyncio
    async def test_zero_results_completes_without_summary(self):
        folder = make_folder()
        db = make_db([
            one(folder), count(0), one(USER),
            count(None),  # next-deliverable-version probe (zero-result package)
            first(None),
        ], folder)

        runner = make_runner([], [make_execution(result_count=0)])
        result = await runner.run(FOLDER_ID, USER_ID, db)

        assert folder.job_state == "completed"
        assert result["status"] == "completed"
        deliverable = added_of_type(db, Deliverable)[0]
        assert deliverable.summary_md is None
        assert deliverable.appendix["outcome"] == "zero_results"
        assert deliverable.appendix["relaxation_suggestions"]
        assert deliverable.appendix["executed_queries"]
        # FR6.1 — the summary generator is never invoked on zero results.
        runner.summary_generator.generate.assert_not_called()
        assert not added_of_type(db, FactSet)


class TestIdempotentReentry:
    @pytest.mark.asyncio
    async def test_terminal_state_returns_without_work(self):
        folder = make_folder(job_state="completed")
        deliverable = SimpleNamespace(id=uuid.uuid4())
        db = make_db([one(folder), first(deliverable)], folder)

        runner = make_runner([make_item()], [make_execution()])
        result = await runner.run(FOLDER_ID, USER_ID, db)

        assert result["status"] == "completed"
        assert result["deliverable_id"] == str(deliverable.id)
        runner.search_adapter.execute_plan.assert_not_called()
        assert not added_of_type(db, SourceItem)

    @pytest.mark.asyncio
    async def test_missing_folder_raises(self):
        db = make_db([one(None)])
        runner = make_runner([], [])
        with pytest.raises(ValueError, match="not found"):
            await runner.run(FOLDER_ID, USER_ID, db)


class TestConcurrencyGuard:
    @pytest.mark.asyncio
    async def test_too_many_active_jobs_raises(self):
        folder = make_folder()
        db = make_db([one(folder), count(3)], folder)  # default max is 3

        runner = make_runner([make_item()], [make_execution()])
        with pytest.raises(TooManyJobsError):
            await runner.run(FOLDER_ID, USER_ID, db)
        runner.search_adapter.execute_plan.assert_not_called()

    @pytest.mark.asyncio
    async def test_below_limit_proceeds(self):
        items = [make_item()]
        rows = [make_row(items[0])]
        folder = make_folder()
        db = make_db(standard_responses(folder, USER, rows), folder)

        runner = make_runner(items, [make_execution()])
        result = await runner.run(FOLDER_ID, USER_ID, db)
        assert result["status"] == "completed"


class TestExtract:
    @pytest.mark.asyncio
    async def test_unparseable_items_marked_content_unavailable(self):
        items = [make_item()]
        rows = [make_row(items[0])]
        folder = make_folder()
        db = make_db(standard_responses(folder, USER, rows), folder)

        extraction = {
            "facts": [],
            "low_confidence": [],
            "unparseable": [str(rows[0].id)],
            "normalization_notes": [],
            "conflicts": [],
        }
        analyses = [{
            "analysis_type": "descriptive",
            "inputs": {"fact_count": 0, "metrics": []},
            "output": {"metrics": []},
            "thresholds_used": {},
            "provenance": [],
            "code_version": "1.0.0",
        }]
        runner = make_runner(items, [make_execution()], extraction=extraction,
                             analyses=analyses)
        await runner.run(FOLDER_ID, USER_ID, db)

        assert rows[0].status == "content_unavailable"  # FR6.6


class TestSummarise:
    @pytest.mark.asyncio
    async def test_no_insights_means_no_fabricated_summary(self):
        items = [make_item()]
        rows = [make_row(items[0])]
        folder = make_folder()
        db = make_db(standard_responses(folder, USER, rows), folder)

        analyses = [{
            "analysis_type": "descriptive",
            "inputs": {"fact_count": 0, "metrics": []},
            "output": {"metrics": []},   # no metrics → no insights
            "thresholds_used": {},
            "provenance": [],
            "code_version": "1.0.0",
        }]
        runner = make_runner(items, [make_execution()], analyses=analyses)
        await runner.run(FOLDER_ID, USER_ID, db)

        runner.summary_generator.generate.assert_not_called()
        deliverable = added_of_type(db, Deliverable)[0]
        assert deliverable.summary_md is None
        assert any(d["type"] == "no_summary" for d in deliverable.disclosures)

    @pytest.mark.asyncio
    async def test_removed_claims_append_disclosure_footer(self):
        items = [make_item()]
        rows = [make_row(items[0])]
        folder = make_folder()
        db = make_db(standard_responses(folder, USER, rows), folder)

        runner = make_runner(
            items, [make_execution()],
            summary_md="# Summary\nGrounded text.",
            removed=["Ungrounded claim 42."],
        )
        await runner.run(FOLDER_ID, USER_ID, db)

        deliverable = added_of_type(db, Deliverable)[0]
        assert "1 statement(s) were removed" in deliverable.summary_md  # FR4.2.5
        removed = [d for d in deliverable.disclosures if d["type"] == "removed_claims"]
        assert removed and removed[0]["sentences"] == ["Ungrounded claim 42."]


class TestPackage:
    @pytest.mark.asyncio
    async def test_truncation_disclosure_carries_ranking_rule(self):
        items = [make_item()]
        rows = [make_row(items[0])]
        folder = make_folder()
        db = make_db(standard_responses(folder, USER, rows), folder)

        runner = make_runner(items, [make_execution()])
        runner.search_adapter.last_run_meta = {
            "truncated": True, "cache_hit": False, "total_items": 100,
        }
        await runner.run(FOLDER_ID, USER_ID, db)

        deliverable = added_of_type(db, Deliverable)[0]
        truncation = [d for d in deliverable.disclosures if d["type"] == "truncation"]
        assert truncation and truncation[0]["truncated"] is True
        assert "ranking v1.0" in truncation[0]["ranking_rule"]
        assert truncation[0]["items_processed"] == 1

    @pytest.mark.asyncio
    async def test_appendix_carries_analyses_conflicts_and_notes(self):
        items = [make_item()]
        rows = [make_row(items[0])]
        folder = make_folder()
        db = make_db(standard_responses(folder, USER, rows), folder)

        extraction = {
            "facts": [{"name": "revenue", "value": 1.0, "unit": "XOF", "date": "2024",
                       "source_ref": {}, "confidence": 0.9, "origin": "text", "raw": "1"}],
            "low_confidence": [{"name": "costs"}],
            "unparseable": [],
            "normalization_notes": ["note A"],
            "conflicts": [{"name": "revenue", "rule": "source_precedence"}],
        }
        runner = make_runner(items, [make_execution()], extraction=extraction)
        await runner.run(FOLDER_ID, USER_ID, db)

        deliverable = added_of_type(db, Deliverable)[0]
        assert deliverable.appendix["low_confidence_fact_count"] == 1
        assert deliverable.appendix["normalization_notes"] == ["note A"]
        assert deliverable.appendix["conflicts"][0]["name"] == "revenue"
        assert deliverable.appendix["links_permission_bound"] is True
        conflict_disc = [d for d in deliverable.disclosures if d["type"] == "conflicts"]
        assert conflict_disc and conflict_disc[0]["count"] == 1


# ---------------------------------------------------------------------------
# Phase 2 — full-row factory (all SourceItem fields, for resume paths)
# ---------------------------------------------------------------------------

def make_full_row(item, *, rank_position=None, status="ok"):
    return SimpleNamespace(
        id=uuid.uuid4(),
        request_id=FOLDER_ID,
        document_id=uuid.UUID(item["document_id"]),
        uri=item["uri"],
        title=item["title"],
        item_type=item["item_type"],
        source=item["source"],
        author=item["author"],
        item_date=item["item_date"],
        relevance_score=item["relevance_score"],
        snippet=item["snippet"],
        acl_stamp=item["acl_stamp"],
        content_hash=None,
        simhash=None,
        canonical_id=None,
        rank_position=rank_position,
        status=status,
    )


def make_execution_row():
    return SimpleNamespace(
        search_call_payload={"query_text": "q", "limit": 100, "offset": 0},
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        duration_ms=42,
        result_count=2,
        status="completed",
    )


def audit_events(db, action):
    return [
        call.args[0]
        for call in db.add.call_args_list
        if type(call.args[0]).__name__ == "CollectionAuditEvent"
        and call.args[0].action == action
    ]


class TestAnalysisBudget:
    @pytest.mark.asyncio
    async def test_budget_excludes_overflow_and_marks_rows(self, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "COLLECTION_ANALYSIS_BUDGET", 1)
        items = [make_item(), make_item(DOC_ID_2, "Costs: 500 EUR in 2024", 0.7)]
        rows = [make_row(it) for it in items]
        folder = make_folder()
        db = make_db(standard_responses(folder, USER, rows), folder)

        runner = make_runner(items, [make_execution()])
        result = await runner.run(FOLDER_ID, USER_ID, db)

        assert result["status"] == "completed"
        # Only the top-1 by rank_position was annotated.
        annotate_items = runner.result_processor.annotate.await_args.args[0]
        assert len(annotate_items) == 1
        assert rows[0].status == "ok"
        assert rows[1].status == "excluded_budget"  # still listed, not analysed
        # Only the budget set produced Annotation rows.
        assert len(added_of_type(db, Annotation)) == 1

    @pytest.mark.asyncio
    async def test_truncation_disclosure_carries_budget_keys(self, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "COLLECTION_ANALYSIS_BUDGET", 1)
        items = [make_item(), make_item(DOC_ID_2, "Costs: 500 EUR in 2024", 0.7)]
        rows = [make_row(it) for it in items]
        folder = make_folder()
        db = make_db(standard_responses(folder, USER, rows), folder)

        runner = make_runner(items, [make_execution()])
        await runner.run(FOLDER_ID, USER_ID, db)

        deliverable = added_of_type(db, Deliverable)[0]
        truncation = [d for d in deliverable.disclosures if d["type"] == "truncation"]
        assert truncation
        assert truncation[0]["items_retrieved"] == 2
        assert truncation[0]["items_processed"] == 1
        assert truncation[0]["items_gated"] == 0
        assert truncation[0]["analysis_budget"] == 1
        # Existing keys preserved (frontend compat).
        assert truncation[0]["truncated"] is False
        assert "cache_hit" in truncation[0]
        assert "ranking_rule" in truncation[0]


class TestPartialDeliverable:
    @pytest.mark.asyncio
    async def test_summarise_failure_packages_partial_deliverable(self):
        items = [make_item()]
        rows = [make_row(items[0])]
        folder = make_folder()
        db = make_db(standard_responses(folder, USER, rows), folder)

        runner = make_runner(items, [make_execution()])
        runner.grounding_validator.validate_with_regeneration = AsyncMock(
            side_effect=RuntimeError("LLM outage")
        )
        result = await runner.run(FOLDER_ID, USER_ID, db)

        # FR6.8: the job completes with a partial deliverable.
        assert result["status"] == "completed"
        assert folder.job_state == "completed"
        deliverable = added_of_type(db, Deliverable)[0]
        assert deliverable.summary_md is None
        assert deliverable.appendix["analyses"]  # computed analyses shipped
        no_summary = [d for d in deliverable.disclosures if d["type"] == "no_summary"]
        assert no_summary
        assert "summary unavailable" in no_summary[0]["message"]
        assert audit_events(db, "summary_failed_partial")


class TestCheckpointResume:
    @pytest.mark.asyncio
    async def test_failed_job_resumes_after_retrieve_without_research(self):
        items = [make_item(), make_item(DOC_ID_2, "Costs: 500 EUR in 2024", 0.7)]
        rows = [make_full_row(it) for it in items]
        folder = make_folder(
            job_state="failed",
            error_message="All 1 search spec(s) failed permanently — search unavailable",
            checkpoint={
                "last_stage": "retrieve",
                "stage_outputs_refs": {"query_executions": 1, "source_items": 2},
                "retry_count": 1,
            },
        )
        db = make_db([
            one(folder),            # _load_folder
            count(0),               # concurrency guard
            one(USER),              # user
            count(2),               # resume probe: SourceItem count
            many(rows),             # reload SourceItems
            many([make_execution_row()]),  # reload QueryExecutions
            many(rows),             # _stage_process SourceItem reload
            count(None),              # next-deliverable-version probe
        ], folder)

        runner = make_runner(items, [make_execution()])
        result = await runner.run(FOLDER_ID, USER_ID, db)

        assert result["status"] == "completed"
        # Retrieve was NOT re-paid — no search, no new SourceItem rows.
        runner.search_adapter.execute_plan.assert_not_called()
        assert not added_of_type(db, SourceItem)
        assert folder.error_message is None  # stale failure cleared
        resumed = audit_events(db, "job_resumed")
        assert resumed and resumed[0].detail["from_stage"] == "retrieve"
        assert resumed[0].detail["retry_count"] == 1

    @pytest.mark.asyncio
    async def test_resume_from_analyse_skips_to_summarise(self):
        items = [make_item()]
        rows = [make_full_row(items[0], rank_position=1)]
        factset = SimpleNamespace(
            id=uuid.uuid4(),
            facts=[{
                "name": "revenue", "value": 3000.0, "unit": "XOF",
                "date": "2024", "source_ref": {"document_id": str(DOC_ID_1)},
                "confidence": 0.9, "origin": "table", "raw": "3000",
            }],
            normalization_notes=["kept currency unit XOF"],
        )
        analysis_row = SimpleNamespace(
            analysis_type="descriptive",
            inputs={"fact_count": 1, "metrics": ["revenue"]},
            output={
                "metrics": [{
                    "metric": "revenue", "unit": "XOF", "count": 1,
                    "total": 3000.0, "mean": 3000.0, "min": 3000.0, "max": 3000.0,
                    "values": [{"value": 3000.0, "date": "2024",
                                "source_refs": [{"document_id": str(DOC_ID_1)}]}],
                }],
            },
            thresholds_used={},
            provenance=[{"document_id": str(DOC_ID_1)}],
            code_version="1.1.0",
        )
        folder = make_folder(
            job_state="failed",
            error_message="crash during summarise",
            checkpoint={"last_stage": "analyse", "stage_outputs_refs": {}},
        )
        db = make_db([
            one(folder),               # _load_folder
            count(0),                  # concurrency guard
            one(USER),                 # user
            count(1),                  # resume probe: AnalysisResult count
            many(rows),                # reload SourceItems
            many([make_execution_row()]),  # reload QueryExecutions
            many(rows),                # _reload_processed
            first(factset),            # _reload_extraction
            many([analysis_row]),      # _reload_analyses
            count(None),                 # next-deliverable-version probe
        ], folder)

        runner = make_runner(items, [make_execution()])
        runner.extraction_pipeline.confidence_threshold = 0.7
        result = await runner.run(FOLDER_ID, USER_ID, db)

        assert result["status"] == "completed"
        # Retrieve/process/extract/analyse were all reloaded, not re-run.
        runner.search_adapter.execute_plan.assert_not_called()
        runner.extraction_pipeline.extract.assert_not_called()
        runner.analysis_engine.run.assert_not_called()
        # …but the summary and deliverable were (re)built.
        assert not added_of_type(db, FactSet)
        assert not added_of_type(db, AnalysisResult)
        assert not added_of_type(db, Insight)
        assert len(added_of_type(db, Deliverable)) == 1

    @pytest.mark.asyncio
    async def test_resume_degrades_to_fresh_run_when_rows_missing(self):
        items = [make_item()]
        rows = [make_row(items[0])]
        folder = make_folder(
            job_state="failed",
            checkpoint={"last_stage": "retrieve", "stage_outputs_refs": {}},
        )
        db = make_db([
            one(folder),   # _load_folder
            count(0),      # concurrency guard
            one(USER),     # user
            count(0),      # resume probe: no SourceItems persisted
            many(rows),    # _stage_process SourceItem reload (fresh path)
            count(None),   # next-deliverable-version probe
        ], folder)

        runner = make_runner(items, [make_execution()])
        result = await runner.run(FOLDER_ID, USER_ID, db)

        assert result["status"] == "completed"
        runner.search_adapter.execute_plan.assert_awaited_once()  # re-ran retrieve
        assert not audit_events(db, "job_resumed")

    @pytest.mark.asyncio
    async def test_cancelled_job_never_resumes(self):
        folder = make_folder(
            job_state="cancelled",
            checkpoint={"last_stage": "retrieve", "stage_outputs_refs": {}},
        )
        deliverable = SimpleNamespace(id=uuid.uuid4())
        db = make_db([one(folder), first(deliverable)], folder)

        runner = make_runner([make_item()], [make_execution()])
        result = await runner.run(FOLDER_ID, USER_ID, db)

        assert result["status"] == "cancelled"
        runner.search_adapter.execute_plan.assert_not_called()


class TestCooperativeCancel:
    @pytest.mark.asyncio
    async def test_cancel_between_stages_aborts_cleanly(self):
        items = [make_item()]
        folder = make_folder()
        db = make_db([
            one(folder),   # _load_folder
            count(0),      # concurrency guard
            one(USER),     # user
            first(None),   # _status_dict deliverable lookup after abort
        ], folder)
        # The cancel endpoint flipped job_state in its own session; the
        # stage-boundary refresh picks it up.
        db.refresh = AsyncMock(
            side_effect=lambda obj: setattr(obj, "job_state", "cancelled")
        )

        runner = make_runner(items, [make_execution()])
        result = await runner.run(FOLDER_ID, USER_ID, db)

        assert result["status"] == "cancelled"
        assert folder.job_state == "cancelled"
        runner.search_adapter.execute_plan.assert_awaited_once()  # retrieve ran
        # …but nothing downstream did.
        runner.result_processor.dedup.assert_not_called()
        assert not added_of_type(db, FactSet)
        assert not added_of_type(db, Deliverable)
        cancelled = audit_events(db, "job_cancelled")
        assert cancelled and cancelled[0].detail["last_stage"] == "retrieve"


class TestTrimmedCountDisclosure:
    @pytest.mark.asyncio
    async def test_acl_trimming_disclosure_with_count(self):
        items = [make_item()]
        rows = [make_row(items[0])]
        folder = make_folder()
        db = make_db(standard_responses(folder, USER, rows), folder)

        runner = make_runner(items, [make_execution()])
        runner.search_adapter.last_run_meta = {
            "truncated": False, "cache_hit": False, "total_items": 1,
            "acl_trimmed_count": 7,
        }
        await runner.run(FOLDER_ID, USER_ID, db)

        deliverable = added_of_type(db, Deliverable)[0]
        disclosure = [d for d in deliverable.disclosures if d["type"] == "acl_trimming"]
        assert disclosure
        assert disclosure[0]["trimmed_count"] == 7
        assert disclosure[0]["shown"] is True

    @pytest.mark.asyncio
    async def test_acl_trimming_count_hidden_when_setting_disabled(self, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "COLLECTION_SHOW_TRIMMED_COUNT", False)
        items = [make_item()]
        rows = [make_row(items[0])]
        folder = make_folder()
        db = make_db(standard_responses(folder, USER, rows), folder)

        runner = make_runner(items, [make_execution()])
        runner.search_adapter.last_run_meta = {
            "truncated": False, "cache_hit": False, "total_items": 1,
            "acl_trimmed_count": 7,
        }
        await runner.run(FOLDER_ID, USER_ID, db)

        deliverable = added_of_type(db, Deliverable)[0]
        disclosure = [d for d in deliverable.disclosures if d["type"] == "acl_trimming"]
        assert disclosure
        assert disclosure[0]["shown"] is False
        assert "trimmed_count" not in disclosure[0]  # boolean note only
        assert disclosure[0]["message"]

    @pytest.mark.asyncio
    async def test_no_trimming_no_disclosure(self):
        items = [make_item()]
        rows = [make_row(items[0])]
        folder = make_folder()
        db = make_db(standard_responses(folder, USER, rows), folder)

        runner = make_runner(items, [make_execution()])
        await runner.run(FOLDER_ID, USER_ID, db)

        deliverable = added_of_type(db, Deliverable)[0]
        assert not [d for d in deliverable.disclosures if d["type"] == "acl_trimming"]


class TestInsightStatements:
    """Statement templates rendered from computed analysis outputs."""

    def test_descriptive_metric_named_total_not_duplicated(self):
        analysis = {
            "analysis_type": "descriptive",
            "output": {
                "metrics": [{
                    "metric": "total", "unit": "XOF", "count": 4,
                    "total": 1501271426, "mean": 375317856.5,
                    "min": 11, "max": 700000000,
                    "values": [{"value": 11, "date": "2024",
                                "source_refs": [{"document_id": "d1"}]}],
                }],
            },
        }
        [insight] = PipelineRunner._insights_for_analysis(analysis)
        statement = insight["statement"]
        assert "total: total" not in statement
        assert statement.startswith("total 1,501,271,426 XOF across 4 values")
        assert "(min 11, max 700,000,000)" in statement
        assert insight["source_refs"] == [{"document_id": "d1"}]

    def test_descriptive_named_metric_template(self):
        analysis = {
            "analysis_type": "descriptive",
            "output": {
                "metrics": [{
                    "metric": "revenue", "unit": "XOF", "count": 1,
                    "total": 3000.0, "mean": 3000.0, "min": 3000.0, "max": 3000.0,
                    "values": [{"value": 3000.0, "date": "2024", "source_refs": []}],
                }],
            },
        }
        [insight] = PipelineRunner._insights_for_analysis(analysis)
        assert insight["statement"] == (
            "revenue: total 3,000 XOF across 1 values (min 3,000, max 3,000)"
        )

    def test_anomaly_insight_with_refs(self):
        analysis = {
            "analysis_type": "anomaly",
            "output": {
                "metrics": [{
                    "metric": "revenue", "unit": "XOF", "sufficient_data": True,
                    "anomalies": [{
                        "value": 10000.0, "date": "2024-12-01",
                        "rules": ["z_score"], "z_score": 3.5,
                        "source_refs": [{"document_id": "d9"}],
                    }],
                }],
            },
        }
        [insight] = PipelineRunner._insights_for_analysis(analysis)
        assert "revenue: 1 anomaly detected" in insight["statement"]
        assert "10,000 XOF on 2024-12-01" in insight["statement"]
        assert insight["source_refs"] == [{"document_id": "d9"}]

    def test_anomaly_insight_skips_insufficient_and_clean_metrics(self):
        analysis = {
            "analysis_type": "anomaly",
            "output": {
                "metrics": [
                    {"metric": "a", "sufficient_data": False},
                    {"metric": "b", "sufficient_data": True, "anomalies": []},
                ],
            },
        }
        assert PipelineRunner._insights_for_analysis(analysis) == []

    def test_comparison_insight(self):
        analysis = {
            "analysis_type": "comparison",
            "output": {
                "sufficient_data": True,
                "comparisons": [{
                    "family": None, "dimension": "metric", "unit": "XOF",
                    "ranking": [
                        {"label": "revenue", "total": 300.0, "mean": 150.0,
                         "rank": 1, "source_refs": [{"document_id": "d1"}]},
                        {"label": "costs", "total": 50.0, "mean": 50.0,
                         "rank": 2, "source_refs": [{"document_id": "d2"}]},
                    ],
                    "pairwise": [{
                        "a": "revenue", "b": "costs",
                        "total_difference": 250.0, "mean_difference": 100.0,
                        "source_refs": [{"document_id": "d1"}, {"document_id": "d2"}],
                    }],
                }],
            },
        }
        [insight] = PipelineRunner._insights_for_analysis(analysis)
        assert insight["statement"] == (
            "revenue leads costs by 250 XOF (total 300 vs 50)"
        )
        assert len(insight["source_refs"]) == 2

    def test_correlation_insight_ends_with_causation_caveat(self):
        analysis = {
            "analysis_type": "correlation",
            "output": {
                "sufficient_data": True,
                "correlations": [{
                    "metric_a": "revenue", "metric_b": "costs",
                    "n": 40, "r": 0.95, "p_value": 1e-20,
                    "label": "association, not causation",
                    "source_refs": [{"document_id": "d1"}],
                }],
            },
        }
        [insight] = PipelineRunner._insights_for_analysis(analysis)
        assert insight["statement"].endswith("(association, not causation)")
        assert "r = 0.95 across 40 paired observations" in insight["statement"]
