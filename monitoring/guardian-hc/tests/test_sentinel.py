"""Tests for SentinelPlugin — silent failure detection."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from guardian_hc.plugin import CheckContext, Severity
from guardian_hc.plugins.sentinel import SentinelPlugin


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ctx(**kwargs):
    defaults = dict(
        patrol_level="full",
        config={
            "backend_url": "http://backend:8000",
            "redis_host": "redis",
            "redis_port": 6379,
            "redis_password": "test-only",  # pragma: allowlist secret
        },
        services=[],
    )
    defaults.update(kwargs)
    return CheckContext(**defaults)


def _make_plugin():
    return SentinelPlugin(config={
        "backend_url": "http://backend:8000",
        "redis_host": "redis",
        "redis_port": 6379,
        "redis_password": "test-only",  # pragma: allowlist secret
    })


def _stale_timestamp(minutes_ago: int) -> str:
    dt = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return dt.isoformat()


# ---------------------------------------------------------------------------
# Plugin attributes
# ---------------------------------------------------------------------------

class TestSentinelPluginAttributes:
    def test_name(self):
        p = _make_plugin()
        assert p.name == "sentinel"

    def test_enabled(self):
        p = _make_plugin()
        assert p.enabled is True

    def test_queue_history_starts_empty(self):
        p = _make_plugin()
        assert p._queue_history == []

    def test_constants(self):
        assert SentinelPlugin.STALENESS_THRESHOLD_MINUTES == 5
        assert SentinelPlugin.QUEUE_GROWTH_CHECKS_THRESHOLD == 3


# ---------------------------------------------------------------------------
# _check_stale_data
# ---------------------------------------------------------------------------

class TestCheckStaleData:
    def _mock_response(self, last_write: str | None, status_code: int = 200):
        resp = MagicMock()
        resp.status_code = status_code
        body = {}
        if last_write is not None:
            body["last_write"] = last_write
        resp.json.return_value = body
        return resp

    def test_stale_data_detected(self):
        """A last_write 10 minutes ago should trigger a fail result."""
        p = _make_plugin()
        ctx = _make_ctx()
        stale_ts = _stale_timestamp(10)

        mock_resp = self._mock_response(stale_ts)
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            results = asyncio.run(p._check_stale_data(ctx))

        assert len(results) == 1
        r = results[0]
        assert r.status == "fail"
        assert r.check_name == "stale_data"
        assert r.module == "Storage Layer"
        assert r.needs_healing is True
        assert r.heal_hint == "restart_backend"
        assert r.severity == Severity.HIGH

    def test_fresh_data_no_alert(self):
        """A last_write 1 minute ago should produce no results."""
        p = _make_plugin()
        ctx = _make_ctx()
        fresh_ts = _stale_timestamp(1)

        mock_resp = self._mock_response(fresh_ts)
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            results = asyncio.run(p._check_stale_data(ctx))

        assert results == []

    def test_no_last_write_field_returns_empty(self):
        """Missing last_write field → empty list (no alarm)."""
        p = _make_plugin()
        ctx = _make_ctx()

        mock_resp = self._mock_response(None)
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            results = asyncio.run(p._check_stale_data(ctx))

        assert results == []

    def test_unreachable_endpoint_returns_empty(self):
        """Network errors should be swallowed and return empty list."""
        p = _make_plugin()
        ctx = _make_ctx()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=Exception("connection refused"))

        with patch("httpx.AsyncClient", return_value=mock_client):
            results = asyncio.run(p._check_stale_data(ctx))

        assert results == []


# ---------------------------------------------------------------------------
# _check_queue_drain
# ---------------------------------------------------------------------------

class TestCheckQueueDrain:
    def _patch_subprocess(self, side_effects):
        """side_effects: list of stdout strings for successive subprocess calls."""
        calls = iter(side_effects)

        def fake_run(cmd, **kwargs):
            result = MagicMock()
            result.returncode = 0
            result.stdout = next(calls, "0")
            return result

        return patch("subprocess.run", side_effect=fake_run)

    def test_growing_queue_detected(self):
        """Queue growing monotonically for 3+ checks above threshold → fail."""
        p = _make_plugin()
        ctx = _make_ctx()

        # Simulate 3 growing readings, each call sums 4 queues (all return same val)
        # Reading 1: total = 20, Reading 2: total = 40, Reading 3: total = 60
        outputs = (
            # reading 1: 4 queues × 5 each
            "5", "5", "5", "5",
            # reading 2: 4 queues × 10 each
            "10", "10", "10", "10",
            # reading 3: 4 queues × 15 each
            "15", "15", "15", "15",
        )

        with self._patch_subprocess(outputs):
            asyncio.run(p._check_queue_drain(ctx))  # reading 1 → [20]
            asyncio.run(p._check_queue_drain(ctx))  # reading 2 → [20, 40]
            results = asyncio.run(p._check_queue_drain(ctx))  # reading 3 → [20, 40, 60]

        assert len(results) == 1
        r = results[0]
        assert r.status == "fail"
        assert r.check_name == "queue_not_draining"
        assert r.module == "Document Pipeline"
        assert r.needs_healing is True
        assert r.heal_hint == "restart_celery_workers"

    def test_stable_queue_no_alert(self):
        """Stable queue depth (not monotonically growing) → no alert."""
        p = _make_plugin()
        ctx = _make_ctx()

        outputs = (
            "5", "5", "5", "5",   # reading 1: total=20
            "5", "5", "5", "5",   # reading 2: total=20 (stable)
            "5", "5", "5", "5",   # reading 3: total=20 (stable)
        )

        with self._patch_subprocess(outputs):
            asyncio.run(p._check_queue_drain(ctx))
            asyncio.run(p._check_queue_drain(ctx))
            results = asyncio.run(p._check_queue_drain(ctx))

        assert results == []

    def test_low_total_no_alert_even_if_growing(self):
        """Growing queue but total <= 10 → no alert (normal cold-start noise)."""
        p = _make_plugin()
        ctx = _make_ctx()

        # All queues have tiny values totaling 4 each reading
        outputs = (
            "1", "1", "1", "1",  # total=4
            "2", "1", "1", "0",  # total=4
            "2", "2", "1", "0",  # total=5
        )

        with self._patch_subprocess(outputs):
            asyncio.run(p._check_queue_drain(ctx))
            asyncio.run(p._check_queue_drain(ctx))
            results = asyncio.run(p._check_queue_drain(ctx))

        assert results == []

    def test_history_capped_at_six(self):
        """_queue_history should not grow beyond 6 entries."""
        p = _make_plugin()
        ctx = _make_ctx()

        # Each call: 4 queues all returning "1"
        outputs = ["1"] * (4 * 10)

        with self._patch_subprocess(outputs):
            for _ in range(10):
                asyncio.run(p._check_queue_drain(ctx))

        assert len(p._queue_history) <= 6


# ---------------------------------------------------------------------------
# _check_frontend_api_bridge
# ---------------------------------------------------------------------------

class TestCheckFrontendApiBridge:
    def _mock_client_with_responses(self, frontend_code: int, backend_code: int):
        async def fake_get(url, **kwargs):
            resp = MagicMock()
            if "frontend" in url or "3000" in url:
                resp.status_code = frontend_code
            else:
                resp.status_code = backend_code
            return resp

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=fake_get)
        return mock_client

    def test_frontend_up_backend_502_detected(self):
        """Frontend healthy + backend 502 → fail."""
        p = _make_plugin()
        ctx = _make_ctx()

        mock_client = self._mock_client_with_responses(200, 502)
        with patch("httpx.AsyncClient", return_value=mock_client):
            results = asyncio.run(p._check_frontend_api_bridge(ctx))

        assert len(results) == 1
        r = results[0]
        assert r.status == "fail"
        assert r.check_name == "frontend_api_bridge"
        assert r.needs_healing is True

    def test_frontend_up_backend_503_detected(self):
        """Frontend healthy + backend 503 → fail."""
        p = _make_plugin()
        ctx = _make_ctx()

        mock_client = self._mock_client_with_responses(200, 503)
        with patch("httpx.AsyncClient", return_value=mock_client):
            results = asyncio.run(p._check_frontend_api_bridge(ctx))

        assert len(results) == 1

    def test_frontend_down_no_alert(self):
        """Frontend unreachable → no alert (don't blame backend for frontend outage)."""
        p = _make_plugin()
        ctx = _make_ctx()

        mock_client = self._mock_client_with_responses(503, 503)
        with patch("httpx.AsyncClient", return_value=mock_client):
            results = asyncio.run(p._check_frontend_api_bridge(ctx))

        assert results == []

    def test_both_healthy_no_alert(self):
        """Frontend + backend both healthy → no results."""
        p = _make_plugin()
        ctx = _make_ctx()

        mock_client = self._mock_client_with_responses(200, 200)
        with patch("httpx.AsyncClient", return_value=mock_client):
            results = asyncio.run(p._check_frontend_api_bridge(ctx))

        assert results == []


# ---------------------------------------------------------------------------
# check() — top-level integration
# ---------------------------------------------------------------------------

class TestSentinelCheck:
    def test_check_returns_list(self):
        """check() should always return a list."""
        p = _make_plugin()
        ctx = _make_ctx()

        with patch.object(p, "_check_stale_data", new=AsyncMock(return_value=[])):
            with patch.object(p, "_check_queue_drain", new=AsyncMock(return_value=[])):
                with patch.object(p, "_check_frontend_api_bridge", new=AsyncMock(return_value=[])):
                    results = asyncio.run(p.check(ctx))

        assert isinstance(results, list)

    def test_check_aggregates_sub_results(self):
        """check() should aggregate results from all sub-checks."""
        from guardian_hc.plugin import CheckResult, Severity

        p = _make_plugin()
        ctx = _make_ctx()

        fake_fail = CheckResult(
            plugin="sentinel",
            module="Storage Layer",
            check_name="stale_data",
            status="fail",
            severity=Severity.HIGH,
            summary="Stale data detected",
            needs_healing=True,
            heal_hint="restart_backend",
        )

        with patch.object(p, "_check_stale_data", new=AsyncMock(return_value=[fake_fail])):
            with patch.object(p, "_check_queue_drain", new=AsyncMock(return_value=[])):
                with patch.object(p, "_check_frontend_api_bridge", new=AsyncMock(return_value=[])):
                    results = asyncio.run(p.check(ctx))

        assert len(results) == 1
        assert results[0].check_name == "stale_data"

    def test_check_continues_on_sub_check_exception(self):
        """If one sub-check raises, check() should continue with others."""
        p = _make_plugin()
        ctx = _make_ctx()

        async def boom(ctx):
            raise RuntimeError("unexpected failure")

        with patch.object(p, "_check_stale_data", new=boom):
            with patch.object(p, "_check_queue_drain", new=AsyncMock(return_value=[])):
                with patch.object(p, "_check_frontend_api_bridge", new=AsyncMock(return_value=[])):
                    results = asyncio.run(p.check(ctx))

        assert isinstance(results, list)


# ---------------------------------------------------------------------------
# heal()
# ---------------------------------------------------------------------------

class TestSentinelHeal:
    def test_heal_restart_backend(self):
        from guardian_hc.plugin import CheckResult, Severity

        p = _make_plugin()
        result = CheckResult(
            plugin="sentinel",
            module="Storage Layer",
            check_name="stale_data",
            status="fail",
            severity=Severity.HIGH,
            summary="Stale",
            needs_healing=True,
            heal_hint="restart_backend",
        )

        mock_healer = AsyncMock()
        mock_healer.heal = AsyncMock(return_value={"healed": True, "action": "restarted"})
        mock_healer_cls = MagicMock(return_value=mock_healer)

        with patch("guardian_hc.plugins.sentinel.ContainerHealer", mock_healer_cls):
            heal_result = asyncio.run(p.heal(result))

        mock_healer.heal.assert_awaited_once_with("sowknow4-backend")
        assert heal_result is not None
        assert heal_result.plugin == "sentinel"

    def test_heal_restart_celery_workers(self):
        from guardian_hc.plugin import CheckResult, Severity

        p = _make_plugin()
        result = CheckResult(
            plugin="sentinel",
            module="Document Pipeline",
            check_name="queue_not_draining",
            status="fail",
            severity=Severity.HIGH,
            summary="Queue growing",
            needs_healing=True,
            heal_hint="restart_celery_workers",
        )

        mock_healer = AsyncMock()
        mock_healer.heal = AsyncMock(return_value={"healed": True, "action": "restarted"})
        mock_healer_cls = MagicMock(return_value=mock_healer)

        with patch("guardian_hc.plugins.sentinel.ContainerHealer", mock_healer_cls):
            heal_result = asyncio.run(p.heal(result))

        assert mock_healer.heal.await_count == 2
        calls = [c.args[0] for c in mock_healer.heal.await_args_list]
        assert "sowknow4-celery-light" in calls
        assert "sowknow4-celery-heavy" in calls
        assert heal_result is not None

    def test_heal_unknown_hint_returns_none(self):
        from guardian_hc.plugin import CheckResult, Severity

        p = _make_plugin()
        result = CheckResult(
            plugin="sentinel",
            module="X",
            check_name="y",
            status="fail",
            severity=Severity.INFO,
            summary="dunno",
            heal_hint="unknown_action",
        )

        mock_healer_cls = MagicMock()
        with patch("guardian_hc.plugins.sentinel.ContainerHealer", mock_healer_cls):
            heal_result = asyncio.run(p.heal(result))

        assert heal_result is None
