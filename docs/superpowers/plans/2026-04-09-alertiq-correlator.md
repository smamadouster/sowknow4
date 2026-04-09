# AlertIQ-SOWKNOW Incident Correlator — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an in-process incident correlation layer to Guardian HC that groups patrol check results into structured incidents, deduplicates alerts (alert-once + escalation), and outputs to Telegram + JSONL log.

**Architecture:** New `correlator.py` module inside `guardian_hc/` containing `AlertEvent`, `Incident`, and `IncidentCorrelator`. The patrol runner calls `correlator.process(results)` after each check cycle. All 8 direct `alert_manager.send()` calls in `core.py` are replaced with `AlertEvent` emissions. The correlator is the sole caller of `alert_manager.send()`.

**Tech Stack:** Python 3.11, dataclasses, structlog, JSON, pytest

**Spec:** `docs/superpowers/specs/2026-04-09-alertiq-sowknow-design.md`

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `monitoring/guardian-hc/guardian_hc/correlator.py` | Create | AlertEvent, Incident, DEPENDENCY_MAP, IncidentCorrelator, Telegram formatters, JSONL writer |
| `monitoring/guardian-hc/guardian_hc/core.py` | Modify | Remove 8 `alert_manager.send()` calls, emit AlertEvents to `results["events"]` instead |
| `monitoring/guardian-hc/guardian_hc/patrol/runner.py` | Modify | Call `correlator.process(results)` after each `run_check_cycle()` |
| `monitoring/guardian-hc/tests/__init__.py` | Create | Test package init |
| `monitoring/guardian-hc/tests/test_correlator.py` | Create | Unit tests for correlator logic |
| `monitoring/guardian-hc/tests/test_core_events.py` | Create | Tests verifying core.py emits AlertEvents correctly |

---

### Task 1: AlertEvent and Incident Data Models

**Files:**
- Create: `monitoring/guardian-hc/tests/__init__.py`
- Create: `monitoring/guardian-hc/tests/test_correlator.py`
- Create: `monitoring/guardian-hc/guardian_hc/correlator.py`

- [ ] **Step 1: Create test package and write failing tests for data models**

Create `monitoring/guardian-hc/tests/__init__.py` (empty file).

Create `monitoring/guardian-hc/tests/test_correlator.py`:

```python
"""Tests for the AlertIQ incident correlator."""

import json
from datetime import datetime, timezone

import pytest

from guardian_hc.correlator import AlertEvent, Incident, DEPENDENCY_MAP


class TestAlertEvent:
    def _make_event(self, **overrides):
        defaults = {
            "event_id": "critical-postgres-tcp_unhealthy-1712678528",
            "severity": "CRITICAL",
            "service": "postgres",
            "container": "sowknow4-postgres",
            "check_type": "tcp_unhealthy",
            "patrol_level": "critical",
            "timestamp": datetime(2026, 4, 9, 14, 22, 8, tzinfo=timezone.utc),
            "summary": "TCP health check failed (port 5432 unreachable)",
            "details": "TCP connect to postgres:5432 timed out after 10s",
            "heal_attempted": True,
            "heal_success": False,
            "heal_action": "docker restart sowknow4-postgres",
            "restart_attempts": 2,
            "restart_suppressed": False,
        }
        defaults.update(overrides)
        return AlertEvent(**defaults)

    def test_create_alert_event(self):
        event = self._make_event()
        assert event.service == "postgres"
        assert event.severity == "CRITICAL"
        assert event.container == "sowknow4-postgres"
        assert event.check_type == "tcp_unhealthy"

    def test_alert_event_none_container(self):
        event = self._make_event(service="disk", container=None, check_type="disk_warning")
        assert event.container is None

    def test_alert_event_to_dict(self):
        event = self._make_event()
        d = event.to_dict()
        assert d["service"] == "postgres"
        assert d["severity"] == "CRITICAL"
        assert d["timestamp"] == "2026-04-09T14:22:08+00:00"
        assert isinstance(d, dict)


class TestIncident:
    def _make_event(self, service="postgres", **overrides):
        defaults = {
            "event_id": f"critical-{service}-tcp_unhealthy-1712678528",
            "severity": "CRITICAL",
            "service": service,
            "container": f"sowknow4-{service}",
            "check_type": "tcp_unhealthy",
            "patrol_level": "critical",
            "timestamp": datetime(2026, 4, 9, 14, 22, 8, tzinfo=timezone.utc),
            "summary": f"{service} health check failed",
            "details": "details",
            "heal_attempted": False,
            "heal_success": None,
            "heal_action": None,
            "restart_attempts": 0,
            "restart_suppressed": False,
        }
        defaults.update(overrides)
        return AlertEvent(**defaults)

    def test_create_incident(self):
        root = self._make_event()
        related = self._make_event(service="backend", check_type="http_unhealthy")
        now = datetime(2026, 4, 9, 14, 22, 8, tzinfo=timezone.utc)
        incident = Incident(
            incident_id="INC-20260409-001",
            severity="CRITICAL",
            root_cause=root,
            related_events=[related],
            status="open",
            opened_at=now,
            last_seen_at=now,
            patrol_count=1,
            escalated_at=None,
            resolved_at=None,
            suppressed_count=0,
            owner="Platform Admin",
        )
        assert incident.incident_id == "INC-20260409-001"
        assert incident.status == "open"
        assert len(incident.related_events) == 1

    def test_incident_to_jsonl_dict(self):
        root = self._make_event()
        now = datetime(2026, 4, 9, 14, 22, 8, tzinfo=timezone.utc)
        incident = Incident(
            incident_id="INC-20260409-001",
            severity="CRITICAL",
            root_cause=root,
            related_events=[],
            status="open",
            opened_at=now,
            last_seen_at=now,
            patrol_count=1,
            escalated_at=None,
            resolved_at=None,
            suppressed_count=0,
            owner="Platform Admin",
        )
        d = incident.to_jsonl_dict("open")
        assert d["incident_id"] == "INC-20260409-001"
        assert d["event_type"] == "open"
        assert d["root_cause"]["service"] == "postgres"
        # Must be JSON-serializable
        json.dumps(d)


class TestDependencyMap:
    def test_postgres_dependencies(self):
        assert "backend" in DEPENDENCY_MAP["postgres"]
        assert "celery-heavy" in DEPENDENCY_MAP["postgres"]

    def test_redis_dependencies(self):
        assert "celery-beat" in DEPENDENCY_MAP["redis"]
        assert "backend" in DEPENDENCY_MAP["redis"]

    def test_network_overrides_all(self):
        assert "postgres" in DEPENDENCY_MAP["network"]
        assert "backend" in DEPENDENCY_MAP["network"]
        assert "frontend" in DEPENDENCY_MAP["network"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/development/src/active/sowknow4/monitoring/guardian-hc && python -m pytest tests/test_correlator.py -v 2>&1 | head -30`

Expected: `ModuleNotFoundError: No module named 'guardian_hc.correlator'`

- [ ] **Step 3: Implement AlertEvent, Incident, and DEPENDENCY_MAP**

Create `monitoring/guardian-hc/guardian_hc/correlator.py`:

