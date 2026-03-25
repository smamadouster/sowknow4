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
"""

import asyncio
import re
import subprocess

import httpx


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
        if stale:
            results["needs_healing"] = True
            results["heal_action"] = "flush_stale_nftables"

        # --- Check 2: Inter-container TCP probes ---
        for pair in self.probe_pairs:
            probe = await self._tcp_probe(
                pair["from"], pair["to_host"], pair["to_port"],
            )
            results["probe_results"].append(probe)
            if not probe["ok"]:
                results["needs_healing"] = True
                if not results["heal_action"]:
                    results["heal_action"] = "flush_stale_nftables"

        return results

    async def _find_stale_nftables_bridges(self) -> list[dict]:
        """Compare bridge IDs in nftables rules vs actually existing bridges."""
        stale = []
        try:
            # Get all bridge IDs referenced in nftables
            nft_proc = await asyncio.create_subprocess_exec(
                "nft", "list", "ruleset",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(nft_proc.communicate(), timeout=10)
            nft_output = stdout.decode()
            nft_bridges = set(re.findall(r'br-[a-f0-9]{12}', nft_output))

            # Get actually existing bridges
            ip_proc = await asyncio.create_subprocess_exec(
                "ip", "link", "show", "type", "bridge",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(ip_proc.communicate(), timeout=5)
            ip_output = stdout.decode()
            real_bridges = set(re.findall(r'br-[a-f0-9]{12}', ip_output))

            for dead_br in nft_bridges - real_bridges:
                # Count how many rules reference this dead bridge
                count = nft_output.count(dead_br)
                stale.append({"bridge": dead_br, "rule_count": count})

        except Exception as e:
            stale.append({"bridge": "error", "error": str(e)[:200]})

        return stale

    async def _tcp_probe(self, container: str, host: str, port: int) -> dict:
        """Test TCP connectivity from one container to another via Docker exec."""
        result = {"from": container, "to": f"{host}:{port}", "ok": False}
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "exec", container,
                "python", "-c",
                f"import socket; s=socket.socket(); s.settimeout(3); s.connect(('{host}',{port})); s.close(); print('OK')",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
            result["ok"] = b"OK" in stdout
            if not result["ok"]:
                result["error"] = stderr.decode()[:100] or "timeout"
        except asyncio.TimeoutError:
            result["error"] = "probe timed out"
        except Exception as e:
            result["error"] = str(e)[:100]
        return result
