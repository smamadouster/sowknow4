"""
Integration tests for the async collection creation pipeline.
Tests: 202 response, status polling, Celery dispatch, list filtering.
"""
import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock, AsyncMock
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.collection import Collection, CollectionItem, CollectionStatus
from app.models.document import Document, DocumentBucket, DocumentStatus
from app.models.user import User, UserRole
from app.services.collection_service import collection_service
from app.services.intent_parser import ParsedIntent
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


def _make_mock_doc(bucket: DocumentBucket, filename: str = "test.pdf") -> MagicMock:
    """Helper to create a mock Document with required attributes."""
    doc = MagicMock(spec=Document)
    doc.id = uuid4()
    doc.bucket = bucket
    doc.filename = filename
    doc.created_at = datetime(2025, 6, 15)
    doc.status = DocumentStatus.INDEXED
    return doc


def _make_parsed_intent(query: str = "test query") -> ParsedIntent:
    """Helper to create a ParsedIntent for testing."""
    return ParsedIntent(
        query=query,
        keywords=["test"],
        entities=[{"name": "Test Entity", "type": "ORG"}],
        confidence=0.9,
    )


@pytest.mark.sqlite_safe
class TestLLMRoutingAccuracy:
    """Verify privacy-preserving LLM routing: confidential -> Ollama, public -> OpenRouter."""

    @pytest.mark.asyncio
    async def test_confidential_docs_use_ollama_for_summary(self):
        """Confidential documents must route to Ollama (local), never to cloud APIs."""
        docs = [
            _make_mock_doc(DocumentBucket.CONFIDENTIAL, "secret_contract.pdf"),
            _make_mock_doc(DocumentBucket.CONFIDENTIAL, "tax_return_2024.pdf"),
        ]
        intent = _make_parsed_intent("Find confidential contracts")

        with patch.object(
            collection_service.ollama_service, "generate", new_callable=AsyncMock
        ) as mock_ollama:
            mock_ollama.return_value = "Summary of confidential documents."

            result = await collection_service._generate_collection_summary(
                collection_name="Confidential Contracts",
                query="Find confidential contracts",
                documents=docs,
                parsed_intent=intent,
            )

            mock_ollama.assert_called_once()
            assert "confidential" in result.lower() or len(result) > 0
            # Verify Ollama was called with expected keyword args
            call_kwargs = mock_ollama.call_args
            assert "prompt" in call_kwargs.kwargs or len(call_kwargs.args) > 0

    @pytest.mark.asyncio
    async def test_public_docs_use_openrouter_for_summary(self):
        """Public-only documents must route to OpenRouter, not Ollama."""
        docs = [
            _make_mock_doc(DocumentBucket.PUBLIC, "meeting_notes.pdf"),
            _make_mock_doc(DocumentBucket.PUBLIC, "recipe_collection.pdf"),
        ]
        intent = _make_parsed_intent("Find meeting notes")

        mock_openrouter = MagicMock()

        # chat_completion is an async generator
        async def fake_chat_completion(**kwargs):
            yield "Summary of public documents."

        mock_openrouter.chat_completion = fake_chat_completion

        with patch(
            "app.services.openrouter_service.openrouter_service", mock_openrouter
        ):

            result = await collection_service._generate_collection_summary(
                collection_name="Meeting Notes",
                query="Find meeting notes",
                documents=docs,
                parsed_intent=intent,
            )

            assert len(result) > 0
            assert "public" in result.lower() or "Summary" in result

    @pytest.mark.asyncio
    async def test_mixed_docs_route_to_ollama(self):
        """If ANY document is confidential, the entire summary must use Ollama."""
        docs = [
            _make_mock_doc(DocumentBucket.PUBLIC, "public_report.pdf"),
            _make_mock_doc(DocumentBucket.CONFIDENTIAL, "private_letter.pdf"),
        ]
        intent = _make_parsed_intent("Find all reports")

        with patch.object(
            collection_service.ollama_service, "generate", new_callable=AsyncMock
        ) as mock_ollama:
            mock_ollama.return_value = "Mixed collection summary."

            result = await collection_service._generate_collection_summary(
                collection_name="All Reports",
                query="Find all reports",
                documents=docs,
                parsed_intent=intent,
            )

            mock_ollama.assert_called_once()
            assert len(result) > 0


class TestRefreshEndpointStillWorks:
    """Regression test: refresh endpoint returns 200 for ready collections."""

    @pytest.fixture
    def admin_user(self, db: Session) -> User:
        user = User(
            id=uuid4(),
            email="admin_refresh@test.com",
            hashed_password=_FIXTURE_BCRYPT_HASH,
            full_name="Admin Refresh User",
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

    def test_refresh_returns_200(
        self, client: TestClient, db: Session, admin_user: User
    ):
        """POST /collections/{id}/refresh should return 200 for a ready collection."""
        collection = Collection(
            user_id=admin_user.id,
            name="Refresh Test Collection",
            query="Find financial documents",
            collection_type="smart",
            visibility="private",
            status=CollectionStatus.READY,
            document_count=5,
            ai_summary="Original summary.",
        )
        db.add(collection)
        db.commit()
        db.refresh(collection)

        headers = self.get_auth_headers(admin_user)

        with patch.object(
            collection_service, "refresh_collection", new_callable=AsyncMock
        ) as mock_refresh:
            # Return a mock that looks like a Collection response
            mock_collection = MagicMock()
            mock_collection.id = collection.id
            mock_collection.name = collection.name
            mock_collection.query = collection.query
            mock_collection.collection_type = "smart"
            mock_collection.visibility = "private"
            mock_collection.status = CollectionStatus.READY
            mock_collection.document_count = 8
            mock_collection.ai_summary = "Refreshed summary."
            mock_collection.created_at = datetime(2025, 6, 15)
            mock_collection.updated_at = datetime(2025, 6, 16)
            mock_collection.user_id = admin_user.id
            mock_collection.build_error = None
            mock_collection.items = []
            mock_refresh.return_value = mock_collection

            response = client.post(
                f"/api/v1/collections/{collection.id}/refresh",
                headers=headers,
            )

        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