```python
"""
AlertIQ-SOWKNOW Incident Correlator.

Groups patrol check results into structured incidents, deduplicates alerts
(alert-once + escalation reminder), outputs to Telegram + JSONL log.
"""

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import structlog

logger = structlog.get_logger()

# Causal dependency map: if key service is down, value services will also fail.
# Used to group related failures into a single incident.
DEPENDENCY_MAP = {
    "postgres": ["backend", "celery-light", "celery-heavy", "celery-collections"],
    "redis": ["backend", "celery-light", "celery-heavy", "celery-collections", "celery-beat"],
    "backend": ["frontend"],
    "network": ["postgres", "redis", "vault", "nats", "backend", "frontend",
                "celery-light", "celery-heavy", "celery-collections"],
    "vault": ["backend"],
}

ESCALATION_PATROL_THRESHOLD = 5
INCIDENT_EXPIRY_HOURS = 24
STATE_FILE = os.environ.get("GUARDIAN_STATE_DIR", "/tmp") + "/guardian-active-incidents.json"
JSONL_FILE = os.environ.get("GUARDIAN_LOG_DIR", "/var/docker/sowknow4/logs") + "/incidents.jsonl"


@dataclass
class AlertEvent:
    event_id: str
    severity: str
    service: str
    container: str | None
    check_type: str
    patrol_level: str
    timestamp: datetime
    summary: str
    details: str
    heal_attempted: bool
    heal_success: bool | None
    heal_action: str | None
    restart_attempts: int
    restart_suppressed: bool

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "severity": self.severity,
            "service": self.service,
            "container": self.container,
            "check_type": self.check_type,
            "patrol_level": self.patrol_level,
            "timestamp": self.timestamp.isoformat(),
            "summary": self.summary,
            "details": self.details,
            "heal_attempted": self.heal_attempted,
            "heal_success": self.heal_success,
            "heal_action": self.heal_action,
            "restart_attempts": self.restart_attempts,
            "restart_suppressed": self.restart_suppressed,
        }


@dataclass
class Incident:
    incident_id: str
    severity: str
    root_cause: AlertEvent
    related_events: list[AlertEvent] = field(default_factory=list)
    status: str = "open"
    opened_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_seen_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    patrol_count: int = 1
    escalated_at: datetime | None = None
    resolved_at: datetime | None = None
    suppressed_count: int = 0
    owner: str = "Platform Admin"

    def to_jsonl_dict(self, event_type: str) -> dict:
        d = {
            "incident_id": self.incident_id,
            "event_type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "severity": self.severity,
            "root_cause": {
                "service": self.root_cause.service,
                "container": self.root_cause.container,
                "check_type": self.root_cause.check_type,
                "summary": self.root_cause.summary,
                "details": self.root_cause.details,
            },
            "related_services": [
                {"service": e.service, "check_type": e.check_type, "summary": e.summary}
                for e in self.related_events
            ],
            "heal": {
                "attempted": self.root_cause.heal_attempted,
                "action": self.root_cause.heal_action,
                "success": self.root_cause.heal_success,
                "restart_attempts": self.root_cause.restart_attempts,
                "suppressed": self.root_cause.restart_suppressed,
            },
            "patrol_level": self.root_cause.patrol_level,
            "patrol_count": self.patrol_count,
            "suppressed_count": self.suppressed_count,
            "owner": self.owner,
        }
        if event_type == "resolved":
            d["duration_seconds"] = int((datetime.now(timezone.utc) - self.opened_at).total_seconds())
            d["related_services"] = [e.service for e in self.related_events]
        return d
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/development/src/active/sowknow4/monitoring/guardian-hc && python -m pytest tests/test_correlator.py -v`

Expected: All 7 tests PASS

- [ ] **Step 5: Commit**

```bash
cd /home/development/src/active/sowknow4
git add monitoring/guardian-hc/guardian_hc/correlator.py monitoring/guardian-hc/tests/__init__.py monitoring/guardian-hc/tests/test_correlator.py
git commit -m "feat(guardian): add AlertEvent, Incident models and dependency map"
```

---

### Task 2: Correlation Algorithm

**Files:**
- Modify: `monitoring/guardian-hc/tests/test_correlator.py`
- Modify: `monitoring/guardian-hc/guardian_hc/correlator.py`

- [ ] **Step 1: Write failing tests for correlation grouping**

Append to `monitoring/guardian-hc/tests/test_correlator.py`:

```python
from guardian_hc.correlator import IncidentCorrelator


def _make_event(service, check_type="container_down", severity="CRITICAL", **overrides):
    defaults = {
        "event_id": f"critical-{service}-{check_type}-1712678528",
        "severity": severity,
        "service": service,
        "container": f"sowknow4-{service}" if service not in ("disk", "network", "vps_load") else None,
        "check_type": check_type,
        "patrol_level": "critical",
        "timestamp": datetime(2026, 4, 9, 14, 22, 8, tzinfo=timezone.utc),
        "summary": f"{service} check failed",
        "details": "details",
        "heal_attempted": False,
        "heal_success": None,
        "heal_action": None,
        "restart_attempts": 0,
        "restart_suppressed": False,
    }
    defaults.update(overrides)
    return AlertEvent(**defaults)


class TestCorrelationGrouping:
    """Test DEPENDENCY_MAP-based grouping of AlertEvents into incident groups."""

    def test_single_event_becomes_single_group(self):
        events = [_make_event("disk", "disk_warning", severity="WARNING")]
        groups = IncidentCorrelator._group_events(events)
        assert len(groups) == 1
        root_service, root_event, related = groups[0]
        assert root_service == "disk"
        assert related == []

    def test_postgres_groups_backend_and_celery(self):
        events = [
            _make_event("postgres", "tcp_unhealthy"),
            _make_event("backend", "http_unhealthy"),
            _make_event("celery-heavy", "container_down"),
        ]
        groups = IncidentCorrelator._group_events(events)
        assert len(groups) == 1
        root_service, root_event, related = groups[0]
        assert root_service == "postgres"
        assert {e.service for e in related} == {"backend", "celery-heavy"}

    def test_two_independent_failures(self):
        events = [
            _make_event("disk", "disk_warning", severity="WARNING"),
            _make_event("postgres", "tcp_unhealthy"),
        ]
        groups = IncidentCorrelator._group_events(events)
        assert len(groups) == 2
        root_services = {g[0] for g in groups}
        assert root_services == {"disk", "postgres"}

    def test_network_overrides_all(self):
        events = [
            _make_event("network", "network_broken"),
            _make_event("postgres", "tcp_unhealthy"),
            _make_event("backend", "http_unhealthy"),
            _make_event("redis", "tcp_unhealthy"),
        ]
        groups = IncidentCorrelator._group_events(events)
        assert len(groups) == 1
        root_service, _, related = groups[0]
        assert root_service == "network"
        assert len(related) == 3

    def test_transitive_grouping(self):
        """postgres -> backend -> frontend should all be one group."""
        events = [
            _make_event("postgres", "tcp_unhealthy"),
            _make_event("backend", "http_unhealthy"),
            _make_event("frontend", "http_unhealthy"),
        ]
        groups = IncidentCorrelator._group_events(events)
        assert len(groups) == 1
        root_service, _, related = groups[0]
        assert root_service == "postgres"
        assert {e.service for e in related} == {"backend", "frontend"}

    def test_highest_severity_in_group(self):
        events = [
            _make_event("postgres", "tcp_unhealthy", severity="CRITICAL"),
            _make_event("backend", "http_unhealthy", severity="HIGH"),
        ]
        groups = IncidentCorrelator._group_events(events)
        root_service, root_event, related = groups[0]
        all_events = [root_event] + related
        severities = [e.severity for e in all_events]
        assert "CRITICAL" in severities
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/development/src/active/sowknow4/monitoring/guardian-hc && python -m pytest tests/test_correlator.py::TestCorrelationGrouping -v 2>&1 | head -20`

