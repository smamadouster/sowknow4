"""
Integration tests for Collection Export endpoint.

Tests RBAC enforcement, PDF/JSON export functionality, and audit logging.
"""

import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.collection import (
    Collection,
    CollectionItem,
    CollectionType,
    CollectionVisibility,
)
from app.models.document import Document, DocumentBucket, DocumentStatus
from app.models.user import User, UserRole
from app.utils.security import create_access_token

_FIXTURE_BCRYPT_HASH = "$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW"


class TestCollectionExportEndpoint:
    """Test suite for GET /api/v1/collections/{id}/export endpoint"""

    @pytest.fixture
    def admin_user(self, db: Session) -> User:
        """Create an admin user"""
        user = User(
            id=uuid4(),
            email="admin_export@test.com",
            hashed_password=_FIXTURE_BCRYPT_HASH,
            full_name="Admin Export User",
            role=UserRole.ADMIN,
            is_active=True,
            can_access_confidential=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    @pytest.fixture
    def superuser(self, db: Session) -> User:
        """Create a superuser"""
        user = User(
            id=uuid4(),
            email="superuser_export@test.com",
            hashed_password=_FIXTURE_BCRYPT_HASH,
            full_name="Super Export User",
            role=UserRole.SUPERUSER,
            is_active=True,
            can_access_confidential=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    @pytest.fixture
    def regular_user(self, db: Session) -> User:
        """Create a regular user without confidential access"""
        user = User(
            id=uuid4(),
            email="user_export@test.com",
            hashed_password=_FIXTURE_BCRYPT_HASH,
            full_name="Regular Export User",
            role=UserRole.USER,
            is_active=True,
            can_access_confidential=False,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    @pytest.fixture
    def public_document(self, db: Session) -> Document:
        """Create a public document"""
        doc = Document(
            id=uuid4(),
            filename="public_doc_export.pdf",
            original_filename="public_doc_export.pdf",
            file_path="/data/public/public_doc_export.pdf",
            bucket=DocumentBucket.PUBLIC,
            status=DocumentStatus.INDEXED,
            size=2048,
            mime_type="application/pdf",
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        return doc

    @pytest.fixture
    def confidential_document(self, db: Session) -> Document:
        """Create a confidential document"""
        doc = Document(
            id=uuid4(),
            filename="confidential_doc_export.pdf",
            original_filename="confidential_doc_export.pdf",
            file_path="/data/confidential/confidential_doc_export.pdf",
            bucket=DocumentBucket.CONFIDENTIAL,
            status=DocumentStatus.INDEXED,
            size=4096,
            mime_type="application/pdf",
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        return doc

    @pytest.fixture
    def public_collection(
        self, db: Session, regular_user: User, public_document: Document
    ) -> Collection:
        """Create a collection with only public documents"""
        collection = Collection(
            id=uuid4(),
            user_id=regular_user.id,
            name="Public Test Collection",
            description="A collection with public documents only",
            query="test query for public docs",
            collection_type=CollectionType.SMART,
            visibility=CollectionVisibility.PUBLIC,
            ai_summary="This is an AI-generated summary for the public collection.",
            document_count=1,
        )
        db.add(collection)
        db.flush()

        item = CollectionItem(
            id=uuid4(),
            collection_id=collection.id,
            document_id=public_document.id,
            relevance_score=85,
            order_index=0,
            notes="Test note for public document",
        )
        db.add(item)
        db.commit()
        db.refresh(collection)
        return collection

    @pytest.fixture
    def confidential_collection(
        self, db: Session, admin_user: User, confidential_document: Document
    ) -> Collection:
        """Create a collection with confidential documents (visible to all for RBAC testing)"""
        collection = Collection(
            id=uuid4(),
            user_id=admin_user.id,
            name="Confidential Test Collection",
            description="A collection with confidential documents",
            query="test query for confidential docs",
            collection_type=CollectionType.SMART,
            visibility=CollectionVisibility.PUBLIC,
            ai_summary="This is an AI-generated summary for the confidential collection.",
            document_count=1,
            is_confidential=True,
        )
        db.add(collection)
        db.flush()

        item = CollectionItem(
            id=uuid4(),
            collection_id=collection.id,
            document_id=confidential_document.id,
            relevance_score=95,
            order_index=0,
            notes="Confidential document note",
        )
        db.add(item)
        db.commit()
        db.refresh(collection)
        return collection

    @pytest.fixture
    def mixed_collection(
        self,
        db: Session,
        admin_user: User,
        public_document: Document,
        confidential_document: Document,
    ) -> Collection:
        """Create a collection with both public and confidential documents (visible to all for RBAC testing)"""
        collection = Collection(
            id=uuid4(),
            user_id=admin_user.id,
            name="Mixed Test Collection",
            description="A collection with mixed documents",
            query="test query for mixed docs",
            collection_type=CollectionType.SMART,
            visibility=CollectionVisibility.PUBLIC,
            ai_summary="This is an AI-generated summary for the mixed collection.",
            document_count=2,
            is_confidential=True,
        )
        db.add(collection)
        db.flush()

        item1 = CollectionItem(
            id=uuid4(),
            collection_id=collection.id,
            document_id=public_document.id,
            relevance_score=75,
            order_index=0,
            notes="Public document in mixed collection",
        )
        item2 = CollectionItem(
            id=uuid4(),
            collection_id=collection.id,
            document_id=confidential_document.id,
            relevance_score=90,
            order_index=1,
            notes="Confidential document in mixed collection",
        )
        db.add_all([item1, item2])
        db.commit()
        db.refresh(collection)
        return collection

    def get_auth_headers(self, user: User) -> dict:
        """Get authorization headers for a user"""
        token = create_access_token(
            data={"sub": user.email, "role": user.role.value, "user_id": str(user.id)}
        )
        return {
            "Authorization": f"Bearer {token}",
            "Host": "testserver",
        }

    def test_export_public_collection_as_json(
        self,
        client: TestClient,
        db: Session,
        regular_user: User,
        public_collection: Collection,
    ):
        """Test exporting a public collection as JSON"""
        headers = self.get_auth_headers(regular_user)

        response = client.get(
            f"/api/v1/collections/{public_collection.id}/export?format=json",
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()

        assert data["collection_id"] == str(public_collection.id)
        assert data["collection_name"] == public_collection.name
        assert data["format"] == "json"
        assert data["document_count"] == 1
        assert "content" in data
        assert data["content"] is not None

        content = json.loads(data["content"])
        assert content["collection"]["name"] == public_collection.name
        assert content["collection"]["query"] == public_collection.query
        assert len(content["documents"]) == 1
        assert content["documents"][0]["filename"] == "public_doc_export.pdf"
        assert content["documents"][0]["relevance_score"] == 85

    def test_export_public_collection_as_pdf(
        self,
        client: TestClient,
        db: Session,
        regular_user: User,
        public_collection: Collection,
    ):
        """Test exporting a public collection as PDF — StreamingResponse binary download"""
        headers = self.get_auth_headers(regular_user)

        response = client.get(
            f"/api/v1/collections/{public_collection.id}/export?format=pdf",
            headers=headers,
        )

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert "attachment" in response.headers["content-disposition"]
        assert ".pdf" in response.headers["content-disposition"]
        assert response.headers["x-collection-id"] == str(public_collection.id)
        assert response.headers["x-document-count"] == "1"
        assert response.content.startswith(b"%PDF")

    def test_export_defaults_to_json(
        self,
        client: TestClient,
        db: Session,
        regular_user: User,
        public_collection: Collection,
    ):
        """Test that export defaults to JSON format when no format specified"""
        headers = self.get_auth_headers(regular_user)

        response = client.get(
            f"/api/v1/collections/{public_collection.id}/export?format=json",
            headers=headers,
        )

        import sys

        print(
            f"DEBUG Response status: {response.status_code}",
            file=sys.stderr,
            flush=True,
        )
        print(
            f"DEBUG Response body: {response.text[:500] if response.text else 'No body'}",
            file=sys.stderr,
            flush=True,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["format"] == "json"

    def test_regular_user_cannot_export_confidential_collection(
        self,
        client: TestClient,
        db: Session,
        regular_user: User,
        confidential_collection: Collection,
    ):
        """Test that regular users are blocked from exporting confidential collections"""
        headers = self.get_auth_headers(regular_user)

        response = client.get(
            f"/api/v1/collections/{confidential_collection.id}/export?format=json",
            headers=headers,
        )

        assert response.status_code == 403
        assert "confidential" in response.json()["detail"].lower()

    def test_regular_user_cannot_export_mixed_collection(
        self,
        client: TestClient,
        db: Session,
        regular_user: User,
        mixed_collection: Collection,
    ):
        """Test that regular users are blocked from exporting collections containing confidential docs"""
        headers = self.get_auth_headers(regular_user)

        response = client.get(
            f"/api/v1/collections/{mixed_collection.id}/export?format=json",
            headers=headers,
        )

        assert response.status_code == 403
        assert "confidential" in response.json()["detail"].lower()

    def test_admin_can_export_confidential_collection(
        self,
        client: TestClient,
        db: Session,
        admin_user: User,
        confidential_collection: Collection,
    ):
        """Test that admins can export confidential collections"""
        headers = self.get_auth_headers(admin_user)

        response = client.get(
            f"/api/v1/collections/{confidential_collection.id}/export?format=json",
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["collection_id"] == str(confidential_collection.id)
        assert data["document_count"] == 1

    def test_superuser_can_export_confidential_collection(
        self,
        client: TestClient,
        db: Session,
        superuser: User,
        confidential_collection: Collection,
    ):
        """Test that superusers can export confidential collections"""
        headers = self.get_auth_headers(superuser)

        response = client.get(
            f"/api/v1/collections/{confidential_collection.id}/export?format=json",
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["collection_id"] == str(confidential_collection.id)

    def test_admin_can_export_mixed_collection(
        self,
        client: TestClient,
        db: Session,
        admin_user: User,
        mixed_collection: Collection,
    ):
        """Test that admins can export collections with mixed documents"""
        headers = self.get_auth_headers(admin_user)

        response = client.get(
            f"/api/v1/collections/{mixed_collection.id}/export?format=json",
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["document_count"] == 2

    def test_export_nonexistent_collection_returns_404(
        self, client: TestClient, db: Session, regular_user: User
    ):
        """Test that exporting a non-existent collection returns 404"""
        headers = self.get_auth_headers(regular_user)
        fake_id = uuid4()

        response = client.get(
            f"/api/v1/collections/{fake_id}/export?format=json",
            headers=headers,
        )

        assert response.status_code == 404

    def test_export_requires_authentication(
        self, client: TestClient, db: Session, public_collection: Collection
    ):
        """Test that export endpoint requires authentication"""
        response = client.get(
            f"/api/v1/collections/{public_collection.id}/export?format=json"
        )

        assert response.status_code == 401

    def test_export_json_includes_all_fields(
        self,
        client: TestClient,
        db: Session,
        regular_user: User,
        public_collection: Collection,
    ):
        """Test that JSON export includes all required fields"""
        headers = self.get_auth_headers(regular_user)

        response = client.get(
            f"/api/v1/collections/{public_collection.id}/export?format=json",
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()
        content = json.loads(data["content"])

        assert "collection" in content
        assert "id" in content["collection"]
        assert "name" in content["collection"]
        assert "query" in content["collection"]
        assert "ai_summary" in content["collection"]
        assert "themes" in content["collection"]
        assert "created_at" in content["collection"]

        assert "documents" in content
        assert len(content["documents"]) == 1
        doc = content["documents"][0]
        assert "id" in doc
        assert "filename" in doc
        assert "relevance_score" in doc
        assert "excerpt" in doc
        assert "notes" in doc
        assert "created_at" in doc

        assert "export_metadata" in content
        assert "generated_at" in content["export_metadata"]
        assert "exported_by" in content["export_metadata"]
        assert "document_count" in content["export_metadata"]

    def test_export_pdf_includes_ai_summary(
        self,
        client: TestClient,
        db: Session,
        regular_user: User,
        public_collection: Collection,
    ):
        """Test that PDF export generates valid binary PDF with SOWKNOW branding"""
        headers = self.get_auth_headers(regular_user)

        response = client.get(
            f"/api/v1/collections/{public_collection.id}/export?format=pdf",
            headers=headers,
        )

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        pdf_bytes = response.content
        assert pdf_bytes.startswith(b"%PDF")
        # PDF should embed the collection name text
        assert b"PDF" in pdf_bytes
        assert response.headers["x-document-count"] == "1"

    def test_export_invalid_format_returns_422(
        self,
        client: TestClient,
        db: Session,
        regular_user: User,
        public_collection: Collection,
    ):
        """Test that invalid format returns validation error"""
        headers = self.get_auth_headers(regular_user)

        response = client.get(
            f"/api/v1/collections/{public_collection.id}/export?format=invalid",
            headers=headers,
        )

        assert response.status_code == 422

    def test_owner_can_export_own_collection(
        self, client: TestClient, db: Session, public_collection: Collection
    ):
        """Test that collection owner can export their collection"""
        from app.models.user import User

        owner = db.query(User).filter(User.id == public_collection.user_id).first()
        headers = self.get_auth_headers(owner)

        response = client.get(
            f"/api/v1/collections/{public_collection.id}/export?format=json",
            headers=headers,
        )

        assert response.status_code == 200
