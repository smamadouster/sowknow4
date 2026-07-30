"""MemoryChecker must use the cgroup working set (usage - inactive_file),
not raw usage, or page-cache-heavy containers (postgres) false-positive."""

import pytest

from guardian_hc.checks.memory import MemoryChecker


def _stats_payload(usage, limit, stats):
    return {"memory_stats": {"usage": usage, "limit": limit, "stats": stats}}


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class FakeClient:
    def __init__(self, containers, stats_by_id):
        self._containers = containers
        self._stats = stats_by_id

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url):
        if url == "/containers/json":
            return FakeResponse(self._containers)
        cid = url.split("/")[2]
        return FakeResponse(self._stats[cid])


def _run(monkeypatch, containers, stats_by_id):
    import httpx

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", lambda *a, **k: None)
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: FakeClient(containers, stats_by_id))
    import asyncio

    return asyncio.run(MemoryChecker().check([]))


LIMIT = 4 * 1024**3


def test_page_cache_excluded_from_percentage(monkeypatch):
    """postgres: usage ~100% of limit but 2.8G is inactive file cache."""
    containers = [{"Id": "abc123def456", "Names": ["/sowknow-postgres"]}]
    stats = {
        "abc123def456": _stats_payload(
            usage=int(LIMIT * 0.998),
            limit=LIMIT,
            stats={
                "total_inactive_file": 2856284160,
                "inactive_file": 2856284160,
                "rss": 17788928,
            },
        )
    }
    results = _run(monkeypatch, containers, stats)
    assert len(results) == 1
    assert results[0]["container"] == "sowknow-postgres"
    assert results[0]["severity"] == "ok"
    assert results[0]["needs_healing"] is False
    assert results[0]["mem_pct"] < 50


def test_real_pressure_still_alerts(monkeypatch):
    """High usage with little page cache must still trip the thresholds."""
    containers = [{"Id": "abc123def456", "Names": ["/sowknow-backend"]}]
    stats = {
        "abc123def456": _stats_payload(
            usage=int(LIMIT * 0.95),
            limit=LIMIT,
            stats={"total_inactive_file": 100 * 1024**2, "inactive_file": 100 * 1024**2},
        )
    }
    results = _run(monkeypatch, containers, stats)
    assert results[0]["severity"] == "critical"
    assert results[0]["needs_healing"] is True


def test_cgroup_v2_inactive_file_key(monkeypatch):
    """cgroup v2 only exposes `inactive_file` (no total_ prefix)."""
    containers = [{"Id": "abc123def456", "Names": ["/x"]}]
    stats = {
        "abc123def456": _stats_payload(
            usage=int(LIMIT * 0.9),
            limit=LIMIT,
            stats={"inactive_file": int(LIMIT * 0.8)},
        )
    }
    results = _run(monkeypatch, containers, stats)
    assert results[0]["severity"] == "ok"


def test_no_stats_key_falls_back_to_raw_usage(monkeypatch):
    containers = [{"Id": "abc123def456", "Names": ["/x"]}]
    stats = {"abc123def456": _stats_payload(usage=int(LIMIT * 0.95), limit=LIMIT, stats={})}
    results = _run(monkeypatch, containers, stats)
    assert results[0]["severity"] == "critical"
