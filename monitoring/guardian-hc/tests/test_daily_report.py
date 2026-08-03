"""Tests for the daily health dashboard HTML (daily_report._generate_html)."""
from datetime import datetime, timezone

from guardian_hc.daily_report import _generate_html


def _metrics() -> dict:
    return {
        "hostname": "testhost",
        "ip": "127.0.0.1",
        "disk": {"pct": 50, "used": "100G", "total": "200G"},
        "memory": {"pct": 50, "used": "8Gi", "total": "16Gi"},
        "load": [1.0, 1.0, 1.0],
    }


def _now() -> datetime:
    return datetime(2026, 8, 3, 6, 0, 0, tzinfo=timezone.utc)


class TestIncidentRows:
    def test_v2_plugin_heal_success_renders_healed_not_pending(self):
        """v2 plugin heals log "success": True, not "healed" — the row must
        use the same condition as the counts, or successful heals render as
        red "Pending" (2026-08-03 dashboard: disk_cleanup rows)."""
        history = [
            {"target": "disk_usage", "action": "plugin_heal:disk_cleanup",
             "plugin": "infrastructure", "success": True, "details": "pruned"},
        ]
        html = _generate_html(_metrics(), [], history, _now())
        assert ">Healed</td>" in html
        # the static legend uses <div>; no incident row may render Pending
        assert ">Pending</td>" not in html

    def test_failed_heal_still_renders_pending(self):
        history = [
            {"target": "disk_usage", "action": "plugin_heal:disk_cleanup",
             "plugin": "infrastructure", "success": False, "details": "boom"},
        ]
        html = _generate_html(_metrics(), [], history, _now())
        assert ">Pending</td>" in html

    def test_v1_healed_entry_still_renders_healed(self):
        history = [
            {"target": "embed-server", "action": "restart_http_unhealthy",
             "healed": True},
        ]
        html = _generate_html(_metrics(), [], history, _now())
        assert ">Healed</td>" in html
        assert ">Pending</td>" not in html
