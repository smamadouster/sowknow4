"""Tests for the vps_load sustained-window gate in core.run_check_cycle.

2026-08-04: shared-VPS steal/load flapped across patrols, opening and resolving
vps_load incidents every cycle and spamming Telegram. A vps_load event must
only be emitted once the condition has been sustained for `sustain_seconds`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from guardian_hc.core import GuardianConfig, GuardianHC


def _make_guardian(sustain_seconds: float = 600) -> GuardianHC:
    config = GuardianConfig(
        app_name="TestApp",
        services=[],
        alerts={},
        vps_load={"sustain_seconds": sustain_seconds},
    )
    return GuardianHC(config)


def _stub_checkers(guardian: GuardianHC, vps_result: list[dict]) -> None:
    """Stub every checker run_check_cycle touches, leaving vps_load real-ish."""
    guardian.container_checker.check = AsyncMock(return_value={})
    guardian.disk_checker.check = AsyncMock(
        return_value={"needs_healing": False, "usage_pct": 40}
    )
    guardian.memory_checker.check = AsyncMock(return_value=[])
    guardian.celery_checker.check = AsyncMock(return_value=[])
    guardian.ollama_checker.check = AsyncMock(return_value={"needs_healing": False})
    guardian.vps_load_checker = AsyncMock()
    guardian.vps_load_checker.check = AsyncMock(return_value=vps_result)


VPS_OVER = [
    {"type": "steal_time", "steal_pct": 38.2, "needs_healing": True},
]
VPS_OK = [
    {"type": "steal_time", "steal_pct": 12.0, "needs_healing": False},
]


class TestVpsLoadSustainGate:
    @pytest.mark.asyncio
    async def test_brief_blip_does_not_open_incident(self):
        g = _make_guardian(sustain_seconds=600)
        _stub_checkers(g, VPS_OVER)
        res = await g.run_check_cycle("standard")
        assert res["events"] == []
        assert res["failed"] == 0
        # The episode is being tracked, but has not yet crossed the window.
        assert "steal_time" in g._vps_load_since

    @pytest.mark.asyncio
    async def test_sustained_condition_emits_event_after_window(self):
        g = _make_guardian(sustain_seconds=600)
        _stub_checkers(g, VPS_OVER)
        # Episode started 15 minutes ago (already beyond the 10 min window).
        g._vps_load_since["steal_time"] = datetime.now(timezone.utc) - timedelta(
            minutes=15
        )
        res = await g.run_check_cycle("standard")
        assert len(res["events"]) == 1
        assert res["failed"] == 1
        assert res["events"][0].service == "vps_load"
        assert "Steal=38.2%" in res["events"][0].summary

    @pytest.mark.asyncio
    async def test_recovery_resets_state(self):
        g = _make_guardian(sustain_seconds=600)
        _stub_checkers(g, VPS_OVER)
        await g.run_check_cycle("standard")
        assert "steal_time" in g._vps_load_since
        # Load recovers — the tracking state must clear.
        _stub_checkers(g, VPS_OK)
        await g.run_check_cycle("standard")
        assert "steal_time" not in g._vps_load_since

    @pytest.mark.asyncio
    async def test_zero_sustain_window_emits_immediately(self):
        g = _make_guardian(sustain_seconds=0)
        _stub_checkers(g, VPS_OVER)
        res = await g.run_check_cycle("standard")
        assert len(res["events"]) == 1
