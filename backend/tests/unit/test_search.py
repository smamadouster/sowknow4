"""
Unit tests for search endpoints
"""
import pytest
from fastapi.testclient import TestClient


def test_search_unauthorized(client: TestClient):
    """Test search without authentication"""
    response = client.post(
        "/api/v1/search",
        json={"query": "test search"}
    )

    assert response.status_code == 401


def test_search_empty_query(client: TestClient, auth_headers):
    """Test search with empty query"""
    response = client.post(
        "/api/v1/search",
        json={"query": ""},
        headers=auth_headers
    )

    assert response.status_code == 400


def test_search_valid_query(client: TestClient, auth_headers):
    """Test search with valid query"""
    response = client.post(
        "/api/v1/search",
        json={"query": "test document", "limit": 10},
        headers=auth_headers
    )

    assert response.status_code == 200
    data = response.json()
    assert "query" in data
    assert "results" in data
    assert "total" in data


def test_search_with_limit(client: TestClient, auth_headers):
    """Test search with custom limit"""
    response = client.post(
        "/api/v1/search",
        json={"query": "test", "limit": 5},
        headers=auth_headers
    )

    assert response.status_code == 200
    data = response.json()
    assert len(data["results"]) <= 5


def test_search_with_offset(client: TestClient, auth_headers):
    """Test search with offset"""
    response = client.post(
        "/api/v1/search",
        json={"query": "test", "limit": 10, "offset": 5},
        headers=auth_headers
    )

    assert response.status_code == 200


def test_search_suggestions(client: TestClient, auth_headers):
    """Test search suggestions"""
    response = client.get(
        "/api/v1/search/suggest?q=test",
        headers=auth_headers
    )

    assert response.status_code == 200
    data = response.json()
    assert "query" in data
    assert "suggestions" in data
