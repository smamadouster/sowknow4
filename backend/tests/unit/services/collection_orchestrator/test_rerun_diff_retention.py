"""Unit tests for FR5.5 (rerun / versioning / diff) and FR8.4 (retention &
privacy) — no DB, no network."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
pytest.skip("Disabled during Ollama removal (Sep 4)", allow_module_level=True)
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.collection_requests as cr
from app.api.deps import get_current_user
from app.database import get_db
from app.services.collection_orchestrator import packaging_service
from app.services.collection_orchestrator.audit_logger import (
    pseudonymise_user_id,
    purge_expired_audit_events,
)
from app.services.collection_orchestrator.pipeline_runner import (
    _next_deliverable_version,
)

USER_ID = uuid.uuid4()
FOLDER_ID = uuid.uuid4()
FAKE_USER = SimpleNamespace(id=USER_ID, email="u@example.com")


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


def make_folder(**overrides):
    folder = SimpleNamespace(
        id=FOLDER_ID,
        user_id=USER_ID,
        query_text="revenue of Bank A",
        job_state="completed",
        confirmed_params={"query": "revenue", "analysis_types": ["descriptive"]},
        celery_task_id="old-task",
        checkpoint={"last_stage": "package"},
        error_message=None,
    )
    for key, value in overrides.items():
        setattr(folder, key, value)
    return folder


def make_client(db, user=FAKE_USER):
    app = FastAPI()
    app.include_router(cr.router)

    async def _get_db():
        yield db

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# FR5.5 — deliverable version increments
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_next_deliverable_version_increments():
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one.return_value = 3
    db.execute = AsyncMock(return_value=result)
    assert await _next_deliverable_version(db, FOLDER_ID) == 4


@pytest.mark.asyncio
async def test_next_deliverable_version_starts_at_one():
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one.return_value = None
    db.execute = AsyncMock(return_value=result)
    assert await _next_deliverable_version(db, FOLDER_ID) == 1


# ---------------------------------------------------------------------------
# FR5.5 — POST /{id}/rerun
# ---------------------------------------------------------------------------

def _patch_task(monkeypatch):
    delay = MagicMock(return_value=SimpleNamespace(id="task-9"))
    monkeypatch.setattr(
        "app.tasks.collection_request_tasks.run_collection_request_task",
        SimpleNamespace(delay=delay),
    )
    return delay


def test_rerun_requeues_with_fresh_state(monkeypatch):
    delay = _patch_task(monkeypatch)
    folder = make_folder()
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[
        one(folder),      # ownership check
        many([1, 2]),     # existing deliverable versions
        MagicMock(),      # DELETE source_items
        MagicMock(),      # DELETE query_executions
        MagicMock(),      # DELETE factsets
    ])
    client = make_client(db)

    response = client.post(f"/collection-requests/{FOLDER_ID}/rerun")

    assert response.status_code == 202
    body = response.json()
    assert body["task_id"] == "task-9"
    assert body["previous_versions"] == [1, 2]
    assert body["next_version"] == 3
    delay.assert_called_once_with(str(FOLDER_ID), str(USER_ID))
    # Fresh retrieval: checkpoint cleared, job re-queued, old task replaced.
    assert folder.job_state == "queued"
    assert folder.checkpoint is None
    assert folder.error_message is None
    assert folder.celery_task_id == "task-9"
    # 5 executes: ownership + versions + 3 working-set deletes.
    assert db.execute.await_count == 5


def test_rerun_rejects_unconfirmed_request():
    folder = make_folder(confirmed_params=None, job_state="clarifying")
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[one(folder)])
    client = make_client(db)

    response = client.post(f"/collection-requests/{FOLDER_ID}/rerun")

    assert response.status_code == 409
    assert db.execute.await_count == 1


def test_rerun_rejects_active_job():
    folder = make_folder(job_state="searching")
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[one(folder)])
    client = make_client(db)

    response = client.post(f"/collection-requests/{FOLDER_ID}/rerun")

    assert response.status_code == 409
    assert "searching" in response.json()["detail"]


def test_rerun_owner_scoped():
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[one(None)])
    client = make_client(db)

    response = client.post(f"/collection-requests/{FOLDER_ID}/rerun")

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# FR5.5 — section split + diff helpers (pure)
# ---------------------------------------------------------------------------

V1_MD = """## Overview

Revenue was 1,000 XOF.

## Key Findings

- Finding A

## Supporting Data

| a | b |
"""

V2_MD = """## Overview

Revenue was 2,000 XOF.

## Trends & Patterns

- Upward drift

## Supporting Data

