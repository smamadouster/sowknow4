"""Tests for NetworkHealthChecker._find_stale_nftables_bridges().

Mocks at two boundaries:
  - httpx Docker socket (GET /networks) for live bridge IDs
  - asyncio.create_subprocess_exec for nsenter nft commands
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from guardian_hc.checks.network_health import NetworkHealthChecker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_checker() -> NetworkHealthChecker:
    return NetworkHealthChecker(config={
        "probe_pairs": [
            {"from": "sowknow4-backend", "to_host": "redis", "to_port": 6379},
        ]
    })


def _fake_networks_response(bridge_ids: list[str]):
    """Build a fake Docker /networks JSON response."""
    return [
        {"Id": bid + "a" * (64 - len(bid)), "Driver": "bridge", "Name": f"net-{i}"}
        for i, bid in enumerate(bridge_ids)
    ]


NFT_OUTPUT_WITH_STALE = """\
table ip raw {
\tchain PREROUTING { # handle 1
\t\ttype filter hook prerouting priority raw; policy accept;
\t\tip daddr 172.18.0.5 iifname != "br-6d25c565a449" counter packets 17212 bytes 1032720 drop # handle 7
\t\tip daddr 172.18.0.7 iifname != "br-6d25c565a449" counter packets 23177 bytes 1390620 drop # handle 10
\t\tip daddr 172.18.0.5 iifname != "br-4c301de03a1f" counter packets 0 bytes 0 drop # handle 304
\t}
}
"""

NFT_OUTPUT_CLEAN = """\
table ip raw {
\tchain PREROUTING { # handle 1
\t\ttype filter hook prerouting priority raw; policy accept;
\t\tip daddr 172.18.0.5 iifname != "br-4c301de03a1f" counter packets 0 bytes 0 drop # handle 304
\t}
}
"""

NFT_OUTPUT_EMPTY = "table ip raw {\n\tchain PREROUTING { # handle 1\n\t}\n}\n"


def _make_nft_proc(output: str, rc: int = 0):
    """Return a mock process for asyncio.create_subprocess_exec."""
    proc = MagicMock()
    proc.returncode = rc
    proc.communicate = AsyncMock(
        return_value=(output.encode(), b"")
    )
    return proc


# ---------------------------------------------------------------------------
# _find_stale_nftables_bridges
# ---------------------------------------------------------------------------

class TestFindStaleBridges:

    @pytest.mark.asyncio
    async def test_returns_stale_bridge_with_handles(self):
        """Bridges in nft rules but absent from Docker /networks are returned
        with their handle numbers."""
        checker = _make_checker()
        # Live bridge: only br-4c301de03a1f (the current sowknow-net)
        live_id = "4c301de03a1f"
        networks = _fake_networks_response([live_id])

        mock_response = MagicMock()
        mock_response.json.return_value = networks

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        nft_proc = _make_nft_proc(NFT_OUTPUT_WITH_STALE)

        with patch("guardian_hc.checks.network_health.httpx.AsyncClient",
                   return_value=mock_client), \
             patch("asyncio.create_subprocess_exec",
                   return_value=nft_proc):
            result = await checker._find_stale_nftables_bridges()

        assert len(result) == 1
        entry = result[0]
        assert entry["bridge"] == "br-6d25c565a449"
        assert set(entry["handles"]) == {7, 10}
        assert entry["rule_count"] == 2

    @pytest.mark.asyncio
    async def test_returns_empty_when_all_bridges_live(self):
        """No stale result when every iifname bridge matches a live Docker network."""
        checker = _make_checker()
        live_id = "4c301de03a1f"
        networks = _fake_networks_response([live_id])

        mock_response = MagicMock()
        mock_response.json.return_value = networks

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        nft_proc = _make_nft_proc(NFT_OUTPUT_CLEAN)

        with patch("guardian_hc.checks.network_health.httpx.AsyncClient",
                   return_value=mock_client), \
             patch("asyncio.create_subprocess_exec",
                   return_value=nft_proc):
            result = await checker._find_stale_nftables_bridges()

        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_when_nft_fails(self):
        """If nft command returns non-zero, return empty (nft unavailable)."""
        checker = _make_checker()
        networks = _fake_networks_response(["4c301de03a1f"])

        mock_response = MagicMock()
        mock_response.json.return_value = networks

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        nft_proc = _make_nft_proc("", rc=1)

        with patch("guardian_hc.checks.network_health.httpx.AsyncClient",
                   return_value=mock_client), \
             patch("asyncio.create_subprocess_exec",
                   return_value=nft_proc):
            result = await checker._find_stale_nftables_bridges()

        assert result == []

    @pytest.mark.asyncio
    async def test_returns_error_entry_on_exception(self):
        """If Docker socket call raises, return a single error entry."""
        checker = _make_checker()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(side_effect=Exception("socket error"))
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("guardian_hc.checks.network_health.httpx.AsyncClient",
                   return_value=mock_client):
            result = await checker._find_stale_nftables_bridges()

        assert len(result) == 1
        assert "error" in result[0]

    @pytest.mark.asyncio
    async def test_multiple_stale_bridges_grouped_correctly(self):
        """Two different dead bridges are returned as two separate entries."""
        checker = _make_checker()
        live_id = "4c301de03a1f"
        networks = _fake_networks_response([live_id])

        nft_two_stale = """\
table ip raw {
\tchain PREROUTING { # handle 1
\t\tip daddr 172.18.0.5 iifname != "br-aaaaaaaaaaaa" drop # handle 3
\t\tip daddr 172.23.0.2 iifname != "br-bbbbbbbbbbbb" drop # handle 4
\t\tip daddr 172.18.0.7 iifname != "br-aaaaaaaaaaaa" drop # handle 5
\t\tip daddr 172.18.0.5 iifname != "br-4c301de03a1f" drop # handle 99
\t}
}
"""
        mock_response = MagicMock()
        mock_response.json.return_value = _fake_networks_response([live_id])

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        nft_proc = _make_nft_proc(nft_two_stale)

        with patch("guardian_hc.checks.network_health.httpx.AsyncClient",
                   return_value=mock_client), \
             patch("asyncio.create_subprocess_exec",
                   return_value=nft_proc):
            result = await checker._find_stale_nftables_bridges()

        assert len(result) == 2
        bridges = {e["bridge"] for e in result}
        assert bridges == {"br-aaaaaaaaaaaa", "br-bbbbbbbbbbbb"}
        aa = next(e for e in result if e["bridge"] == "br-aaaaaaaaaaaa")
        assert set(aa["handles"]) == {3, 5}
        bb = next(e for e in result if e["bridge"] == "br-bbbbbbbbbbbb")
        assert set(bb["handles"]) == {4}