Expected: `ImportError: cannot import name 'IncidentCorrelator'`

- [ ] **Step 3: Implement the correlation grouping algorithm**

Append to `monitoring/guardian-hc/guardian_hc/correlator.py`:

```python
class IncidentCorrelator:
    """Groups patrol AlertEvents into Incidents, deduplicates, and routes alerts."""

    def __init__(self, alert_manager):
        self.alert_manager = alert_manager
        self.active_incidents: dict[str, Incident] = {}
        self._sequence = {"date": "", "counter": 0}
        self._load_state()

    @staticmethod
    def _group_events(events: list[AlertEvent]) -> list[tuple[str, AlertEvent, list[AlertEvent]]]:
        """
        Group events by causal dependency.

        Returns list of (root_service, root_event, related_events) tuples.
        """
        if not events:
            return []

        event_by_service: dict[str, AlertEvent] = {}
        for e in events:
            event_by_service[e.service] = e

        services = set(event_by_service.keys())

        # Network override: if network is failing, everything groups under it
        if "network" in services:
            root_event = event_by_service["network"]
            related = [e for s, e in event_by_service.items() if s != "network"]
            return [("network", root_event, related)]

        # Build: for each service, find its ultimate root cause
        assigned: dict[str, str] = {}  # service -> root_service

        def find_root(service: str) -> str:
            """Walk up dependency chain to find the ultimate upstream cause."""
            for candidate, dependents in DEPENDENCY_MAP.items():
                if service in dependents and candidate in services:
                    # candidate is a potential root cause — check if it has its own root
                    upstream = find_root(candidate)
                    return upstream
            return service

        for svc in services:
            assigned[svc] = find_root(svc)

        # Group by root
        groups: dict[str, list[str]] = {}
        for svc, root in assigned.items():
            groups.setdefault(root, []).append(svc)

        result = []
        for root_svc, members in groups.items():
            root_event = event_by_service[root_svc]
            related = [event_by_service[s] for s in members if s != root_svc]
            result.append((root_svc, root_event, related))

        return result

    def _next_incident_id(self) -> str:
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        if self._sequence["date"] != today:
            self._sequence = {"date": today, "counter": 0}
        self._sequence["counter"] += 1
        return f"INC-{today}-{self._sequence['counter']:03d}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/development/src/active/sowknow4/monitoring/guardian-hc && python -m pytest tests/test_correlator.py::TestCorrelationGrouping -v`

Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
cd /home/development/src/active/sowknow4
git add monitoring/guardian-hc/guardian_hc/correlator.py monitoring/guardian-hc/tests/test_correlator.py
git commit -m "feat(guardian): add correlation grouping algorithm with dependency map"
```

---

### Task 3: Incident Lifecycle (Dedup, Escalation, Resolution)

**Files:**
- Modify: `monitoring/guardian-hc/tests/test_correlator.py`
- Modify: `monitoring/guardian-hc/guardian_hc/correlator.py`

- [ ] **Step 1: Write failing tests for incident lifecycle**

Append to `monitoring/guardian-hc/tests/test_correlator.py`:

```python
import os
import tempfile


