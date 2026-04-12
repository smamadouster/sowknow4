# nftables Permanent Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permanently auto-heal stale Docker nftables DROP rules that break inter-container networking, via surgical per-handle deletion in both the host watchdog (primary, 2-min cycle) and Guardian HC (secondary, fixes broken detector + healer).

**Architecture:** The host watchdog (`watchdog.sh`) gains a new `check_nftables_stale_rules()` function that runs every 2 minutes as root, detects stale handles by diffing `nft -a list chain ip raw PREROUTING` against live Docker network IDs, and deletes them surgically with no Docker restart. Guardian's detector is fixed to use the Docker socket API (not `ip link`) for accurate live bridge enumeration; the healer is rewritten to use the same surgical per-handle approach.

**Tech Stack:** Bash (watchdog), Python 3.11 + asyncio + httpx (Guardian), pytest + unittest.mock (tests), nftables CLI on host.

---

## File Map

| File | Change |
|------|--------|
| `monitoring/guardian-hc/scripts/watchdog.sh` | Add `check_nftables_stale_rules()`, call from `main()` |
| `monitoring/guardian-hc/guardian_hc/checks/network_health.py` | Fix `_find_stale_nftables_bridges()` — Docker socket API + handle extraction |
| `monitoring/guardian-hc/guardian_hc/healers/network_healer.py` | Rewrite `heal()` — surgical per-handle deletion + `_tcp_probe_verify()` helper |
| `monitoring/guardian-hc/tests/test_network_health.py` | New — unit tests for detector |
| `monitoring/guardian-hc/tests/test_network_healer.py` | New — unit tests for healer |

---

### Task 1: Failing tests for Guardian detector

**Files:**
- Create: `monitoring/guardian-hc/tests/test_network_health.py`

Background: `_find_stale_nftables_bridges()` currently uses `ip link show type bridge`
to get live bridges — but dead Docker bridges linger in the kernel, so the set
difference always returns empty. The fix uses the Docker socket API for live networks
and parses `nft -a list chain ip raw PREROUTING` (specific chain with handles).

The raw PREROUTING line format is:
```
ip daddr 172.18.0.5 iifname != "br-6d25c565a449" ... drop # handle 7
```
The regex `r'iifname[^"]*"(br-[a-f0-9]{12})"'` matches the bridge name from any
`iifname` expression regardless of operator (`!=`, `==`, bare).

- [ ] **Step 1: Create the test file**

```python
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
```

- [ ] **Step 2: Run tests — confirm they all fail**

```bash
cd /home/development/src/active/sowknow4/monitoring/guardian-hc
python3 -m pytest tests/test_network_health.py -v 2>&1 | tail -20
```

Expected: 5 failures — `_find_stale_nftables_bridges` still uses old `ip link` approach.

---

### Task 2: Fix Guardian detector

**Files:**
- Modify: `monitoring/guardian-hc/guardian_hc/checks/network_health.py`

Replace `_find_stale_nftables_bridges()` entirely. The method uses:
1. Docker socket `GET /networks` → live bridge IDs (first 12 hex chars of network ID)
2. `nsenter nft -a list chain ip raw PREROUTING` → extract `(bridge, handle)` pairs
3. Set difference → stale entries with handles list

- [ ] **Step 1: Replace `_find_stale_nftables_bridges()` in `network_health.py`**

Open `monitoring/guardian-hc/guardian_hc/checks/network_health.py`.

Replace the entire `_find_stale_nftables_bridges` method (lines 81–107) with:

