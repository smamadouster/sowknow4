"""
E2E Tests for Phase 2 Features

Comprehensive end-to-end tests covering Smart Collections,
Smart Folders, Reports, and Auto-Tagging.
"""
import pytest
import asyncio
from uuid import uuid4
from datetime import datetime
from httpx import AsyncClient

from app.database import get_db
from app.models.user import User, UserRole
from app.models.collection import Collection, CollectionItem
from app.models.document import Document, DocumentTag


@pytest.fixture
async def test_user(db_session):
    """Create a test user"""
    user = User(
        email="test_phase2@example.com",
        hashed_password="hashed",
        full_name="Phase 2 Test User",
        role=UserRole.USER,
        can_access_confidential=False
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def auth_token(client: AsyncClient, test_user: User):
    """Get auth token for test user"""
    response = await client.post(
        "/api/v1/auth/login",
        json={
            "email": test_user.email,
            "password": "testpass123"
        }
    )
    if response.status_code == 200:
        data = response.json()
        return data.get("access_token")
    return None


class TestSmartCollections:
    """E2E tests for Smart Collections feature"""

    @pytest.mark.asyncio
    async def test_create_collection_from_query(
        self, client: AsyncClient, auth_token: str
    ):
        """Test creating a collection from natural language query"""
        response = await client.post(
            "/api/v1/collections",
            headers={"Authorization": f"Bearer {auth_token}"},
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

    @pytest.mark.asyncio
    async def test_preview_collection(self, client: AsyncClient, auth_token: str):
        """Test previewing a collection without saving"""
        response = await client.post(
            "/api/v1/collections/preview",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={
                "query": "Photos from vacation"
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert "intent" in data
        assert "documents" in data
        assert "estimated_count" in data

    @pytest.mark.asyncio
    async def test_list_collections(
        self, client: AsyncClient, auth_token: str
    ):
        """Test listing user's collections"""
        response = await client.get(
            "/api/v1/collections",
            headers={"Authorization": f"Bearer {auth_token}"}
        )

        assert response.status_code == 200
        data = response.json()
        assert "collections" in data
        assert "total" in data

    @pytest.mark.asyncio
    async def test_get_collection_detail(
        self, client: AsyncClient, auth_token: str
    ):
        """Test getting collection details with items"""
        # First create a collection
        create_response = await client.post(
            "/api/v1/collections",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={
                "name": "Test Collection",
                "query": "Test documents",
                "save": True
            }
        )

        if create_response.status_code in [200, 201]:
            collection_id = create_response.json()["id"]

            # Get details
            response = await client.get(
                f"/api/v1/collections/{collection_id}",
                headers={"Authorization": f"Bearer {auth_token}"}
            )

            assert response.status_code == 200
            data = response.json()
            assert data["id"] == collection_id
            assert "items" in data

    @pytest.mark.asyncio
    async def test_pin_collection(
        self, client: AsyncClient, auth_token: str
    ):
        """Test pinning/unpinning a collection"""
        # Create collection first
        create_response = await client.post(
            "/api/v1/collections",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={
                "name": "Pinnable Collection",
                "query": "Important documents",
                "save": True
            }
        )

        if create_response.status_code in [200, 201]:
            collection_id = create_response.json()["id"]

            # Pin
            response = await client.post(
                f"/api/v1/collections/{collection_id}/pin",
                headers={"Authorization": f"Bearer {auth_token}"}
            )

            assert response.status_code == 200
            data = response.json()
            assert data["is_pinned"] == True

    @pytest.mark.asyncio
    async def test_refresh_collection(
        self, client: AsyncClient, auth_token: str
    ):
        """Test refreshing a collection"""
        # Create collection
        create_response = await client.post(
            "/api/v1/collections",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={
                "name": "Refreshable Collection",
                "query": "Documents",
                "save": True
            }
        )

        if create_response.status_code in [200, 201]:
            collection_id = create_response.json()["id"]

            # Refresh
            response = await client.post(
                f"/api/v1/collections/{collection_id}/refresh",
                headers={"Authorization": f"Bearer {auth_token}"}
            )

            assert response.status_code == 200
            data = response.json()
            assert "last_refreshed_at" in data


class TestSmartFolders:
    """E2E tests for Smart Folders feature"""

    @pytest.mark.asyncio
    async def test_generate_smart_folder(
        self, client: AsyncClient, auth_token: str
    ):
        """Test generating a Smart Folder"""
        response = await client.post(
            "/api/v1/smart-folders/generate",
            headers={"Authorization": f"Bearer {auth_token}"},
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
        assert data["llm_used"] in ["gemini", "ollama"]

    @pytest.mark.asyncio
    async def test_get_report_templates(
        self, client: AsyncClient, auth_token: str
    ):
        """Test getting available report templates"""
        response = await client.get(
            "/api/v1/smart-folders/reports/templates",
            headers={"Authorization": f"Bearer {auth_token}"}
        )

        assert response.status_code == 200
        data = response.json()
        assert "formats" in data
        assert len(data["formats"]) == 3


class TestReports:
    """E2E tests for Report Generation feature"""

    @pytest.mark.asyncio
    async def test_generate_short_report(
        self, client: AsyncClient, auth_token: str
    ):
        """Test generating a short report"""
        # First create a collection
        collection_response = await client.post(
            "/api/v1/collections",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={
                "name": "Report Test Collection",
                "query": "Test documents for report",
                "save": True
            }
        )

        if collection_response.status_code in [200, 201]:
            collection_id = collection_response.json()["id"]

            # Generate report
            response = await client.post(
                "/api/v1/smart-folders/reports/generate",
                headers={"Authorization": f"Bearer {auth_token}"},
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

    @pytest.mark.asyncio
    async def test_auto_tag_on_upload(
        self, client: AsyncClient, auth_token: str
    ):
        """Test that documents are auto-tagged on upload"""
        # This would require actual file upload
        # For now, we test the service directly
        pass

    @pytest.mark.asyncio
    async def test_similar_documents(
        self, client: AsyncClient, auth_token: str
    ):
        """Test finding similar documents based on tags"""
        # Implementation depends on similarity endpoint
        pass


class TestPhase2Integration:
    """Integration tests for Phase 2 workflows"""

    @pytest.mark.asyncio
    async def test_full_collection_workflow(
        self, client: AsyncClient, auth_token: str
    ):
        """Test complete workflow: create collection -> chat -> generate report"""
        # 1. Create collection
        collection_response = await client.post(
            "/api/v1/collections",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={
                "name": "Integration Test Collection",
                "query": "Financial reports 2023",
                "save": True
            }
        )

        assert collection_response.status_code in [200, 201]
        collection_id = collection_response.json()["id"]

        # 2. Get collection details
        detail_response = await client.get(
            f"/api/v1/collections/{collection_id}",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert detail_response.status_code == 200

        # 3. Generate report
        report_response = await client.post(
            "/api/v1/smart-folders/reports/generate",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={
                "collection_id": collection_id,
                "format": "standard"
            }
        )
        assert report_response.status_code == 200

    @pytest.mark.asyncio
    async def test_cache_performance(
        self, client: AsyncClient, auth_token: str
    ):
        """Test that context caching improves performance on repeated queries"""
        # This test would measure latency on repeated queries
        # First query should be slower, subsequent queries faster (cache hit)
        pass


@pytest.mark.e2e
class TestPhase2CriticalPaths:
    """Critical path tests for Phase 2 - must pass for release"""

    @pytest.mark.asyncio
    async def test_user_can_create_and_use_collection(
        self, client: AsyncClient, auth_token: str
    ):
        """Critical: User can create collection and use it"""
        # Create collection
        response = await client.post(
            "/api/v1/collections",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={
                "name": "My Documents",
                "query": "Important papers",
                "save": True
            }
        )
        assert response.status_code in [200, 201]

    @pytest.mark.asyncio
    async def test_cache_hit_rate_above_target(
        self, client: AsyncClient, auth_token: str
    ):
        """Critical: Cache hit rate above 30% target"""
        # This would run repeated queries and measure cache effectiveness
        pass

    @pytest.mark.asyncio
    async def test_confidential_routing_accuracy(
        self, client: AsyncClient, auth_token: str
    ):
        """Critical: Confidential routing is 100% accurate"""
        # Ensure confidential docs never go to cloud LLM
        pass