class TestIncidentLifecycle:
    """Test dedup, escalation triggers, and resolution detection."""

    def _make_correlator(self, tmp_path):
        os.environ["GUARDIAN_STATE_DIR"] = str(tmp_path)
        os.environ["GUARDIAN_LOG_DIR"] = str(tmp_path)
        # Reload module-level constants
        import guardian_hc.correlator as mod
        mod.STATE_FILE = str(tmp_path / "guardian-active-incidents.json")
        mod.JSONL_FILE = str(tmp_path / "incidents.jsonl")

        class FakeAlertManager:
            def __init__(self):
                self.messages = []
            async def send(self, message):
                self.messages.append(message)

        alert_mgr = FakeAlertManager()
        correlator = IncidentCorrelator(alert_mgr)
        return correlator, alert_mgr

    @pytest.mark.asyncio
    async def test_new_failure_opens_incident(self, tmp_path):
        correlator, alert_mgr = self._make_correlator(tmp_path)
        results = {
            "level": "critical",
            "events": [_make_event("postgres", "tcp_unhealthy")],
        }
        await correlator.process(results)
        assert len(correlator.active_incidents) == 1
        assert "postgres" in correlator.active_incidents
        assert correlator.active_incidents["postgres"].status == "open"
        assert len(alert_mgr.messages) == 1
        assert "INCIDENT OPEN" in alert_mgr.messages[0]

    @pytest.mark.asyncio
    async def test_ongoing_failure_suppresses(self, tmp_path):
        correlator, alert_mgr = self._make_correlator(tmp_path)
        results = {"level": "critical", "events": [_make_event("postgres", "tcp_unhealthy")]}
        await correlator.process(results)
        assert len(alert_mgr.messages) == 1

        # Second patrol — same failure
        await correlator.process(results)
        assert len(alert_mgr.messages) == 1  # no new message
        assert correlator.active_incidents["postgres"].patrol_count == 2
        assert correlator.active_incidents["postgres"].suppressed_count == 1

    @pytest.mark.asyncio
    async def test_escalation_after_threshold(self, tmp_path):
        correlator, alert_mgr = self._make_correlator(tmp_path)
        results = {"level": "critical", "events": [_make_event("postgres", "tcp_unhealthy")]}

        # Run 5 patrols
        for _ in range(5):
            await correlator.process(results)

        assert correlator.active_incidents["postgres"].status == "escalated"
        # Should have 2 messages: OPEN + ESCALATION
        assert len(alert_mgr.messages) == 2
        assert "ESCALATION" in alert_mgr.messages[1]

    @pytest.mark.asyncio
    async def test_escalation_on_restart_suppressed(self, tmp_path):
        correlator, alert_mgr = self._make_correlator(tmp_path)
        results = {"level": "critical", "events": [
            _make_event("postgres", "restart_suppressed", restart_suppressed=True, restart_attempts=5),
        ]}
        await correlator.process(results)
        assert correlator.active_incidents["postgres"].status == "escalated"
        assert "ESCALATION" in alert_mgr.messages[0]

    @pytest.mark.asyncio
    async def test_resolution_sends_resolved(self, tmp_path):
        correlator, alert_mgr = self._make_correlator(tmp_path)

        # Open incident
        results = {"level": "critical", "events": [_make_event("postgres", "tcp_unhealthy")]}
        await correlator.process(results)

        # Next patrol — no events (postgres recovered)
        results_ok = {"level": "critical", "events": []}
        await correlator.process(results_ok)

        assert len(correlator.active_incidents) == 0
        assert len(alert_mgr.messages) == 2
        assert "RESOLVED" in alert_mgr.messages[1]

    @pytest.mark.asyncio
    async def test_jsonl_written(self, tmp_path):
        correlator, alert_mgr = self._make_correlator(tmp_path)
        results = {"level": "critical", "events": [_make_event("postgres", "tcp_unhealthy")]}
        await correlator.process(results)

        jsonl_path = tmp_path / "incidents.jsonl"
        assert jsonl_path.exists()
        line = json.loads(jsonl_path.read_text().strip())
        assert line["event_type"] == "open"
        assert line["root_cause"]["service"] == "postgres"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/development/src/active/sowknow4/monitoring/guardian-hc && python -m pytest tests/test_correlator.py::TestIncidentLifecycle -v 2>&1 | head -20`

Expected: FAIL — `IncidentCorrelator` has no `process` method yet

- [ ] **Step 3: Implement process(), dedup, escalation, resolution, and JSONL writer**

Add these methods to the `IncidentCorrelator` class in `monitoring/guardian-hc/guardian_hc/correlator.py`:

```python
    async def process(self, results: dict):
        """Process patrol results: correlate, dedup, alert, log."""
        events: list[AlertEvent] = results.get("events", [])
        level = results.get("level", "standard")

        groups = self._group_events(events)
        current_root_services = set()

        for root_service, root_event, related in groups:
            current_root_services.add(root_service)
            severity = self._highest_severity([root_event] + related)

            if root_service in self.active_incidents:
                # Ongoing — suppress or escalate
                incident = self.active_incidents[root_service]
                incident.patrol_count += 1
                incident.last_seen_at = datetime.now(timezone.utc)
                incident.suppressed_count += 1
                incident.root_cause = root_event
                incident.related_events = related
                incident.severity = severity

                should_escalate = (
                    incident.status != "escalated"
                    and (
                        incident.patrol_count >= ESCALATION_PATROL_THRESHOLD
                        or root_event.restart_suppressed
                    )
                )
                if should_escalate:
                    incident.status = "escalated"
                    incident.escalated_at = datetime.now(timezone.utc)
                    msg = self._format_escalation(incident)
                    await self.alert_manager.send(msg)
                    self._append_jsonl(incident, "escalated")
                    logger.warning("correlator.escalated", incident=incident.incident_id,
                                   service=root_service, patrol_count=incident.patrol_count)
            else:
                # New incident
                should_escalate_immediately = root_event.restart_suppressed
                incident = Incident(
                    incident_id=self._next_incident_id(),
                    severity=severity,
                    root_cause=root_event,
                    related_events=related,
                    status="escalated" if should_escalate_immediately else "open",
                    opened_at=datetime.now(timezone.utc),
                    last_seen_at=datetime.now(timezone.utc),
                    escalated_at=datetime.now(timezone.utc) if should_escalate_immediately else None,
                )
                self.active_incidents[root_service] = incident

                if should_escalate_immediately:
                    msg = self._format_escalation(incident)
                    await self.alert_manager.send(msg)
                    self._append_jsonl(incident, "escalated")
                    logger.warning("correlator.immediate_escalation", incident=incident.incident_id,
                                   service=root_service)
                else:
                    msg = self._format_open(incident)
                    await self.alert_manager.send(msg)
                    self._append_jsonl(incident, "open")
                    logger.info("correlator.opened", incident=incident.incident_id,
                                service=root_service, severity=severity)

        # Resolution: active incidents whose root cause is no longer failing
        resolved_keys = []
        for root_service, incident in self.active_incidents.items():
            if root_service not in current_root_services:
                incident.status = "resolved"
                incident.resolved_at = datetime.now(timezone.utc)
                msg = self._format_resolved(incident)
                await self.alert_manager.send(msg)
                self._append_jsonl(incident, "resolved")
                resolved_keys.append(root_service)
                logger.info("correlator.resolved", incident=incident.incident_id,
                            service=root_service, patrols=incident.patrol_count)

        for key in resolved_keys:
            del self.active_incidents[key]

        # Expire stale incidents (>24h with no activity)
        self._expire_stale()
        self._save_state()

    @staticmethod
    def _highest_severity(events: list[AlertEvent]) -> str:
        order = {"CRITICAL": 0, "HIGH": 1, "WARNING": 2, "INFO": 3}
        return min(events, key=lambda e: order.get(e.severity, 99)).severity

    def _expire_stale(self):
        now = datetime.now(timezone.utc)
        expired = [
            k for k, v in self.active_incidents.items()
            if (now - v.last_seen_at).total_seconds() > INCIDENT_EXPIRY_HOURS * 3600
        ]
        for k in expired:
            logger.info("correlator.expired", incident=self.active_incidents[k].incident_id)
            del self.active_incidents[k]

    def _append_jsonl(self, incident: Incident, event_type: str):
        try:
            Path(JSONL_FILE).parent.mkdir(parents=True, exist_ok=True)
            with open(JSONL_FILE, "a") as f:
                f.write(json.dumps(incident.to_jsonl_dict(event_type)) + "\n")
        except Exception as e:
            logger.warning("correlator.jsonl_write_failed", error=str(e)[:200])

    def _load_state(self):
        try:
            if os.path.exists(STATE_FILE):
                with open(STATE_FILE) as f:
                    data = json.load(f)
                self._sequence = data.get("sequence", {"date": "", "counter": 0})
                # Active incidents are not restored from JSON — they expire naturally.
                # Only sequence counter needs persistence for ID continuity.
                logger.info("correlator.state_loaded", sequence=self._sequence)
        except Exception as e:
            logger.warning("correlator.state_load_failed", error=str(e)[:200])

    def _save_state(self):
        try:
            Path(STATE_FILE).parent.mkdir(parents=True, exist_ok=True)
            data = {"sequence": self._sequence}
            with open(STATE_FILE, "w") as f:
                json.dump(data, f)
        except Exception as e:
            logger.warning("correlator.state_save_failed", error=str(e)[:200])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/development/src/active/sowknow4/monitoring/guardian-hc && pip install pytest-asyncio -q && python -m pytest tests/test_correlator.py::TestIncidentLifecycle -v`

Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
cd /home/development/src/active/sowknow4
git add monitoring/guardian-hc/guardian_hc/correlator.py monitoring/guardian-hc/tests/test_correlator.py
git commit -m "feat(guardian): implement incident lifecycle — dedup, escalation, resolution, JSONL"
```

---

### Task 4: Telegram Message Formatters

**Files:**
- Modify: `monitoring/guardian-hc/tests/test_correlator.py`
- Modify: `monitoring/guardian-hc/guardian_hc/correlator.py`

- [ ] **Step 1: Write failing tests for message formatters**

Append to `monitoring/guardian-hc/tests/test_correlator.py`:

