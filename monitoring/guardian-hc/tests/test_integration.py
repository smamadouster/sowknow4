"""Integration tests for Guardian v2 full plugin lifecycle."""
from __future__ import annotations

import asyncio
import tempfile
import os

import pytest
import yaml

from guardian_hc.core import GuardianHC
from guardian_hc.plugin import GuardianPlugin, CheckResult, HealResult, Insight, CheckContext, AnalysisContext, Severity
from guardian_hc.db import MetricsDB


V2_CONFIG = """
version: "2.0"
app:
  name: "Test App"
  compose_file: "./docker-compose.yml"

services:
  - name: "backend"
    container: "test-backend"
    health_check:
      type: http
      url: "http://backend:8000/api/v1/health"
    auto_heal:
      restart: true

plugins:
  infrastructure:
    enabled: false
  probes:
    enabled: false
  sentinel:
    enabled: false
  trends:
    enabled: false
  memory:
    enabled: false

modules:
  - name: "Authentication Service"
    services: [backend]
    probes: [jwt_validity]
  - name: "Storage Layer"
    services: [postgres, redis]
    probes: [redis_deep]

agents:
  - id: "GA-0"
    name: "Watcher"
    role: "monitor"
    plugins: [probes, sentinel]
  - id: "GA-1"
    name: "Healer"
    role: "heal-executor"
  - id: "GA-2"
    name: "Debugger"
    role: "correlator"

patrols:
  critical:
    interval: "2m"

alerts:
  telegram:
    token: "test"
    chat_id: "test"

daily_report:
  time: "06:00"
  timezone: "America/Toronto"
  channels: [telegram, email]
"""


@pytest.fixture
def v2_guardian():
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as f:
        f.write(V2_CONFIG)
        f.flush()
        guardian = GuardianHC.from_config(f.name)
        os.unlink(f.name)
    return guardian


class TestV2ConfigLoading:
    def test_v2_config_detected(self, v2_guardian):
        assert v2_guardian._v2_config is not None
        assert v2_guardian._v2_config.version == "2.0"

    def test_agent_registry_created(self, v2_guardian):
        assert v2_guardian._agent_registry is not None
        assert len(v2_guardian._agent_registry.summary()) == 3

    def test_agent_lookup(self, v2_guardian):
        watcher = v2_guardian._agent_registry.get("GA-0")
        assert watcher.name == "Watcher"

    def test_modules_loaded(self, v2_guardian):
        assert len(v2_guardian._v2_config.modules) == 2
        assert v2_guardian._v2_config.modules[0].name == "Authentication Service"

    def test_daily_report_config(self, v2_guardian):
        assert v2_guardian._v2_config.daily_report["time"] == "06:00"

    def test_plugins_all_disabled(self, v2_guardian):
        """All plugins disabled in test config — no auto-registration."""
        assert len(v2_guardian._plugins) == 0