```python
    async def _find_stale_nftables_bridges(self) -> list[dict]:
        """Compare bridge IDs in nftables raw PREROUTING vs live Docker networks.

        Uses Docker socket API for authoritative live bridge list — NOT ip link,
        which retains dead bridge interfaces in the kernel for seconds after removal.

        Returns a list of dicts:
            {"bridge": "br-XXXX", "handles": [3, 7, 10], "rule_count": 3}
        On error returns [{"bridge": "error", "error": "..."}].
        """
        try:
            # 1. Live bridge IDs from Docker socket (first 12 hex chars of network ID)
            transport = httpx.AsyncHTTPTransport(uds="/var/run/docker.sock")
            async with httpx.AsyncClient(
                transport=transport, base_url="http://docker", timeout=5
            ) as client:
                resp = await client.get("/networks")
                live_bridges = {
                    net["Id"][:12]
                    for net in resp.json()
                    if net.get("Driver") == "bridge"
                }

            # 2. Parse raw PREROUTING chain on host with handle numbers
            rc, nft_out, _ = await _host_exec(
                "nft", "-a", "list", "chain", "ip", "raw", "PREROUTING",
                timeout=10,
            )
            if rc != 0:
                return []

            # 3. Build bridge → [handles] map
            #    Line example:
            #    ip daddr 1.2.3.4 iifname != "br-6d25c565a449" ... drop # handle 7
            bridge_handles: dict[str, list[int]] = {}
            for line in nft_out.splitlines():
                m_bridge = re.search(r'iifname[^"]*"(br-[a-f0-9]{12})"', line)
                m_handle = re.search(r'#\s+handle\s+(\d+)', line)
                if m_bridge and m_handle:
                    br = m_bridge.group(1)
                    bridge_handles.setdefault(br, []).append(int(m_handle.group(1)))

            # 4. Stale = referenced in rules but absent from live Docker networks
            stale = []
            for br, handles in bridge_handles.items():
                br_id = br.replace("br-", "")
                if br_id not in live_bridges:
                    stale.append({
                        "bridge": br,
                        "handles": handles,
                        "rule_count": len(handles),
                    })
            return stale

        except Exception as e:
            return [{"bridge": "error", "error": str(e)[:200]}]
```

- [ ] **Step 2: Run detector tests — all pass**

```bash
cd /home/development/src/active/sowknow4/monitoring/guardian-hc
python3 -m pytest tests/test_network_health.py -v 2>&1 | tail -20
```

Expected: 5 passed.

- [ ] **Step 3: Run full test suite — no regressions**

```bash
python3 -m pytest tests/ -q --no-header 2>&1 | tail -5
```

Expected: 275 passed (270 pre-existing + 5 new).

- [ ] **Step 4: Commit**

```bash
cd /home/development/src/active/sowknow4
git add monitoring/guardian-hc/guardian_hc/checks/network_health.py \
        monitoring/guardian-hc/tests/test_network_health.py
git commit -m "fix(guardian): detector uses Docker socket API to find stale nftables bridges

Replaced ip link show with GET /networks via Docker socket — ip link
retains dead bridge interfaces in the kernel so the stale-bridge set
difference always returned empty. Now parses nft -a list chain ip raw
PREROUTING for (bridge, handle) pairs and diffs against live Docker
network IDs, returning handles for surgical deletion.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 3: Failing tests for Guardian healer

**Files:**
- Create: `monitoring/guardian-hc/tests/test_network_healer.py`

The healer currently does a disruptive 3-step: flush entire raw PREROUTING → restart
Docker daemon → force-recreate all containers. The rewrite does surgical per-handle
deletion (`nft delete rule ip raw PREROUTING handle N`), TCP probes to verify, and
only falls back to flush+restart if handles can't be deleted AND probes still fail.

- [ ] **Step 1: Create the test file**

```python
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
```

- [ ] **Step 2: Run tests — confirm they all fail**

```bash
cd /home/development/src/active/sowknow4/monitoring/guardian-hc
python3 -m pytest tests/test_network_healer.py -v 2>&1 | tail -20
```

Expected: 6 failures — `heal()` doesn't yet do surgical deletion.

---

### Task 4: Rewrite Guardian healer

**Files:**
- Modify: `monitoring/guardian-hc/guardian_hc/healers/network_healer.py`

Replace the entire file contents:

- [ ] **Step 1: Rewrite `network_healer.py`**

```python
"""
Guardian HC -- Docker network healer.

Fixes stale nftables rules that break inter-container networking by
surgically deleting only the identified stale handles.

The heal strategy (fast path — no Docker restart needed):
  1. For each stale handle: nft delete rule ip raw PREROUTING handle N
  2. TCP probe to verify connectivity restored
  3. If probe still fails: fallback to flush entire chain + docker restart

Commands run on the HOST via nsenter (PID 1).
"""

import asyncio
import structlog

logger = structlog.get_logger()


