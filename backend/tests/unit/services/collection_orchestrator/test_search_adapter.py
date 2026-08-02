"""Unit tests for SearchAdapter (FR2) — search_service and DB mocked."""

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.services.collection_orchestrator.search_adapter as sa_module
from app.services.collection_orchestrator.query_planner import SearchCallSpec
from app.services.collection_orchestrator.search_adapter import (
    SearchAdapter,
    SearchUnavailableError,
)

DOC_ID_1 = str(uuid.uuid4())
DOC_ID_2 = str(uuid.uuid4())


def make_user():
    return SimpleNamespace(id=uuid.uuid4(), email="u@example.com", role="user", can_access_confidential=False)


def make_result(chunk_id, document_id=DOC_ID_1, final_score=0.5, text="some chunk text"):
    return SimpleNamespace(
        chunk_id=str(chunk_id),
        document_id=str(document_id),
        document_name=f"doc-{str(document_id)[:4]}.pdf",
        document_bucket="public",
        chunk_text=text,
        chunk_index=0,
        page_number=1,
        semantic_score=0.5,
        keyword_score=0.4,
        final_score=final_score,
        result_type="chunk",
        article_id=None,
        article_title=None,
        article_summary=None,
        match_source="hybrid",
    )


def make_response(results, total=None):
    return {"results": results, "total": total if total is not None else len(results)}


def scalars_result(values):
    mock = MagicMock()
    mock.scalars.return_value.all.return_value = values
    return mock


def count_result(value):
    mock = MagicMock()
    mock.scalar_one.return_value = value
    return mock


def make_doc(doc_id=DOC_ID_1, filename="report.pdf"):
    return SimpleNamespace(
        id=doc_id,
        file_path=f"/data/{filename}",
        original_filename=filename,
        document_metadata={"author": "Jane"},
        created_at=datetime(2021, 6, 1, tzinfo=timezone.utc),
        mime_type="application/pdf",
        bucket="public",
    )


@pytest.fixture
def db():
    mock = AsyncMock()
    mock.execute.return_value = scalars_result([])  # default: no docs
    return mock


@pytest.fixture
def audit(monkeypatch):
    mock = AsyncMock()
    monkeypatch.setattr(sa_module.audit_logger, "log_event", mock)
    return mock


@pytest.fixture
def adapter():
    return SearchAdapter(cache_enabled=False, sleep=AsyncMock(), base_backoff=0.001)


def patch_search(monkeypatch, side_effect=None, return_value=None):
    mock = AsyncMock(side_effect=side_effect, return_value=return_value)
    monkeypatch.setattr(sa_module.search_service, "hybrid_search", mock)
    return mock


def spec(**kw):
    return SearchCallSpec(query_text=kw.pop("query_text", "q"), **kw)


class TestExecutePlan:
    @pytest.mark.asyncio
    async def test_success_maps_and_enriches_items(self, monkeypatch, db, audit, adapter):
        patch_search(monkeypatch, return_value=make_response([make_result("c1"), make_result("c2")]))
        db.execute.return_value = scalars_result([make_doc()])

        items, executions = await adapter.execute_plan([spec()], make_user(), db, request_id=uuid.uuid4())

        assert len(items) == 2
        item = items[0]
        assert item["document_id"] == DOC_ID_1
        assert item["uri"] == "/data/report.pdf"
        assert item["author"] == "Jane"
        assert item["item_type"] == "pdf"
        assert item["item_date"] == datetime(2021, 6, 1, tzinfo=timezone.utc)
        assert item["acl_stamp"] == "public"
        assert item["relevance_score"] == 0.5
        assert item["status"] == "ok"
        assert executions[0]["status"] == "completed"
        assert executions[0]["result_count"] == 2
        assert adapter.last_run_meta["truncated"] is False

    @pytest.mark.asyncio
    async def test_timeout_and_retry_policy_passed_to_search(self, monkeypatch, db, audit, adapter):
        search = patch_search(monkeypatch, return_value=make_response([]))
        await adapter.execute_plan([spec()], make_user(), db)
        assert search.await_args.kwargs["timeout"] == 30.0

    @pytest.mark.asyncio
    async def test_audit_event_per_search_call(self, monkeypatch, db, audit, adapter):
        patch_search(monkeypatch, return_value=make_response([make_result("c1")]))
        await adapter.execute_plan([spec()], make_user(), db, request_id=uuid.uuid4())
        search_calls = [c for c in audit.await_args_list if c.kwargs["action"] == "search_call"]
        assert len(search_calls) == 1
        assert search_calls[0].kwargs["stage"] == "retrieve"
        assert search_calls[0].kwargs["duration_ms"] is not None


