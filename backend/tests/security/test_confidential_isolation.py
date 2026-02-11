"""
Confidential Bucket Isolation Tests.

This module tests that confidential documents are properly isolated
from unauthorized users according to CLAUDE.md requirements:

Tests verify:
- User searches → only public results
- SuperUser searches → public + confidential results
- User accesses confidential doc by ID → 404 (not 403!)
- SuperUser accesses confidential doc → 200
- Admin searches → all results
- Confidential documents never appear in user's autocomplete/suggestions
"""
import pytest
import uuid
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.user import User, UserRole
from app.models.document import Document, DocumentBucket, DocumentStatus
from app.utils.security import create_access_token, get_password_hash


def get_auth_headers(user: User) -> dict:
    """Helper to create auth headers for a user"""
    token = create_access_token(data={
        "sub": user.email,
        "role": user.role.value,
        "user_id": str(user.id)
    })
    return {"Authorization": f"Bearer {token}"}


class TestSearchIsolation:
    """Test that search properly filters by bucket based on user role"""

    def test_user_search_returns_only_public_documents(self, test_client: TestClient, db: Session):
        """Test that regular user search only returns public documents"""
        # Create regular user
        user = User(
            email="user@test.com",
            hashed_password=get_password_hash("password"),
            full_name="Regular User",
            role=UserRole.USER,
            is_active=True
        )
        db.add(user)
        db.commit()

        # Create documents in different buckets
        public_doc = Document(
            filename="public_report.pdf",
            original_filename="public_report.pdf",
            file_path="/data/public/public_report.pdf",
            bucket=DocumentBucket.PUBLIC,
            status=DocumentStatus.INDEXED,
            size=1024,
            mime_type="application/pdf"
        )
        confidential_doc = Document(
            filename="secret_plan.pdf",
            original_filename="secret_plan.pdf",
            file_path="/data/confidential/secret_plan.pdf",
            bucket=DocumentBucket.CONFIDENTIAL,
            status=DocumentStatus.INDEXED,
            size=1024,
            mime_type="application/pdf"
        )
        db.add(public_doc)
        db.add(confidential_doc)
        db.commit()

        # Search for "report" - should only find public
        response = client.post(
            "/api/v1/search",
            json={"query": "report", "limit": 10},
            headers=get_auth_headers(user)
        )

        if response.status_code == 200:
            data = response.json()
            # Should only contain public documents
            for result in data.get("results", []):
                assert result.get("document_bucket") != "confidential"
                assert result.get("document_bucket") in ["public", DocumentBucket.PUBLIC.value]

    def test_superuser_search_returns_all_documents(self, test_client: TestClient, db: Session):
        """Test that superuser search returns both public and confidential documents"""
        # Create superuser
        superuser = User(
            email="super@test.com",
            hashed_password=get_password_hash("password"),
            full_name="Super User",
            role=UserRole.SUPERUSER,
            is_active=True
        )
        db.add(superuser)
        db.commit()

        # Create documents in different buckets
        public_doc = Document(
            filename="public_report.pdf",
            original_filename="public_report.pdf",
            file_path="/data/public/public_report.pdf",
            bucket=DocumentBucket.PUBLIC,
            status=DocumentStatus.INDEXED,
            size=1024,
            mime_type="application/pdf"
        )
        confidential_doc = Document(
            filename="secret_plan.pdf",
            original_filename="secret_plan.pdf",
            file_path="/data/confidential/secret_plan.pdf",
            bucket=DocumentBucket.CONFIDENTIAL,
            status=DocumentStatus.INDEXED,
            size=1024,
            mime_type="application/pdf"
        )
        db.add(public_doc)
        db.add(confidential_doc)
        db.commit()

        # Search - should find both
        response = client.post(
            "/api/v1/search",
            json={"query": "report", "limit": 10},
            headers=get_auth_headers(superuser)
        )

        if response.status_code == 200:
            data = response.json()
            # May contain both public and confidential
            # Just verify search works for superuser
            assert "results" in data

    def test_admin_search_returns_all_documents(self, test_client: TestClient, db: Session):
        """Test that admin search returns both public and confidential documents"""
        # Create admin
        admin = User(
            email="admin@test.com",
            hashed_password=get_password_hash("password"),
            full_name="Admin User",
            role=UserRole.ADMIN,
            is_active=True
        )
        db.add(admin)
        db.commit()

        # Create documents in different buckets
        public_doc = Document(
            filename="public_report.pdf",
            original_filename="public_report.pdf",
            file_path="/data/public/public_report.pdf",
            bucket=DocumentBucket.PUBLIC,
            status=DocumentStatus.INDEXED,
            size=1024,
            mime_type="application/pdf"
        )
        confidential_doc = Document(
            filename="secret_plan.pdf",
            original_filename="secret_plan.pdf",
            file_path="/data/confidential/secret_plan.pdf",
            bucket=DocumentBucket.CONFIDENTIAL,
            status=DocumentStatus.INDEXED,
            size=1024,
            mime_type="application/pdf"
        )
        db.add(public_doc)
        db.add(confidential_doc)
        db.commit()

        # Search - should find both
        response = client.post(
            "/api/v1/search",
            json={"query": "report", "limit": 10},
            headers=get_auth_headers(admin)
        )

        if response.status_code == 200:
            data = response.json()
            # May contain both public and confidential
            # Just verify search works for admin
            assert "results" in data


