import pytest
@pytest.mark.skip(reason="Ollama removed")
"""Unit tests for DELETE /smart-folders/{id} — owner-scoped, idempotent.

FastAPI TestClient with dependency_overrides for auth + DB. No DB, no network.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.smart_folders as sf_api
from app.api.deps import get_current_user
from app.database import get_db

USER_ID = uuid.uuid4()
FOLDER_ID = uuid.uuid4()

FAKE_USER = SimpleNamespace(id=USER_ID, email="u@example.com")


def one(value):
    mock = MagicMock()
    mock.scalar_one_or_none.return_value = value
    return mock


def make_folder(**overrides):
    folder = SimpleNamespace(
        id=FOLDER_ID,
        user_id=USER_ID,
        name="Test folder",
        celery_task_id=None,
        job_state="completed",
    )
    for key, value in overrides.items():
        setattr(folder, key, value)
    return folder


def make_client(db, user=FAKE_USER):
    app = FastAPI()
    app.include_router(sf_api.router)

    async def _get_db():
        yield db

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app, raise_server_exceptions=False)


class TestDeleteSmartFolder:
    def test_delete_returns_204_and_deletes(self, monkeypatch):
        monkeypatch.setattr(sf_api, "_create_audit_log", AsyncMock())
        folder = make_folder()
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[one(folder)])
        client = make_client(db)

        response = client.delete(f"/smart-folders/{FOLDER_ID}")

        assert response.status_code == 204
        db.delete.assert_awaited_once_with(folder)

    def test_delete_is_idempotent_when_already_gone(self, monkeypatch):
        monkeypatch.setattr(sf_api, "_create_audit_log", AsyncMock())
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[one(None)])
        client = make_client(db)

        response = client.delete(f"/smart-folders/{FOLDER_ID}")

        assert response.status_code == 204
        db.delete.assert_not_called()

    def test_delete_404_for_other_users_folder(self, monkeypatch):
        monkeypatch.setattr(sf_api, "_create_audit_log", AsyncMock())
        folder = make_folder(user_id=uuid.uuid4())
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[one(folder)])
        client = make_client(db)

        response = client.delete(f"/smart-folders/{FOLDER_ID}")

        assert response.status_code == 404
        db.delete.assert_not_called()

    def test_delete_active_job_revokes_task(self, monkeypatch):
        monkeypatch.setattr(sf_api, "_create_audit_log", AsyncMock())
        revoke = MagicMock()
        celery = SimpleNamespace(control=SimpleNamespace(revoke=revoke))
        monkeypatch.setattr("app.celery_app.celery_app", celery)
        folder = make_folder(job_state="searching", celery_task_id="task-3")
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[one(folder)])
        client = make_client(db)

        response = client.delete(f"/smart-folders/{FOLDER_ID}")

        assert response.status_code == 204
        revoke.assert_called_once_with("task-3", terminate=True)
        db.delete.assert_awaited_once_with(folder)
