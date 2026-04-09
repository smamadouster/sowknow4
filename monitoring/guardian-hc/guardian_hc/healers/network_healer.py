"""
Guardian HC -- Docker network healer.

Fixes stale nftables rules that break inter-container networking.

The healing strategy is conservative:
  1. Flush ONLY the nftables raw PREROUTING chain (where stale rules live)
  2. Restart Docker daemon so it recreates correct rules for active networks
  3. Restart the compose stack to reconnect all containers

Commands run on the HOST via nsenter (PID 1), since nft/systemctl
are not available inside the container.
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
        self.compose_file = self.config.get("compose_file", "/var/docker/sowknow4/docker-compose.yml")

    async def heal(self, stale_bridges: list[dict] = None) -> dict:
        """Flush stale nftables rules and restart Docker networking."""
        actions = []
        try:
            # Step 1: Flush the raw PREROUTING chain (runs on host)
            logger.warning(
                "network_healer.flushing_nftables",
                stale_bridges=[s.get("bridge") for s in (stale_bridges or [])],
            )
            rc, _, err = await _host_exec(
                "nft", "flush", "chain", "ip", "raw", "PREROUTING",
                timeout=10,
            )
            if rc == 0:
                actions.append("nftables raw PREROUTING flushed")
            else:
                logger.error("network_healer.nft_flush_failed", error=err[:200])
                return {"healed": False, "error": f"nft flush failed: {err[:200]}", "actions": actions}

            # Step 2: Restart Docker daemon to rebuild clean rules (runs on host)
            logger.warning("network_healer.restarting_docker")
            rc, _, err = await _host_exec(
                "systemctl", "restart", "docker",
                timeout=60,
            )
            if rc == 0:
                actions.append("Docker daemon restarted")
            else:
                logger.error("network_healer.docker_restart_failed", error=err[:200])
                return {"healed": False, "error": f"docker restart failed: {err[:200]}", "actions": actions}

            # Step 3: Wait for Docker to be ready, then restart compose stack
            await asyncio.sleep(5)
            compose_dir = self.compose_file.rsplit("/", 1)[0]
            logger.warning("network_healer.restarting_compose", dir=compose_dir)
            rc, _, err = await _host_exec(
                "bash", "-c",
                f"cd {compose_dir} && docker compose --profile monitoring down && docker compose --profile monitoring up -d",
                timeout=180,
            )
            if rc == 0:
                actions.append("Compose stack restarted")
            else:
                # Partial success -- Docker was restarted, compose may need manual help
                actions.append(f"Compose restart failed: {err[:200]}")
                logger.error("network_healer.compose_restart_failed", error=err[:200])

            healed = len(actions) >= 2  # At minimum nft flush + docker restart
            logger.info("network_healer.complete", healed=healed, actions=actions)
            return {"healed": healed, "actions": actions}

        except Exception as e:
            logger.error("network_healer.failed", error=str(e)[:200])
            return {"healed": False, "error": str(e)[:200], "actions": actions}
