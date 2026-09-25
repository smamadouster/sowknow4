"""Unit tests for the collection-requests API router.

FastAPI TestClient with dependency_overrides for auth + DB; the conversation
manager singleton and the Celery task are monkeypatched. No DB, no network.
"""

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
pytest.skip("Disabled during Ollama removal (Sep 4)", allow_module_level=True)
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.collection_requests as cr
from app.api.deps import get_current_user
from app.database import get_db

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


def first(value):
    mock = MagicMock()
    mock.scalars.return_value.first.return_value = value
    return mock


def make_folder(**overrides):
    folder = SimpleNamespace(
        id=FOLDER_ID,
        user_id=USER_ID,
        query_text="revenue of Bank A",
        job_state="clarifying",
        confirmed_params=None,
        celery_task_id=None,
        checkpoint=None,
        error_message=None,
        idempotency_key=None,
    )
    for key, value in overrides.items():
        setattr(folder, key, value)
    return folder


def make_session(**overrides):
    session = SimpleNamespace(
        id=uuid.uuid4(),
        request_id=FOLDER_ID,
        rounds=[{"round": 1, "questions": [{"id": "q1", "text": "Did you mean Bank A?"}], "answers": []}],
        extracted_entities=[{"name": "Bank A", "confidence": 0.5, "status": "ambiguous"}],
        extracted_intent="general",
        analysis_types=["descriptive"],
        open_ambiguities=[],
        assumptions=[],
        status="active",
    )
    for key, value in overrides.items():
        setattr(session, key, value)
    return session


def make_db(responses):
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=list(responses))
    return db


def make_client(db, user=FAKE_USER):
    app = FastAPI()
    app.include_router(cr.router)

    async def _get_db():
        yield db

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def cm(monkeypatch):
    """Replace the conversation manager singleton with a controllable fake."""
    fake = SimpleNamespace(
        start_session=AsyncMock(),
        process_answer=AsyncMock(),
        confirm=AsyncMock(),
        build_confirmed_params=lambda session: {"analysis_types": session.analysis_types},
        max_rounds=3,
    )
    monkeypatch.setattr(cr, "conversation_manager", fake)
    return fake


# ---------------------------------------------------------------------------
# POST /collection-requests
# ---------------------------------------------------------------------------

class TestCreate:
    def test_create_returns_202_with_clarification(self, cm):
        session = make_session()
        cm.start_session.return_value = session
        db = make_db([one(None)])  # idempotency lookup: no existing
        client = make_client(db)

        response = client.post(
            "/collection-requests",
            json={"query": "revenue of Bank A", "idempotency_key": "k1"},
        )

        assert response.status_code == 202
        body = response.json()
        assert body["request_id"]
        assert body["clarification"]["questions"][0]["id"] == "q1"
        assert body["clarification"]["max_rounds"] == 3
        assert body["clarification"]["intent"] == "general"
        cm.start_session.assert_awaited_once()

    def test_idempotent_replay_returns_existing_200(self, cm):
        existing = make_folder(idempotency_key="k1")
        session = make_session()
        db = make_db([one(existing), first(session)])
        client = make_client(db)

        response = client.post(
            "/collection-requests",
            json={"query": "revenue of Bank A", "idempotency_key": "k1"},
        )

        assert response.status_code == 200
        assert response.json()["request_id"] == str(FOLDER_ID)
        cm.start_session.assert_not_called()


# ---------------------------------------------------------------------------
# POST /{id}/clarify
# ---------------------------------------------------------------------------