| a | b |
"""


def test_split_sections_preamble_and_case():
    md = "intro line\n\n## overview\n\nbody\n"
    sections = packaging_service.split_summary_sections(md)
    assert sections["Preamble"] == ["intro line", ""]
    assert sections["Overview"] == ["", "body"]


def test_split_sections_unrecognized_heading_stays():
    md = "## Overview\n\nline\n\n## Random Heading\n\nmore\n"
    sections = packaging_service.split_summary_sections(md)
    assert list(sections) == ["Overview"]
    assert "## Random Heading" in sections["Overview"]


def test_diff_disclosures_added_removed_changed():
    old = [
        {"type": "truncation", "truncated": False},
        {"type": "conflicts", "count": 1},
    ]
    new = [
        {"type": "truncation", "truncated": True},
        {"type": "degraded_sources", "failed_queries": []},
    ]
    diff = packaging_service.diff_disclosures(old, new)
    assert [d["type"] for d in diff["added"]] == ["degraded_sources"]
    assert [d["type"] for d in diff["removed"]] == ["conflicts"]
    assert [d["type"] for d in diff["changed"]] == ["truncation"]


def test_diff_deliverables_section_statuses():
    del_from = SimpleNamespace(version=1, summary_md=V1_MD, disclosures=[])
    del_to = SimpleNamespace(version=2, summary_md=V2_MD, disclosures=[])
    diff = packaging_service.diff_deliverables(del_from, del_to)

    assert diff["from_version"] == 1
    assert diff["to_version"] == 2
    statuses = {s["section"]: s["status"] for s in diff["sections"]}
    assert statuses["Overview"] == "changed"
    assert statuses["Key Findings"] == "removed"
    assert statuses["Trends & Patterns"] == "added"
    assert statuses["Supporting Data"] == "unchanged"

    overview = next(s for s in diff["sections"] if s["section"] == "Overview")
    assert any(line.startswith("-Revenue was 1,000") for line in overview["diff"])
    assert any(line.startswith("+Revenue was 2,000") for line in overview["diff"])


# ---------------------------------------------------------------------------
# FR5.5 — GET /{id}/deliverable/diff
# ---------------------------------------------------------------------------

def test_diff_endpoint_returns_section_diff():
    folder = make_folder()
    del_from = SimpleNamespace(version=1, summary_md=V1_MD, disclosures=[])
    del_to = SimpleNamespace(version=2, summary_md=V2_MD, disclosures=[
        {"type": "removed_claims", "count": 1},
    ])
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[one(folder), many([del_from, del_to])])
    client = make_client(db)

    response = client.get(
        f"/collection-requests/{FOLDER_ID}/deliverable/diff"
        "?from_version=1&to_version=2"
    )

    assert response.status_code == 200
    body = response.json()
    statuses = {s["section"]: s["status"] for s in body["sections"]}
    assert statuses["Overview"] == "changed"
    assert statuses["Key Findings"] == "removed"
    assert [d["type"] for d in body["disclosures"]["added"]] == ["removed_claims"]


def test_diff_endpoint_404_for_missing_version():
    folder = make_folder()
    del_from = SimpleNamespace(version=1, summary_md=V1_MD, disclosures=[])
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[one(folder), many([del_from])])
    client = make_client(db)

    response = client.get(
        f"/collection-requests/{FOLDER_ID}/deliverable/diff"
        "?from_version=1&to_version=2"
    )

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# FR8.4 — pseudonymisation + retention purge
# ---------------------------------------------------------------------------

def test_pseudonymise_stable_and_salted():
    first = pseudonymise_user_id(USER_ID)
    assert first == pseudonymise_user_id(USER_ID)  # stable
    assert first.startswith("user_")
    assert len(first) == len("user_") + 32
    assert str(USER_ID) not in first
    assert pseudonymise_user_id(uuid.uuid4()) != first  # input-dependent


def test_pseudonymise_none_passthrough():
    assert pseudonymise_user_id(None) is None


@pytest.mark.asyncio
async def test_purge_expired_audit_events_deletes_and_commits():
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(rowcount=7))

    deleted = await purge_expired_audit_events(db, retention_days=30)

    assert deleted == 7
    db.execute.assert_awaited_once()
    db.commit.assert_awaited_once()


def _make_audit_event(user_id=USER_ID):
    from datetime import datetime, timezone

    return SimpleNamespace(
        id=uuid.uuid4(),
        timestamp=datetime(2026, 1, 15, tzinfo=timezone.utc),
        stage="retrieve",
        action="search_call",
        status="success",
        input_ref=None,
        output_ref=None,
        component_version="collection-orchestrator 1.0.0",
        duration_ms=42,
        detail={},
        user_id=user_id,
    )


def test_audit_export_pseudonymised_when_enabled(monkeypatch):
    monkeypatch.setattr(
        "app.core.config.settings.COLLECTION_AUDIT_PSEUDONYMISE", True
    )
    folder = make_folder()
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[one(folder), many([_make_audit_event()])])
    client = make_client(db)

    response = client.get(f"/collection-requests/{FOLDER_ID}/audit?format=json")

    assert response.status_code == 200
    body = response.json()
    assert body["pseudonymised"] is True
    exported = body["events"][0]["user_id"]
    assert exported.startswith("user_")
    assert str(USER_ID) not in exported


def test_audit_export_raw_user_id_by_default(monkeypatch):
    monkeypatch.setattr(
        "app.core.config.settings.COLLECTION_AUDIT_PSEUDONYMISE", False
    )
    folder = make_folder()
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[one(folder), many([_make_audit_event()])])
    client = make_client(db)

    response = client.get(f"/collection-requests/{FOLDER_ID}/audit?format=csv")

    assert response.status_code == 200
    assert str(USER_ID) in response.text
    assert response.text.splitlines()[0].endswith(",user_id")
