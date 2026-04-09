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