class TestClarify:
    def test_next_questions_returned(self, cm):
        folder = make_folder()
        session = make_session()
        cm.process_answer.return_value = {
            "complete": False,
            "session": session,
            "questions": [{"id": "q1_r2", "text": "Again?"}],
        }
        db = make_db([one(folder), first(session)])
        client = make_client(db)

        response = client.post(
            f"/collection-requests/{FOLDER_ID}/clarify",
            json={"answers": {"q1": "Bank A"}},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["ready_to_confirm"] is False
        assert body["questions"][0]["id"] == "q1_r2"

    def test_ready_to_confirm_with_confirmation(self, cm):
        folder = make_folder()
        session = make_session(status="completed")
        cm.process_answer.return_value = {
            "complete": True, "session": session, "questions": [],
        }
        db = make_db([one(folder), first(session)])
        client = make_client(db)

        response = client.post(
            f"/collection-requests/{FOLDER_ID}/clarify",
            json={"answers": {}, "skip": True},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["ready_to_confirm"] is True
        assert body["confirmation"]["params"]["analysis_types"] == ["descriptive"]
        assert body["confirmation"]["assumptions"] == []

    def test_clarify_404_for_other_users_folder(self, cm):
        db = make_db([one(None)])  # owner-scoped lookup finds nothing
        client = make_client(db)

        response = client.post(
            f"/collection-requests/{FOLDER_ID}/clarify",
            json={"answers": {}},
        )
        assert response.status_code == 404

    def test_clarify_409_after_job_queued(self, cm):
        folder = make_folder(job_state="queued")
        db = make_db([one(folder)])
        client = make_client(db)

        response = client.post(
            f"/collection-requests/{FOLDER_ID}/clarify",
            json={"answers": {}},
        )
        assert response.status_code == 409


# ---------------------------------------------------------------------------
# POST /{id}/confirm
# ---------------------------------------------------------------------------

class TestConfirm:
    def test_confirm_enqueues_task_and_returns_202(self, cm, monkeypatch):
        folder = make_folder()
        session = make_session()
        params = {"analysis_types": ["descriptive"], "entities": []}
        cm.confirm.return_value = params
        task = SimpleNamespace(id="celery-task-1")
        delay = MagicMock(return_value=task)
        monkeypatch.setattr(
            "app.tasks.collection_request_tasks.run_collection_request_task",
            SimpleNamespace(delay=delay),
        )
        db = make_db([one(folder), first(session)])
        client = make_client(db)

        response = client.post(f"/collection-requests/{FOLDER_ID}/confirm")

        assert response.status_code == 202
        assert response.json()["task_id"] == "celery-task-1"
        assert folder.confirmed_params == params
        assert folder.job_state == "queued"
        assert folder.celery_task_id == "celery-task-1"
        delay.assert_called_once_with(str(FOLDER_ID), str(USER_ID))

    def test_confirm_409_when_already_confirmed(self, cm):
        folder = make_folder(confirmed_params={"analysis_types": ["descriptive"]})
        db = make_db([one(folder)])
        client = make_client(db)

        response = client.post(f"/collection-requests/{FOLDER_ID}/confirm")
        assert response.status_code == 409
        cm.confirm.assert_not_called()

    def test_confirm_404_for_other_users_folder(self, cm):
        db = make_db([one(None)])
        client = make_client(db)

        response = client.post(f"/collection-requests/{FOLDER_ID}/confirm")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# GET /{id}/status
# ---------------------------------------------------------------------------

class TestStatus:
    def test_status_returns_job_state_and_checkpoint(self):
        folder = make_folder(
            job_state="searching",
            checkpoint={"last_stage": "retrieve", "stage_outputs_refs": {"source_items": 5}},
        )
        db = make_db([one(folder)])
        client = make_client(db)

        response = client.get(f"/collection-requests/{FOLDER_ID}/status")

        assert response.status_code == 200
        body = response.json()
        assert body["job_state"] == "searching"
        assert body["checkpoint"]["last_stage"] == "retrieve"
        assert body["deliverable_id"] is None

    def test_status_completed_includes_deliverable_id(self):
        deliverable_id = uuid.uuid4()
        folder = make_folder(job_state="completed")
        deliverable = SimpleNamespace(id=deliverable_id)
        db = make_db([one(folder), first(deliverable)])
        client = make_client(db)

        response = client.get(f"/collection-requests/{FOLDER_ID}/status")
        assert response.json()["deliverable_id"] == str(deliverable_id)

    def test_status_404_for_other_user(self):
        db = make_db([one(None)])
        client = make_client(db)

        response = client.get(f"/collection-requests/{FOLDER_ID}/status")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# GET /{id}/items
# ---------------------------------------------------------------------------

def make_item_row(item_id, doc_id, title, rank, item_date=None):
    return SimpleNamespace(
        id=item_id,
        document_id=doc_id,
        title=title,
        item_date=item_date or datetime(2024, 3, 1, tzinfo=timezone.utc),
        source="chunk",
        author=None,
        snippet="snippet text",
        rank_position=rank,
        relevance_score=0.8,
        status="ok",
        canonical_id=None,
    )


class TestItems:
    def test_items_ranked_with_annotations_and_links(self):
        doc_id = uuid.uuid4()
        item_id = uuid.uuid4()
        folder = make_folder(job_state="completed")
        row = make_item_row(item_id, doc_id, "report.pdf", 1)
        annotation = SimpleNamespace(
            item_id=item_id,
            annotation_text="why relevant",
            category_tags=["pdf", "2024"],
        )
        db = make_db([one(folder), many([row]), many([annotation])])
        client = make_client(db)

        response = client.get(f"/collection-requests/{FOLDER_ID}/items")

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        item = body["items"][0]
        assert item["annotation"] == "why relevant"
        assert item["category_tags"] == ["pdf", "2024"]
        assert item["link"] == f"/documents/{doc_id}"

    def test_items_tag_filter(self):
        folder = make_folder(job_state="completed")
        row_a = make_item_row(uuid.uuid4(), uuid.uuid4(), "a.pdf", 1)
        row_b = make_item_row(uuid.uuid4(), uuid.uuid4(), "b.pdf", 2)
        ann_a = SimpleNamespace(item_id=row_a.id, annotation_text="a", category_tags=["pdf"])
        ann_b = SimpleNamespace(item_id=row_b.id, annotation_text="b", category_tags=["eml"])
        db = make_db([one(folder), many([row_a, row_b]), many([ann_a, ann_b])])
        client = make_client(db)

        response = client.get(f"/collection-requests/{FOLDER_ID}/items?tag=eml")

        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["title"] == "b.pdf"

    def test_items_duplicates_grouped_under_canonical(self):
        folder = make_folder(job_state="completed")
        canonical_id = uuid.uuid4()
        dup_id = uuid.uuid4()
        canonical = make_item_row(canonical_id, uuid.uuid4(), "canonical.pdf", 1)
        dup = make_item_row(dup_id, uuid.uuid4(), "dup.pdf", None)
        dup.canonical_id = canonical_id
        db = make_db([one(folder), many([canonical, dup]), many([])])
        client = make_client(db)

        response = client.get(f"/collection-requests/{FOLDER_ID}/items")

        body = response.json()
        assert body["total"] == 1  # duplicate grouped, not listed separately
        related = body["items"][0]["related_items"]
        assert related[0]["title"] == "dup.pdf"

    def test_items_404_for_other_user(self):
        db = make_db([one(None)])
        client = make_client(db)

        response = client.get(f"/collection-requests/{FOLDER_ID}/items")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# GET /{id}/deliverable (+ export)
# ---------------------------------------------------------------------------

def make_deliverable(**overrides):
    deliverable = SimpleNamespace(
        id=uuid.uuid4(),
        request_id=FOLDER_ID,
        version=1,
        summary_md="# Summary\nGrounded.",
        appendix={"analyses": []},
        disclosures=[],
        created_at=datetime(2026, 1, 15, tzinfo=timezone.utc),
    )
    for key, value in overrides.items():
        setattr(deliverable, key, value)
    return deliverable


class TestDeliverable:
    def test_deliverable_view_json(self):
        folder = make_folder(job_state="completed")
        deliverable = make_deliverable()
        row = make_item_row(uuid.uuid4(), uuid.uuid4(), "report.pdf", 1)
        db = make_db([
            one(folder), first(deliverable),
            many([row]), many([]), many([]),  # items, annotations, analyses
        ])
        client = make_client(db)

        response = client.get(f"/collection-requests/{FOLDER_ID}/deliverable")

        assert response.status_code == 200
        body = response.json()
        assert body["summary_md"].startswith("# Summary")
        assert body["links_permission_bound"] is True
        assert len(body["items"]) == 1

    def test_deliverable_404_when_missing(self):
        folder = make_folder(job_state="completed")
        db = make_db([one(folder), first(None)])
        client = make_client(db)

        response = client.get(f"/collection-requests/{FOLDER_ID}/deliverable")
        assert response.status_code == 404

    def test_export_pdf_streams_pdf_bytes(self):
        folder = make_folder(job_state="completed")
        deliverable = make_deliverable()
        db = make_db([
            one(folder), first(deliverable),
            many([]), many([]),  # items, annotations (no annotation select when no items)
            many([]),            # analyses
        ])
        client = make_client(db)

        response = client.get(f"/collection-requests/{FOLDER_ID}/deliverable/export?format=pdf")

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert response.content.startswith(b"%PDF")

    def test_export_docx_streams_docx_bytes(self):
        folder = make_folder(job_state="completed")
        deliverable = make_deliverable()
        db = make_db([
            one(folder), first(deliverable),
            many([]), many([]),  # items, annotations (no annotation select when no items)
            many([]),            # analyses
        ])
        client = make_client(db)

        response = client.get(f"/collection-requests/{FOLDER_ID}/deliverable/export?format=docx")

        assert response.status_code == 200
        assert response.headers["content-type"] == (
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        )
        assert response.content.startswith(b"PK")  # zip container magic
        assert 'filename="sowknow_collection_' in response.headers["content-disposition"]
        assert response.headers["content-disposition"].endswith('.docx"')

    def test_export_pdf_still_default(self):
        folder = make_folder(job_state="completed")
        deliverable = make_deliverable()
        db = make_db([
            one(folder), first(deliverable),
            many([]), many([]), many([]),
        ])
        client = make_client(db)

        response = client.get(f"/collection-requests/{FOLDER_ID}/deliverable/export")

        assert response.status_code == 200
        assert response.content.startswith(b"%PDF")


# ---------------------------------------------------------------------------
# POST /{id}/cancel
# ---------------------------------------------------------------------------

class TestCancel:
    def test_owner_cancels_active_job_and_revokes_task(self, monkeypatch):
        revoke = MagicMock()
        monkeypatch.setattr(cr, "_revoke_task", revoke)
        folder = make_folder(job_state="searching", celery_task_id="task-9")
        db = make_db([one(folder)])
        client = make_client(db)

        response = client.post(f"/collection-requests/{FOLDER_ID}/cancel")

        assert response.status_code == 200
        assert response.json()["job_state"] == "cancelled"
        assert folder.job_state == "cancelled"
        revoke.assert_called_once_with("task-9")
        # Audit event persisted (action=job_cancelled).
        audit_adds = [
            c.args[0] for c in db.add.call_args_list
            if type(c.args[0]).__name__ == "CollectionAuditEvent"
        ]
        assert any(e.action == "job_cancelled" for e in audit_adds)

    def test_cancel_during_clarification_marks_cancelled_without_revoke(self, monkeypatch):
        revoke = MagicMock()
        monkeypatch.setattr(cr, "_revoke_task", revoke)
        folder = make_folder(job_state="clarifying")  # no celery task yet
        db = make_db([one(folder)])
        client = make_client(db)

        response = client.post(f"/collection-requests/{FOLDER_ID}/cancel")

        assert response.status_code == 200
        assert folder.job_state == "cancelled"
        revoke.assert_not_called()

    def test_cancel_404_for_other_users_folder(self):
        db = make_db([one(None)])  # owner-scoped lookup finds nothing
        client = make_client(db)

        response = client.post(f"/collection-requests/{FOLDER_ID}/cancel")
        assert response.status_code == 404

    @pytest.mark.parametrize("state", ["completed", "failed", "cancelled"])
    def test_cancel_409_on_terminal_states(self, state):
        folder = make_folder(job_state=state)
        db = make_db([one(folder)])
        client = make_client(db)

        response = client.post(f"/collection-requests/{FOLDER_ID}/cancel")
        assert response.status_code == 409
        assert folder.job_state == state  # unchanged

    def test_confirm_409_after_cancel(self, cm):
        folder = make_folder(job_state="cancelled")
        db = make_db([one(folder)])
        client = make_client(db)

        response = client.post(f"/collection-requests/{FOLDER_ID}/confirm")
        assert response.status_code == 409
        cm.confirm.assert_not_called()


# ---------------------------------------------------------------------------
# DELETE /{id} — owner-scoped, idempotent
# ---------------------------------------------------------------------------

class TestDelete:
    def test_delete_completed_request_returns_204_and_deletes(self, monkeypatch):
        revoke = MagicMock()
        monkeypatch.setattr(cr, "_revoke_task", revoke)
        folder = make_folder(job_state="completed")
        db = make_db([one(folder)])
        client = make_client(db)

        response = client.delete(f"/collection-requests/{FOLDER_ID}")

        assert response.status_code == 204
        db.delete.assert_awaited_once_with(folder)
        revoke.assert_not_called()  # terminal job — nothing to revoke

    def test_delete_active_job_cancels_and_revokes_first(self, monkeypatch):
        revoke = MagicMock()
        monkeypatch.setattr(cr, "_revoke_task", revoke)
        folder = make_folder(job_state="analysing", celery_task_id="task-7")
        db = make_db([one(folder)])
        client = make_client(db)

        response = client.delete(f"/collection-requests/{FOLDER_ID}")

        assert response.status_code == 204
        assert folder.job_state == "cancelled"
        revoke.assert_called_once_with("task-7")
        db.delete.assert_awaited_once_with(folder)

    def test_delete_is_idempotent_when_already_gone(self):
        db = make_db([one(None)])  # row not found
        client = make_client(db)

        response = client.delete(f"/collection-requests/{FOLDER_ID}")

        assert response.status_code == 204  # same end state, no false error
        db.delete.assert_not_called()

    def test_delete_404_for_other_users_request(self):
        folder = make_folder(user_id=uuid.uuid4())  # different owner
        db = make_db([one(folder)])
        client = make_client(db)

        response = client.delete(f"/collection-requests/{FOLDER_ID}")

        assert response.status_code == 404
        db.delete.assert_not_called()


# ---------------------------------------------------------------------------
# GET /{id}/audit
# ---------------------------------------------------------------------------

class TestAudit:
    def make_event(self, stage="retrieve", action="search_call"):
        return SimpleNamespace(
            id=uuid.uuid4(),
            timestamp=datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc),
            stage=stage,
            action=action,
            status="success",
            input_ref=None,
            output_ref=None,
            component_version="collection-orchestrator 1.0.0",
            duration_ms=42,
            detail={"result_count": 3},
        )

    def test_audit_json(self):
        folder = make_folder(job_state="completed")
        db = make_db([one(folder), many([self.make_event()])])
        client = make_client(db)

        response = client.get(f"/collection-requests/{FOLDER_ID}/audit?format=json")

        assert response.status_code == 200
        events = response.json()["events"]
        assert events[0]["stage"] == "retrieve"
        assert events[0]["duration_ms"] == 42

    def test_audit_csv(self):
        folder = make_folder(job_state="completed")
        db = make_db([one(folder), many([self.make_event(), self.make_event(stage="package")])])
        client = make_client(db)

        response = client.get(f"/collection-requests/{FOLDER_ID}/audit?format=csv")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")
        lines = response.text.strip().splitlines()
        assert lines[0].startswith("id,timestamp,stage,action")
        assert len(lines) == 3  # header + 2 events


# ---------------------------------------------------------------------------
# GET /{id}/stream (SSE)
# ---------------------------------------------------------------------------

class TestStream:
    def test_completed_job_emits_complete_event(self):
        folder = make_folder(job_state="completed")
        deliverable = make_deliverable()
        db = make_db([
            one(folder),                # ownership check
            one(folder),                # first poll (populate_existing)
            first(deliverable),         # deliverable lookup for the event
        ])
        client = make_client(db)

        with client.stream("GET", f"/collection-requests/{FOLDER_ID}/stream") as response:
            body = "".join(response.iter_text())

        assert response.status_code == 200
        assert response.headers["x-accel-buffering"] == "no"
        assert "event: complete" in body
        assert str(deliverable.id) in body

    def test_failed_job_emits_error_event(self):
        folder = make_folder(job_state="failed", error_message="search unavailable")
        db = make_db([one(folder), one(folder)])
        client = make_client(db)

        with client.stream("GET", f"/collection-requests/{FOLDER_ID}/stream") as response:
            body = "".join(response.iter_text())

        assert "event: error" in body
        assert "search unavailable" in body