class TestFilterPushdown:
    @pytest.mark.asyncio
    async def test_results_outside_filter_set_dropped(self, monkeypatch, db, audit, adapter):
        patch_search(monkeypatch, return_value=make_response([
            make_result("c1", DOC_ID_1),
            make_result("c2", DOC_ID_2),
        ]))
        # Execute order: filter pushdown ids → FR6.2 count (all buckets) →
        # FR6.2 count (user buckets) → enrichment docs.
        db.execute.side_effect = [
            scalars_result([DOC_ID_1]),
            count_result(10),
            count_result(4),
            scalars_result([make_doc()]),
        ]

        items, _ = await adapter.execute_plan(
            [spec(doc_types=("pdf",), date_from="2020-01-01")], make_user(), db
        )

        assert [i["chunk_id"] for i in items] == ["c1"]
        # The pushdown SELECT ran against the documents table
        assert db.execute.await_count == 4
        assert adapter.last_run_meta["acl_trimmed_count"] == 6

    @pytest.mark.asyncio
    async def test_no_filters_means_no_restriction(self, monkeypatch, db, audit, adapter):
        patch_search(monkeypatch, return_value=make_response([
            make_result("c1", DOC_ID_1), make_result("c2", DOC_ID_2),
        ]))
        db.execute.return_value = scalars_result([])  # enrichment finds nothing

        items, _ = await adapter.execute_plan([spec()], make_user(), db)
        assert len(items) == 2
        # No filters → no pushdown query and no FR6.2 count queries
        # (trimmed count is meaningless without filters) — enrichment only.
        assert db.execute.await_count == 1


class TestRetriesAndDegradedMode:
    @pytest.mark.asyncio
    async def test_retries_with_backoff_then_succeeds(self, monkeypatch, db, audit, adapter):
        search = patch_search(monkeypatch, side_effect=[
            RuntimeError("boom"), RuntimeError("boom"), make_response([make_result("c1")]),
        ])
        items, executions = await adapter.execute_plan([spec()], make_user(), db)

        assert search.await_count == 3
        assert adapter._sleep.await_count == 2
        # Exponential backoff: base * 2**attempt
        delays = [c.args[0] for c in adapter._sleep.await_args_list]
        assert delays[1] == pytest.approx(delays[0] * 2)
        assert len(items) == 1
        assert executions[0]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_failed_spec_recorded_others_continue(self, monkeypatch, db, audit, adapter):
        patch_search(monkeypatch, side_effect=[
            RuntimeError("down"), RuntimeError("down"), RuntimeError("down"),
            make_response([make_result("c1")]),
        ])
        items, executions = await adapter.execute_plan([spec(), spec(query_text="q2")], make_user(), db)

        assert [e["status"] for e in executions] == ["failed", "completed"]
        assert executions[0]["error"] == "down"
        assert len(items) == 1
        failure_audits = [
            c for c in audit.await_args_list
            if c.kwargs["action"] == "search_call" and c.kwargs.get("status") == "failure"
        ]
        assert len(failure_audits) == 1

    @pytest.mark.asyncio
    async def test_all_specs_fail_raises_unavailable(self, monkeypatch, db, audit, adapter):
        patch_search(monkeypatch, side_effect=RuntimeError("down"))
        with pytest.raises(SearchUnavailableError):
            await adapter.execute_plan([spec(), spec(query_text="q2")], make_user(), db)


class TestPagination:
    @pytest.mark.asyncio
    async def test_paginates_until_exhausted_with_duplicate_guard(self, monkeypatch, db, audit):
        adapter = SearchAdapter(cache_enabled=False, sleep=AsyncMock(), page_size=2)
        # Page 2 overlaps page 1 on the boundary (c2 repeats) — must not duplicate
        search = patch_search(monkeypatch, side_effect=[
            make_response([make_result("c1"), make_result("c2")], total=3),
            make_response([make_result("c2"), make_result("c3")], total=3),
        ])
        items, executions = await adapter.execute_plan(
            [spec(limit=2)], make_user(), db
        )
        assert [i["chunk_id"] for i in items] == ["c1", "c2", "c3"]
        assert [c.kwargs["offset"] for c in search.await_args_list] == [0, 2]
        assert len(executions) == 2

    @pytest.mark.asyncio
    async def test_stops_when_page_not_full(self, monkeypatch, db, audit, adapter):
        search = patch_search(monkeypatch, return_value=make_response([make_result("c1")], total=500))
        await adapter.execute_plan([spec(limit=100)], make_user(), db)
        assert search.await_count == 1  # short page → branch exhausted

    @pytest.mark.asyncio
    async def test_truncation_at_hard_cap(self, monkeypatch, db, audit):
        adapter = SearchAdapter(cache_enabled=False, sleep=AsyncMock(), max_items=3, page_size=2)
        patch_search(monkeypatch, side_effect=[
            make_response([make_result("c1"), make_result("c2")], total=100),
            make_response([make_result("c3"), make_result("c4")], total=100),
        ])
        items, _ = await adapter.execute_plan([spec(limit=2), spec(query_text="q2", limit=2)], make_user(), db)

        assert len(items) == 3
        assert adapter.last_run_meta["truncated"] is True


