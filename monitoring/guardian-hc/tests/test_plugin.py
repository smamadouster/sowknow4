"""Tests for Guardian v2 plugin base classes and shared types."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from guardian_hc.plugin import (
    AnalysisContext,
    CheckContext,
    CheckResult,
    GuardianPlugin,
    HealResult,
    Insight,
    Severity,
)


# ---------------------------------------------------------------------------
# Severity
# ---------------------------------------------------------------------------

class TestSeverity:
    def test_ordering(self):
        assert Severity.CRITICAL > Severity.HIGH
        assert Severity.HIGH > Severity.WARNING
        assert Severity.WARNING > Severity.INFO

    def test_values(self):
        assert Severity.INFO == 0
        assert Severity.WARNING == 1
        assert Severity.HIGH == 2
        assert Severity.CRITICAL == 3

    def test_is_int_enum(self):
        assert isinstance(Severity.INFO, int)


# ---------------------------------------------------------------------------
# CheckContext
# ---------------------------------------------------------------------------

class TestCheckContext:
    def test_creation(self):
        ctx = CheckContext(patrol_level="full", config={}, services=[])
        assert ctx.patrol_level == "full"
        assert ctx.config == {}
        assert ctx.services == []
        assert ctx.metrics_db is None

    def test_with_metrics_db(self):
        ctx = CheckContext(patrol_level="quick", config={"key": "val"}, services=["svc1"], metrics_db="db")
        assert ctx.metrics_db == "db"


# ---------------------------------------------------------------------------
# AnalysisContext
# ---------------------------------------------------------------------------

class TestAnalysisContext:
    def test_creation_defaults(self):
        ctx = AnalysisContext(config={})
        assert ctx.config == {}
        assert ctx.metrics_db is None
        assert ctx.patterns_db is None
        assert ctx.recent_incidents == []

    def test_creation_full(self):
        incidents = [{"id": 1}]
        ctx = AnalysisContext(config={"k": "v"}, metrics_db="m", patterns_db="p", recent_incidents=incidents)
        assert ctx.metrics_db == "m"
        assert ctx.patterns_db == "p"
        assert ctx.recent_incidents == incidents

    def test_recent_incidents_independent(self):
        """Default factory should produce independent lists per instance."""
        ctx1 = AnalysisContext(config={})
        ctx2 = AnalysisContext(config={})
        ctx1.recent_incidents.append({"id": 1})
        assert ctx2.recent_incidents == []


# ---------------------------------------------------------------------------
# CheckResult
# ---------------------------------------------------------------------------

class TestCheckResult:
    def _make(self, **kwargs):
        defaults = dict(
            plugin="infra",
            module="guardian_hc.plugins.infra",
            check_name="disk_space",
            status="pass",
            severity=Severity.INFO,
            summary="All good",
        )
        defaults.update(kwargs)
        return CheckResult(**defaults)

    def test_creation_minimal(self):
        r = self._make()
        assert r.plugin == "infra"
        assert r.module == "guardian_hc.plugins.infra"
        assert r.check_name == "disk_space"
        assert r.status == "pass"
        assert r.severity == Severity.INFO
        assert r.summary == "All good"
        assert r.details == {}
        assert r.needs_healing is False
        assert r.heal_hint is None
        assert isinstance(r.timestamp, datetime)

    def test_timestamp_is_utc(self):
        r = self._make()
        assert r.timestamp.tzinfo is not None

    def test_custom_fields(self):
        r = self._make(
            status="fail",
            severity=Severity.CRITICAL,
            details={"used": 95},
            needs_healing=True,
            heal_hint="free disk space",
        )
        assert r.status == "fail"
        assert r.severity == Severity.CRITICAL
        assert r.details == {"used": 95}
        assert r.needs_healing is True
        assert r.heal_hint == "free disk space"

    def test_details_independent(self):
        r1 = CheckResult(plugin="a", module="m", check_name="c", status="pass", severity=Severity.INFO, summary="ok")
        r2 = CheckResult(plugin="b", module="m", check_name="c", status="pass", severity=Severity.INFO, summary="ok")
        r1.details["key"] = "val"
        assert r2.details == {}

    def test_valid_statuses(self):
        for status in ("pass", "fail", "warning", "degraded"):
            r = self._make(status=status)
            assert r.status == status


# ---------------------------------------------------------------------------
# HealResult
# ---------------------------------------------------------------------------

class TestHealResult:
    def test_creation_minimal(self):
        r = HealResult(plugin="infra", target="disk", action="cleanup", success=True)
        assert r.plugin == "infra"
        assert r.target == "disk"
        assert r.action == "cleanup"
        assert r.success is True
        assert r.details == ""
        assert isinstance(r.timestamp, datetime)

    def test_timestamp_is_utc(self):
        r = HealResult(plugin="p", target="t", action="a", success=False)
        assert r.timestamp.tzinfo is not None

    def test_failure_with_details(self):
        r = HealResult(plugin="p", target="t", action="a", success=False, details="timeout")
        assert r.success is False
        assert r.details == "timeout"


# ---------------------------------------------------------------------------
# Insight
# ---------------------------------------------------------------------------

class TestInsight:
    def _make(self, **kwargs):
        defaults = dict(
            plugin="trends",
            insight_type="anomaly",
            severity=Severity.WARNING,
            summary="Unusual CPU spike",
        )
        defaults.update(kwargs)
        return Insight(**defaults)

    def test_creation_minimal(self):
        i = self._make()
        assert i.plugin == "trends"
        assert i.insight_type == "anomaly"
        assert i.severity == Severity.WARNING
        assert i.summary == "Unusual CPU spike"
        assert i.metric == ""
        assert i.current_value is None
        assert i.predicted_value is None
        assert i.predicted_time_hours is None
        assert i.recommended_action is None
        assert i.pattern_name is None
        assert i.confidence is None
        assert isinstance(i.timestamp, datetime)

    def test_timestamp_is_utc(self):
        i = self._make()
        assert i.timestamp.tzinfo is not None

    def test_full_prediction(self):
        i = self._make(
            insight_type="prediction",
            metric="cpu_percent",
            current_value=70.5,
            predicted_value=95.0,
            predicted_time_hours=4.0,
            recommended_action="scale out",
            confidence=0.87,
        )
        assert i.insight_type == "prediction"
        assert i.current_value == 70.5
        assert i.predicted_value == 95.0
        assert i.predicted_time_hours == 4.0
        assert i.confidence == 0.87

    def test_valid_insight_types(self):
        for itype in ("prediction", "anomaly", "capacity", "pattern_match"):
            i = self._make(insight_type=itype)
            assert i.insight_type == itype


# ---------------------------------------------------------------------------
# GuardianPlugin base class
# ---------------------------------------------------------------------------

class ConcretePlugin(GuardianPlugin):
    name = "test_plugin"

    async def check(self, context: CheckContext) -> list[CheckResult]:
        return [
            CheckResult(
                plugin=self.name,
                module=__name__,
                check_name="always_pass",
                status="pass",
                severity=Severity.INFO,
                summary="OK",
            )
        ]

    async def heal(self, result: CheckResult) -> HealResult | None:
        return HealResult(plugin=self.name, target=result.check_name, action="noop", success=True)

    async def analyze(self, context: AnalysisContext) -> list[Insight]:
        return []


class TestGuardianPlugin:
    def test_default_attributes(self):
        p = ConcretePlugin()
        assert p.name == "test_plugin"
        assert p.enabled is True

    def test_check_returns_results(self):
        p = ConcretePlugin()
        ctx = CheckContext(patrol_level="quick", config={}, services=[])
        results = asyncio.run(p.check(ctx))
        assert len(results) == 1
        assert results[0].status == "pass"
        assert results[0].plugin == "test_plugin"

    def test_heal_returns_heal_result(self):
        p = ConcretePlugin()
        cr = CheckResult(
            plugin="test_plugin",
            module=__name__,
            check_name="disk",
            status="fail",
            severity=Severity.HIGH,
            summary="Disk full",
            needs_healing=True,
        )
        result = asyncio.run(p.heal(cr))
        assert result is not None
        assert result.success is True

    def test_analyze_returns_list(self):
        p = ConcretePlugin()
        ctx = AnalysisContext(config={})
        insights = asyncio.run(p.analyze(ctx))
        assert insights == []

    def test_base_class_check_returns_empty(self):
        """Base GuardianPlugin.check() returns empty list."""
        p = GuardianPlugin()
        ctx = CheckContext(patrol_level="quick", config={}, services=[])
        results = asyncio.run(p.check(ctx))
        assert results == []

    def test_base_heal_returns_none(self):
        p = GuardianPlugin()
        cr = CheckResult(
            plugin="base",
            module=__name__,
            check_name="x",
            status="pass",
            severity=Severity.INFO,
            summary="ok",
        )
        result = asyncio.run(p.heal(cr))
        assert result is None

    def test_base_analyze_returns_empty(self):
        p = GuardianPlugin()
        ctx = AnalysisContext(config={})
        insights = asyncio.run(p.analyze(ctx))
        assert insights == []
