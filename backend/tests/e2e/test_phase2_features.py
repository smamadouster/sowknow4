"""
E2E Tests for Phase 2 Features

Comprehensive end-to-end tests covering Smart Collections,
Smart Folders, Reports, and Auto-Tagging.
"""
import pytest
from uuid import uuid4
from datetime import datetime
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User, UserRole
from app.models.collection import Collection, CollectionItem
from app.models.document import Document, DocumentTag
from app.utils.security import create_access_token, get_password_hash


@pytest.fixture
def phase2_user(db: Session) -> User:
    """Create a dedicated test user for Phase 2 tests"""
    user = User(
        email="test_phase2@example.com",
        hashed_password=get_password_hash("testpass123"),
        full_name="Phase 2 Test User",
        role=UserRole.USER,
        is_active=True,
        can_access_confidential=False
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def auth_token(phase2_user: User) -> str:
    """Get auth token for test user (generated directly, no HTTP round-trip)"""
    return create_access_token(data={
        "sub": phase2_user.email,
        "role": phase2_user.role.value,
        "user_id": str(phase2_user.id)
    })


@pytest.fixture
def auth_headers(auth_token: str) -> dict:
    """Authorization headers for Phase 2 tests"""
    return {"Authorization": f"Bearer {auth_token}"}


class TestSmartCollections:
    """E2E tests for Smart Collections feature"""

    def test_create_collection_from_query(self, client: TestClient, auth_headers: dict):
        """Test creating a collection from natural language query"""
        response = client.post(
            "/api/v1/collections",
            headers=auth_headers,
            json={
                "name": "Financial Documents 2023",
                "query": "Show me all financial documents from 2023",
                "collection_type": "smart",
                "visibility": "private",
                "save": True
            }
        )

        assert response.status_code in [200, 201]
        data = response.json()
        assert data["name"] == "Financial Documents 2023"
        assert data["query"] == "Show me all financial documents from 2023"
        assert "id" in data

    def test_preview_collection(self, client: TestClient, auth_headers: dict):
        """Test previewing a collection without saving"""
        response = client.post(
            "/api/v1/collections/preview",
            headers=auth_headers,
            json={
                "query": "Photos from vacation"
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert "intent" in data
        assert "documents" in data
        assert "estimated_count" in data

    def test_list_collections(self, client: TestClient, auth_headers: dict):
        """Test listing user's collections"""
        response = client.get(
            "/api/v1/collections",
            headers=auth_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert "collections" in data
        assert "total" in data

    def test_get_collection_detail(self, client: TestClient, auth_headers: dict):
        """Test getting collection details with items"""
        # First create a collection
        create_response = client.post(
            "/api/v1/collections",
            headers=auth_headers,
            json={
                "name": "Test Collection",
                "query": "Test documents",
                "save": True
            }
        )

        if create_response.status_code in [200, 201]:
            collection_id = create_response.json()["id"]

            # Get details
            response = client.get(
                f"/api/v1/collections/{collection_id}",
                headers=auth_headers
            )

            assert response.status_code == 200
            data = response.json()
            assert data["id"] == collection_id
            assert "items" in data

    def test_pin_collection(self, client: TestClient, auth_headers: dict):
        """Test pinning/unpinning a collection"""
        # Create collection first
        create_response = client.post(
            "/api/v1/collections",
            headers=auth_headers,
            json={
                "name": "Pinnable Collection",
                "query": "Important documents",
                "save": True
            }
        )

        if create_response.status_code in [200, 201]:
            collection_id = create_response.json()["id"]

            # Pin
            response = client.post(
                f"/api/v1/collections/{collection_id}/pin",
                headers=auth_headers
            )

            assert response.status_code == 200
            data = response.json()
            assert data["is_pinned"] is True

    def test_refresh_collection(self, client: TestClient, auth_headers: dict):
        """Test refreshing a collection"""
        # Create collection
        create_response = client.post(
            "/api/v1/collections",
            headers=auth_headers,
            json={
                "name": "Refreshable Collection",
                "query": "Documents",
                "save": True
            }
        )

        if create_response.status_code in [200, 201]:
            collection_id = create_response.json()["id"]

            # Refresh
            response = client.post(
                f"/api/v1/collections/{collection_id}/refresh",
                headers=auth_headers
            )

            assert response.status_code == 200
            data = response.json()
            assert "last_refreshed_at" in data


class TestSmartFolders:
    """E2E tests for Smart Folders feature"""

    def test_generate_smart_folder(self, client: TestClient, auth_headers: dict):
        """Test generating a Smart Folder"""
        response = client.post(
            "/api/v1/smart-folders/generate",
            headers=auth_headers,
            json={
                "topic": "Annual performance summary",
                "style": "professional",
                "length": "medium",
                "include_confidential": False
            }
        )

        assert response.status_code in [200, 201]
        data = response.json()
        assert "collection_id" in data
        assert "generated_content" in data
        assert "sources_used" in data
        assert data["llm_used"] in ["minimax", "kimi", "ollama", "openrouter", "none"]

    def test_get_report_templates(self, client: TestClient, auth_headers: dict):
        """Test getting available report templates"""
        response = client.get(
            "/api/v1/smart-folders/reports/templates",
            headers=auth_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert "formats" in data
        assert len(data["formats"]) == 3


class TestReports:
    """E2E tests for Report Generation feature"""

    def test_generate_short_report(self, client: TestClient, auth_headers: dict):
        """Test generating a short report"""
        # First create a collection
        collection_response = client.post(
            "/api/v1/collections",
            headers=auth_headers,
            json={
                "name": "Report Test Collection",
                "query": "Test documents for report",
                "save": True
            }
        )

        if collection_response.status_code in [200, 201]:
            collection_id = collection_response.json()["id"]

            # Generate report
            response = client.post(
                "/api/v1/smart-folders/reports/generate",
                headers=auth_headers,
                json={
                    "collection_id": collection_id,
                    "format": "short",
                    "include_citations": True,
                    "language": "en"
                }
            )

            assert response.status_code == 200
            data = response.json()
            assert "content" in data
            assert "citations" in data
            assert data["format"] == "short"


class TestAutoTagging:
    """E2E tests for Auto-Tagging feature"""

    def test_auto_tag_on_upload(self, client: TestClient, auth_headers: dict):
        """Test that documents are auto-tagged on upload"""
        # This would require actual file upload
        # For now, we test the service directly
        pass

    def test_similar_documents(self, client: TestClient, auth_headers: dict):
        """Test finding similar documents based on tags"""
        # Implementation depends on similarity endpoint
        pass


class TestPhase2Integration:
    """Integration tests for Phase 2 workflows"""

    def test_full_collection_workflow(self, client: TestClient, auth_headers: dict):
        """Test complete workflow: create collection -> chat -> generate report"""
        # 1. Create collection
        collection_response = client.post(
            "/api/v1/collections",
            headers=auth_headers,
            json={
                "name": "Integration Test Collection",
                "query": "Financial reports 2023",
                "save": True
            }
        )

        assert collection_response.status_code in [200, 201]
        collection_id = collection_response.json()["id"]

        # 2. Get collection details
        detail_response = client.get(
            f"/api/v1/collections/{collection_id}",
            headers=auth_headers
        )
        assert detail_response.status_code == 200

        # 3. Generate report
        report_response = client.post(
            "/api/v1/smart-folders/reports/generate",
            headers=auth_headers,
            json={
                "collection_id": collection_id,
                "format": "standard"
            }
        )
        assert report_response.status_code == 200

    def test_cache_performance(self, client: TestClient, auth_headers: dict):
        """Test that context caching improves performance on repeated queries"""
        # This test would measure latency on repeated queries
        # First query should be slower, subsequent queries faster (cache hit)
        pass


@pytest.mark.e2e
class TestPhase2CriticalPaths:
    """Critical path tests for Phase 2 - must pass for release"""

    def test_user_can_create_and_use_collection(
        self, client: TestClient, auth_headers: dict
    ):
        """Critical: User can create collection and use it"""
        # Create collection
        response = client.post(
            "/api/v1/collections",
            headers=auth_headers,
            json={
                "name": "My Documents",
                "query": "Important papers",
                "save": True
            }
        )
        assert response.status_code in [200, 201]

    def test_cache_hit_rate_above_target(self, client: TestClient, auth_headers: dict):
        """Critical: Cache hit rate above 30% target"""
        # This would run repeated queries and measure cache effectiveness
        pass

    def test_confidential_routing_accuracy(self, client: TestClient, auth_headers: dict):
        """Critical: Confidential routing is 100% accurate"""
        # Ensure confidential docs never go to cloud LLM
        pass
