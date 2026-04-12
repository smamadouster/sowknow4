"""
Guardian HC -- Docker network health check.

Detects two critical failure modes on Docker 29.x with nftables:
  1. Stale nftables raw PREROUTING rules from dead bridges
  2. Broken inter-container connectivity (TCP probe)

Background:
  Docker 29.x on Ubuntu 24.04 uses iptables-nft (nftables backend).
  When a bridge network is destroyed and recreated, the bridge gets a new
  ID but Docker does NOT clean up old nftables `raw PREROUTING` DROP rules.
  If the same subnet is reused, stale rules from the dead bridge drop all
  packets before iptables even sees them -- killing ALL inter-container
  networking on that subnet. This affects every app on the VPS.

Detection commands run on the HOST via nsenter (PID 1), since nft/ip
are not available inside the container.
"""

import asyncio
import re

import httpx


async def _host_exec(*cmd: str, timeout: int = 10) -> tuple[int, str, str]:
    """Run a command on the host via nsenter into PID 1."""
    proc = await asyncio.create_subprocess_exec(
        "nsenter", "--target", "1", "--mount", "--uts", "--ipc", "--net", "--pid",
        "--", *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    return proc.returncode, stdout.decode(), stderr.decode()


class NetworkHealthChecker:
    """Check Docker bridge network health and detect stale nftables rules."""

    def __init__(self, config: dict = None):
        cfg = config or {}
        self.probe_pairs = cfg.get("probe_pairs", [
            {"from": "sowknow4-backend", "to_host": "redis", "to_port": 6379},
            {"from": "sowknow4-backend", "to_host": "postgres", "to_port": 5432},
        ])

    async def check(self) -> dict:
        results = {
            "stale_bridges": [],
            "probe_results": [],
            "needs_healing": False,
            "heal_action": None,
        }

        # --- Check 1: Stale nftables rules ---
        stale = await self._find_stale_nftables_bridges()
        results["stale_bridges"] = stale
        if stale and not any(s.get("error") for s in stale):
            results["needs_healing"] = True
            results["heal_action"] = "flush_stale_nftables"

        # --- Check 2: Inter-container TCP probes ---
        probes_failed = 0
        for pair in self.probe_pairs:
            probe = await self._tcp_probe(
                pair["from"], pair["to_host"], pair["to_port"],
            )
            results["probe_results"].append(probe)
            if not probe["ok"]:
                probes_failed += 1

        # Only trigger healing if stale nftables bridges were found.
        # Probe-only failures are reported but NOT auto-healed — they're
        # usually transient (container restarting) not nftables bugs.
        if probes_failed > 0 and not stale:
            results["probes_degraded"] = True

        return results

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

    async def _tcp_probe(self, container: str, host: str, port: int) -> dict:
        """Test TCP connectivity from one container to another via Docker API exec."""
        result = {"from": container, "to": f"{host}:{port}", "ok": False}
        try:
            transport = httpx.AsyncHTTPTransport(uds="/var/run/docker.sock")
            async with httpx.AsyncClient(transport=transport, base_url="http://docker", timeout=10) as client:
                # Find container ID
                resp = await client.get("/containers/json")
                cid = None
                for c in resp.json():
                    if any(container in n for n in c.get("Names", [])):
                        cid = c["Id"]
                        break
                if not cid:
                    result["error"] = f"container {container} not found"
                    return result

                # Create exec instance
                cmd = f"import socket; s=socket.socket(); s.settimeout(3); s.connect(('{host}',{port})); s.close(); print('OK')"
                exec_resp = await client.post(
                    f"/containers/{cid}/exec",
                    json={"Cmd": ["python", "-c", cmd], "AttachStdout": True, "AttachStderr": True},
                )
                exec_id = exec_resp.json().get("Id")
                if not exec_id:
                    result["error"] = "exec create failed"
                    return result

                # Start exec and read output
                start_resp = await client.post(
                    f"/exec/{exec_id}/start",
                    json={"Detach": False},
                )
                result["ok"] = b"OK" in start_resp.content
                if not result["ok"]:
                    result["error"] = start_resp.text[:100] or "no OK in output"
        except Exception as e:
            result["error"] = str(e)[:100]
        return result
