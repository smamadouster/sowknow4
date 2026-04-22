"""
Tests for /api/v1/search/suggest endpoint
"""
import time

import pytest
from fastapi.testclient import TestClient


class TestSearchSuggest:
    def test_suggest_unauthorized(self, client: TestClient):
        response = client.get("/api/v1/search/suggest?q=test")
        assert response.status_code == 401

    def test_suggest_empty_query_rejected(self, client: TestClient, auth_headers):
        response = client.get("/api/v1/search/suggest?q=", headers=auth_headers)
        assert response.status_code in [400, 422]

    def test_suggest_returns_structure(self, client: TestClient, auth_headers):
        response = client.get("/api/v1/search/suggest?q=fin", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "query" in data
        assert "suggestions" in data
        assert isinstance(data["suggestions"], list)
        for s in data["suggestions"]:
            assert "id" in s
            assert "title" in s
            assert "type" in s
            assert s["type"] in ("document", "bookmark", "note", "tag")

    def test_suggest_latency_under_50ms(self, client: TestClient, auth_headers):
        start = time.time()
        response = client.get("/api/v1/search/suggest?q=doc", headers=auth_headers)
        elapsed = (time.time() - start) * 1000
        assert response.status_code == 200
        assert elapsed < 50, f"Suggest latency {elapsed:.1f}ms exceeds 50ms budget"

    def test_suggest_respects_limit(self, client: TestClient, auth_headers):
        response = client.get("/api/v1/search/suggest?q=a&limit=3", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data["suggestions"]) <= 3

    def test_suggest_limit_validation(self, client: TestClient, auth_headers):
        response = client.get("/api/v1/search/suggest?q=test&limit=0", headers=auth_headers)
        assert response.status_code in [400, 422]

        response = client.get("/api/v1/search/suggest?q=test&limit=20", headers=auth_headers)
        assert response.status_code in [400, 422]