class FakeRedis:
    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def setex(self, key, ttl, value):
        self.store[key] = value


class TestAclTrimmedCount:
    """FR6.2 — per-spec count of matches hidden by ACL bucket trimming."""

    @pytest.mark.asyncio
    async def test_counts_aggregated_across_specs(self, monkeypatch, db, audit, adapter):
        patch_search(monkeypatch, return_value=make_response([make_result("c1")]))
        # Filtered specs → per spec: pushdown ids, count(all buckets),
        # count(user buckets); enrichment SELECT last.
        db.execute.side_effect = [
            scalars_result([]),                    # spec 1 pushdown ids
            count_result(10), count_result(4),     # spec 1: 6 trimmed
            scalars_result([]),                    # spec 2 pushdown ids
            count_result(8), count_result(8),      # spec 2: 0 trimmed
            scalars_result([]),                    # enrichment
        ]

        await adapter.execute_plan(
            [spec(date_from="2020-01-01"), spec(query_text="q2", date_from="2020-01-01")],
            make_user(), db,
        )

        assert adapter.last_run_meta["acl_trimmed_count"] == 6
        by_spec = adapter.last_run_meta["acl_trimmed_by_spec"]
        assert [s["trimmed_count"] for s in by_spec] == [6, 0]
        assert by_spec[0]["query_text"] == "q"

    @pytest.mark.asyncio
    async def test_no_filters_no_trimmed_count(self, monkeypatch, db, audit, adapter):
        """Without spec filters the corpus-wide bucket difference is
        meaningless — no count queries, trimmed count stays 0."""
        patch_search(monkeypatch, return_value=make_response([make_result("c1")]))
        db.execute.return_value = scalars_result([])  # enrichment only

        await adapter.execute_plan([spec()], make_user(), db)

        assert adapter.last_run_meta["acl_trimmed_count"] == 0
        assert db.execute.await_count == 1

    @pytest.mark.asyncio
    async def test_count_failure_never_breaks_retrieval(self, monkeypatch, db, audit, adapter):
        patch_search(monkeypatch, return_value=make_response([make_result("c1")]))
        db.execute.side_effect = [
            scalars_result([DOC_ID_1]),           # pushdown ids (filtered spec)
            RuntimeError("count exploded"),       # trimmed count query fails
            scalars_result([]),                   # enrichment still runs
        ]

        items, _ = await adapter.execute_plan([spec(date_from="2020-01-01")], make_user(), db)

        assert len(items) == 1
        assert adapter.last_run_meta["acl_trimmed_count"] == 0

    @pytest.mark.asyncio
    async def test_trimmed_count_survives_cache_roundtrip(self, monkeypatch, db, audit):
        redis = FakeRedis()
        adapter = SearchAdapter(redis_client=redis, sleep=AsyncMock())
        patch_search(monkeypatch, return_value=make_response([make_result("c1")]))
        db.execute.side_effect = [
            scalars_result([]),                   # pushdown ids
            count_result(5), count_result(2),     # 3 trimmed
            scalars_result([]),                   # enrichment
        ]
        user = make_user()

        await adapter.execute_plan([spec(date_from="2020-01-01")], user, db)
        assert adapter.last_run_meta["acl_trimmed_count"] == 3

        db.execute.side_effect = None  # cache hit: no further queries
        db.execute.reset_mock()
        await adapter.execute_plan([spec(date_from="2020-01-01")], user, db)
        assert adapter.last_run_meta["cache_hit"] is True
        assert adapter.last_run_meta["acl_trimmed_count"] == 3
        db.execute.assert_not_called()


class TestResultCache:
    @pytest.mark.asyncio
    async def test_identical_params_hit_cache(self, monkeypatch, db, audit):
        redis = FakeRedis()
        adapter = SearchAdapter(redis_client=redis, sleep=AsyncMock())
        search = patch_search(monkeypatch, return_value=make_response([make_result("c1")]))
        user = make_user()

        items1, _ = await adapter.execute_plan([spec()], user, db)
        items2, _ = await adapter.execute_plan([spec()], user, db)

        assert search.await_count == 1  # second call served from cache
        assert adapter.last_run_meta["cache_hit"] is True
        assert [i["chunk_id"] for i in items2] == [i["chunk_id"] for i in items1]

    @pytest.mark.asyncio
    async def test_cache_scoped_per_user(self, monkeypatch, db, audit):
        redis = FakeRedis()
        adapter = SearchAdapter(redis_client=redis, sleep=AsyncMock())
        search = patch_search(monkeypatch, return_value=make_response([make_result("c1")]))

        await adapter.execute_plan([spec()], make_user(), db)
        await adapter.execute_plan([spec()], make_user(), db)  # different user

        assert search.await_count == 2  # no cross-user sharing (ACL-scoped)
