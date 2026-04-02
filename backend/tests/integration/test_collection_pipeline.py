"""
Integration tests for the async collection creation pipeline.
Tests: 202 response, status polling, Celery dispatch, list filtering.
"""
import pytest
from unittest.mock import patch, MagicMock
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.collection import Collection, CollectionStatus
from app.models.user import User, UserRole
from app.utils.security import create_access_token

_FIXTURE_BCRYPT_HASH = "$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW"


class TestCreateCollectionReturns202:
    """POST /api/v1/collections must return 202 with status=building."""

    @pytest.fixture
    def admin_user(self, db: Session) -> User:
        user = User(
            id=uuid4(),
            email="admin_pipeline@test.com",
            hashed_password=_FIXTURE_BCRYPT_HASH,
            full_name="Admin Pipeline User",
            role=UserRole.ADMIN,
            is_active=True,
            can_access_confidential=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    def get_auth_headers(self, user: User) -> dict:
        token = create_access_token(
            data={"sub": user.email, "role": user.role.value, "user_id": str(user.id)}
        )
        return {"Authorization": f"Bearer {token}", "Host": "testserver"}

    def test_create_returns_202_with_building_status(
        self, client: TestClient, db: Session, admin_user: User
    ):
        headers = self.get_auth_headers(admin_user)
        with patch("app.api.collections.build_smart_collection") as mock_task:
            mock_task.delay = MagicMock()

            response = client.post(
                "/api/v1/collections",
                headers=headers,
                json={
                    "name": "Test Async Collection",
                    "query": "Find all financial documents from 2024",
                    "collection_type": "smart",
                    "visibility": "private",
                },
            )

        assert response.status_code == 202, f"Expected 202, got {response.status_code}: {response.text}"
        data = response.json()
        assert data["status"] == "building"
        assert data["name"] == "Test Async Collection"
        assert data["document_count"] == 0

    def test_create_dispatches_celery_task(
        self, client: TestClient, db: Session, admin_user: User
    ):
        headers = self.get_auth_headers(admin_user)
        with patch("app.api.collections.build_smart_collection") as mock_task:
            mock_task.delay = MagicMock()

            client.post(
                "/api/v1/collections",
                headers=headers,
                json={
                    "name": "Celery Dispatch Test",
                    "query": "Find contracts",
                    "collection_type": "smart",
                    "visibility": "private",
                },
            )

            mock_task.delay.assert_called_once()
            args = mock_task.delay.call_args[0]
            assert len(args) == 2
            assert isinstance(args[0], str)  # collection_id
            assert isinstance(args[1], str)  # user_id


class TestCollectionStatusEndpoint:
    """GET /api/v1/collections/{id}/status returns build status."""

    @pytest.fixture
    def admin_user(self, db: Session) -> User:
        user = User(
            id=uuid4(),
            email="admin_status@test.com",
            hashed_password=_FIXTURE_BCRYPT_HASH,
            full_name="Admin Status User",
            role=UserRole.ADMIN,
            is_active=True,
            can_access_confidential=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    def get_auth_headers(self, user: User) -> dict:
        token = create_access_token(
            data={"sub": user.email, "role": user.role.value, "user_id": str(user.id)}
        )
        return {"Authorization": f"Bearer {token}", "Host": "testserver"}

    def test_status_returns_building(
        self, client: TestClient, db: Session, admin_user: User
    ):
        collection = Collection(
            user_id=admin_user.id,
            name="Building Collection",
            query="test",
            collection_type="smart",
            visibility="private",
            status=CollectionStatus.BUILDING,
            document_count=0,
        )
        db.add(collection)
        db.commit()
        db.refresh(collection)

        headers = self.get_auth_headers(admin_user)
        response = client.get(
            f"/api/v1/collections/{collection.id}/status",
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "building"
        assert data["document_count"] == 0

    def test_status_returns_ready_with_count(
        self, client: TestClient, db: Session, admin_user: User
    ):
        collection = Collection(
            user_id=admin_user.id,
            name="Ready Collection",
            query="test",
            collection_type="smart",
            visibility="private",
            status=CollectionStatus.READY,
            document_count=15,
            ai_summary="A summary.",
        )
        db.add(collection)
        db.commit()
        db.refresh(collection)

        headers = self.get_auth_headers(admin_user)
        response = client.get(
            f"/api/v1/collections/{collection.id}/status",
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"
        assert data["document_count"] == 15

    def test_status_returns_failed_with_error(
        self, client: TestClient, db: Session, admin_user: User
    ):
        collection = Collection(
            user_id=admin_user.id,
            name="Failed Collection",
            query="test",
            collection_type="smart",
            visibility="private",
            status=CollectionStatus.FAILED,
            build_error="OpenRouter API timeout after 120s",
            document_count=0,
        )
        db.add(collection)
        db.commit()
        db.refresh(collection)

        headers = self.get_auth_headers(admin_user)
        response = client.get(
            f"/api/v1/collections/{collection.id}/status",
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "failed"
        assert "error" in data
        assert "timeout" in data["error"].lower()


class TestCollectionListFiltering:
    """GET /api/v1/collections must include building/failed collections."""

    @pytest.fixture
    def admin_user(self, db: Session) -> User:
        user = User(
            id=uuid4(),
            email="admin_list@test.com",
            hashed_password=_FIXTURE_BCRYPT_HASH,
            full_name="Admin List User",
            role=UserRole.ADMIN,
            is_active=True,
            can_access_confidential=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    def get_auth_headers(self, user: User) -> dict:
        token = create_access_token(
            data={"sub": user.email, "role": user.role.value, "user_id": str(user.id)}
        )
        return {"Authorization": f"Bearer {token}", "Host": "testserver"}

    def test_list_includes_building_collections(
        self, client: TestClient, db: Session, admin_user: User
    ):
        collection = Collection(
            user_id=admin_user.id,
            name="Building In List",
            query="test",
            collection_type="smart",
            visibility="private",
            status=CollectionStatus.BUILDING,
            document_count=0,
        )
        db.add(collection)
        db.commit()

        headers = self.get_auth_headers(admin_user)
        response = client.get("/api/v1/collections", headers=headers)
        assert response.status_code == 200
        data = response.json()
        names = [c["name"] for c in data["collections"]]
        assert "Building In List" in names
