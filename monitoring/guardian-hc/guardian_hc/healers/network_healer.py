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