class TestPluginRegistration:
    def test_register_custom_plugin(self, v2_guardian):
        class TestPlugin(GuardianPlugin):
            name = "test"
            enabled = True
        v2_guardian.register_plugin(TestPlugin())
        assert "test" in v2_guardian._plugins

    @pytest.mark.asyncio
    async def test_plugin_check_cycle(self, v2_guardian):
        class PassPlugin(GuardianPlugin):
            name = "pass"
            enabled = True
            async def check(self, ctx):
                return [CheckResult(
                    plugin="pass", module="Test", check_name="test",
                    status="pass", severity=Severity.INFO, summary="OK",
                )]

        v2_guardian.register_plugin(PassPlugin())
        results = await v2_guardian.run_plugin_checks("standard")
        assert len(results) == 1
        assert results[0].status == "pass"

    @pytest.mark.asyncio
    async def test_plugin_heal_cycle(self, v2_guardian):
        class HealPlugin(GuardianPlugin):
            name = "healplugin"
            enabled = True
            async def check(self, ctx):
                return [CheckResult(
                    plugin="healplugin", module="Test", check_name="broken",
                    status="fail", severity=Severity.HIGH, summary="broken",
                    needs_healing=True, heal_hint="test_heal",
                )]
            async def heal(self, result):
                return HealResult(
                    plugin="healplugin", target="test", action="fixed", success=True,
                )

        v2_guardian.register_plugin(HealPlugin())
        checks = await v2_guardian.run_plugin_checks("standard")
        heals = await v2_guardian.run_plugin_heals(checks)
        assert len(heals) == 1
        assert heals[0].success is True

    @pytest.mark.asyncio
    async def test_plugin_analysis_cycle(self, v2_guardian):
        class AnalyzePlugin(GuardianPlugin):
            name = "analyzer"
            enabled = True
            async def analyze(self, ctx):
                return [Insight(
                    plugin="analyzer", insight_type="prediction",
                    severity=Severity.WARNING,
                    summary="Disk will fill in 4h",
                    metric="disk.usage_pct",
                    predicted_time_hours=4.0,
                )]

        v2_guardian.register_plugin(AnalyzePlugin())
        insights = await v2_guardian.run_plugin_analysis()
        assert len(insights) == 1
        assert insights[0].insight_type == "prediction"

    @pytest.mark.asyncio
    async def test_disabled_plugin_skipped(self, v2_guardian):
        class DisabledPlugin(GuardianPlugin):
            name = "disabled"
            enabled = False
            async def check(self, ctx):
                raise RuntimeError("Should not be called")

        v2_guardian.register_plugin(DisabledPlugin())
        results = await v2_guardian.run_plugin_checks("standard")
        assert results == []

    @pytest.mark.asyncio
    async def test_plugin_exception_does_not_crash(self, v2_guardian):
        class CrashPlugin(GuardianPlugin):
            name = "crasher"
            enabled = True
            async def check(self, ctx):
                raise RuntimeError("boom")

        class GoodPlugin(GuardianPlugin):
            name = "good"
            enabled = True
            async def check(self, ctx):
                return [CheckResult(
                    plugin="good", module="Test", check_name="ok",
                    status="pass", severity=Severity.INFO, summary="fine",
                )]

        v2_guardian.register_plugin(CrashPlugin())
        v2_guardian.register_plugin(GoodPlugin())
        results = await v2_guardian.run_plugin_checks("standard")
        # Good plugin's result should still appear
        assert len(results) == 1
        assert results[0].plugin == "good"


class TestMetricsDBIntegration:
    @pytest.mark.asyncio
    async def test_sqlite_fallback_works(self):
        db = MetricsDB(pg_dsn=None, fallback_path=":memory:")
        await db.connect()
        assert not db.is_pg

        await db.write_metric("test.metric", 42.0, service="test")
        val = await db.get_latest("test.metric")
        assert val == 42.0

        await db.close()

    @pytest.mark.asyncio
    async def test_pattern_lifecycle(self):
        db = MetricsDB(pg_dsn=None, fallback_path=":memory:")
        await db.connect()

        pid = await db.create_pattern(
            "test-pattern", {"metric": {">": 50}},
            "bad things", "fix_it", confidence=0.5,
        )
        patterns = await db.get_active_patterns()
        assert len(patterns) == 1

        # Increase confidence
        await db.update_pattern_confidence(pid, matched=True, correct=True)
        patterns = await db.get_active_patterns()
        assert patterns[0]["confidence"] == 0.6

        await db.close()


class TestV1BackwardCompat:
    def test_v1_config_still_works(self):
        v1_config = """
app:
  name: "V1 Test"
  compose_file: "./docker-compose.yml"
services:
  - name: "backend"
    container: "sowknow4-backend"
    health_check:
      type: http
      url: "http://backend:8000/api/v1/health"
    auto_heal:
      restart: true
patrols:
  critical:
    interval: "2m"
alerts:
  telegram:
    token: "test"
    chat_id: "test"
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as f:
            f.write(v1_config)
            f.flush()
            guardian = GuardianHC.from_config(f.name)
            os.unlink(f.name)

        # v1 should work without v2 features
        assert guardian._v2_config is None
        assert guardian._agent_registry is None
        assert len(guardian._plugins) == 0
        assert guardian.config.app_name == "V1 Test"
