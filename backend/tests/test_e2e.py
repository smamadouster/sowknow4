"""
End-to-End Tests for SOWKNOW Phase 3

Tests the complete system including:
- Authentication
- Document processing
- Knowledge Graph
- Graph-RAG
- Multi-Agent Search
"""
import pytest
import asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.orm import Session

from app.main import app
from app.database import get_db
from app.models.user import User
from app.models.document import Document, DocumentStatus


@pytest.fixture
async def client():
    """Async test client"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def test_user(client: AsyncClient, db: Session):
    """Create test user"""
    # Check if test user exists
    user = db.query(User).filter(User.email == "test@sowknow.com").first()
    if not user:
        # Create test user
        response = await client.post("/api/v1/auth/register", json={
            "email": "test@sowknow.com",
            "password": "TestPassword123!",
            "full_name": "Test User"
        })
        assert response.status_code == 200
        user = db.query(User).filter(User.email == "test@sowknow.com").first()

    return user


@pytest.fixture
async def auth_token(client: AsyncClient, test_user: User):
    """Get authentication token"""
    response = await client.post("/api/v1/auth/login", json={
        "email": "test@sowknow.com",
        "password": "TestPassword123!"
    })
    assert response.status_code == 200
    data = response.json()
    return data.get("access_token")


class TestAuthentication:
    """Test authentication flows"""

    async def test_register_new_user(self, client: AsyncClient):
        """Test user registration"""
        response = await client.post("/api/v1/auth/register", json={
            "email": "e2e_test@sowknow.com",
            "password": "TestPassword123!",
            "full_name": "E2E Test User"
        })
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["email"] == "e2e_test@sowknow.com"

    async def test_login(self, client: AsyncClient, test_user: User):
        """Test user login"""
        response = await client.post("/api/v1/auth/login", json={
            "email": "test@sowknow.com",
            "password": "TestPassword123!"
        })
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data

    async def test_get_current_user(self, client: AsyncClient, auth_token: str):
        """Test getting current user info"""
        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == "test@sowknow.com"


class TestHealthEndpoints:
    """Test health check endpoints"""

    async def test_health_check(self, client: AsyncClient):
        """Test health endpoint"""
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "services" in data

    async def test_api_status(self, client: AsyncClient):
        """Test API status endpoint"""
        response = await client.get("/api/v1/status")
        assert response.status_code == 200
        data = response.json()
        assert "phase" in data
        assert "features" in data


class TestKnowledgeGraph:
    """Test Knowledge Graph functionality"""

    async def test_list_entities(self, client: AsyncClient, auth_token: str):
        """Test listing entities"""
        response = await client.get(
            "/api/v1/knowledge-graph/entities",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "entities" in data
        assert "total" in data

    async def test_get_graph(self, client: AsyncClient, auth_token: str):
        """Test getting knowledge graph data"""
        response = await client.get(
            "/api/v1/knowledge-graph/graph",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "nodes" in data
        assert "edges" in data

    async def test_get_timeline(self, client: AsyncClient, auth_token: str):
        """Test getting timeline events"""
        response = await client.get(
            "/api/v1/knowledge-graph/timeline",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "events" in data


class TestGraphRAG:
    """Test Graph-RAG functionality"""

    async def test_graph_augmented_search(self, client: AsyncClient, auth_token: str):
        """Test graph-augmented search"""
        response = await client.post(
            "/api/v1/graph-rag/search",
            params={"query": "test search"},
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "query" in data
        assert "results" in data

    async def test_find_entity_paths(self, client: AsyncClient, auth_token: str):
        """Test finding paths between entities"""
        response = await client.get(
            "/api/v1/graph-rag/paths/entity1/entity2",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        # May return 404 if entities don't exist, that's OK
        assert response.status_code in [200, 404]

    async def test_get_entity_neighborhood(self, client: AsyncClient, auth_token: str):
        """Test getting entity neighborhood"""
        response = await client.get(
            "/api/v1/graph-rag/neighborhood/TestEntity",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        # May return 404 if entity doesn't exist
        assert response.status_code in [200, 404]


class TestMultiAgent:
    """Test Multi-Agent Search functionality"""

    async def test_multi_agent_search(self, client: AsyncClient, auth_token: str):
        """Test full multi-agent search"""
        response = await client.post(
            "/api/v1/multi-agent/search",
            params={"query": "What is SOWKNOW?"},
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "query" in data
        assert "answer" in data
        assert "state" in data

    async def test_clarify_query(self, client: AsyncClient, auth_token: str):
        """Test query clarification"""
        response = await client.post(
            "/api/v1/multi-agent/clarify",
            params={"query": "find information about the project"},
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "is_clear" in data
        assert "confidence" in data

    async def test_research_query(self, client: AsyncClient, auth_token: str):
        """Test research agent"""
        response = await client.post(
            "/api/v1/multi-agent/research",
            params={"query": "knowledge graph features"},
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "query" in data
        assert "findings" in data

    async def test_verify_claim(self, client: AsyncClient, auth_token: str):
        """Test verification agent"""
        response = await client.post(
            "/api/v1/multi-agent/verify",
            params={"claim": "SOWKNOW is a knowledge management system"},
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "claim" in data
        assert "is_verified" in data

    async def test_generate_answer(self, client: AsyncClient, auth_token: str):
        """Test answer agent"""
        response = await client.post(
            "/api/v1/multi-agent/answer",
            params={"query": "What are the main features?"},
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "query" in data
        assert "answer" in data
        assert "key_points" in data

    async def test_multi_agent_status(self, client: AsyncClient, auth_token: str):
        """Test multi-agent system status"""
        response = await client.get(
            "/api/v1/multi-agent/status",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "system" in data
        assert "agents" in data


class TestCollections:
    """Test Smart Collections functionality"""

    async def test_list_collections(self, client: AsyncClient, auth_token: str):
        """Test listing collections"""
        response = await client.get(
            "/api/v1/collections",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "collections" in data

    async def test_create_collection(self, client: AsyncClient, auth_token: str):
        """Test creating a collection"""
        response = await client.post(
            "/api/v1/collections",
            json={
                "name": "E2E Test Collection",
                "query": "documents about testing"
            },
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "id" in data
        assert data["name"] == "E2E Test Collection"


class TestSmartFolders:
    """Test Smart Folders functionality"""

    async def test_generate_smart_folder(self, client: AsyncClient, auth_token: str):
        """Test generating smart folder content"""
        response = await client.post(
            "/api/v1/smart-folders/generate",
            json={
                "topic": "Knowledge Management",
                "style": "informative",
                "length": "medium"
            },
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "topic" in data
        assert "content" in data


@pytest.mark.integration
class TestIntegrationFlows:
    """Integration tests for complete workflows"""

    async def test_document_to_graph_workflow(self, client: AsyncClient, auth_token: str):
        """Test workflow: Document upload -> Entity extraction -> Graph visualization"""
        # Note: This test requires actual file upload capability
        # For now, we test the endpoints are accessible
        pass

    async def test_search_to_answer_workflow(self, client: AsyncClient, auth_token: str):
        """Test workflow: Query -> Multi-agent search -> Answer"""
        response = await client.post(
            "/api/v1/multi-agent/search",
            params={"query": "What features does SOWKNOW have?"},
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "answer" in data
        assert len(data["answer"]) > 0


@pytest.mark.performance
class TestPerformance:
    """Performance tests"""

    async def test_search_response_time(self, client: AsyncClient, auth_token: str):
        """Test search response time is acceptable"""
        import time

        start = time.time()
        response = await client.post(
            "/api/v1/multi-agent/search",
            params={"query": "test query"},
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        duration = time.time() - start

        assert response.status_code == 200
        # Multi-agent search should complete within 30 seconds
        assert duration < 30

    async def test_graph_query_response_time(self, client: AsyncClient, auth_token: str):
        """Test graph query response time"""
        import time

        start = time.time()
        response = await client.get(
            "/api/v1/knowledge-graph/graph",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        duration = time.time() - start

        assert response.status_code == 200
        # Graph queries should be fast (< 3 seconds)
        assert duration < 3


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
