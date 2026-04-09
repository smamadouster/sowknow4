"""Tests for Guardian HC v2 plugin system integration in core.py."""
from __future__ import annotations

import tempfile
import os
import pytest
import pytest_asyncio

from guardian_hc.plugin import (
    AnalysisContext,
    CheckContext,
    CheckResult,
    GuardianPlugin,
    HealResult,
    Insight,
    Severity,
)
from guardian_hc.core import GuardianHC, GuardianConfig


# ---------------------------------------------------------------------------
# Mock plugins
# ---------------------------------------------------------------------------

class PassingPlugin(GuardianPlugin):
    """Plugin that always passes its check."""
    name = "passing"
    enabled = True

    async def check(self, context: CheckContext) -> list[CheckResult]:
        return [
            CheckResult(
                plugin=self.name,
                module=__name__,
                check_name="always_pass",
                status="pass",
                severity=Severity.INFO,
                summary="All systems go",
            )
        ]

    async def heal(self, result: CheckResult) -> HealResult | None:
        return HealResult(
            plugin=self.name,
            target=result.check_name,
            action="noop_heal",
            success=True,
        )

    async def analyze(self, context: AnalysisContext) -> list[Insight]:
        return [
            Insight(
                plugin=self.name,
                insight_type="anomaly",
                severity=Severity.INFO,
                summary="No anomalies detected",
            )
        ]


class FailingPlugin(GuardianPlugin):
    """Plugin that reports a failing check that needs healing."""
    name = "failing"
    enabled = True

    async def check(self, context: CheckContext) -> list[CheckResult]:
        return [
            CheckResult(
                plugin=self.name,
                module=__name__,
                check_name="disk_check",
                status="fail",
                severity=Severity.HIGH,
                summary="Disk nearly full",
                needs_healing=True,
                heal_hint="free disk space",
            )
        ]

    async def heal(self, result: CheckResult) -> HealResult | None:
        return HealResult(
            plugin=self.name,
            target=result.check_name,
            action="disk_cleanup",
            success=True,
            details="Freed 2GB",
        )


class ExplodingPlugin(GuardianPlugin):
    """Plugin that raises an exception in check() to test error isolation."""
    name = "exploding"
    enabled = True

    async def check(self, context: CheckContext) -> list[CheckResult]:
        raise RuntimeError("Simulated plugin crash")

    async def heal(self, result: CheckResult) -> HealResult | None:
        raise RuntimeError("Simulated heal crash")

    async def analyze(self, context: AnalysisContext) -> list[Insight]:
        raise RuntimeError("Simulated analyze crash")


class DisabledPlugin(GuardianPlugin):
    """Plugin that is disabled and should be skipped."""
    name = "disabled"
    enabled = False

    async def check(self, context: CheckContext) -> list[CheckResult]:
        return [
            CheckResult(
                plugin=self.name,
                module=__name__,
                check_name="should_not_run",
                status="pass",
                severity=Severity.INFO,
                summary="Should not appear",
            )
        ]


# ---------------------------------------------------------------------------
# Fixture: minimal GuardianHC instance (no real services)
# ---------------------------------------------------------------------------

@pytest.fixture
def guardian() -> GuardianHC:
    config = GuardianConfig(
        app_name="TestApp",
        services=[],
        alerts={},
    )
    return GuardianHC(config)


# ---------------------------------------------------------------------------
# Test: register_plugin
# ---------------------------------------------------------------------------

class TestRegisterPlugin:
    def test_register_stores_by_name(self, guardian):
        plugin = PassingPlugin()
        guardian.register_plugin(plugin)
        assert "passing" in guardian._plugins
        assert guardian._plugins["passing"] is plugin

    def test_register_multiple_plugins(self, guardian):
        p1 = PassingPlugin()
        p2 = FailingPlugin()
        guardian.register_plugin(p1)
        guardian.register_plugin(p2)
        assert len(guardian._plugins) == 2
        assert "passing" in guardian._plugins
        assert "failing" in guardian._plugins

    def test_register_overwrites_same_name(self, guardian):
        p1 = PassingPlugin()
        p2 = PassingPlugin()
        guardian.register_plugin(p1)
        guardian.register_plugin(p2)
        # Second registration replaces first (same name)
        assert guardian._plugins["passing"] is p2

    def test_initial_plugins_dict_empty(self, guardian):
        assert guardian._plugins == {}


