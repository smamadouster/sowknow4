"""
SOWKNOW load test — simulates up to 5 concurrent users
Run:
    locust --headless -u 5 -r 1 --run-time 60s -f locustfile.py --host http://localhost:8001
"""

import json
import random

from locust import HttpUser, between, task


MOCK_AUTH_HEADER = {"Authorization": "Bearer load-test-token"}

MOCK_QUERIES = [
    "What documents do I have about taxes?",
    "Find information about my insurance policy",
    "Show me letters from 2023",
    "What is my pension plan?",
    "Search for medical records",
]


class SowknowUser(HttpUser):
    """Simulates a logged-in SOWKNOW user performing typical actions."""

    wait_time = between(1, 3)
    host = "http://localhost:8001"

    @task(1)
    def health_check(self) -> None:
        """Lightweight health probe — weight 1."""
        with self.client.get("/health", catch_response=True) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Health check failed: {response.status_code}")

    @task(2)
    def list_documents(self) -> None:
        """List documents page — weight 2."""
        with self.client.get(
            "/api/v1/documents",
            headers=MOCK_AUTH_HEADER,
            catch_response=True,
        ) as response:
            if response.status_code in (200, 401, 403):
                # 401/403 expected without a real token — still validates the route exists
                response.success()
            else:
                response.failure(f"Unexpected status: {response.status_code}")

    @task(3)
    def chat_stream(self) -> None:
        """SSE streaming chat endpoint — highest weight (3)."""
        payload = {
            "message": random.choice(MOCK_QUERIES),
            "session_id": "load-test-session-001",
        }
        with self.client.post(
            "/api/v1/chat/stream",
            json=payload,
            headers={**MOCK_AUTH_HEADER, "Accept": "text/event-stream"},
            catch_response=True,
            stream=False,  # Locust reads full response
        ) as response:
            if response.status_code in (200, 401, 403, 422):
                response.success()
            else:
                response.failure(f"Unexpected status: {response.status_code}")

    @task(1)
    def list_collections(self) -> None:
        """List smart collections — weight 1."""
        with self.client.get(
            "/api/v1/collections",
            headers=MOCK_AUTH_HEADER,
            catch_response=True,
        ) as response:
            if response.status_code in (200, 401, 403):
                response.success()
            else:
                response.failure(f"Unexpected status: {response.status_code}")
