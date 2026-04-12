"""Tests for NetworkHealer.heal() — surgical per-handle deletion.

Mocks at asyncio.create_subprocess_exec (the nsenter boundary).
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from guardian_hc.healers.network_healer import NetworkHealer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_healer() -> NetworkHealer:
    return NetworkHealer(config={
        "compose_file": "/var/docker/sowknow4/docker-compose.yml"
    })


def _stale(bridge: str, handles: list[int]) -> dict:
    return {"bridge": bridge, "handles": handles, "rule_count": len(handles)}


def _make_proc(rc: int = 0, stdout: str = "", stderr: str = ""):
    proc = MagicMock()
    proc.returncode = rc
    proc.communicate = AsyncMock(return_value=(stdout.encode(), stderr.encode()))
    return proc


# ---------------------------------------------------------------------------
# heal()
# ---------------------------------------------------------------------------

class TestHeal:

    @pytest.mark.asyncio
    async def test_deletes_each_stale_handle(self):
        """heal() calls nft delete rule for every handle in stale_bridges."""
        healer = _make_healer()
        stale = [_stale("br-6d25c565a449", [7, 10, 13])]

        # All nft delete calls succeed; probe returns "ok"
        procs = [_make_proc(0) for _ in range(3)] + [_make_proc(0, stdout="ok\n")]

        with patch("asyncio.create_subprocess_exec", side_effect=procs) as mock_exec:
            result = await healer.heal(stale_bridges=stale)

        assert result["healed"] is True
        # Verify nft delete was called with correct handle numbers
        delete_calls = [
            c for c in mock_exec.call_args_list
            if "delete" in c.args
        ]
        handles_deleted = [c.args[c.args.index("handle") + 1] for c in delete_calls]
        assert set(handles_deleted) == {"7", "10", "13"}

    @pytest.mark.asyncio
    async def test_returns_healed_false_when_no_handles(self):
        """heal() with empty stale_bridges returns healed=False immediately."""
        healer = _make_healer()
        result = await healer.heal(stale_bridges=[])
        assert result["healed"] is False
        assert "no stale handles" in result.get("error", "")

    @pytest.mark.asyncio
    async def test_returns_healed_false_when_stale_lacks_handles_key(self):
        """heal() skips entries without handles (old detector format)."""
        healer = _make_healer()
        stale = [{"bridge": "br-aaaaaa", "rule_count": 1}]  # no "handles" key
        result = await healer.heal(stale_bridges=stale)
        assert result["healed"] is False

    @pytest.mark.asyncio
    async def test_probe_failure_triggers_fallback(self):
        """If probe still fails after handle deletion, fallback flush+restart runs."""
        healer = _make_healer()
        stale = [_stale("br-6d25c565a449", [7])]

        delete_ok = _make_proc(0)
        probe_fail = _make_proc(0, stdout="timeout\n")   # not "ok"
        flush_ok = _make_proc(0)
        restart_ok = _make_proc(0)

        procs = [delete_ok, probe_fail, flush_ok, restart_ok]

        with patch("asyncio.create_subprocess_exec", side_effect=procs):
            result = await healer.heal(stale_bridges=stale)

        # healed is True because handle was deleted (fallback ran)
        assert result["healed"] is True
        actions_str = str(result.get("actions", []))
        assert "fallback" in actions_str

    @pytest.mark.asyncio
    async def test_partial_deletion_continues(self):
        """If one handle deletion fails, remaining handles are still attempted."""
        healer = _make_healer()
        stale = [_stale("br-6d25c565a449", [7, 10])]

        delete_fail = _make_proc(rc=1, stderr="no such rule")
        delete_ok = _make_proc(0)
        probe_ok = _make_proc(0, stdout="ok\n")

        procs = [delete_fail, delete_ok, probe_ok]

        with patch("asyncio.create_subprocess_exec", side_effect=procs):
            result = await healer.heal(stale_bridges=stale)

        assert result["healed"] is True
        actions_str = str(result.get("actions", []))
        assert "10" in actions_str   # handle 10 was deleted

    @pytest.mark.asyncio
    async def test_handles_across_multiple_bridges(self):
        """Handles from two stale bridge entries are all deleted."""
        healer = _make_healer()
        stale = [
            _stale("br-aaaaaaaaaaaa", [3, 5]),
            _stale("br-bbbbbbbbbbbb", [4]),
        ]

        procs = [_make_proc(0)] * 3 + [_make_proc(0, stdout="ok\n")]

        with patch("asyncio.create_subprocess_exec", side_effect=procs) as mock_exec:
            result = await healer.heal(stale_bridges=stale)

        assert result["healed"] is True
        delete_calls = [c for c in mock_exec.call_args_list if "delete" in c.args]
        assert len(delete_calls) == 3
