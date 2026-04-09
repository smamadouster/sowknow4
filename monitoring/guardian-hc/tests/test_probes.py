"""Tests for ProbesPlugin (Watcher) — TDD.

Focuses on JWT probe (pass/fail) and plugin identity.
Mocks at the HTTP/subprocess boundary.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from guardian_hc.plugin import CheckContext, Severity
from guardian_hc.plugins.probes import ProbesPlugin


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ctx(level: str = "standard") -> CheckContext:
    return CheckContext(patrol_level=level, config={}, services=[])


def _make_plugin() -> ProbesPlugin:
    return ProbesPlugin(config={
        "backend_url": "http://localhost:8000",
        "redis_host": "localhost",
        "redis_port": 6379,
        "redis_password": "secret",  # pragma: allowlist secret
        "nginx_url": "http://localhost:80",
        "service_account": {"username": "guardian", "password": "test"},  # pragma: allowlist secret
    })


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

class TestProbesPluginIdentity:
    def test_name(self):
        plugin = _make_plugin()
        assert plugin.name == "probes"

    def test_enabled(self):
        plugin = _make_plugin()
        assert plugin.enabled is True


# ---------------------------------------------------------------------------
# Probe levels
# ---------------------------------------------------------------------------

class TestProbeLevels:
    def test_critical_level_subset(self):
        assert "jwt" in ProbesPlugin.PROBE_LEVELS["critical"]
        assert "redis_deep" in ProbesPlugin.PROBE_LEVELS["critical"]
        assert "celery_completion" in ProbesPlugin.PROBE_LEVELS["critical"]

    def test_standard_level_superset_of_critical(self):
        for probe in ProbesPlugin.PROBE_LEVELS["critical"]:
            assert probe in ProbesPlugin.PROBE_LEVELS["standard"]

    def test_deep_level_superset_of_standard(self):
        for probe in ProbesPlugin.PROBE_LEVELS["standard"]:
            assert probe in ProbesPlugin.PROBE_LEVELS["deep"]

    def test_deep_includes_auth_flow(self):
        assert "auth_flow" in ProbesPlugin.PROBE_LEVELS["deep"]


# ---------------------------------------------------------------------------
# _check_jwt — pass
# ---------------------------------------------------------------------------

class TestCheckJwtPass:
    def test_jwt_pass_status(self):
        plugin = _make_plugin()
        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(plugin._check_jwt(_make_ctx()))

        assert result.status == "pass"

    def test_jwt_pass_module(self):
        plugin = _make_plugin()
        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(plugin._check_jwt(_make_ctx()))

        assert result.module == "Authentication Service"

    def test_jwt_pass_no_healing_needed(self):
        plugin = _make_plugin()
        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(plugin._check_jwt(_make_ctx()))

        assert result.needs_healing is False


# ---------------------------------------------------------------------------
# _check_jwt — fail (non-200)
# ---------------------------------------------------------------------------

class TestCheckJwtFail:
    def _run_failing_jwt(self, status_code: int):
        plugin = _make_plugin()
        mock_response = MagicMock()
        mock_response.status_code = status_code

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            return asyncio.run(plugin._check_jwt(_make_ctx()))

    def test_jwt_fail_status(self):
        result = self._run_failing_jwt(500)
        assert result.status == "fail"

    def test_jwt_fail_needs_healing(self):
        result = self._run_failing_jwt(500)
        assert result.needs_healing is True

    def test_jwt_fail_heal_hint(self):
        result = self._run_failing_jwt(500)
        assert result.heal_hint == "restart_backend"

    def test_jwt_fail_severity_critical(self):
        result = self._run_failing_jwt(500)
        assert result.severity == Severity.CRITICAL

    def test_jwt_401_also_fails(self):
        result = self._run_failing_jwt(401)
        assert result.status == "fail"
        assert result.needs_healing is True


# ---------------------------------------------------------------------------
# _check_jwt — exception path
# ---------------------------------------------------------------------------

class TestCheckJwtException:
    def test_jwt_exception_returns_fail(self):
        plugin = _make_plugin()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=Exception("connection refused"))

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(plugin._check_jwt(_make_ctx()))

        assert result.status == "fail"
        assert result.needs_healing is True
        assert result.heal_hint == "restart_backend"

    def test_jwt_exception_severity_critical(self):
        plugin = _make_plugin()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=Exception("timeout"))

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(plugin._check_jwt(_make_ctx()))

        assert result.severity == Severity.CRITICAL


# ---------------------------------------------------------------------------
# check() — dispatches probes per level
# ---------------------------------------------------------------------------

class TestCheckDispatch:
    def test_critical_level_returns_results(self):
        """check() with 'critical' level returns one result per critical probe."""
        plugin = _make_plugin()

        # Mock all internal probe methods
        async def _pass_result(ctx):
            from guardian_hc.plugin import CheckResult
            return CheckResult(
                plugin="probes", module="test", check_name="mocked",
                status="pass", severity=Severity.INFO, summary="ok",
            )

        plugin._check_jwt = _pass_result
        plugin._check_redis_deep = _pass_result
        plugin._check_celery_completion = _pass_result

        ctx = _make_ctx(level="critical")
        results = asyncio.run(plugin.check(ctx))

        assert len(results) == len(ProbesPlugin.PROBE_LEVELS["critical"])

    def test_unknown_level_falls_back_to_standard(self):
        """check() with an unknown patrol level uses standard probe set."""
        plugin = _make_plugin()

        async def _pass_result(ctx):
            from guardian_hc.plugin import CheckResult
            return CheckResult(
                plugin="probes", module="test", check_name="mocked",
                status="pass", severity=Severity.INFO, summary="ok",
            )

        for probe in ProbesPlugin.PROBE_LEVELS["standard"]:
            method_name = f"_check_{probe}"
            setattr(plugin, method_name, _pass_result)

        ctx = _make_ctx(level="unknown_level")
        results = asyncio.run(plugin.check(ctx))

        assert len(results) == len(ProbesPlugin.PROBE_LEVELS["standard"])


# ---------------------------------------------------------------------------
# heal() dispatch
# ---------------------------------------------------------------------------

class TestHealDispatch:
    def test_restart_backend_heal_hint(self):
        """heal() with restart_backend hint calls ContainerHealer."""
        plugin = _make_plugin()

        from guardian_hc.plugin import CheckResult
        result = CheckResult(
            plugin="probes", module="Authentication Service",
            check_name="jwt", status="fail", severity=Severity.CRITICAL,
            summary="JWT auth down", needs_healing=True, heal_hint="restart_backend",
        )

        mock_healer = AsyncMock()
        mock_healer.heal = AsyncMock(return_value={"healed": True, "action": "restarted"})

        with patch("guardian_hc.plugins.probes.ContainerHealer", return_value=mock_healer):
            heal_result = asyncio.run(plugin.heal(result))

        assert heal_result is not None
        assert heal_result.plugin == "probes"
        mock_healer.heal.assert_called_once_with("sowknow4-backend")

    def test_unknown_heal_hint_returns_none(self):
        """heal() with unrecognized hint returns None gracefully."""
        plugin = _make_plugin()

        from guardian_hc.plugin import CheckResult
        result = CheckResult(
            plugin="probes", module="Storage Layer",
            check_name="redis_deep", status="fail", severity=Severity.WARNING,
            summary="Redis high", needs_healing=True, heal_hint=None,
        )

        heal_result = asyncio.run(plugin.heal(result))
        assert heal_result is None
