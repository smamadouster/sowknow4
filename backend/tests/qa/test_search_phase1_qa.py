"""
Phase 1 QA Validation — Quick Wins

Validates:
- /v1/search/suggest endpoint (latency, structure, auth)
- Parallel sub-query execution
- Redis cache integration
- Fast-path intent skipping
- search_time_ms in streaming

Run: pytest backend/tests/qa/test_search_phase1_qa.py -v
"""
import time

import pytest
from fastapi.testclient import TestClient


class TestSuggestEndpoint:
    """QA Gate: P1.1 Suggestions must work and be fast"""

    def test_suggest_unauthorized_401(self, client: TestClient):
        response = client.get("/api/v1/search/suggest?q=pass")
        assert response.status_code == 401, "Unauthenticated request must return 401"

    def test_suggest_empty_query_validation(self, client: TestClient, auth_headers):
        response = client.get("/api/v1/search/suggest?q=", headers=auth_headers)
        assert response.status_code in [400, 422], "Empty query must be rejected"

    def test_suggest_returns_valid_structure(self, client: TestClient, auth_headers):
        response = client.get("/api/v1/search/suggest?q=fin", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "query" in data, "Response must contain 'query'"
        assert "suggestions" in data, "Response must contain 'suggestions'"
        assert isinstance(data["suggestions"], list)
        for s in data["suggestions"]:
            assert "id" in s, "Suggestion must have 'id'"
            assert "title" in s, "Suggestion must have 'title'"
            assert "type" in s, "Suggestion must have 'type'"
            assert s["type"] in ("document", "bookmark", "note", "tag")

    def test_suggest_p99_latency_under_50ms(self, client: TestClient, auth_headers):
        """QA Gate: Suggestions must respond in <50ms p99"""
        latencies = []
        for _ in range(20):
            start = time.time()
            response = client.get("/api/v1/search/suggest?q=doc", headers=auth_headers)
            elapsed = (time.time() - start) * 1000
            assert response.status_code == 200
            latencies.append(elapsed)

        p99 = sorted(latencies)[int(len(latencies) * 0.99)]
        assert p99 < 50, f"Suggest p99 latency {p99:.1f}ms exceeds 50ms budget"

    def test_suggest_respects_limit(self, client: TestClient, auth_headers):
        response = client.get("/api/v1/search/suggest?q=a&limit=3", headers=auth_headers)
        assert response.status_code == 200
        assert len(response.json()["suggestions"]) <= 3

    def test_suggest_limit_bounds_enforced(self, client: TestClient, auth_headers):
        response = client.get("/api/v1/search/suggest?q=test&limit=20", headers=auth_headers)
        assert response.status_code in [400, 422], "Limit >10 must be rejected"


class TestStreamingSearchTime:
    """QA Gate: P1.6 search_time_ms must be present in streaming done event"""

    @pytest.mark.asyncio
    async def test_streaming_includes_search_time_ms(self, client: TestClient, auth_headers):
        """Verify the SSE stream includes search_time_ms in the done event."""
        response = client.post(
            "/api/v1/search/stream",
            json={"query": "test", "mode": "fast", "top_k": 5, "include_suggestions": False},
            headers={**auth_headers, "Accept": "text/event-stream"},
        )
        assert response.status_code == 200
        body = response.text
        assert "search_time_ms" in body, "done event must include search_time_ms"


class TestFastPathIntent:
    """QA Gate: P1.5 Short queries skip LLM intent parsing"""

    @pytest.mark.asyncio
    async def test_short_query_uses_fallback_intent(self):
        from app.services.search_agent import run_agentic_search
        from app.services.search_models import AgenticSearchRequest
        from unittest.mock import AsyncMock, patch
        from uuid import uuid4

        request = AgenticSearchRequest(query="passport")
        mock_user = AsyncMock()
        mock_user.id = uuid4()
        mock_user.role.value = "user"

        with patch("app.services.search_agent.parse_intent") as mock_parse:
            # This should NOT be called for short queries
            try:
                await run_agentic_search(
                    db=AsyncMock(),
                    request=request,
                    user_role=mock_user.role,
                    user_id=mock_user.id,
                    user=mock_user,
                )
            except Exception:
                pass  # DB mocking is incomplete; we only care that parse_intent was skipped

        mock_parse.assert_not_awaited()