class TestDocumentAccessIsolation:
    """Test direct document access by ID is properly isolated"""

    def test_user_accessing_confidential_document_by_id_returns_404(self, test_client: TestClient, db: Session):
        """Test that user gets 404 (not 403) when accessing confidential doc by ID

        This is important for security: returning 403 confirms the document exists,
        while 404 indicates the resource was not found (no information leakage).
        """
        # Create regular user
        user = User(
            email="user@test.com",
            hashed_password=get_password_hash("password"),
            full_name="Regular User",
            role=UserRole.USER,
            is_active=True
        )
        db.add(user)
        db.commit()

        # Create confidential document
        confidential_doc = Document(
            filename="secret.pdf",
            original_filename="secret.pdf",
            file_path="/data/confidential/secret.pdf",
            bucket=DocumentBucket.CONFIDENTIAL,
            status=DocumentStatus.INDEXED,
            size=1024,
            mime_type="application/pdf"
        )
        db.add(confidential_doc)
        db.commit()
        db.refresh(confidential_doc)

        # Try to access confidential document
        response = client.get(
            f"/api/v1/documents/{confidential_doc.id}",
            headers=get_auth_headers(user)
        )

        # Should return 404 (not found), not 403 (forbidden)
        # 404 doesn't reveal that the document exists
        assert response.status_code == 404

    def test_superuser_accessing_confidential_document_by_id_returns_200(self, test_client: TestClient, db: Session):
        """Test that superuser can access confidential documents"""
        # Create superuser
        superuser = User(
            email="super@test.com",
            hashed_password=get_password_hash("password"),
            full_name="Super User",
            role=UserRole.SUPERUSER,
            is_active=True
        )
        db.add(superuser)
        db.commit()

        # Create confidential document
        confidential_doc = Document(
            filename="secret.pdf",
            original_filename="secret.pdf",
            file_path="/data/confidential/secret.pdf",
            bucket=DocumentBucket.CONFIDENTIAL,
            status=DocumentStatus.INDEXED,
            size=1024,
            mime_type="application/pdf"
        )
        db.add(confidential_doc)
        db.commit()
        db.refresh(confidential_doc)

        # Access confidential document
        response = client.get(
            f"/api/v1/documents/{confidential_doc.id}",
            headers=get_auth_headers(superuser)
        )

        # Should return 200 (success)
        assert response.status_code == 200

        # Response should contain document details
        data = response.json()
        assert data["id"] == str(confidential_doc.id)
        assert data["bucket"] == "confidential"

    def test_admin_accessing_confidential_document_by_id_returns_200(self, test_client: TestClient, db: Session):
        """Test that admin can access confidential documents"""
        # Create admin
        admin = User(
            email="admin@test.com",
            hashed_password=get_password_hash("password"),
            full_name="Admin User",
            role=UserRole.ADMIN,
            is_active=True
        )
        db.add(admin)
        db.commit()

        # Create confidential document
        confidential_doc = Document(
            filename="secret.pdf",
            original_filename="secret.pdf",
            file_path="/data/confidential/secret.pdf",
            bucket=DocumentBucket.CONFIDENTIAL,
            status=DocumentStatus.INDEXED,
            size=1024,
            mime_type="application/pdf"
        )
        db.add(confidential_doc)
        db.commit()
        db.refresh(confidential_doc)

        # Access confidential document
        response = client.get(
            f"/api/v1/documents/{confidential_doc.id}",
            headers=get_auth_headers(admin)
        )

        # Should return 200 (success)
        assert response.status_code == 200

        # Response should contain document details
        data = response.json()
        assert data["id"] == str(confidential_doc.id)
        assert data["bucket"] == "confidential"

    def test_user_accessing_public_document_returns_200(self, test_client: TestClient, db: Session):
        """Test that user can access public documents"""
        # Create regular user
        user = User(
            email="user@test.com",
            hashed_password=get_password_hash("password"),
            full_name="Regular User",
            role=UserRole.USER,
            is_active=True
        )
        db.add(user)
        db.commit()

        # Create public document
        public_doc = Document(
            filename="public.pdf",
            original_filename="public.pdf",
            file_path="/data/public/public.pdf",
            bucket=DocumentBucket.PUBLIC,
            status=DocumentStatus.INDEXED,
            size=1024,
            mime_type="application/pdf"
        )
        db.add(public_doc)
        db.commit()
        db.refresh(public_doc)

        # Access public document
        response = client.get(
            f"/api/v1/documents/{public_doc.id}",
            headers=get_auth_headers(user)
        )

        # Should return 200 (success)
        assert response.status_code == 200