async def _host_exec(*cmd: str, timeout: int = 30) -> tuple[int, str, str]:
    """Run a command on the host via nsenter into PID 1."""
    proc = await asyncio.create_subprocess_exec(
        "nsenter", "--target", "1", "--mount", "--uts", "--ipc", "--net", "--pid",
        "--", *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    return proc.returncode, stdout.decode(), stderr.decode()


class NetworkHealer:
    def __init__(self, config: dict = None):
        self.config = config or {}
        self.compose_file = self.config.get(
            "compose_file", "/var/docker/sowknow4/docker-compose.yml"
        )

    async def heal(self, stale_bridges: list[dict] = None) -> dict:
        """Surgically delete stale nftables handles to restore inter-container networking.

        Args:
            stale_bridges: list of dicts from NetworkHealthChecker, each containing
                           {"bridge": "br-XXXX", "handles": [3, 7, 10], "rule_count": N}
                           Entries without a "handles" key are skipped (old format).

        Returns:
            {"healed": bool, "actions": [str, ...], "error"?: str}
        """
        actions: list[str] = []

        # Filter to entries that have handles (new detector format)
        stale = [s for s in (stale_bridges or []) if s.get("handles")]
        if not stale:
            return {"healed": False, "error": "no stale handles to delete", "actions": actions}

        logger.warning(
            "network_healer.deleting_stale_handles",
            bridges=[s["bridge"] for s in stale],
            total_handles=sum(len(s["handles"]) for s in stale),
        )

        # Step 1: Surgical deletion — one nft call per stale handle
        deleted: list[int] = []
        failed: list[tuple[int, str]] = []

        for entry in stale:
            for handle in entry["handles"]:
                rc, _, err = await _host_exec(
                    "nft", "delete", "rule", "ip", "raw", "PREROUTING",
                    "handle", str(handle),
                    timeout=10,
                )
                if rc == 0:
                    deleted.append(handle)
                    logger.info(
                        "network_healer.handle_deleted",
                        handle=handle,
                        bridge=entry["bridge"],
                    )
                else:
                    failed.append((handle, err.strip()[:80]))
                    logger.warning(
                        "network_healer.handle_delete_failed",
                        handle=handle,
                        error=err.strip()[:80],
                    )

        if deleted:
            actions.append(f"deleted stale handles: {deleted}")
        if failed:
            actions.append(f"failed handles: {failed}")

        # Step 2: TCP probe to verify connectivity restored
        probe_ok = await self._tcp_probe_verify()
        if probe_ok:
            logger.info("network_healer.complete", healed=True, actions=actions)
            return {"healed": True, "actions": actions}

        # Step 3: Fallback — flush entire chain + restart Docker
        # Used when surgical deletion wasn't sufficient (e.g. nft version quirk).
        logger.warning("network_healer.fallback_flush", reason="probe still failing after handle deletion")
        rc, _, err = await _host_exec(
            "nft", "flush", "chain", "ip", "raw", "PREROUTING",
            timeout=10,
        )
        if rc == 0:
            actions.append("fallback: nftables raw PREROUTING flushed")
            rc2, _, _ = await _host_exec(
                "systemctl", "restart", "docker",
                timeout=60,
            )
            if rc2 == 0:
                actions.append("fallback: Docker daemon restarted")

        healed = bool(deleted)  # partial success if we deleted at least something
        logger.info("network_healer.complete", healed=healed, actions=actions)
        return {"healed": healed, "actions": actions}

    async def _tcp_probe_verify(self) -> bool:
        """Quick TCP probe: backend → redis:6379. Returns True if OK."""
        cmd = (
            "python3 -c \""
            "import socket; s=socket.socket(); s.settimeout(3); "
            "s.connect(('redis', 6379)); print('ok')\""
        )
        rc, out, _ = await _host_exec(
            "docker", "exec", "sowknow4-backend",
            "sh", "-c", cmd,
            timeout=10,
        )
        return rc == 0 and "ok" in out
```

- [ ] **Step 2: Run healer tests — all pass**

```bash
cd /home/development/src/active/sowknow4/monitoring/guardian-hc
python3 -m pytest tests/test_network_healer.py -v 2>&1 | tail -20
```

Expected: 6 passed.

- [ ] **Step 3: Run full test suite — no regressions**

```bash
python3 -m pytest tests/ -q --no-header 2>&1 | tail -5
```

Expected: 281 passed (270 pre-existing + 5 detector + 6 healer).

- [ ] **Step 4: Commit**

```bash
cd /home/development/src/active/sowknow4
git add monitoring/guardian-hc/guardian_hc/healers/network_healer.py \
        monitoring/guardian-hc/tests/test_network_healer.py
git commit -m "fix(guardian): rewrite healer to use surgical per-handle nft deletion

Replaces 3-step flush+docker-restart+service-recreate (~5min downtime)
with surgical nft delete rule per stale handle (zero downtime, instant).
Detector now returns handles so healer can act without re-parsing.
TCP probe verification added post-heal. Fallback to flush+restart only
if probe still fails after handle deletion.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 5: Add `check_nftables_stale_rules()` to watchdog

**Files:**
- Modify: `monitoring/guardian-hc/scripts/watchdog.sh`

This is the primary heal path (root, host, every 2 minutes). It reads `nft -a list
chain ip raw PREROUTING`, diffs bridge names against live Docker network IDs, and
deletes stale handles surgically. A TCP probe gate prevents healing during clean
network teardown (stale handles present but connectivity fine).

- [ ] **Step 1: Add the function before `main()`**

Open `monitoring/guardian-hc/scripts/watchdog.sh`.

Insert the following block immediately before the `# -- Main --` comment (line 233):

```bash
# -- Check 6: Stale nftables handles from dead Docker bridges --
check_nftables_stale_rules() {
    # nft must be available (package: nftables)
    command -v nft > /dev/null 2>&1 || return

    # Get live Docker bridge IDs (first 12 hex chars of network ID)
    local live_bridges
    live_bridges=$(docker network ls --no-trunc --format '{{.ID}}' 2>/dev/null | cut -c1-12)
    [ -z "$live_bridges" ] && return

    # Read raw PREROUTING chain with handle numbers
    local nft_output
    nft_output=$(nft -a list chain ip raw PREROUTING 2>/dev/null)
    [ -z "$nft_output" ] && return

    # Find handles whose iifname bridge is absent from live Docker networks
    # Line format: ... iifname != "br-XXXXXXXXXXXX" ... # handle N
    local stale_handles=()
    while IFS= read -r line; do
        local bridge handle
        bridge=$(echo "$line" | grep -oP '"br-[a-f0-9]{12}"' | tr -d '"')
        handle=$(echo "$line" | grep -oP '#\s+handle\s+\K[0-9]+')
        [ -z "$bridge" ] || [ -z "$handle" ] && continue
        local br_id="${bridge#br-}"
        echo "$live_bridges" | grep -qF "$br_id" && continue   # bridge is live
        stale_handles+=("${handle}:${bridge}")
    done <<< "$nft_output"

    [ ${#stale_handles[@]} -eq 0 ] && return

    log "nftables: ${#stale_handles[@]} stale handle(s) found: ${stale_handles[*]}"

    # TCP probe gate: only heal if connectivity is actually broken.
    # Avoids false-positive heals during clean Docker network teardown.
    local probe_result
    probe_result=$(docker exec sowknow4-backend python3 -c \
        "import socket; s=socket.socket(); s.settimeout(3); s.connect(('redis',6379)); print('ok')" \
        2>/dev/null)
    if [ "$probe_result" = "ok" ]; then
        log "nftables: stale handles present but probes pass — skipping heal (network teardown?)"
        return
    fi

    # Surgical deletion
    local healed_count=0
    local failed_handles=()
    for entry in "${stale_handles[@]}"; do
        local h="${entry%%:*}"
        local br="${entry##*:}"
        if nft delete rule ip raw PREROUTING handle "$h" 2>/dev/null; then
            healed_count=$((healed_count + 1))
            log "nftables: deleted stale handle $h (bridge $br)"
        else
            failed_handles+=("$h")
            log "nftables: failed to delete handle $h"
        fi
    done

    # Verify
    probe_result=$(docker exec sowknow4-backend python3 -c \
        "import socket; s=socket.socket(); s.settimeout(3); s.connect(('redis',6379)); print('ok')" \
        2>/dev/null)

    if [ "$probe_result" = "ok" ]; then
        alert_healed "nftables stale handles healed: deleted $healed_count handle(s) from br-$(echo "${stale_handles[0]##*br-}" | cut -c1-12)... Connectivity restored."
    else
        local failed_str="${failed_handles[*]:-none}"
        alert "nftables heal FAILED. Deleted $healed_count handle(s), failed: $failed_str. Backend→redis probe still broken. Manual fix: sudo nft -a list chain ip raw PREROUTING — then sudo nft delete rule ip raw PREROUTING handle N for each stale handle."
    fi
}
```

- [ ] **Step 2: Add `check_nftables_stale_rules` call to `main()`**

In `main()` (currently lines 234–246), add the new check after `check_disk`:

```bash
main() {
    check_docker_daemon

    if ! docker info > /dev/null 2>&1; then
        return 1
    fi

    check_containers
    check_nftables_stale_rules
    check_api
    check_worker
    check_disk
    rotate_log
}
```

Note: `check_nftables_stale_rules` is placed **before** `check_api` intentionally —
stale nftables rules cause `check_api` to fail (backend→postgres broken), so we
heal the network first, then check API health. This avoids a false "backend down"
alert immediately followed by a "healed nftables" log.

- [ ] **Step 3: Verify the script is valid bash**

```bash
bash -n /home/development/src/active/sowknow4/monitoring/guardian-hc/scripts/watchdog.sh && echo "syntax OK"
```

Expected: `syntax OK`

- [ ] **Step 4: Smoke-test the function in dry-run mode (no stale rules present)**

Source only the function definitions without running `main()`:

```bash
bash -c '
  source <(grep -v "^main" /home/development/src/active/sowknow4/monitoring/guardian-hc/scripts/watchdog.sh | grep -v "^main$")
  check_nftables_stale_rules
  echo "exit: $?"
'
```

Expected: function runs, no output (no stale handles currently), exits 0.

- [ ] **Step 5: Commit**

```bash
cd /home/development/src/active/sowknow4
git add monitoring/guardian-hc/scripts/watchdog.sh
git commit -m "fix(watchdog): add check_nftables_stale_rules() — primary heal path

Detects stale Docker nftables DROP handles every 2 minutes on the host.
Diffs nft -a list chain ip raw PREROUTING bridge names against live
docker network IDs, TCP-probes before acting (avoids false heals during
clean teardown), and surgically deletes stale handles with no Docker
restart. Runs before check_api so network is healthy before API probe.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 6: Deploy and verify on VPS

**Files:** None — deploy only.

- [ ] **Step 1: Push to VPS and pull**

```bash
# From dev machine
cd /home/development/src/active/sowknow4
git push devrepo master

# On VPS
ssh vps "cd /var/docker/sowknow4 && git pull"
```

- [ ] **Step 2: Guardian container does not need rebuild**

Guardian bind-mounts its source at runtime (confirmed in docker-compose.yml). The
Python changes are live immediately — no image rebuild needed.

Verify the bind mount is in place:

```bash
ssh vps "docker inspect sowknow4-guardian-hc --format '{{json .Mounts}}' | python3 -m json.tool | grep guardian_hc"
```

Expected: line showing `./monitoring/guardian-hc/guardian_hc` → `/app/guardian_hc`.

- [ ] **Step 3: Restart Guardian to pick up new code**

```bash
ssh vps "cd /var/docker/sowknow4 && docker compose restart guardian-hc"
```

- [ ] **Step 4: Confirm Guardian starts cleanly**

```bash
ssh vps "docker logs sowknow4-guardian-hc --tail 20 2>&1"
```

Expected: no Python import errors, `guardian.started` log line.

- [ ] **Step 5: Verify watchdog script is synced on VPS**

The watchdog runs directly from the repo path (`/var/docker/sowknow4/monitoring/...`),
so the git pull already updated it. Confirm:

```bash
ssh vps "grep check_nftables /var/docker/sowknow4/monitoring/guardian-hc/scripts/watchdog.sh | head -3"
```

Expected: lines showing the function definition.

- [ ] **Step 6: Confirm watchdog cron is installed on VPS**

```bash
ssh vps "crontab -l | grep watchdog"
```

Expected: `*/2 * * * * /var/docker/sowknow4/monitoring/guardian-hc/scripts/watchdog.sh >> /var/log/sowknow4-watchdog.log 2>&1`

If missing, install it:
```bash
ssh vps "(crontab -l 2>/dev/null; echo '*/2 * * * * /var/docker/sowknow4/monitoring/guardian-hc/scripts/watchdog.sh >> /var/log/sowknow4-watchdog.log 2>&1') | crontab -"
```

- [ ] **Step 7: Validate watchdog syntax on VPS**

```bash
ssh vps "bash -n /var/docker/sowknow4/monitoring/guardian-hc/scripts/watchdog.sh && echo OK"
```

Expected: `OK`

- [ ] **Step 8: Update memory and buglog**

Append to `.wolf/memory.md`:
```
| HH:MM | Deployed nftables permanent fix — watchdog + guardian detector/healer | watchdog.sh, network_health.py, network_healer.py | deployed | ~2k |
```

Update `project_guardian_nftables_heal_broken.md` memory to reflect that the fix is deployed.
