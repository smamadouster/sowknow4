"""
Tests for /api/v1/search/feedback endpoint
"""
import pytest
from fastapi.testclient import TestClient


class TestSearchFeedback:
    def test_feedback_unauthorized(self, client: TestClient):
        response = client.post("/api/v1/search/feedback", json={
            "query": "test",
            "document_id": "550e8400-e29b-41d4-a716-446655440000",
            "feedback_type": "thumbs_up",
        })
        assert response.status_code == 401

    def test_feedback_invalid_type_rejected(self, client: TestClient, auth_headers):
        response = client.post("/api/v1/search/feedback", json={
            "query": "test",
            "document_id": "550e8400-e29b-41d4-a716-446655440000",
            "feedback_type": "invalid_type",
        }, headers=auth_headers)
        assert response.status_code in [400, 422]

    def test_feedback_valid(self, client: TestClient, auth_headers):
        response = client.post("/api/v1/search/feedback", json={
            "query": "passport search",
            "document_id": "550e8400-e29b-41d4-a716-446655440000",
            "chunk_id": "550e8400-e29b-41d4-a716-446655440001",
            "feedback_type": "thumbs_up",
        }, headers=auth_headers)
        assert response.status_code == 201
        data = response.json()
        assert data["status"] == "recorded"

    def test_feedback_stats_unauthorized(self, client: TestClient):
        response = client.get("/api/v1/search/feedback/stats")
        assert response.status_code == 401
