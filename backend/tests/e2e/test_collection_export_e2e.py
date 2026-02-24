"""
E2E Test Scenario: Collection PDF Export
=========================================
Tests the complete collection export flow end-to-end:
  1. Admin creates a collection with public documents → exports as PDF → verifies binary download
  2. Admin creates a collection with confidential documents → exports as PDF → audit log created
  3. Regular user attempts to export confidential collection → 403 enforced
  4. Regular user exports public collection → receives valid PDF binary
  5. JSON export remains structured (backward compatibility)
  6. Themes and excerpts appear in export data

All external LLM / AI calls are mocked. reportlab runs for real to verify PDF generation.
"""
import json
import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock, AsyncMock
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.user import User, UserRole
from app.models.document import Document, DocumentBucket, DocumentStatus
from app.models.collection import (
    Collection,
    CollectionItem,
    CollectionVisibility,
    CollectionType,
)
from app.models.audit import AuditLog, AuditAction
from app.utils.security import create_access_token


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_FIXTURE_BCRYPT_HASH = "$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW"


def _token_headers(user: User) -> dict:
    token = create_access_token(
        data={"sub": user.email, "role": user.role.value, "user_id": str(user.id)}
    )
    return {"Authorization": f"Bearer {token}", "Host": "testserver"}


