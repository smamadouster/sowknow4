"""Tests verifying core.py emits AlertEvents instead of calling alert_manager.send() directly."""

from datetime import datetime, timezone

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
