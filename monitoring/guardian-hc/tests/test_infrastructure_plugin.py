"""Tests for InfrastructurePlugin — wraps all v1 checkers/healers in the v2 plugin interface."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from guardian_hc.config import ServiceConfig
from guardian_hc.plugin import CheckContext, CheckResult, HealResult, Severity


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_service(
    name="backend",
    container="sowknow4-backend",
    http_url="http://localhost:8000/health",
    tcp_host=None,
    tcp_port=None,
) -> ServiceConfig:
    hc: dict = {}
    if http_url:
        hc["http"] = {"url": http_url, "timeout": 5}
    if tcp_host and tcp_port:
        hc["tcp"] = {"host": tcp_host, "port": tcp_port, "timeout": 3}
    return ServiceConfig(name=name, container=container, health_check=hc)


def _make_config(services=None, **overrides) -> dict:
    base = {
        "services": services or [_make_service()],
        "disk": {"warning_threshold": 75, "critical_threshold": 85},
        "ssl": {"domains": ["example.com"], "critical_days": 3},
        "network": {"probe_pairs": []},
        "celery": {"redis_host": "redis", "redis_port": 6379},
        "ollama": {"url": "http://localhost:11434", "enabled": True},
        "vps_load": {"load_threshold": 6.0},
        "compose_file": "./docker-compose.yml",
    }
    base.update(overrides)
    return base


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Import guard
# ---------------------------------------------------------------------------

class TestInfrastructurePluginImport:
    def test_importable(self):
        from guardian_hc.plugins.infrastructure import InfrastructurePlugin  # noqa: F401


# ---------------------------------------------------------------------------
# Identity / metadata
# ---------------------------------------------------------------------------

class TestInfrastructurePluginIdentity:
    def setup_method(self):
        from guardian_hc.plugins.infrastructure import InfrastructurePlugin
        self.Plugin = InfrastructurePlugin

    def test_name(self):
        p = self.Plugin(_make_config())
        assert p.name == "infrastructure"

    def test_enabled_default(self):
        p = self.Plugin(_make_config())
        assert p.enabled is True

    def test_inherits_guardian_plugin(self):
        from guardian_hc.plugin import GuardianPlugin
        p = self.Plugin(_make_config())
        assert isinstance(p, GuardianPlugin)


# ---------------------------------------------------------------------------
# check() — critical patrol level
# ---------------------------------------------------------------------------

class TestCheckCritical:
    def setup_method(self):
        from guardian_hc.plugins.infrastructure import InfrastructurePlugin
        self.Plugin = InfrastructurePlugin

    def _ctx(self, level="critical", services=None):
        cfg = _make_config(services=services)
        svc_list = cfg["services"]
        return CheckContext(patrol_level=level, config=cfg, services=svc_list)

    @patch("guardian_hc.plugins.infrastructure.ContainerChecker")
    @patch("guardian_hc.plugins.infrastructure.HttpHealthChecker")
    def test_critical_returns_check_results(self, MockHttp, MockContainer):
        MockContainer.return_value.check = AsyncMock(return_value={"status": "running", "container": "sowknow4-backend"})
        MockHttp.check = AsyncMock(return_value={"healthy": True, "status_code": 200, "url": "http://localhost:8000/health"})

        p = self.Plugin(_make_config())
        ctx = self._ctx("critical")
        results = _run(p.check(ctx))

        assert isinstance(results, list)
        assert all(isinstance(r, CheckResult) for r in results)

    @patch("guardian_hc.plugins.infrastructure.ContainerChecker")
    @patch("guardian_hc.plugins.infrastructure.HttpHealthChecker")
    def test_critical_healthy_container_passes(self, MockHttp, MockContainer):
        MockContainer.return_value.check = AsyncMock(return_value={"status": "running", "container": "sowknow4-backend"})
        MockHttp.check = AsyncMock(return_value={"healthy": True, "status_code": 200, "url": "http://localhost:8000/health"})

        p = self.Plugin(_make_config())
        ctx = self._ctx("critical")
        results = _run(p.check(ctx))

        container_results = [r for r in results if "container" in r.check_name]
        assert len(container_results) >= 1
        assert all(r.status == "pass" for r in container_results)
        assert all(r.needs_healing is False for r in container_results)

    @patch("guardian_hc.plugins.infrastructure.ContainerChecker")
    @patch("guardian_hc.plugins.infrastructure.HttpHealthChecker")
    def test_critical_unhealthy_container_needs_healing(self, MockHttp, MockContainer):
        MockContainer.return_value.check = AsyncMock(return_value={"status": "exited", "container": "sowknow4-backend"})
        MockHttp.check = AsyncMock(return_value={"healthy": False, "status_code": 503, "url": "http://localhost:8000/health"})

        p = self.Plugin(_make_config())
        ctx = self._ctx("critical")
        results = _run(p.check(ctx))

        container_results = [r for r in results if "container" in r.check_name]
        assert len(container_results) >= 1
        failing = [r for r in container_results if r.needs_healing]
        assert len(failing) >= 1

    @patch("guardian_hc.plugins.infrastructure.ContainerChecker")
    @patch("guardian_hc.plugins.infrastructure.HttpHealthChecker")
    def test_critical_fail_heal_hint_is_restart(self, MockHttp, MockContainer):
        MockContainer.return_value.check = AsyncMock(return_value={"status": "exited", "container": "sowknow4-backend"})
        MockHttp.check = AsyncMock(return_value={"healthy": True, "status_code": 200, "url": ""})

        p = self.Plugin(_make_config())
        ctx = self._ctx("critical")
        results = _run(p.check(ctx))

        failing = [r for r in results if r.needs_healing and r.heal_hint and r.heal_hint.startswith("restart:")]
        assert len(failing) >= 1

    @patch("guardian_hc.plugins.infrastructure.ContainerChecker")
    @patch("guardian_hc.plugins.infrastructure.HttpHealthChecker")
    def test_critical_result_module_is_infrastructure(self, MockHttp, MockContainer):
        MockContainer.return_value.check = AsyncMock(return_value={"status": "running", "container": "sowknow4-backend"})
        MockHttp.check = AsyncMock(return_value={"healthy": True, "status_code": 200, "url": ""})

        p = self.Plugin(_make_config())
        ctx = self._ctx("critical")
        results = _run(p.check(ctx))

        assert all(r.module == "Infrastructure" for r in results)

    @patch("guardian_hc.plugins.infrastructure.ContainerChecker")
    @patch("guardian_hc.plugins.infrastructure.HttpHealthChecker")
    def test_critical_result_plugin_is_infrastructure(self, MockHttp, MockContainer):
        MockContainer.return_value.check = AsyncMock(return_value={"status": "running", "container": "sowknow4-backend"})
        MockHttp.check = AsyncMock(return_value={"healthy": True, "status_code": 200, "url": ""})

        p = self.Plugin(_make_config())
        ctx = self._ctx("critical")
        results = _run(p.check(ctx))

        assert all(r.plugin == "infrastructure" for r in results)


# ---------------------------------------------------------------------------
# check() — standard patrol level (adds disk/memory/network/celery/vps_load)
# ---------------------------------------------------------------------------

class TestCheckStandard:
    def setup_method(self):
        from guardian_hc.plugins.infrastructure import InfrastructurePlugin
        self.Plugin = InfrastructurePlugin

    def _ctx(self, services=None):
        cfg = _make_config(services=services)
        return CheckContext(patrol_level="standard", config=cfg, services=cfg["services"])

    @patch("guardian_hc.plugins.infrastructure.ContainerChecker")
    @patch("guardian_hc.plugins.infrastructure.HttpHealthChecker")
    @patch("guardian_hc.plugins.infrastructure.DiskChecker")
    @patch("guardian_hc.plugins.infrastructure.MemoryChecker")
    @patch("guardian_hc.plugins.infrastructure.NetworkHealthChecker")
    @patch("guardian_hc.plugins.infrastructure.CeleryHealthChecker")
    @patch("guardian_hc.plugins.infrastructure.VpsLoadChecker")
    def test_standard_includes_disk_check(
        self, MockVps, MockCelery, MockNetwork, MockMemory, MockDisk, MockHttp, MockContainer
    ):
        MockContainer.return_value.check = AsyncMock(return_value={"status": "running", "container": "sowknow4-backend"})
        MockHttp.check = AsyncMock(return_value={"healthy": True, "status_code": 200, "url": ""})
        MockDisk.return_value.check = AsyncMock(return_value={"usage_pct": 50, "severity": "ok", "needs_healing": False})
        MockMemory.return_value.check = AsyncMock(return_value=[{"container": "sowknow4-backend", "mem_pct": 40.0, "needs_healing": False}])
        MockNetwork.return_value.check = AsyncMock(return_value={"stale_bridges": [], "probe_results": [], "needs_healing": False})
        MockCelery.return_value.check = AsyncMock(return_value=[{"check": "celery-worker", "container": "sowknow4-celery-worker", "needs_healing": False}])
        MockVps.return_value.check = AsyncMock(return_value=[{"type": "load_average", "load1": 1.0, "needs_healing": False}])

        p = self.Plugin(_make_config())
        results = _run(p.check(self._ctx()))

        check_names = [r.check_name for r in results]
        assert any("disk" in n for n in check_names)
        assert any("memory" in n or "mem" in n for n in check_names)
        assert any("network" in n for n in check_names)
        assert any("celery" in n for n in check_names)
        assert any("vps" in n or "load" in n for n in check_names)

    @patch("guardian_hc.plugins.infrastructure.ContainerChecker")
    @patch("guardian_hc.plugins.infrastructure.HttpHealthChecker")
    @patch("guardian_hc.plugins.infrastructure.DiskChecker")
    @patch("guardian_hc.plugins.infrastructure.MemoryChecker")
    @patch("guardian_hc.plugins.infrastructure.NetworkHealthChecker")
    @patch("guardian_hc.plugins.infrastructure.CeleryHealthChecker")
    @patch("guardian_hc.plugins.infrastructure.VpsLoadChecker")
    def test_standard_disk_fail_needs_healing(
        self, MockVps, MockCelery, MockNetwork, MockMemory, MockDisk, MockHttp, MockContainer
    ):
        MockContainer.return_value.check = AsyncMock(return_value={"status": "running", "container": "sowknow4-backend"})
        MockHttp.check = AsyncMock(return_value={"healthy": True, "status_code": 200, "url": ""})
        MockDisk.return_value.check = AsyncMock(return_value={"usage_pct": 90, "severity": "critical", "needs_healing": True})
        MockMemory.return_value.check = AsyncMock(return_value=[{"container": "sowknow4-backend", "mem_pct": 40.0, "needs_healing": False}])
        MockNetwork.return_value.check = AsyncMock(return_value={"stale_bridges": [], "probe_results": [], "needs_healing": False})
        MockCelery.return_value.check = AsyncMock(return_value=[{"check": "celery-worker", "container": "sowknow4-celery-worker", "needs_healing": False}])
        MockVps.return_value.check = AsyncMock(return_value=[{"type": "load_average", "load1": 1.0, "needs_healing": False}])

        p = self.Plugin(_make_config())
        results = _run(p.check(self._ctx()))

        disk_results = [r for r in results if "disk" in r.check_name]
        assert len(disk_results) >= 1
        assert disk_results[0].needs_healing is True
        assert disk_results[0].heal_hint == "disk_cleanup"

    @patch("guardian_hc.plugins.infrastructure.ContainerChecker")
    @patch("guardian_hc.plugins.infrastructure.HttpHealthChecker")
    @patch("guardian_hc.plugins.infrastructure.DiskChecker")
    @patch("guardian_hc.plugins.infrastructure.MemoryChecker")
    @patch("guardian_hc.plugins.infrastructure.NetworkHealthChecker")
    @patch("guardian_hc.plugins.infrastructure.CeleryHealthChecker")
    @patch("guardian_hc.plugins.infrastructure.VpsLoadChecker")
    def test_standard_network_fail_needs_healing(
        self, MockVps, MockCelery, MockNetwork, MockMemory, MockDisk, MockHttp, MockContainer
    ):
        MockContainer.return_value.check = AsyncMock(return_value={"status": "running", "container": "sowknow4-backend"})
        MockHttp.check = AsyncMock(return_value={"healthy": True, "status_code": 200, "url": ""})
        MockDisk.return_value.check = AsyncMock(return_value={"usage_pct": 50, "severity": "ok", "needs_healing": False})
        MockMemory.return_value.check = AsyncMock(return_value=[{"container": "sowknow4-backend", "mem_pct": 40.0, "needs_healing": False}])
        MockNetwork.return_value.check = AsyncMock(return_value={
            "stale_bridges": [{"bridge": "br-abc123456789", "rule_count": 3}],
            "probe_results": [],
            "needs_healing": True,
        })
        MockCelery.return_value.check = AsyncMock(return_value=[{"check": "celery-worker", "container": "sowknow4-celery-worker", "needs_healing": False}])
        MockVps.return_value.check = AsyncMock(return_value=[{"type": "load_average", "load1": 1.0, "needs_healing": False}])

        p = self.Plugin(_make_config())
        results = _run(p.check(self._ctx()))

        network_results = [r for r in results if "network" in r.check_name]
        assert len(network_results) >= 1
        assert network_results[0].needs_healing is True
        assert network_results[0].heal_hint == "network_heal"


# ---------------------------------------------------------------------------
# check() — deep patrol level (adds ssl/config_drift)
# ---------------------------------------------------------------------------

class TestCheckDeep:
    def setup_method(self):
        from guardian_hc.plugins.infrastructure import InfrastructurePlugin
        self.Plugin = InfrastructurePlugin

    def _all_mocks_healthy(self, MockVps, MockCelery, MockNetwork, MockMemory, MockDisk, MockHttp, MockContainer, MockSsl=None, MockDrift=None):
        MockContainer.return_value.check = AsyncMock(return_value={"status": "running", "container": "sowknow4-backend"})
        MockHttp.check = AsyncMock(return_value={"healthy": True, "status_code": 200, "url": ""})
        MockDisk.return_value.check = AsyncMock(return_value={"usage_pct": 50, "severity": "ok", "needs_healing": False})
        MockMemory.return_value.check = AsyncMock(return_value=[{"container": "sowknow4-backend", "mem_pct": 40.0, "needs_healing": False}])
        MockNetwork.return_value.check = AsyncMock(return_value={"stale_bridges": [], "probe_results": [], "needs_healing": False})
        MockCelery.return_value.check = AsyncMock(return_value=[{"check": "celery-worker", "container": "sowknow4-celery-worker", "needs_healing": False}])
        MockVps.return_value.check = AsyncMock(return_value=[{"type": "load_average", "load1": 1.0, "needs_healing": False}])
        if MockSsl is not None:
            MockSsl.return_value.check = AsyncMock(return_value=[{"domain": "example.com", "days_left": 30, "needs_healing": False}])
        if MockDrift is not None:
            MockDrift.return_value.check = AsyncMock(return_value={"drifts": [], "count": 0, "status": "ok"})

    @patch("guardian_hc.plugins.infrastructure.ContainerChecker")
    @patch("guardian_hc.plugins.infrastructure.HttpHealthChecker")
    @patch("guardian_hc.plugins.infrastructure.DiskChecker")
    @patch("guardian_hc.plugins.infrastructure.MemoryChecker")
    @patch("guardian_hc.plugins.infrastructure.NetworkHealthChecker")
    @patch("guardian_hc.plugins.infrastructure.CeleryHealthChecker")
    @patch("guardian_hc.plugins.infrastructure.VpsLoadChecker")
    @patch("guardian_hc.plugins.infrastructure.SslChecker")
    @patch("guardian_hc.plugins.infrastructure.ConfigDriftChecker")
    def test_deep_includes_ssl_and_drift(
        self, MockDrift, MockSsl, MockVps, MockCelery, MockNetwork, MockMemory, MockDisk, MockHttp, MockContainer
    ):
        self._all_mocks_healthy(MockVps, MockCelery, MockNetwork, MockMemory, MockDisk, MockHttp, MockContainer, MockSsl, MockDrift)

        cfg = _make_config()
        p = self.Plugin(cfg)
        ctx = CheckContext(patrol_level="deep", config=cfg, services=cfg["services"])
        results = _run(p.check(ctx))

        check_names = [r.check_name for r in results]
        assert any("ssl" in n for n in check_names)
        assert any("drift" in n or "config" in n for n in check_names)

    @patch("guardian_hc.plugins.infrastructure.ContainerChecker")
    @patch("guardian_hc.plugins.infrastructure.HttpHealthChecker")
    @patch("guardian_hc.plugins.infrastructure.DiskChecker")
    @patch("guardian_hc.plugins.infrastructure.MemoryChecker")
    @patch("guardian_hc.plugins.infrastructure.NetworkHealthChecker")
    @patch("guardian_hc.plugins.infrastructure.CeleryHealthChecker")
    @patch("guardian_hc.plugins.infrastructure.VpsLoadChecker")
    @patch("guardian_hc.plugins.infrastructure.SslChecker")
    @patch("guardian_hc.plugins.infrastructure.ConfigDriftChecker")
    def test_deep_ssl_expiring_needs_healing(
        self, MockDrift, MockSsl, MockVps, MockCelery, MockNetwork, MockMemory, MockDisk, MockHttp, MockContainer
    ):
        self._all_mocks_healthy(MockVps, MockCelery, MockNetwork, MockMemory, MockDisk, MockHttp, MockContainer, MockSsl, MockDrift)
        MockSsl.return_value.check = AsyncMock(return_value=[{"domain": "example.com", "days_left": 2, "needs_healing": True}])

        cfg = _make_config()
        p = self.Plugin(cfg)
        ctx = CheckContext(patrol_level="deep", config=cfg, services=cfg["services"])
        results = _run(p.check(ctx))

        ssl_results = [r for r in results if "ssl" in r.check_name]
        assert len(ssl_results) >= 1
        failing = [r for r in ssl_results if r.needs_healing]
        assert len(failing) >= 1
        assert failing[0].heal_hint and failing[0].heal_hint.startswith("ssl_renew:")


# ---------------------------------------------------------------------------
# check() — no ssl/drift on standard patrol
# ---------------------------------------------------------------------------

class TestCheckStandardExclusions:
    def setup_method(self):
        from guardian_hc.plugins.infrastructure import InfrastructurePlugin
        self.Plugin = InfrastructurePlugin

    @patch("guardian_hc.plugins.infrastructure.ContainerChecker")
    @patch("guardian_hc.plugins.infrastructure.HttpHealthChecker")
    @patch("guardian_hc.plugins.infrastructure.DiskChecker")
    @patch("guardian_hc.plugins.infrastructure.MemoryChecker")
    @patch("guardian_hc.plugins.infrastructure.NetworkHealthChecker")
    @patch("guardian_hc.plugins.infrastructure.CeleryHealthChecker")
    @patch("guardian_hc.plugins.infrastructure.VpsLoadChecker")
    @patch("guardian_hc.plugins.infrastructure.SslChecker")
    @patch("guardian_hc.plugins.infrastructure.ConfigDriftChecker")
    def test_standard_excludes_ssl_and_drift(
        self, MockDrift, MockSsl, MockVps, MockCelery, MockNetwork, MockMemory, MockDisk, MockHttp, MockContainer
    ):
        MockContainer.return_value.check = AsyncMock(return_value={"status": "running", "container": "sowknow4-backend"})
        MockHttp.check = AsyncMock(return_value={"healthy": True, "status_code": 200, "url": ""})
        MockDisk.return_value.check = AsyncMock(return_value={"usage_pct": 50, "severity": "ok", "needs_healing": False})
        MockMemory.return_value.check = AsyncMock(return_value=[{"container": "sowknow4-backend", "mem_pct": 40.0, "needs_healing": False}])
        MockNetwork.return_value.check = AsyncMock(return_value={"stale_bridges": [], "probe_results": [], "needs_healing": False})
        MockCelery.return_value.check = AsyncMock(return_value=[{"check": "celery-worker", "needs_healing": False}])
        MockVps.return_value.check = AsyncMock(return_value=[{"type": "load_average", "load1": 1.0, "needs_healing": False}])
        MockSsl.return_value.check = AsyncMock(return_value=[])
        MockDrift.return_value.check = AsyncMock(return_value={"drifts": [], "count": 0, "status": "ok"})

        cfg = _make_config()
        p = self.Plugin(cfg)
        ctx = CheckContext(patrol_level="standard", config=cfg, services=cfg["services"])
        results = _run(p.check(ctx))

        check_names = [r.check_name for r in results]
        assert not any("ssl" in n for n in check_names)
        assert not any("drift" in n or "config_drift" in n for n in check_names)


# ---------------------------------------------------------------------------
# heal() dispatch
# ---------------------------------------------------------------------------

class TestHealDispatch:
    def setup_method(self):
        from guardian_hc.plugins.infrastructure import InfrastructurePlugin
        self.Plugin = InfrastructurePlugin

    def _make_result(self, heal_hint, check_name="container_backend", status="fail") -> CheckResult:
        return CheckResult(
            plugin="infrastructure",
            module="Infrastructure",
            check_name=check_name,
            status=status,
            severity=Severity.CRITICAL,
            summary="Test fail",
            needs_healing=True,
            heal_hint=heal_hint,
        )

    @patch("guardian_hc.plugins.infrastructure.ContainerHealer")
    def test_heal_restart_dispatches_to_container_healer(self, MockHealer):
        MockHealer.return_value.heal = AsyncMock(return_value={"healed": True, "action": "restarted"})
        p = self.Plugin(_make_config())
        result = _run(p.heal(self._make_result("restart:sowknow4-backend")))
        assert result is not None
        assert isinstance(result, HealResult)
        assert result.success is True
        MockHealer.return_value.heal.assert_called_once()

    @patch("guardian_hc.plugins.infrastructure.DiskHealer")
    def test_heal_disk_cleanup_dispatches_to_disk_healer(self, MockHealer):
        MockHealer.return_value.heal = AsyncMock(return_value={"healed": True, "actions": ["Docker pruned"]})
        p = self.Plugin(_make_config())
        result = _run(p.heal(self._make_result("disk_cleanup")))
        assert result is not None
        assert isinstance(result, HealResult)
        assert result.success is True
        MockHealer.return_value.heal.assert_called_once()

    @patch("guardian_hc.plugins.infrastructure.NetworkHealer")
    def test_heal_network_dispatches_to_network_healer(self, MockHealer):
        MockHealer.return_value.heal = AsyncMock(return_value={"healed": True, "actions": ["nftables flushed"]})
        p = self.Plugin(_make_config())
        result = _run(p.heal(self._make_result("network_heal")))
        assert result is not None
        assert isinstance(result, HealResult)
        assert result.success is True
        MockHealer.return_value.heal.assert_called_once()

    @patch("guardian_hc.plugins.infrastructure.SslHealer")
    def test_heal_ssl_renew_dispatches_to_ssl_healer(self, MockHealer):
        MockHealer.return_value.heal = AsyncMock(return_value={"healed": True, "action": "certbot renew + nginx reload"})
        p = self.Plugin(_make_config())
        result = _run(p.heal(self._make_result("ssl_renew:example.com")))
        assert result is not None
        assert isinstance(result, HealResult)
        assert result.success is True
        # Should pass domain to healer
        call_args = MockHealer.return_value.heal.call_args
        assert "example.com" in str(call_args)

    def test_heal_unknown_hint_returns_none(self):
        p = self.Plugin(_make_config())
        result = _run(p.heal(self._make_result("unknown_action")))
        assert result is None

    def test_heal_none_hint_returns_none(self):
        result_no_hint = CheckResult(
            plugin="infrastructure",
            module="Infrastructure",
            check_name="x",
            status="fail",
            severity=Severity.WARNING,
            summary="whatever",
            needs_healing=False,
            heal_hint=None,
        )
        p = self.Plugin(_make_config())
        result = _run(p.heal(result_no_hint))
        assert result is None

    @patch("guardian_hc.plugins.infrastructure.ContainerHealer")
    def test_heal_restart_healer_fail_returns_heal_result_with_success_false(self, MockHealer):
        MockHealer.return_value.heal = AsyncMock(return_value={"healed": False, "error": "Container not found"})
        p = self.Plugin(_make_config())
        result = _run(p.heal(self._make_result("restart:sowknow4-missing")))
        assert result is not None
        assert isinstance(result, HealResult)
        assert result.success is False


# ---------------------------------------------------------------------------
# TCP health check integration
# ---------------------------------------------------------------------------

class TestTcpHealthCheck:
    def setup_method(self):
        from guardian_hc.plugins.infrastructure import InfrastructurePlugin
        self.Plugin = InfrastructurePlugin

    @patch("guardian_hc.plugins.infrastructure.ContainerChecker")
    @patch("guardian_hc.plugins.infrastructure.TcpHealthChecker")
    def test_tcp_service_checked_when_configured(self, MockTcp, MockContainer):
        MockContainer.return_value.check = AsyncMock(return_value={"status": "running", "container": "sowknow4-postgres"})
        MockTcp.check = AsyncMock(return_value={"healthy": True, "host": "localhost", "port": 5432})

        svc = ServiceConfig(
            name="postgres",
            container="sowknow4-postgres",
            health_check={"tcp": {"host": "localhost", "port": 5432, "timeout": 3}},
        )
        cfg = _make_config(services=[svc])
        p = self.Plugin(cfg)
        ctx = CheckContext(patrol_level="critical", config=cfg, services=cfg["services"])
        results = _run(p.check(ctx))

        tcp_results = [r for r in results if "tcp" in r.check_name]
        assert len(tcp_results) >= 1

    @patch("guardian_hc.plugins.infrastructure.ContainerChecker")
    @patch("guardian_hc.plugins.infrastructure.TcpHealthChecker")
    def test_tcp_unhealthy_returns_fail(self, MockTcp, MockContainer):
        MockContainer.return_value.check = AsyncMock(return_value={"status": "running", "container": "sowknow4-postgres"})
        MockTcp.check = AsyncMock(return_value={"healthy": False, "host": "localhost", "port": 5432, "error": "refused"})

        svc = ServiceConfig(
            name="postgres",
            container="sowknow4-postgres",
            health_check={"tcp": {"host": "localhost", "port": 5432, "timeout": 3}},
        )
        cfg = _make_config(services=[svc])
        p = self.Plugin(cfg)
        ctx = CheckContext(patrol_level="critical", config=cfg, services=cfg["services"])
        results = _run(p.check(ctx))

        tcp_results = [r for r in results if "tcp" in r.check_name]
        assert len(tcp_results) >= 1
        assert tcp_results[0].status in ("fail", "warning", "degraded")


# ---------------------------------------------------------------------------
# Multiple services
# ---------------------------------------------------------------------------

class TestMultipleServices:
    def setup_method(self):
        from guardian_hc.plugins.infrastructure import InfrastructurePlugin
        self.Plugin = InfrastructurePlugin

    @patch("guardian_hc.plugins.infrastructure.ContainerChecker")
    @patch("guardian_hc.plugins.infrastructure.HttpHealthChecker")
    def test_multiple_services_all_checked(self, MockHttp, MockContainer):
        MockContainer.return_value.check = AsyncMock(return_value={"status": "running", "container": "any"})
        MockHttp.check = AsyncMock(return_value={"healthy": True, "status_code": 200, "url": ""})

        services = [
            _make_service("backend", "sowknow4-backend", "http://localhost:8000/health"),
            _make_service("frontend", "sowknow4-frontend", "http://localhost:3000/"),
        ]
        cfg = _make_config(services=services)
        p = self.Plugin(cfg)
        ctx = CheckContext(patrol_level="critical", config=cfg, services=cfg["services"])
        results = _run(p.check(ctx))

        # Should have container checks for both services
        container_results = [r for r in results if "container" in r.check_name]
        assert len(container_results) >= 2