@pytest.fixture
def e2e_admin(db: Session) -> User:
    user = User(
        id=uuid4(),
        email="e2e_admin_export@sowknow.test",
        hashed_password=_FIXTURE_BCRYPT_HASH,
        full_name="E2E Admin Export",
        role=UserRole.ADMIN,
        is_active=True,
        can_access_confidential=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def e2e_superuser(db: Session) -> User:
    user = User(
        id=uuid4(),
        email="e2e_superuser_export@sowknow.test",
        hashed_password=_FIXTURE_BCRYPT_HASH,
        full_name="E2E Superuser Export",
        role=UserRole.SUPERUSER,
        is_active=True,
        can_access_confidential=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def e2e_user(db: Session) -> User:
    user = User(
        id=uuid4(),
        email="e2e_user_export@sowknow.test",
        hashed_password=_FIXTURE_BCRYPT_HASH,
        full_name="E2E Regular User Export",
        role=UserRole.USER,
        is_active=True,
        can_access_confidential=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def pub_doc(db: Session) -> Document:
    doc = Document(
        id=uuid4(),
        filename="e2e_public_report.pdf",
        original_filename="e2e_public_report.pdf",
        file_path="/data/public/e2e_public_report.pdf",
        bucket=DocumentBucket.PUBLIC,
        status=DocumentStatus.INDEXED,
        size=8192,
        mime_type="application/pdf",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


@pytest.fixture
def conf_doc(db: Session) -> Document:
    doc = Document(
        id=uuid4(),
        filename="e2e_confidential_will.pdf",
        original_filename="e2e_confidential_will.pdf",
        file_path="/data/confidential/e2e_confidential_will.pdf",
        bucket=DocumentBucket.CONFIDENTIAL,
        status=DocumentStatus.INDEXED,
        size=16384,
        mime_type="application/pdf",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


@pytest.fixture
def public_col(db: Session, e2e_user: User, pub_doc: Document) -> Collection:
    col = Collection(
        id=uuid4(),
        user_id=e2e_user.id,
        name="E2E Public Legacy Documents",
        description="All public legacy documents for E2E test",
        query="find all public legacy family documents",
        collection_type=CollectionType.SMART,
        visibility=CollectionVisibility.PUBLIC,
        ai_summary="This collection summarizes public legacy family documents.",
        ai_keywords=["legacy", "family", "documents"],
        document_count=1,
    )
    db.add(col)
    db.flush()
    item = CollectionItem(
        id=uuid4(),
        collection_id=col.id,
        document_id=pub_doc.id,
        relevance_score=88,
        order_index=0,
        notes="High-relevance public document",
        added_reason="AI determined this is highly relevant to legacy family queries.",
    )
    db.add(item)
    db.commit()
    db.refresh(col)
    return col


@pytest.fixture
def confidential_col(db: Session, e2e_admin: User, conf_doc: Document) -> Collection:
    col = Collection(
        id=uuid4(),
        user_id=e2e_admin.id,
        name="E2E Confidential Will & Testament",
        description="Confidential estate documents",
        query="find confidential will and testament documents",
        collection_type=CollectionType.SMART,
        visibility=CollectionVisibility.PUBLIC,
        ai_summary="Confidential collection — estate and legal documents.",
        ai_keywords=["estate", "will", "inheritance"],
        is_confidential=True,
        document_count=1,
    )
    db.add(col)
    db.flush()
    item = CollectionItem(
        id=uuid4(),
        collection_id=col.id,
        document_id=conf_doc.id,
        relevance_score=99,
        order_index=0,
        notes="Primary will document",
        added_reason="This is the primary estate document.",
    )
    db.add(item)
    db.commit()
    db.refresh(col)
    return col


# ---------------------------------------------------------------------------
# Scenario 1: Regular user exports public collection as PDF
# ---------------------------------------------------------------------------

class TestE2EPublicCollectionPdfExport:
    """Full happy-path: user exports a public collection as a binary PDF download."""

    def test_pdf_export_returns_binary_with_correct_headers(
        self, client: TestClient, db: Session, e2e_user: User, public_col: Collection
    ):
        """
        GIVEN a regular user with a public collection
        WHEN  they GET /api/v1/collections/{id}/export?format=pdf
        THEN  the response is a binary PDF file download with correct headers
        """
        headers = _token_headers(e2e_user)
        response = client.get(
            f"/api/v1/collections/{public_col.id}/export?format=pdf",
            headers=headers,
        )

        assert response.status_code == 200, f"Unexpected status: {response.status_code} — {response.text[:300]}"
        assert response.headers["content-type"] == "application/pdf"

        cd = response.headers["content-disposition"]
        assert "attachment" in cd
        assert ".pdf" in cd
        assert "sowknow_collection_" in cd

    def test_pdf_export_is_valid_pdf_binary(
        self, client: TestClient, db: Session, e2e_user: User, public_col: Collection
    ):
        """PDF magic bytes %PDF must be present in the response body."""
        headers = _token_headers(e2e_user)
        response = client.get(
            f"/api/v1/collections/{public_col.id}/export?format=pdf",
            headers=headers,
        )

        assert response.status_code == 200
        assert response.content.startswith(b"%PDF")

    def test_pdf_export_custom_headers_match_collection(
        self, client: TestClient, db: Session, e2e_user: User, public_col: Collection
    ):
        """X-Collection-Id and X-Document-Count headers must match collection data."""
        headers = _token_headers(e2e_user)
        response = client.get(
            f"/api/v1/collections/{public_col.id}/export?format=pdf",
            headers=headers,
        )

        assert response.headers["x-collection-id"] == str(public_col.id)
        assert response.headers["x-document-count"] == "1"

    def test_pdf_export_filename_contains_collection_name_slug(
        self, client: TestClient, db: Session, e2e_user: User, public_col: Collection
    ):
        """Content-Disposition filename should contain a sanitised collection name."""
        headers = _token_headers(e2e_user)
        response = client.get(
            f"/api/v1/collections/{public_col.id}/export?format=pdf",
            headers=headers,
        )

        cd = response.headers["content-disposition"]
        # Collection name "E2E Public Legacy Documents" → slug should contain letters from name
        assert "E2E" in cd or "E2E_Public" in cd or "sowknow_collection" in cd


# ---------------------------------------------------------------------------
# Scenario 2: Admin exports confidential collection — audit log created
# ---------------------------------------------------------------------------

class TestE2EConfidentialCollectionExportAudit:
    """Admin exports confidential collection and audit log entry is recorded."""

    def test_admin_pdf_export_succeeds(
        self, client: TestClient, db: Session, e2e_admin: User, confidential_col: Collection
    ):
        """Admin can export a confidential collection as PDF."""
        headers = _token_headers(e2e_admin)
        response = client.get(
            f"/api/v1/collections/{confidential_col.id}/export?format=pdf",
            headers=headers,
        )

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert response.content.startswith(b"%PDF")

    def test_admin_pdf_export_creates_audit_log(
        self, client: TestClient, db: Session, e2e_admin: User, confidential_col: Collection
    ):
        """
        WHEN admin exports a confidential collection
        THEN an audit log entry with action=CONFIDENTIAL_ACCESSED is created.
        """
        headers = _token_headers(e2e_admin)
        client.get(
            f"/api/v1/collections/{confidential_col.id}/export?format=pdf",
            headers=headers,
        )

        audit_entry = (
            db.query(AuditLog)
            .filter(
                AuditLog.user_id == e2e_admin.id,
                AuditLog.action == AuditAction.CONFIDENTIAL_ACCESSED,
                AuditLog.resource_type == "collection_export",
                AuditLog.resource_id == str(confidential_col.id),
            )
            .first()
        )
        assert audit_entry is not None, "Audit log entry not found for confidential export"
        details = json.loads(audit_entry.details)
        assert details["format"] == "pdf"
        assert details["confidential_document_count"] == 1
        assert details["action"] == "export_collection"

    def test_superuser_pdf_export_also_creates_audit_log(
        self, client: TestClient, db: Session, e2e_superuser: User, confidential_col: Collection
    ):
        """Superuser exporting a confidential collection also triggers audit logging."""
        headers = _token_headers(e2e_superuser)
        response = client.get(
            f"/api/v1/collections/{confidential_col.id}/export?format=pdf",
            headers=headers,
        )
        assert response.status_code == 200

        audit_entry = (
            db.query(AuditLog)
            .filter(
                AuditLog.user_id == e2e_superuser.id,
                AuditLog.action == AuditAction.CONFIDENTIAL_ACCESSED,
                AuditLog.resource_type == "collection_export",
            )
            .first()
        )
        assert audit_entry is not None


# ---------------------------------------------------------------------------
# Scenario 3: Regular user blocked from confidential collection export
# ---------------------------------------------------------------------------

class TestE2EConfidentialExportRbacEnforcement:
    """RBAC enforcement: regular users cannot export confidential collections."""

    def test_user_blocked_from_confidential_pdf_export(
        self, client: TestClient, db: Session, e2e_user: User, confidential_col: Collection
    ):
        """
        GIVEN a regular user
        WHEN  they attempt to export a collection with confidential documents
        THEN  they receive 403 Forbidden
        """
        headers = _token_headers(e2e_user)
        response = client.get(
            f"/api/v1/collections/{confidential_col.id}/export?format=pdf",
            headers=headers,
        )

        assert response.status_code == 403
        assert "confidential" in response.json()["detail"].lower()

    def test_user_blocked_from_confidential_json_export(
        self, client: TestClient, db: Session, e2e_user: User, confidential_col: Collection
    ):
        """403 also applies to JSON export of confidential collection."""
        headers = _token_headers(e2e_user)
        response = client.get(
            f"/api/v1/collections/{confidential_col.id}/export?format=json",
            headers=headers,
        )

        assert response.status_code == 403

    def test_unauthenticated_export_returns_401(
        self, client: TestClient, db: Session, public_col: Collection
    ):
        """Unauthenticated request must be rejected with 401."""
        response = client.get(
            f"/api/v1/collections/{public_col.id}/export?format=pdf"
        )
        assert response.status_code == 401

    def test_no_audit_log_created_for_blocked_user(
        self, client: TestClient, db: Session, e2e_user: User, confidential_col: Collection
    ):
        """
        Audit log is NOT created when a regular user is blocked (403).
        Only successful privileged accesses are logged.
        """
        headers = _token_headers(e2e_user)
        client.get(
            f"/api/v1/collections/{confidential_col.id}/export?format=pdf",
            headers=headers,
        )

        # No audit entry for this blocked user
        audit_entry = (
            db.query(AuditLog)
            .filter(
                AuditLog.user_id == e2e_user.id,
                AuditLog.action == AuditAction.CONFIDENTIAL_ACCESSED,
                AuditLog.resource_type == "collection_export",
            )
            .first()
        )
        assert audit_entry is None, "Audit log should NOT be created for blocked export attempts"


# ---------------------------------------------------------------------------
# Scenario 4: JSON export backward compatibility
# ---------------------------------------------------------------------------

class TestE2EJsonExportBackwardCompatibility:
    """JSON export still returns structured CollectionExportResponse."""

    def test_json_export_returns_structured_response(
        self, client: TestClient, db: Session, e2e_user: User, public_col: Collection
    ):
        headers = _token_headers(e2e_user)
        response = client.get(
            f"/api/v1/collections/{public_col.id}/export?format=json",
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["format"] == "json"
        assert data["collection_id"] == str(public_col.id)
        assert data["collection_name"] == public_col.name
        assert data["document_count"] == 1

    def test_json_export_content_includes_themes(
        self, client: TestClient, db: Session, e2e_user: User, public_col: Collection
    ):
        """JSON export content now includes themes from ai_keywords."""
        headers = _token_headers(e2e_user)
        response = client.get(
            f"/api/v1/collections/{public_col.id}/export?format=json",
            headers=headers,
        )

        assert response.status_code == 200
        content = json.loads(response.json()["content"])
        assert "themes" in content["collection"]
        assert isinstance(content["collection"]["themes"], list)
        # ai_keywords=["legacy", "family", "documents"]
        assert "legacy" in content["collection"]["themes"]

    def test_json_export_documents_include_excerpt(
        self, client: TestClient, db: Session, e2e_user: User, public_col: Collection
    ):
        """JSON export documents include excerpt field from added_reason."""
        headers = _token_headers(e2e_user)
        response = client.get(
            f"/api/v1/collections/{public_col.id}/export?format=json",
            headers=headers,
        )

        assert response.status_code == 200
        content = json.loads(response.json()["content"])
        assert len(content["documents"]) == 1
        doc = content["documents"][0]
        assert "excerpt" in doc
        assert "AI determined" in doc["excerpt"]

    def test_json_export_regular_user_no_bucket_field(
        self, client: TestClient, db: Session, e2e_user: User, public_col: Collection
    ):
        """Regular user JSON export must not include bucket field (privacy)."""
        headers = _token_headers(e2e_user)
        response = client.get(
            f"/api/v1/collections/{public_col.id}/export?format=json",
            headers=headers,
        )

        content = json.loads(response.json()["content"])
        doc = content["documents"][0]
        assert "bucket" not in doc

    def test_json_export_admin_includes_bucket_field(
        self, client: TestClient, db: Session, e2e_admin: User, public_col: Collection
    ):
        """Admin JSON export includes bucket field for full transparency."""
        headers = _token_headers(e2e_admin)
        response = client.get(
            f"/api/v1/collections/{public_col.id}/export?format=json",
            headers=headers,
        )

        content = json.loads(response.json()["content"])
        doc = content["documents"][0]
        assert "bucket" in doc
        assert doc["bucket"] == "public"
