"""
Regression test for missing await on get_collection_stats endpoint.

The endpoint handler calls the async method collection_service.get_collection_stats()
without await, returning a coroutine object instead of the stats dict. This causes
a 500 error when Pydantic tries to unpack the coroutine as a dict.

This test overrides FastAPI dependencies, patches the lifespan DB init, and patches
the service call at the API module level. It uses its own TestClient to avoid the
conftest auto-skip for client-fixture tests on SQLite.
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.database import get_db
from app.main import app
from app.models.user import User, UserRole


def _fake_admin_user():
    """Create a fake admin user for dependency injection."""
    user = MagicMock(spec=User)
    user.id = uuid4()
    user.email = "admin@test.local"
    user.role = UserRole.ADMIN
    user.is_active = True
    user.is_superuser = True
    user.can_access_confidential = True
    return user


VALID_STATS = {
    "total_collections": 5,
    "pinned_collections": 2,
    "favorite_collections": 1,
    "total_documents_in_collections": 42,
    "average_documents_per_collection": 8.4,
    "collections_by_type": {"smart": 3, "manual": 2},
    "recent_activity": [],
}


class TestGetCollectionStatsBug:
    """Regression: GET /api/v1/collections/stats must await the async service call."""

    def test_stats_returns_200_with_valid_data(self):
        admin = _fake_admin_user()

        # Override FastAPI dependencies
        app.dependency_overrides[get_current_user] = lambda: admin
        app.dependency_overrides[get_db] = lambda: MagicMock()

        try:
            with patch("app.main.init_pgvector", new_callable=AsyncMock), \
                 patch("app.main.create_all_tables", new_callable=AsyncMock), \
                 patch("app.main.engine", new_callable=MagicMock) as mock_engine, \
                 patch(
                     "app.api.collections.collection_service.get_collection_stats",
                     new_callable=AsyncMock,
                     return_value=VALID_STATS,
                 ):
                # Make engine.dispose() awaitable
                mock_engine.dispose = AsyncMock()

                with TestClient(app, raise_server_exceptions=False) as client:
                    resp = client.get("/api/v1/collections/stats")

            assert resp.status_code == 200, f"Expected 200 but got {resp.status_code}: {resp.text}"
            data = resp.json()
            assert isinstance(data["total_collections"], int)
            assert data["total_collections"] == 5
        finally:
            app.dependency_overrides.clear()