# ---------------------------------------------------------------------------
# Test: run_plugin_checks
# ---------------------------------------------------------------------------

class TestRunPluginChecks:
    @pytest.mark.asyncio
    async def test_check_calls_enabled_plugin(self, guardian):
        guardian.register_plugin(PassingPlugin())
        results = await guardian.run_plugin_checks("standard")
        assert len(results) == 1
        assert results[0].plugin == "passing"
        assert results[0].status == "pass"

    @pytest.mark.asyncio
    async def test_check_returns_results_from_multiple_plugins(self, guardian):
        guardian.register_plugin(PassingPlugin())
        guardian.register_plugin(FailingPlugin())
        results = await guardian.run_plugin_checks("standard")
        assert len(results) == 2
        plugin_names = {r.plugin for r in results}
        assert "passing" in plugin_names
        assert "failing" in plugin_names

    @pytest.mark.asyncio
    async def test_check_skips_disabled_plugins(self, guardian):
        guardian.register_plugin(DisabledPlugin())
        results = await guardian.run_plugin_checks("standard")
        assert results == []

    @pytest.mark.asyncio
    async def test_check_skips_disabled_but_runs_enabled(self, guardian):
        guardian.register_plugin(DisabledPlugin())
        guardian.register_plugin(PassingPlugin())
        results = await guardian.run_plugin_checks("standard")
        assert len(results) == 1
        assert results[0].plugin == "passing"

    @pytest.mark.asyncio
    async def test_check_returns_empty_with_no_plugins(self, guardian):
        results = await guardian.run_plugin_checks("standard")
        assert results == []

    @pytest.mark.asyncio
    async def test_check_passes_correct_level(self, guardian):
        """Verify the patrol_level is forwarded to the plugin."""
        received_levels = []

        class LevelCapture(GuardianPlugin):
            name = "level_capture"
            enabled = True

            async def check(self_, context: CheckContext) -> list[CheckResult]:
                received_levels.append(context.patrol_level)
                return []

        guardian.register_plugin(LevelCapture())
        await guardian.run_plugin_checks("deep")
        assert received_levels == ["deep"]

    @pytest.mark.asyncio
    async def test_check_passes_services_from_config(self, guardian):
        """Verify services list from guardian config is forwarded."""
        from guardian_hc.core import ServiceConfig
        svc = ServiceConfig(name="web", container="web-container")
        guardian.config.services = [svc]

        received_services = []

        class ServiceCapture(GuardianPlugin):
            name = "svc_capture"
            enabled = True

            async def check(self_, context: CheckContext) -> list[CheckResult]:
                received_services.extend(context.services)
                return []

        guardian.register_plugin(ServiceCapture())
        await guardian.run_plugin_checks("standard")
        assert len(received_services) == 1
        assert received_services[0].name == "web"


# ---------------------------------------------------------------------------
# Test: exception isolation in run_plugin_checks
# ---------------------------------------------------------------------------

class TestPluginCheckExceptionIsolation:
    @pytest.mark.asyncio
    async def test_exception_does_not_crash_cycle(self, guardian):
        """An exception in one plugin must not prevent other plugins from running."""
        guardian.register_plugin(ExplodingPlugin())
        guardian.register_plugin(PassingPlugin())
        # Should not raise
        results = await guardian.run_plugin_checks("standard")
        # PassingPlugin still contributes its result
        assert any(r.plugin == "passing" for r in results)

    @pytest.mark.asyncio
    async def test_exception_plugin_result_excluded(self, guardian):
        """Crashed plugin results are excluded (not partially added)."""
        guardian.register_plugin(ExplodingPlugin())
        results = await guardian.run_plugin_checks("standard")
        # No result from exploding plugin
        assert not any(r.plugin == "exploding" for r in results)

    @pytest.mark.asyncio
    async def test_multiple_crashes_still_returns_passing(self, guardian):
        class Explode2(GuardianPlugin):
            name = "explode2"
            enabled = True
            async def check(self, context: CheckContext) -> list[CheckResult]:
                raise ValueError("Another crash")

        guardian.register_plugin(ExplodingPlugin())
        guardian.register_plugin(Explode2())
        guardian.register_plugin(PassingPlugin())
        results = await guardian.run_plugin_checks("standard")
        assert len(results) == 1
        assert results[0].plugin == "passing"


