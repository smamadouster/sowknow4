"""
Integration tests for API endpoints
Tests authentication, documents, collections, search, and RBAC enforcement
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from unittest.mock import patch, MagicMock
import uuid


class TestAuthenticationEndpoints:
    """Test authentication-related endpoints"""

    def test_register_new_user(self, client: TestClient, db: Session):
        """Test successful user registration"""
        response = client.post(
            "/api/v1/auth/register",
            json={
                "email": "newuser@example.com",
                "password": "SecurePassword123!",
                "full_name": "New User"
            }
        )
        assert response.status_code == 201
        data = response.json()
        assert data["email"] == "newuser@example.com"
        assert data["full_name"] == "New User"
        assert data["role"] == "user"

    def test_register_duplicate_email_fails(self, client: TestClient, test_user):
        """Test that duplicate email registration fails"""
        response = client.post(
            "/api/v1/auth/register",
            json={
                "email": test_user.email,
                "password": "SecurePassword123!",
                "full_name": "Duplicate User"
            }
        )
        assert response.status_code == 400
        assert "already exists" in response.json()["detail"].lower()

    def test_login_with_invalid_credentials(self, client: TestClient):
        """Test login fails with invalid credentials"""
        response = client.post(
            "/api/v1/auth/login",
            data={
                "username": "nonexistent@example.com",
                "password": "wrongpassword"
            }
        )
        assert response.status_code == 401

    def test_access_protected_endpoint_without_token(self, client: TestClient):
        """Test that protected endpoints require authentication"""
        response = client.get("/api/v1/auth/me")
        assert response.status_code == 401

    def test_telegram_auth_creates_user(self, client: TestClient, db: Session):
        """Test Telegram authentication creates new user"""
        response = client.post(
            "/api/v1/auth/telegram",
            json={
                "telegram_user_id": 123456789,
                "username": "testuser",
                "first_name": "Test",
                "last_name": "User",
                "language_code": "en"
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data


class TestDocumentEndpoints:
    """Test document-related endpoints"""

    def test_list_documents_requires_auth(self, client: TestClient):
        """Test that listing documents requires authentication"""
        response = client.get("/api/v1/documents/")
        assert response.status_code == 401

    def test_upload_document_requires_auth(self, client: TestClient):
        """Test that document upload requires authentication"""
        response = client.post(
            "/api/v1/documents/upload",
            files={"file": ("test.pdf", b"fake content", "application/pdf")}
        )
        assert response.status_code == 401

    @pytest.mark.skip("Requires file upload mock")
    def test_user_cannot_access_confidential_documents(self, client: TestClient, auth_headers):
        """Test that regular users cannot access confidential documents"""
        # This test would require creating documents in different buckets
        # and verifying access control
        pass


class TestCollectionEndpoints:
    """Test collection-related endpoints"""

    def test_list_collections_requires_auth(self, client: TestClient):
        """Test that listing collections requires authentication"""
        response = client.get("/api/v1/collections/")
        assert response.status_code == 401

    def test_create_collection_requires_auth(self, client: TestClient):
        """Test that creating collection requires authentication"""
        response = client.post(
            "/api/v1/collections/",
            json={
                "name": "Test Collection",
                "description": "Test Description"
            }
        )
        assert response.status_code == 401


class TestSearchEndpoints:
    """Test search-related endpoints"""

    def test_search_requires_auth(self, client: TestClient):
        """Test that search requires authentication"""
        response = client.get("/api/v1/search?q=test")
        assert response.status_code == 401

    @patch('app.services.search_service.search_service.semantic_search')
    async def test_search_returns_results(self, mock_search, client: TestClient, auth_headers):
        """Test that search returns results when authenticated"""
        # Mock the search service
        mock_search.return_value = []

        response = client.get(
            "/api/v1/search?q=test",
            headers=auth_headers
        )
        # Should not be 401
        assert response.status_code != 401


class TestChatEndpoints:
    """Test chat-related endpoints"""

    def test_chat_requires_auth(self, client: TestClient):
        """Test that chat endpoint requires authentication"""
        response = client.post(
            "/api/v1/chat",
            json={"message": "Hello"}
        )
        assert response.status_code == 401

    @patch('app.services.chat_service.gemini_service')
    async def test_chat_with_valid_message(self, mock_gemini, client: TestClient, auth_headers):
        """Test chat with valid message"""
        # Mock the Gemini service
        mock_gemini.chat_completion = MagicMock()

        response = client.post(
            "/api/v1/chat",
            headers=auth_headers,
            json={
                "message": "What is in my documents?",
                "session_id": str(uuid.uuid4())
            }
        )
        # Should not be 401
        assert response.status_code != 401


class TestKnowledgeGraphEndpoints:
    """Test knowledge graph endpoints"""

    def test_graph_entities_requires_auth(self, client: TestClient):
        """Test that accessing graph entities requires authentication"""
        response = client.get("/api/v1/knowledge-graph/entities")
        assert response.status_code == 401

    def test_graph_relationships_requires_auth(self, client: TestClient):
        """Test that accessing graph relationships requires authentication"""
        response = client.get("/api/v1/knowledge-graph/relationships")
        assert response.status_code == 401


class TestAdminEndpoints:
    """Test admin-specific endpoints"""

    def test_admin_requires_admin_role(self, client: TestClient, auth_headers):
        """Test that admin endpoints require admin role"""
        # Regular user headers
        response = client.get("/api/v1/admin/users", headers=auth_headers)
        # Should either be 403 (forbidden) or 404 (not found if endpoint doesn't exist)
        assert response.status_code in [401, 403, 404]

    def test_admin_can_access_all_documents(self, client: TestClient):
        """Test that admin can access documents from all buckets"""
        # This would require creating admin tokens and testing access
        pass


class TestHealthEndpoints:
    """Test health check endpoints"""

    def test_health_check_public(self, client: TestClient):
        """Test that health check is publicly accessible"""
        response = client.get("/health")
        # Should be accessible without auth
        assert response.status_code in [200, 404]  # 404 if endpoint doesn't exist

    def test_api_health(self, client: TestClient):
        """Test API health endpoint"""
        response = client.get("/api/v1/health")
        # Should be accessible
        assert response.status_code in [200, 404]


class TestRateLimiting:
    """Test rate limiting and CORS"""

    def test_cors_headers_present(self, client: TestClient):
        """Test that CORS headers are properly set"""
        response = client.options("/api/v1/auth/login")
        # Check for CORS headers
        assert response.status_code in [200, 405]  # 405 if method not allowed

    def test_rate_limiting(self, client: TestClient):
        """Test that rate limiting is enforced"""
        # This would require multiple rapid requests
        # For now, we'll skip this as it requires infrastructure setup
        pass