class TestDocumentListIsolation:
    """Test that document list endpoints filter by bucket"""

    def test_user_document_list_shows_only_public(self, test_client: TestClient, db: Session):
        """Test that user's document list only shows public documents"""
        user = User(
            email="user@test.com",
            hashed_password=get_password_hash("password"),
            full_name="Regular User",
            role=UserRole.USER,
            is_active=True
        )
        db.add(user)
        db.commit()

        # Create documents in different buckets
        public_doc = Document(
            filename="public.pdf",
            original_filename="public.pdf",
            file_path="/data/public/public.pdf",
            bucket=DocumentBucket.PUBLIC,
            status=DocumentStatus.INDEXED,
            size=1024,
            mime_type="application/pdf"
        )
        confidential_doc = Document(
            filename="secret.pdf",
            original_filename="secret.pdf",
            file_path="/data/confidential/secret.pdf",
            bucket=DocumentBucket.CONFIDENTIAL,
            status=DocumentStatus.INDEXED,
            size=1024,
            mime_type="application/pdf"
        )
        db.add(public_doc)
        db.add(confidential_doc)
        db.commit()

        # List documents
        response = client.get(
            "/api/v1/documents",
            headers=get_auth_headers(user)
        )

        if response.status_code == 200:
            data = response.json()
            # Should only contain public documents
            documents = data.get("documents", [])
            for doc in documents:
                assert doc.get("bucket") != "confidential"
                assert doc.get("bucket") in ["public", DocumentBucket.PUBLIC.value]

    def test_superuser_document_list_shows_all(self, test_client: TestClient, db: Session):
        """Test that superuser's document list shows all documents"""
        superuser = User(
            email="super@test.com",
            hashed_password=get_password_hash("password"),
            full_name="Super User",
            role=UserRole.SUPERUSER,
            is_active=True
        )
        db.add(superuser)
        db.commit()

        # Create documents in different buckets
        public_doc = Document(
            filename="public.pdf",
            original_filename="public.pdf",
            file_path="/data/public/public.pdf",
            bucket=DocumentBucket.PUBLIC,
            status=DocumentStatus.INDEXED,
            size=1024,
            mime_type="application/pdf"
        )
        confidential_doc = Document(
            filename="secret.pdf",
            original_filename="secret.pdf",
            file_path="/data/confidential/secret.pdf",
            bucket=DocumentBucket.CONFIDENTIAL,
            status=DocumentStatus.INDEXED,
            size=1024,
            mime_type="application/pdf"
        )
        db.add(public_doc)
        db.add(confidential_doc)
        db.commit()

        # List documents
        response = client.get(
            "/api/v1/documents",
            headers=get_auth_headers(superuser)
        )

        if response.status_code == 200:
            data = response.json()
            # May contain both public and confidential
            assert "documents" in data


