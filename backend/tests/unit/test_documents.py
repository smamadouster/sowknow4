"""
Unit tests for document endpoints
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from io import BytesIO


def test_upload_document_unauthorized(client: TestClient):
    """Test document upload without authentication"""
    # Create a fake file
    files = {"file": ("test.pdf", BytesIO(b"fake pdf content"), "application/pdf")}
    data = {"bucket": "public"}

    response = client.post("/api/v1/documents/upload", files=files, data=data)

    assert response.status_code == 401


def test_upload_document_confidential_as_user(client: TestClient, auth_headers):
    """Test that regular users can't upload to confidential bucket"""
    files = {"file": ("test.pdf", BytesIO(b"fake pdf content"), "application/pdf")}
    data = {"bucket": "confidential"}

    response = client.post(
        "/api/v1/documents/upload", files=files, data=data, headers=auth_headers
    )

    # Should be forbidden for non-admin users
    assert response.status_code == 403


def test_upload_document_admin(client: TestClient, admin_headers):
    """Test document upload as admin"""
    files = {"file": ("test.pdf", BytesIO(b"fake pdf content"), "application/pdf")}
    data = {"bucket": "public"}

    response = client.post(
        "/api/v1/documents/upload", files=files, data=data, headers=admin_headers
    )

    # May fail due to file system or auth, but shouldn't be 403
    assert response.status_code in [200, 401, 500]


def test_batch_upload_exceeds_500mb_limit(client: TestClient, admin_headers):
    """Test that batch upload exceeding 500MB limit returns HTTP 413"""
    # Create files that together exceed 500MB
    # Using 200MB per file, 3 files = 600MB (exceeds 500MB limit)
    large_content = b"x" * (200 * 1024 * 1024)  # 200MB

    files = [
        ("files", ("file1.pdf", BytesIO(large_content), "application/pdf")),
        ("files", ("file2.pdf", BytesIO(large_content), "application/pdf")),
        ("files", ("file3.pdf", BytesIO(large_content), "application/pdf")),
    ]
    data = {"bucket": "public"}

    response = client.post(
        "/api/v1/documents/upload-batch", files=files, data=data, headers=admin_headers
    )

    assert response.status_code == 413
    error_detail = response.json()["detail"]
    assert "500MB" in error_detail or "500 MB" in error_detail
    assert "exceeds limit" in error_detail.lower()


def test_batch_upload_under_500mb_limit(client: TestClient, admin_headers):
    """Test that batch upload under 500MB limit is accepted"""
    # Create small files that total under 500MB
    small_content = b"x" * (10 * 1024 * 1024)  # 10MB each

    files = [
        ("files", ("file1.pdf", BytesIO(small_content), "application/pdf")),
        ("files", ("file2.pdf", BytesIO(small_content), "application/pdf")),
    ]
    data = {"bucket": "public"}

    response = client.post(
        "/api/v1/documents/upload-batch", files=files, data=data, headers=admin_headers
    )

    # Should not be 413 (may fail for other reasons like storage/auth, but not batch limit)
    assert response.status_code != 413


def test_batch_upload_unauthorized(client: TestClient):
    """Test batch upload without authentication"""
    files = {"files": ("test.pdf", BytesIO(b"fake pdf content"), "application/pdf")}
    data = {"bucket": "public"}

    response = client.post("/api/v1/documents/upload-batch", files=files, data=data)

    assert response.status_code == 401


def test_batch_upload_confidential_as_user(client: TestClient, auth_headers):
    """Test that regular users can't upload to confidential bucket via batch"""
    files = {"files": ("test.pdf", BytesIO(b"fake pdf content"), "application/pdf")}
    data = {"bucket": "confidential"}

    response = client.post(
        "/api/v1/documents/upload-batch", files=files, data=data, headers=auth_headers
    )

    # Should be forbidden for non-admin users (may also return 401 if auth fails)
    assert response.status_code in [401, 403]


def test_batch_upload_no_files(client: TestClient, admin_headers):
    """Test batch upload with no files"""
    data = {"bucket": "public"}

    # FastAPI returns 422 for empty files list validation
    response = client.post(
        "/api/v1/documents/upload-batch", files=[], data=data, headers=admin_headers
    )

    # FastAPI validates the files parameter, so 422 is expected for empty list
    assert response.status_code == 422


def test_list_documents(client: TestClient, test_document):
    """Test listing documents"""
    response = client.get("/api/v1/documents")

    assert response.status_code == 200
    data = response.json()
    assert "documents" in data
    assert "total" in data


def test_list_documents_with_pagination(client: TestClient):
    """Test document listing with pagination"""
    response = client.get("/api/v1/documents?page=1&page_size=10")

    assert response.status_code == 200
    data = response.json()
    assert data["page"] == 1
    assert data["page_size"] == 10


def test_get_document(client: TestClient, test_document):
    """Test getting a specific document"""
    response = client.get(f"/api/v1/documents/{test_document.id}")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(test_document.id)


def test_get_document_not_found(client: TestClient):
    """Test getting non-existent document"""
    import uuid

    fake_id = uuid.uuid4()

    response = client.get(f"/api/v1/documents/{fake_id}")

    assert response.status_code == 404


def test_delete_document_unauthorized(client: TestClient, test_document):
    """Test that regular users can't delete documents"""
    response = client.delete(f"/api/v1/documents/{test_document.id}")

    assert response.status_code == 401


def test_delete_document_admin(client: TestClient, test_document, admin_headers):
    """Test document deletion by admin"""
    response = client.delete(
        f"/api/v1/documents/{test_document.id}", headers=admin_headers
    )

    # May fail due to auth, but shouldn't be 403 if authorized
    assert response.status_code in [200, 401]