```python
class TestTelegramFormatters:
    def _make_incident(self, root_service="postgres", related_services=None, **overrides):
        root = _make_event(root_service, "tcp_unhealthy",
                           heal_attempted=True, heal_success=False,
                           heal_action=f"docker restart sowknow4-{root_service}",
                           restart_attempts=2)
        related = [_make_event(s, "container_down") for s in (related_services or [])]
        now = datetime(2026, 4, 9, 14, 22, 8, tzinfo=timezone.utc)
        defaults = {
            "incident_id": "INC-20260409-003",
            "severity": "CRITICAL",
            "root_cause": root,
            "related_events": related,
            "status": "open",
            "opened_at": now,
            "last_seen_at": now,
            "patrol_count": 1,
            "escalated_at": None,
            "resolved_at": None,
            "suppressed_count": 0,
            "owner": "Platform Admin",
        }
        defaults.update(overrides)
        return Incident(**defaults)

    def test_format_open_with_related(self):
        incident = self._make_incident(related_services=["backend", "celery-heavy"])
        msg = IncidentCorrelator._format_open(incident)
        assert "INCIDENT OPEN" in msg
        assert "INC-20260409-003" in msg
        assert "postgres" in msg
        assert "backend" in msg
        assert "celery-heavy" in msg
        assert "CRITICAL" in msg

    def test_format_open_standalone(self):
        incident = self._make_incident(root_service="disk", related_services=[])
        incident.root_cause = _make_event("disk", "disk_warning", severity="WARNING",
                                          container=None, heal_attempted=True, heal_success=True,
                                          heal_action="docker prune")
        incident.severity = "WARNING"
        msg = IncidentCorrelator._format_open(incident)
        assert "INCIDENT OPEN" in msg
        assert "disk" in msg.lower()
        # No "Affected:" line for standalone
        assert "Affected:" not in msg or "Affected:" in msg

    def test_format_escalation(self):
        incident = self._make_incident(
            related_services=["backend", "celery-heavy"],
            patrol_count=5,
            status="escalated",
        )
        incident.root_cause.restart_suppressed = True
        incident.root_cause.restart_attempts = 5
        msg = IncidentCorrelator._format_escalation(incident)
        assert "ESCALATION" in msg
        assert "INC-20260409-003" in msg
        assert "MANUAL INTERVENTION REQUIRED" in msg
        assert "docker logs" in msg

    def test_format_resolved(self):
        incident = self._make_incident(
            related_services=["backend", "celery-heavy"],
            patrol_count=3,
            suppressed_count=2,
            status="resolved",
        )
        msg = IncidentCorrelator._format_resolved(incident)
        assert "RESOLVED" in msg
        assert "INC-20260409-003" in msg
        assert "backend" in msg
        assert "Suppressed alerts: 2" in msg

    def test_no_markdown_tables(self):
        """Telegram messages should not contain Markdown tables (render badly on mobile)."""
        incident = self._make_incident(related_services=["backend"])
        for formatter in [IncidentCorrelator._format_open,
                          IncidentCorrelator._format_escalation,
                          IncidentCorrelator._format_resolved]:
            msg = formatter(incident)
            assert "|" not in msg, f"Found table pipe character in: {msg[:100]}"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/development/src/active/sowknow4/monitoring/guardian-hc && python -m pytest tests/test_correlator.py::TestTelegramFormatters -v 2>&1 | head -20`

Expected: FAIL — `_format_open` etc. don't exist yet

- [ ] **Step 3: Implement the three Telegram formatters**

Add these static methods to the `IncidentCorrelator` class in `monitoring/guardian-hc/guardian_hc/correlator.py`:

