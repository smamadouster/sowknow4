"""Guardian v2 plugin base classes and shared types.

All plugins (infrastructure, probes, sentinel, trends, memory) depend on
these types. This is a pure data model — stdlib only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import IntEnum
from typing import Any


# ---------------------------------------------------------------------------
# Severity
# ---------------------------------------------------------------------------

class Severity(IntEnum):
    """Severity levels for check results and insights."""
    INFO = 0
    WARNING = 1
    HIGH = 2
    CRITICAL = 3


# ---------------------------------------------------------------------------
# Context dataclasses (inputs to plugin methods)
# ---------------------------------------------------------------------------

@dataclass
class CheckContext:
    """Context passed to GuardianPlugin.check()."""
    patrol_level: str
    config: dict
    services: list
    metrics_db: Any = None


@dataclass
class AnalysisContext:
    """Context passed to GuardianPlugin.analyze()."""
    config: dict
    metrics_db: Any = None
    patterns_db: Any = None
    recent_incidents: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Result dataclasses (outputs from plugin methods)
# ---------------------------------------------------------------------------

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class CheckResult:
    """Result of a single health check."""
    plugin: str
    module: str
    check_name: str
    status: str                          # "pass" | "fail" | "warning" | "degraded"
    severity: Severity
    summary: str
    details: dict = field(default_factory=dict)
    needs_healing: bool = False
    heal_hint: str | None = None
    timestamp: datetime = field(default_factory=_now_utc)


@dataclass
class HealResult:
    """Result of a heal attempt."""
    plugin: str
    target: str
    action: str
    success: bool
    details: str = ""
    timestamp: datetime = field(default_factory=_now_utc)


@dataclass
class Insight:
    """Analytical insight produced by GuardianPlugin.analyze()."""
    plugin: str
    insight_type: str                    # "prediction" | "anomaly" | "capacity" | "pattern_match"
    severity: Severity
    summary: str
    metric: str = ""
    current_value: float | None = None
    predicted_value: float | None = None
    predicted_time_hours: float | None = None
    recommended_action: str | None = None
    pattern_name: str | None = None
    confidence: float | None = None
    timestamp: datetime = field(default_factory=_now_utc)


# ---------------------------------------------------------------------------
# Plugin base class
# ---------------------------------------------------------------------------

class GuardianPlugin:
    """Base class for all Guardian v2 plugins.

    Subclasses must override ``check`` and may override ``heal`` and
    ``analyze``.  The base implementations of ``heal`` and ``analyze`` are
    no-ops that return ``None`` / ``[]`` respectively so that minimal plugins
    only need to implement ``check``.
    """

    name: str = "unnamed"
    enabled: bool = True

    async def check(self, context: CheckContext) -> list[CheckResult]:
        """Run health checks. Called every patrol cycle."""
        return []

    async def heal(self, result: CheckResult) -> HealResult | None:
        """Attempt to heal a failing check.

        Default implementation is a no-op (returns None).
        """
        return None

    async def analyze(self, context: AnalysisContext) -> list[Insight]:
        """Produce analytical insights from historical metrics.

        Default implementation returns an empty list.
        """
        return []
