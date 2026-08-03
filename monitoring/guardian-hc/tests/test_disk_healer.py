"""Tests for DiskHealer."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from guardian_hc.healers.disk_healer import DiskHealer


def _mock_client() -> MagicMock:
    client = MagicMock()
    client.post = AsyncMock(return_value=MagicMock(status_code=200))
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


def _mock_proc() -> AsyncMock:
    proc = AsyncMock()
    proc.communicate = AsyncMock(return_value=(b"", b""))
    return proc


class TestDiskHealer:
    @pytest.mark.asyncio
    async def test_prunes_build_cache_by_default(self):
        """2026-08-03: container/image prune alone could not get below the
        70% warn threshold — the hog was ~100GB of Docker build cache."""
        client = _mock_client()
        with patch("guardian_hc.healers.disk_healer.httpx.AsyncClient", return_value=client), \
             patch("guardian_hc.healers.disk_healer.asyncio.create_subprocess_shell",
                   new=AsyncMock(return_value=_mock_proc())):
            result = await DiskHealer().heal()
        assert result["healed"] is True
        paths = [c.args[0] for c in client.post.await_args_list]
        assert "/containers/prune" in paths
        assert "/images/prune" in paths
        assert "/build/prune" in paths
        assert "Build cache pruned" in result["actions"]

    @pytest.mark.asyncio
    async def test_build_cache_prune_can_be_disabled(self):
        client = _mock_client()
        with patch("guardian_hc.healers.disk_healer.httpx.AsyncClient", return_value=client), \
             patch("guardian_hc.healers.disk_healer.asyncio.create_subprocess_shell",
                   new=AsyncMock(return_value=_mock_proc())):
            result = await DiskHealer({"auto_clean": {"build_cache_prune": False}}).heal()
        assert result["healed"] is True
        paths = [c.args[0] for c in client.post.await_args_list]
        assert "/build/prune" not in paths