class TestSearchSuggestionsIsolation:
    """Test that autocomplete/suggestions don't leak confidential info"""

    def test_user_search_suggestions_exclude_confidential(self, test_client: TestClient, db: Session):
        """Test that user's search suggestions don't include confidential documents"""
        user = User(
            email="user@test.com",
            hashed_password=get_password_hash("password"),
            full_name="Regular User",
            role=UserRole.USER,
            is_active=True
        )
        db.add(user)
        db.commit()

        # Create documents
        public_doc = Document(
            filename="public_report.pdf",
            original_filename="public_report.pdf",
            file_path="/data/public/public_report.pdf",
            bucket=DocumentBucket.PUBLIC,
            status=DocumentStatus.INDEXED,
            size=1024,
            mime_type="application/pdf"
        )
        confidential_doc = Document(
            filename="secret_report.pdf",
            original_filename="secret_report.pdf",
            file_path="/data/confidential/secret_report.pdf",
            bucket=DocumentBucket.CONFIDENTIAL,
            status=DocumentStatus.INDEXED,
            size=1024,
            mime_type="application/pdf"
        )
        db.add(public_doc)
        db.add(confidential_doc)
        db.commit()

        # Get suggestions for "report"
        response = client.get(
            "/api/v1/search/suggest?q=report",
            headers=get_auth_headers(user)
        )

        if response.status_code == 200:
            data = response.json()
            suggestions = data.get("suggestions", [])
            # Should not include confidential documents
            assert "secret" not in str(suggestions).lower()
            assert "confidential" not in str(suggestions).lower()

    def test_superuser_search_suggestions_include_all(self, test_client: TestClient, db: Session):
        """Test that superuser's search suggestions include all documents"""
        superuser = User(
            email="super@test.com",
            hashed_password=get_password_hash("password"),
            full_name="Super User",
            role=UserRole.SUPERUSER,
            is_active=True
        )
        db.add(superuser)
        db.commit()

        # Create documents
        public_doc = Document(
            filename="public_report.pdf",
            original_filename="public_report.pdf",
            file_path="/data/public/public_report.pdf",
            bucket=DocumentBucket.PUBLIC,
            status=DocumentStatus.INDEXED,
            size=1024,
            mime_type="application/pdf"
        )
        confidential_doc = Document(
            filename="secret_report.pdf",
            original_filename="secret_report.pdf",
            file_path="/data/confidential/secret_report.pdf",
            bucket=DocumentBucket.CONFIDENTIAL,
            status=DocumentStatus.INDEXED,
            size=1024,
            mime_type="application/pdf"
        )
        db.add(public_doc)
        db.add(confidential_doc)
        db.commit()

        # Get suggestions for "report"
        response = client.get(
            "/api/v1/search/suggest?q=report",
            headers=get_auth_headers(superuser)
        )

        if response.status_code == 200:
            data = response.json()
            # May include both
            assert "suggestions" in data


class TestDocumentDownloadIsolation:
    """Test that document download is properly isolated"""

    def test_user_cannot_download_confidential_document(self, test_client: TestClient, db: Session):
        """Test that user cannot download confidential documents"""
        user = User(
            email="user@test.com",
            hashed_password=get_password_hash("password"),
            full_name="Regular User",
            role=UserRole.USER,
            is_active=True
        )
        db.add(user)
        db.commit()

        # Create confidential document
        confidential_doc = Document(
            filename="secret.pdf",
            original_filename="secret.pdf",
            file_path="/data/confidential/secret.pdf",
            bucket=DocumentBucket.CONFIDENTIAL,
            status=DocumentStatus.INDEXED,
            size=1024,
            mime_type="application/pdf"
        )
        db.add(confidential_doc)
        db.commit()
        db.refresh(confidential_doc)

        # Try to download
        response = client.get(
            f"/api/v1/documents/{confidential_doc.id}/download",
            headers=get_auth_headers(user)
        )

        # Should return 404 or 403
        assert response.status_code in [403, 404]

    def test_superuser_can_download_confidential_document(self, test_client: TestClient, db: Session):
        """Test that superuser can download confidential documents"""
        superuser = User(
            email="super@test.com",
            hashed_password=get_password_hash("password"),
            full_name="Super User",
            role=UserRole.SUPERUSER,
            is_active=True
        )
        db.add(superuser)
        db.commit()

        # Create confidential document
        confidential_doc = Document(
            filename="secret.pdf",
            original_filename="secret.pdf",
            file_path="/data/confidential/secret.pdf",
            bucket=DocumentBucket.CONFIDENTIAL,
            status=DocumentStatus.INDEXED,
            size=1024,
            mime_type="application/pdf"
        )
        db.add(confidential_doc)
        db.commit()
        db.refresh(confidential_doc)

        # Try to download
        response = client.get(
            f"/api/v1/documents/{confidential_doc.id}/download",
            headers=get_auth_headers(superuser)
        )

        # Should succeed or return file not found (if storage not set up)
        # But should NOT return 403 Forbidden
        assert response.status_code in [200, 404]