# ---------------------------------------------------------------------------
# Test: run_plugin_heals
# ---------------------------------------------------------------------------

class TestRunPluginHeals:
    @pytest.mark.asyncio
    async def test_heal_called_for_needs_healing_result(self, guardian):
        guardian.register_plugin(FailingPlugin())
        check_results = await guardian.run_plugin_checks("standard")
        heal_results = await guardian.run_plugin_heals(check_results)
        assert len(heal_results) == 1
        assert heal_results[0].plugin == "failing"
        assert heal_results[0].success is True

    @pytest.mark.asyncio
    async def test_heal_not_called_when_no_healing_needed(self, guardian):
        guardian.register_plugin(PassingPlugin())
        check_results = await guardian.run_plugin_checks("standard")
        heal_results = await guardian.run_plugin_heals(check_results)
        assert heal_results == []

    @pytest.mark.asyncio
    async def test_heal_logs_action(self, guardian):
        guardian.register_plugin(FailingPlugin())
        check_results = await guardian.run_plugin_checks("standard")
        history_before = len(guardian._history)
        await guardian.run_plugin_heals(check_results)
        assert len(guardian._history) > history_before

    @pytest.mark.asyncio
    async def test_heal_skips_if_plugin_not_found(self, guardian):
        """A CheckResult referencing an unregistered plugin is skipped safely."""
        orphan_result = CheckResult(
            plugin="ghost_plugin",
            module=__name__,
            check_name="orphan_check",
            status="fail",
            severity=Severity.HIGH,
            summary="Ghost check failed",
            needs_healing=True,
        )
        # Should not raise
        heal_results = await guardian.run_plugin_heals([orphan_result])
        assert heal_results == []

    @pytest.mark.asyncio
    async def test_heal_exception_does_not_crash(self, guardian):
        """Exception in heal() is caught and does not crash the cycle."""
        # Register exploding plugin, then manually create a check result for it
        guardian.register_plugin(ExplodingPlugin())

        failing_result = CheckResult(
            plugin="exploding",
            module=__name__,
            check_name="boom",
            status="fail",
            severity=Severity.CRITICAL,
            summary="Boom",
            needs_healing=True,
        )
        # Should not raise
        heal_results = await guardian.run_plugin_heals([failing_result])
        # Failed heal is excluded
        assert heal_results == []

    @pytest.mark.asyncio
    async def test_heal_returns_none_excluded(self, guardian):
        """HealResult=None from plugin.heal() is excluded from results."""

        class NoneHealPlugin(GuardianPlugin):
            name = "none_heal"
            enabled = True

            async def check(self, context: CheckContext) -> list[CheckResult]:
                return [CheckResult(
                    plugin=self.name, module=__name__, check_name="x",
                    status="fail", severity=Severity.WARNING, summary="fail",
                    needs_healing=True,
                )]

            async def heal(self, result: CheckResult) -> HealResult | None:
                return None

        guardian.register_plugin(NoneHealPlugin())
        check_results = await guardian.run_plugin_checks("standard")
        heal_results = await guardian.run_plugin_heals(check_results)
        assert heal_results == []


# ---------------------------------------------------------------------------
# Test: run_plugin_analysis
# ---------------------------------------------------------------------------