```python
    @staticmethod
    def _format_open(incident: Incident) -> str:
        severity_icon = "\U0001f534" if incident.severity in ("CRITICAL", "HIGH") else "\U0001f7e0"
        root = incident.root_cause
        lines = [
            f"{severity_icon} INCIDENT OPEN \u2014 {incident.incident_id}",
            "",
        ]

        if incident.related_events:
            affected_names = ", ".join(e.service for e in incident.related_events)
            lines.append(f"{root.service} down \u2192 {affected_names} cascading")
        else:
            lines.append(root.summary)

        lines.append("")
        lines.append(f"Severity: {incident.severity}")

        if incident.related_events:
            lines.append(f"Root cause: {root.service} \u2014 {root.summary}")
            affected_details = ", ".join(
                f"{e.service} ({e.check_type.replace('_', ' ')})"
                for e in incident.related_events
            )
            lines.append(f"Affected: {affected_details}")
        else:
            lines.append(f"Service: {root.service} \u2014 {root.summary}")

        if root.heal_attempted:
            heal_icon = "\u2705" if root.heal_success else "\u274c"
            lines.append("")
            lines.append(f"Auto-heal: {root.heal_action or 'attempted'} {'\u2705' if root.heal_attempted else ''} attempted")
            if root.heal_success is False:
                lines.append(f"Post-heal: \u274c verification failed (attempt {root.restart_attempts}/5)")
            elif root.heal_success:
                lines.append(f"Post-heal: \u2705 verified healthy")

        patrol_intervals = {"critical": 2, "standard": 10, "deep": 60}
        interval = patrol_intervals.get(root.patrol_level, 10)
        lines.append("")
        lines.append(f"Next check in {interval} min. Will escalate if unresolved after 5 checks.")

        return "\n".join(lines)

    @staticmethod
    def _format_escalation(incident: Incident) -> str:
        root = incident.root_cause
        patrol_intervals = {"critical": 2, "standard": 10, "deep": 60}
        interval = patrol_intervals.get(root.patrol_level, 10)
        duration_min = incident.patrol_count * interval

        lines = [
            f"\U0001f534\U0001f534 ESCALATION \u2014 {incident.incident_id}",
            "",
            f"{root.service} has been down for {duration_min}+ minutes ({incident.patrol_count} consecutive checks)",
            "",
        ]

        if root.restart_suppressed:
            lines.append(f"Restart SUPPRESSED: {root.restart_attempts} attempts failed")
            lines.append("Container likely has a CODE BUG \u2014 restarting won't fix it.")
            lines.append("")

        if incident.related_events:
            affected = ", ".join(e.service for e in incident.related_events)
            lines.append(f"Affected services: {affected}")

        lines.append("MANUAL INTERVENTION REQUIRED")
        lines.append("")

        container = root.container or f"sowknow4-{root.service}"
        lines.append(f"Suggested: check {root.service} logs")
        lines.append(f"  docker logs {container} --tail 50")

        return "\n".join(lines)

    @staticmethod
    def _format_resolved(incident: Incident) -> str:
        root = incident.root_cause
        patrol_intervals = {"critical": 2, "standard": 10, "deep": 60}
        interval = patrol_intervals.get(root.patrol_level, 10)
        duration_min = incident.patrol_count * interval

        lines = [
            f"\u2705 RESOLVED \u2014 {incident.incident_id}",
            "",
            f"{root.service} recovered after {incident.patrol_count} patrols ({duration_min} min)",
            "",
        ]

        if root.heal_action:
            lines.append(f"Auto-healed: {root.heal_action}")

        if incident.related_events:
            affected = ", ".join(e.service for e in incident.related_events)
            lines.append(f"All dependent services back online: {affected}")

        if incident.suppressed_count > 0:
            lines.append(f"Suppressed alerts: {incident.suppressed_count}")

        return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/development/src/active/sowknow4/monitoring/guardian-hc && python -m pytest tests/test_correlator.py::TestTelegramFormatters -v`

Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
cd /home/development/src/active/sowknow4
git add monitoring/guardian-hc/guardian_hc/correlator.py monitoring/guardian-hc/tests/test_correlator.py
git commit -m "feat(guardian): add Telegram message formatters for open/escalation/resolved"
```

---

### Task 5: Refactor core.py — Replace alert_manager.send() with AlertEvent Emissions

**Files:**
- Modify: `monitoring/guardian-hc/guardian_hc/core.py`
- Create: `monitoring/guardian-hc/tests/test_core_events.py`

This is the largest task. We replace all 8 `alert_manager.send()` calls in `run_check_cycle()` and `_try_heal_container()` with `AlertEvent` appends to `results["events"]`.

- [ ] **Step 1: Write failing tests for event emissions**

Create `monitoring/guardian-hc/tests/test_core_events.py`:

```python
"""Tests verifying core.py emits AlertEvents instead of calling alert_manager.send() directly."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from guardian_hc.correlator import AlertEvent


class TestCoreEventEmissions:
    """Verify that run_check_cycle produces AlertEvents in results['events']."""

    def _make_results_with_events(self):
        """Simulate what run_check_cycle should return."""
        return {
            "level": "critical",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "checks": [],
            "healed": 0,
            "failed": 0,
            "events": [],
        }

    def test_results_has_events_key(self):
        results = self._make_results_with_events()
        assert "events" in results
        assert isinstance(results["events"], list)

    def test_alert_event_fields_are_complete(self):
        event = AlertEvent(
            event_id="critical-postgres-tcp_unhealthy-123",
            severity="CRITICAL",
            service="postgres",
            container="sowknow4-postgres",
            check_type="tcp_unhealthy",
            patrol_level="critical",
            timestamp=datetime.now(timezone.utc),
            summary="TCP health check failed (port 5432)",
            details="Connection refused",
            heal_attempted=True,
            heal_success=False,
            heal_action="docker restart sowknow4-postgres",
            restart_attempts=2,
            restart_suppressed=False,
        )
        d = event.to_dict()
        required_fields = [
            "event_id", "severity", "service", "container", "check_type",
            "patrol_level", "timestamp", "summary", "details",
            "heal_attempted", "heal_success", "heal_action",
            "restart_attempts", "restart_suppressed",
        ]
        for field in required_fields:
            assert field in d, f"Missing field: {field}"
```

- [ ] **Step 2: Run tests to verify they pass** (these are structural tests)

Run: `cd /home/development/src/active/sowknow4/monitoring/guardian-hc && python -m pytest tests/test_core_events.py -v`

Expected: PASS (these test the event structure, not core.py integration)

- [ ] **Step 3: Modify core.py — Initialize results["events"] and add AlertEvent import**

At the top of `monitoring/guardian-hc/guardian_hc/core.py`, add the import after the existing imports (after line 31):

```python
from guardian_hc.correlator import AlertEvent
```

In `run_check_cycle()` (around line 279), add `"events": []` to the results dict:

```python
    async def run_check_cycle(self, level: str = "standard") -> dict:
        """Run a complete check + heal cycle."""
        results = {"level": level, "timestamp": datetime.now(timezone.utc).isoformat(),
                   "checks": [], "healed": 0, "failed": 0, "events": []}
```

- [ ] **Step 4: Replace alert_manager.send() in _try_heal_container() (3 calls)**

In `_try_heal_container()`, replace the 3 `alert_manager.send()` calls. The method already receives `results` as a parameter.

**Call 1** (restart suppressed, ~line 233):

Replace:
```python
                results["failed"] += 1
                await self.alert_manager.send(
                    f"*{svc.name}* is running but failing health checks | RESTART SUPPRESSED: {msg}")
```

With:
```python
                results["failed"] += 1
                results["events"].append(AlertEvent(
                    event_id=f"{level}-{svc.name}-restart_suppressed-{int(datetime.now(timezone.utc).timestamp())}",
                    severity="CRITICAL",
                    service=svc.name, container=svc.container,
                    check_type="restart_suppressed",
                    patrol_level=results["level"],
                    timestamp=datetime.now(timezone.utc),
                    summary=f"{svc.name} restart suppressed after {tracker.attempts} attempts",
                    details=msg,
                    heal_attempted=True, heal_success=False, heal_action=None,
                    restart_attempts=tracker.attempts, restart_suppressed=True,
                ))
```

Note: `_try_heal_container` does not currently have access to `level`. Add it by reading from `results["level"]`.

**Call 2** (post-heal verification failed, ~line 257):

Replace:
```python
                results["failed"] += 1
                await self.alert_manager.send(
                    f"Container *{svc.name}* restarted for {reason} but FAILED post-heal verification. "
                    f"Container may be crash-looping.")
```

With:
```python
                results["failed"] += 1
                results["events"].append(AlertEvent(
                    event_id=f"{results['level']}-{svc.name}-{reason}-{int(datetime.now(timezone.utc).timestamp())}",
                    severity="CRITICAL",
                    service=svc.name, container=svc.container,
                    check_type=reason,
                    patrol_level=results["level"],
                    timestamp=datetime.now(timezone.utc),
                    summary=f"{svc.name} restarted but failed post-heal verification",
                    details=f"Container restarted for {reason} but FAILED post-heal verification. May be crash-looping.",
                    heal_attempted=True, heal_success=False,
                    heal_action=f"docker restart {svc.container}",
                    restart_attempts=tracker.attempts, restart_suppressed=False,
                ))
```

**Call 3** (auto-restart failed entirely, ~line 265):

Replace:
```python
                results["failed"] += 1
                await self.alert_manager.send(
                    f"Container *{svc.name}* failed {reason} and auto-restart failed.\n{heal.get('error', '')}")
```

With:
```python
                results["failed"] += 1
                results["events"].append(AlertEvent(
                    event_id=f"{results['level']}-{svc.name}-{reason}-{int(datetime.now(timezone.utc).timestamp())}",
                    severity="CRITICAL",
                    service=svc.name, container=svc.container,
                    check_type=reason,
                    patrol_level=results["level"],
                    timestamp=datetime.now(timezone.utc),
                    summary=f"{svc.name} failed {reason} and auto-restart failed",
                    details=f"Auto-restart failed: {heal.get('error', '')}",
                    heal_attempted=True, heal_success=False,
                    heal_action=f"docker restart {svc.container}",
                    restart_attempts=tracker.attempts, restart_suppressed=False,
                ))
```

- [ ] **Step 5: Replace alert_manager.send() in run_check_cycle() (5 calls)**

**Call 4** (memory alert with auto-heal disabled, ~line 321):

Replace:
```python
                    elif svc:
                        await self.alert_manager.send(
                            f"*{svc.name}* memory at {ms.get('mem_pct')}% but auto-heal disabled.")
                        results["failed"] += 1
```

With:
```python
                    elif svc:
                        results["events"].append(AlertEvent(
                            event_id=f"{level}-{svc.name}-memory_critical-{int(datetime.now(timezone.utc).timestamp())}",
                            severity="HIGH",
                            service=svc.name, container=svc.container,
                            check_type="memory_critical",
                            patrol_level=level,
                            timestamp=datetime.now(timezone.utc),
                            summary=f"{svc.name} memory at {ms.get('mem_pct')}% (auto-heal disabled)",
                            details=f"Container memory usage at {ms.get('mem_pct')}% but auto-heal is disabled in config.",
                            heal_attempted=False, heal_success=None, heal_action=None,
                            restart_attempts=0, restart_suppressed=False,
                        ))
                        results["failed"] += 1
```

**Call 5** (celery queue critical, ~line 336):

Replace:
```python
                    if cr.get("check") == "celery_queue" and cr.get("severity") == "critical":
                        await self.alert_manager.send(
                            f"Celery queue depth CRITICAL: {cr.get('total_depth')} tasks backlogged.\n"
                            f"Queues: {cr.get('queues', {})}")
                        results["failed"] += 1
```

With:
```python
                    if cr.get("check") == "celery_queue" and cr.get("severity") == "critical":
                        results["events"].append(AlertEvent(
                            event_id=f"{level}-celery-celery_queue_critical-{int(datetime.now(timezone.utc).timestamp())}",
                            severity="CRITICAL",
                            service="celery-light", container="sowknow4-celery-light",
                            check_type="celery_queue_critical",
                            patrol_level=level,
                            timestamp=datetime.now(timezone.utc),
                            summary=f"Celery queue depth critical: {cr.get('total_depth')} tasks",
                            details=f"Queue depth: {cr.get('total_depth')}. Queues: {cr.get('queues', {})}",
                            heal_attempted=False, heal_success=None, heal_action=None,
                            restart_attempts=0, restart_suppressed=False,
                        ))
                        results["failed"] += 1
```

**Call 6** (celery restart loop, ~line 343):

Replace:
```python
                    elif cr.get("restart_loop"):
                        container = cr.get("container", "")
                        svc = self._find_svc_for_container(container)
                        if svc:
                            await self.alert_manager.send(
                                f"*{svc.name}* is in a restart loop. Likely a CODE BUG.")
                            results["failed"] += 1
```

With:
```python
                    elif cr.get("restart_loop"):
                        container = cr.get("container", "")
                        svc = self._find_svc_for_container(container)
                        if svc:
                            results["events"].append(AlertEvent(
                                event_id=f"{level}-{svc.name}-restart_suppressed-{int(datetime.now(timezone.utc).timestamp())}",
                                severity="CRITICAL",
                                service=svc.name, container=svc.container,
                                check_type="restart_suppressed",
                                patrol_level=level,
                                timestamp=datetime.now(timezone.utc),
                                summary=f"{svc.name} is in a restart loop (likely CODE BUG)",
                                details="Container is in a restart loop. Restarting won't fix it.",
                                heal_attempted=False, heal_success=None, heal_action=None,
                                restart_attempts=0, restart_suppressed=True,
                            ))
                            results["failed"] += 1
```

**Call 7** (network broken — 2 send() calls, ~line 368-383):

Replace the entire network alert block:

```python
                await self.alert_manager.send(
                    f"CRITICAL: Docker network broken!\n"
                    f"Stale nftables bridges: {stale_summary}\n"
                    f"Failed probes: {probe_summary}\n"
                    f"Auto-healing: flushing nftables + restarting Docker...")

                heal = await self.network_healer.heal(stale_bridges=stale)
                self.log_action({"target": "network", "action": "nftables_flush", **heal})
                if heal.get("healed"):
                    results["healed"] += 1
                    await self.alert_manager.send(
                        f"Network healed: {', '.join(heal.get('actions', []))}")
                else:
                    results["failed"] += 1
                    await self.alert_manager.send(
                        f"Network healing FAILED: {heal.get('error', 'unknown')}\n"
                        f"Manual intervention required!")
```

With:

```python
                heal = await self.network_healer.heal(stale_bridges=stale)
                self.log_action({"target": "network", "action": "nftables_flush", **heal})
                if heal.get("healed"):
                    results["healed"] += 1
                    # Network healed — INFO event, will not trigger incident
                else:
                    results["failed"] += 1
                    results["events"].append(AlertEvent(
                        event_id=f"{level}-network-network_broken-{int(datetime.now(timezone.utc).timestamp())}",
                        severity="CRITICAL",
                        service="network", container=None,
                        check_type="network_broken",
                        patrol_level=level,
                        timestamp=datetime.now(timezone.utc),
                        summary="Docker network broken — nftables stale rules",
                        details=f"Stale bridges: {stale_summary}. Failed probes: {probe_summary}. Heal failed: {heal.get('error', 'unknown')}",
                        heal_attempted=True,
                        heal_success=False,
                        heal_action="nftables flush + docker restart",
                        restart_attempts=0, restart_suppressed=False,
                    ))
```

**Call 8** (VPS load, ~line 403):

Replace:
```python
                    await self.alert_manager.send(
                        f"VPS load critical: {detail} -- {vls['type']} threshold exceeded.")
                    results["failed"] += 1
```

With:
```python
                    results["events"].append(AlertEvent(
                        event_id=f"{level}-vps_load-vps_load_high-{int(datetime.now(timezone.utc).timestamp())}",
                        severity="WARNING",
                        service="vps_load", container=None,
                        check_type="vps_load_high",
                        patrol_level=level,
                        timestamp=datetime.now(timezone.utc),
                        summary=f"VPS load critical: {detail}",
                        details=f"{vls['type']} threshold exceeded: {detail}",
                        heal_attempted=False, heal_success=None, heal_action=None,
                        restart_attempts=0, restart_suppressed=False,
                    ))
                    results["failed"] += 1
```

Note: The `ollama` alert (`~line 390`) stays as `alert_manager.send()` since ollama is disabled in config (`enabled: false`). If you prefer consistency, convert it too, but it's dead code.

- [ ] **Step 6: Run all correlator tests**

Run: `cd /home/development/src/active/sowknow4/monitoring/guardian-hc && python -m pytest tests/ -v`

Expected: All tests PASS

- [ ] **Step 7: Commit**

```bash
cd /home/development/src/active/sowknow4
git add monitoring/guardian-hc/guardian_hc/core.py monitoring/guardian-hc/tests/test_core_events.py
git commit -m "refactor(guardian): replace 8 alert_manager.send() calls with AlertEvent emissions"
```

---

### Task 6: Wire Correlator into PatrolRunner

**Files:**
- Modify: `monitoring/guardian-hc/guardian_hc/patrol/runner.py`
- Modify: `monitoring/guardian-hc/guardian_hc/core.py` (init correlator)

- [ ] **Step 1: Add IncidentCorrelator initialization to GuardianHC.__init__**

In `monitoring/guardian-hc/guardian_hc/core.py`, add to `__init__` (after `self.patrol_runner = PatrolRunner(self)` on line 137):

```python
        from guardian_hc.correlator import IncidentCorrelator
        self.correlator = IncidentCorrelator(self.alert_manager)
```

- [ ] **Step 2: Modify PatrolRunner to call correlator.process()**

In `monitoring/guardian-hc/guardian_hc/patrol/runner.py`, modify `_run_patrol`:

Replace the entire `_run_patrol` method:

```python
    async def _run_patrol(self, name: str, level: str, interval_sec: int):
        logger.info(f"patrol.{name}.started", interval=interval_sec)
        while True:
            try:
                result = await self.guardian.run_check_cycle(level)
                healed = result.get("healed", 0)
                failed = result.get("failed", 0)
                if healed > 0 or failed > 0:
                    logger.info(f"patrol.{name}.complete", healed=healed, failed=failed)

                # Correlate events and send grouped alerts
                await self.guardian.correlator.process(result)
            except Exception as e:
                logger.error(f"patrol.{name}.error", error=str(e)[:200])
            await asyncio.sleep(interval_sec)
```

- [ ] **Step 3: Run all tests**

Run: `cd /home/development/src/active/sowknow4/monitoring/guardian-hc && python -m pytest tests/ -v`

Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
cd /home/development/src/active/sowknow4
git add monitoring/guardian-hc/guardian_hc/core.py monitoring/guardian-hc/guardian_hc/patrol/runner.py
git commit -m "feat(guardian): wire IncidentCorrelator into patrol runner"
```

---

### Task 7: State Persistence Tests

**Files:**
- Modify: `monitoring/guardian-hc/tests/test_correlator.py`

- [ ] **Step 1: Write tests for state persistence and sequence counter**

Append to `monitoring/guardian-hc/tests/test_correlator.py`:

```python
class TestStatePersistence:
    def _make_correlator(self, tmp_path):
        import guardian_hc.correlator as mod
        mod.STATE_FILE = str(tmp_path / "guardian-active-incidents.json")
        mod.JSONL_FILE = str(tmp_path / "incidents.jsonl")

        class FakeAlertManager:
            def __init__(self):
                self.messages = []
            async def send(self, message):
                self.messages.append(message)

        return IncidentCorrelator(FakeAlertManager())

    def test_sequence_resets_daily(self):
        correlator = self._make_correlator(pytest.importorskip("tmp_path", reason="need tmp_path"))
        # This test uses the internal _next_incident_id
        import guardian_hc.correlator as mod
        # Simulate yesterday's state
        correlator._sequence = {"date": "20260408", "counter": 5}
        new_id = correlator._next_incident_id()
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        assert new_id == f"INC-{today}-001"
        assert correlator._sequence["counter"] == 1

    def test_sequence_increments(self, tmp_path):
        correlator = self._make_correlator(tmp_path)
        id1 = correlator._next_incident_id()
        id2 = correlator._next_incident_id()
        assert id1.endswith("-001")
        assert id2.endswith("-002")

    @pytest.mark.asyncio
    async def test_state_survives_restart(self, tmp_path):
        import guardian_hc.correlator as mod
        mod.STATE_FILE = str(tmp_path / "guardian-active-incidents.json")
        mod.JSONL_FILE = str(tmp_path / "incidents.jsonl")

        class FakeAlertManager:
            def __init__(self):
                self.messages = []
            async def send(self, message):
                self.messages.append(message)

        # First correlator — generate an incident ID
        c1 = IncidentCorrelator(FakeAlertManager())
        id1 = c1._next_incident_id()
        c1._save_state()

        # Second correlator — should continue from saved sequence
        c2 = IncidentCorrelator(FakeAlertManager())
        id2 = c2._next_incident_id()
        assert id1.endswith("-001")
        assert id2.endswith("-002")

    @pytest.mark.asyncio
    async def test_jsonl_appends_multiple_events(self, tmp_path):
        import guardian_hc.correlator as mod
        mod.STATE_FILE = str(tmp_path / "guardian-active-incidents.json")
        mod.JSONL_FILE = str(tmp_path / "incidents.jsonl")

        class FakeAlertManager:
            def __init__(self):
                self.messages = []
            async def send(self, message):
                self.messages.append(message)

        correlator = IncidentCorrelator(FakeAlertManager())

        # Open
        results = {"level": "critical", "events": [_make_event("postgres", "tcp_unhealthy")]}
        await correlator.process(results)

        # Resolve
        await correlator.process({"level": "critical", "events": []})

        jsonl_path = tmp_path / "incidents.jsonl"
        lines = jsonl_path.read_text().strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["event_type"] == "open"
        assert json.loads(lines[1])["event_type"] == "resolved"
```

- [ ] **Step 2: Run tests**

Run: `cd /home/development/src/active/sowknow4/monitoring/guardian-hc && python -m pytest tests/test_correlator.py::TestStatePersistence -v`

Expected: All tests PASS (implementation already exists from Task 3)

- [ ] **Step 3: Fix test_sequence_resets_daily fixture issue**

The `test_sequence_resets_daily` test uses `pytest.importorskip` incorrectly. Replace it with:

```python
    def test_sequence_resets_daily(self, tmp_path):
        correlator = self._make_correlator(tmp_path)
        correlator._sequence = {"date": "20260408", "counter": 5}
        new_id = correlator._next_incident_id()
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        assert new_id == f"INC-{today}-001"
        assert correlator._sequence["counter"] == 1
```

- [ ] **Step 4: Run all tests**

Run: `cd /home/development/src/active/sowknow4/monitoring/guardian-hc && python -m pytest tests/ -v`

Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
cd /home/development/src/active/sowknow4
git add monitoring/guardian-hc/tests/test_correlator.py
git commit -m "test(guardian): add state persistence and sequence counter tests"
```

---

### Task 8: Final Integration Verification

**Files:**
- No new files

- [ ] **Step 1: Run the full test suite**

Run: `cd /home/development/src/active/sowknow4/monitoring/guardian-hc && python -m pytest tests/ -v --tb=short`

Expected: All tests PASS

- [ ] **Step 2: Verify no remaining direct alert_manager.send() in core.py check cycle**

Run: `cd /home/development/src/active/sowknow4 && grep -n "alert_manager.send" monitoring/guardian-hc/guardian_hc/core.py`

Expected: Zero matches (all calls replaced with AlertEvent emissions). The only `alert_manager.send()` calls that remain should be in `correlator.py` (the correlator itself) and `_verify_alert_channels()` (deep patrol channel testing — this is OK, it's not an incident alert).

If `_verify_alert_channels` still has `send()` calls, that's fine — it tests whether Telegram/email are functional, not an incident alert.

- [ ] **Step 3: Verify correlator.py imports cleanly**

Run: `cd /home/development/src/active/sowknow4/monitoring/guardian-hc && python -c "from guardian_hc.correlator import AlertEvent, Incident, IncidentCorrelator, DEPENDENCY_MAP; print('OK')"`

Expected: `OK`

- [ ] **Step 4: Commit final state**

```bash
cd /home/development/src/active/sowknow4
git add -A monitoring/guardian-hc/
git commit -m "feat(guardian): AlertIQ incident correlator — complete implementation"
```
