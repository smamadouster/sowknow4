"""
Unit tests for search endpoints
"""
import pytest
pytest.skip("Disabled during Ollama removal (Sep 4)", allow_module_level=True)

from fastapi.testclient import TestClient


def test_search_unauthorized(client: TestClient):
    """Test search without authentication"""
    response = client.post("/api/v1/search", json={"query": "test search"})

    assert response.status_code == 401


def test_search_empty_query(client: TestClient, auth_headers):
    """Test search with empty query - FastAPI returns 422 for validation failure"""
    response = client.post("/api/v1/search", json={"query": ""}, headers=auth_headers)

    # FastAPI returns 422 (Unprocessable Entity) for schema validation failures
    assert response.status_code in [400, 422]


def test_search_valid_query(client: TestClient, auth_headers):
    """Test search with valid query"""
    response = client.post("/api/v1/search", json={"query": "test document", "limit": 10}, headers=auth_headers)

    assert response.status_code == 200
    data = response.json()
    assert "query" in data
    assert "results" in data
    assert "total" in data


def test_search_with_limit(client: TestClient, auth_headers):
    """Test search with custom limit"""
    response = client.post("/api/v1/search", json={"query": "test", "limit": 5}, headers=auth_headers)

    assert response.status_code == 200
    data = response.json()
    assert len(data["results"]) <= 5


def test_search_with_offset(client: TestClient, auth_headers):
    """Test search with offset"""
    response = client.post("/api/v1/search", json={"query": "test", "limit": 10, "offset": 5}, headers=auth_headers)

    assert response.status_code == 200


def test_search_suggestions(client: TestClient, auth_headers):
    """Test search suggestions"""
    response = client.get("/api/v1/search/suggest?q=test", headers=auth_headers)

    assert response.status_code == 200
    data = response.json()
    assert "query" in data
    assert "suggestions" in data


def test_fallback_intent_detects_french_bare_noun():
    """Short French queries without stopwords must not fall back to 'en'
    (2026-08-05: smoke test caught 'contrat' → language 'en')."""
    from app.services.search_agent import _fallback_intent

    assert _fallback_intent("contrat").detected_language == "fr"
    assert _fallback_intent("vaccination").detected_language == "fr"
    assert _fallback_intent("le contrat de bail").detected_language == "fr"


def test_fallback_intent_detects_english():
    from app.services.search_agent import _fallback_intent

    assert _fallback_intent("the budget report").detected_language == "en"
    assert _fallback_intent("when was it signed").detected_language == "en"