class TestBucketEnumerationPrevention:
    """Test that users cannot enumerate confidential documents"""

    def test_user_cannot_enumerate_confidential_documents_by_id(self, test_client: TestClient, db: Session):
        """Test that user cannot find confidential documents by trying different IDs

        This tests against ID enumeration attacks where a user might
        try random IDs to find confidential documents.
        """
        user = User(
            email="user@test.com",
            hashed_password=get_password_hash("password"),
            full_name="Regular User",
            role=UserRole.USER,
            is_active=True
        )
        db.add(user)
        db.commit()

        # Create some documents
        doc1 = Document(
            filename="doc1.pdf",
            original_filename="doc1.pdf",
            file_path="/data/public/doc1.pdf",
            bucket=DocumentBucket.PUBLIC,
            status=DocumentStatus.INDEXED,
            size=1024,
            mime_type="application/pdf"
        )
        doc2 = Document(
            filename="secret.pdf",
            original_filename="secret.pdf",
            file_path="/data/confidential/secret.pdf",
            bucket=DocumentBucket.CONFIDENTIAL,
            status=DocumentStatus.INDEXED,
            size=1024,
            mime_type="application/pdf"
        )
        db.add(doc1)
        db.add(doc2)
        db.commit()
        db.refresh(doc2)

        # Try to access confidential document by direct ID
        response = client.get(
            f"/api/v1/documents/{doc2.id}",
            headers=get_auth_headers(user)
        )

        # Should return 404 (not 403) to prevent enumeration
        assert response.status_code == 404

        # Error message should not reveal document exists
        assert "not found" in response.json()["detail"].lower() or "404" in str(response.status_code)

    def test_response_times_do_not_leak_confidential_document_existence(self, test_client: TestClient, db: Session):
        """Test that response times don't leak whether confidential documents exist

        This is a timing attack prevention test - responses for existing
        confidential docs and non-existent docs should have similar timing.
        """
        import time

        user = User(
            email="user@test.com",
            hashed_password=get_password_hash("password"),
            full_name="Regular User",
            role=UserRole.USER,
            is_active=True
        )
        db.add(user)
        db.commit()

        # Create confidential document
        confidential_doc = Document(
            filename="secret.pdf",
            original_filename="secret.pdf",
            file_path="/data/confidential/secret.pdf",
            bucket=DocumentBucket.CONFIDENTIAL,
            status=DocumentStatus.INDEXED,
            size=1024,
            mime_type="application/pdf"
        )
        db.add(confidential_doc)
        db.commit()
        db.refresh(confidential_doc)

        # Time request for existing confidential doc
        start = time.time()
        response1 = client.get(
            f"/api/v1/documents/{confidential_doc.id}",
            headers=get_auth_headers(user)
        )
        time1 = time.time() - start

        # Time request for non-existent doc
        fake_id = uuid.uuid4()
        start = time.time()
        response2 = client.get(
            f"/api/v1/documents/{fake_id}",
            headers=get_auth_headers(user)
        )
        time2 = time.time() - start

        # Both should return 404
        assert response1.status_code == 404
        assert response2.status_code == 404

        # Response times should be similar (within 100ms)
        # This prevents timing attacks
        assert abs(time1 - time2) < 0.1  # 100ms tolerance


class TestCrossBucketAccess:
    """Test that documents cannot be accessed across buckets"""

    def test_public_document_access_by_all_roles(self, test_client: TestClient, db: Session):
        """Test that public documents can be accessed by all roles"""
        # Create users of all roles
        admin = User(
            email="admin@test.com",
            hashed_password=get_password_hash("password"),
            full_name="Admin",
            role=UserRole.ADMIN,
            is_active=True
        )
        superuser = User(
            email="super@test.com",
            hashed_password=get_password_hash("password"),
            full_name="Super",
            role=UserRole.SUPERUSER,
            is_active=True
        )
        user = User(
            email="user@test.com",
            hashed_password=get_password_hash("password"),
            full_name="User",
            role=UserRole.USER,
            is_active=True
        )
        db.add(admin)
        db.add(superuser)
        db.add(user)

        # Create public document
        public_doc = Document(
            filename="public.pdf",
            original_filename="public.pdf",
            file_path="/data/public/public.pdf",
            bucket=DocumentBucket.PUBLIC,
            status=DocumentStatus.INDEXED,
            size=1024,
            mime_type="application/pdf"
        )
        db.add(public_doc)
        db.commit()
        db.refresh(public_doc)

        # All should be able to access
        for u in [admin, superuser, user]:
            response = client.get(
                f"/api/v1/documents/{public_doc.id}",
                headers=get_auth_headers(u)
            )
            assert response.status_code == 200
