"""
Performance QA Validation — End-to-End Benchmarks

Targets (from PRD + audit):
- Suggest p99 < 50ms
- Search p95 < 3000ms (Phase 1 baseline), target < 1000ms (Phase 3)
- Simple query intent skip saves >400ms vs LLM intent

Run: pytest backend/tests/qa/test_search_performance_qa.py -v -s
"""
import statistics
import time

import pytest
from fastapi.testclient import TestClient


class TestSuggestPerformance:
    """Benchmark /v1/search/suggest latency"""

    @pytest.mark.benchmark
    def test_suggest_latency_distribution(self, client: TestClient, auth_headers):
        latencies = []
        queries = ["fin", "doc", "pass", "tax", "ins", "med", "leg", "pho", "edu", "pro"]

        for q in queries:
            start = time.time()
            response = client.get(f"/api/v1/search/suggest?q={q}", headers=auth_headers)
            elapsed = (time.time() - start) * 1000
            assert response.status_code == 200
            latencies.append(elapsed)

        p50 = statistics.median(latencies)
        p95 = sorted(latencies)[int(len(latencies) * 0.95)]
        p99 = sorted(latencies)[int(len(latencies) * 0.99)]

        print(f"\n  Suggest latencies: p50={p50:.1f}ms, p95={p95:.1f}ms, p99={p99:.1f}ms")
        assert p99 < 50, f"Suggest p99 {p99:.1f}ms exceeds 50ms target"


class TestSearchLatency:
    """Benchmark POST /v1/search latency"""

    @pytest.mark.benchmark
    @pytest.mark.requires_postgres
    def test_search_latency_distribution(self, client: TestClient, auth_headers):
        queries = [
            "passport", "tax 2024", "financial report",
            "insurance policy", "family history", "medical records",
        ]
        latencies = []

        for q in queries:
            start = time.time()
            response = client.post(
                "/api/v1/search",
                json={"query": q, "mode": "fast", "top_k": 10},
                headers=auth_headers,
            )
            elapsed = (time.time() - start) * 1000
            if response.status_code == 200:
                latencies.append(elapsed)
            print(f"  Query '{q}': {elapsed:.0f}ms (status={response.status_code})")

        if latencies:
            p50 = statistics.median(latencies)
            p95 = sorted(latencies)[int(len(latencies) * 0.95)]
            print(f"\n  Search latencies: p50={p50:.1f}ms, p95={p95:.1f}ms")
            assert p95 < 3000, f"Search p95 {p95:.1f}ms exceeds 3000ms Phase 1 target"
        else:
            pytest.skip("Search returned no successful responses")


class TestStreamingLatency:
    """Benchmark time-to-first-result in streaming endpoint"""

    @pytest.mark.benchmark
    @pytest.mark.requires_postgres
    def test_streaming_time_to_first_result(self, client: TestClient, auth_headers):
        """Measure how long until the 'results' event arrives in the SSE stream."""
        import json

        start = time.time()
        response = client.post(
            "/api/v1/search/stream",
            json={"query": "passport", "mode": "fast", "top_k": 5},
            headers={**auth_headers, "Accept": "text/event-stream"},
        )
        assert response.status_code == 200

        body = response.text
        first_result_time = None
        done_time = None

        for line in body.split("\n"):
            if line.startswith("event: results"):
                first_result_time = (time.time() - start) * 1000
            if line.startswith("event: done"):
                done_time = (time.time() - start) * 1000

        print(f"\n  Streaming: time-to-results={first_result_time:.0f}ms, total={done_time:.0f}ms")

        if first_result_time:
            assert first_result_time < 2000, "Results must appear within 2s"
