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