class TestRunPluginAnalysis:
    @pytest.mark.asyncio
    async def test_analyze_called_on_enabled_plugin(self, guardian):
        guardian.register_plugin(PassingPlugin())
        insights = await guardian.run_plugin_analysis()
        assert len(insights) == 1
        assert insights[0].plugin == "passing"

    @pytest.mark.asyncio
    async def test_analyze_skips_disabled_plugin(self, guardian):
        guardian.register_plugin(DisabledPlugin())
        insights = await guardian.run_plugin_analysis()
        assert insights == []

    @pytest.mark.asyncio
    async def test_analyze_exception_does_not_crash(self, guardian):
        guardian.register_plugin(ExplodingPlugin())
        guardian.register_plugin(PassingPlugin())
        insights = await guardian.run_plugin_analysis()
        assert any(i.plugin == "passing" for i in insights)
        assert not any(i.plugin == "exploding" for i in insights)

    @pytest.mark.asyncio
    async def test_analyze_returns_empty_with_no_plugins(self, guardian):
        insights = await guardian.run_plugin_analysis()
        assert insights == []


# ---------------------------------------------------------------------------
# Test: from_config with v2 YAML
# ---------------------------------------------------------------------------

class TestFromConfigV2:
    def _write_v2_yaml(self, path: str):
        content = """
version: "2.0"
app_name: TestV2App
compose_file: ./docker-compose.yml
services: []
alerts: {}
patrols: {}
disk: {}
ssl: {}
ollama: {}
vps_load: {}
network: {}
celery: {}
plugins: {}
modules: []
database: {}
daily_report: {}
dashboard_port: 9090
agents:
  - agent_id: agent-001
    name: infrastructure
    role: infra_monitor
    plugins: []
"""
        with open(path, "w") as f:
            f.write(content)

    def _write_v1_yaml(self, path: str):
        content = """
app:
  name: TestV1App
  compose_file: ./docker-compose.yml
services: []
alerts: {}
patrols: {}
disk: {}
ssl: {}
ollama: {}
vps_load: {}
network: {}
celery: {}
dashboard:
  port: 9090
"""
        with open(path, "w") as f:
            f.write(content)

    def test_from_config_v2_sets_v2_config(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            path = f.name
        try:
            self._write_v2_yaml(path)
            instance = GuardianHC.from_config(path)
            assert instance._v2_config is not None
            assert instance._v2_config.version == "2.0"
            assert instance._v2_config.app_name == "TestV2App"
        finally:
            os.unlink(path)

    def test_from_config_v2_creates_agent_registry(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            path = f.name
        try:
            self._write_v2_yaml(path)
            instance = GuardianHC.from_config(path)
            assert instance._agent_registry is not None
            agent = instance._agent_registry.get("agent-001")
            assert agent is not None
            assert agent.name == "infrastructure"
        finally:
            os.unlink(path)

    def test_from_config_v1_leaves_v2_attrs_none(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            path = f.name
        try:
            self._write_v1_yaml(path)
            instance = GuardianHC.from_config(path)
            assert instance._v2_config is None
            assert instance._agent_registry is None
        finally:
            os.unlink(path)

    def test_from_config_v2_initial_plugins_empty(self):
        """Plugin registry starts empty even for v2 configs."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            path = f.name
        try:
            self._write_v2_yaml(path)
            instance = GuardianHC.from_config(path)
            assert instance._plugins == {}
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Test: v2 attrs initialized on plain GuardianHC instances
# ---------------------------------------------------------------------------

class TestV2AttrsInit:
    def test_plugins_dict_initialized(self, guardian):
        assert hasattr(guardian, "_plugins")
        assert isinstance(guardian._plugins, dict)

    def test_metrics_db_initialized_none(self, guardian):
        assert hasattr(guardian, "_metrics_db")
        assert guardian._metrics_db is None

    def test_agent_registry_initialized_none(self, guardian):
        assert hasattr(guardian, "_agent_registry")
        assert guardian._agent_registry is None

    def test_v2_config_initialized_none(self, guardian):
        assert hasattr(guardian, "_v2_config")
        assert guardian._v2_config is None
