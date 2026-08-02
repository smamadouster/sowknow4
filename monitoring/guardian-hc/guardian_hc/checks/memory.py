import re

import httpx

# Ephemeral `docker compose run` containers (e.g. ghostshell-researcher-run-742d2e58fc28,
# legacy <project>_<service>_run_<n>). They are one-shot jobs: by the time a
# memory alert is read the container is already gone, so the alert can never
# be acted on (2026-07-31: three INCIDENT OPEN pages for a researcher-run
# container that no longer existed). Readings are still recorded; alerting
# and healing are suppressed.
EPHEMERAL_RUN_RE = re.compile(r"(?:-run-[0-9a-f]{6,}|_run_\d+)$")


class MemoryChecker:
    async def check(self, services: list) -> list[dict]:
        # Declared services may opt out of memory alerts (memory.alert: false)
        # when a high working set is their steady state — e.g. embed-server-2's
        # torch allocator pins ~100% of its cgroup limit by design, so a
        # critical reading carries no actionable signal. The reading itself is
        # still recorded for reports; only alerting/healing is suppressed.
        silenced = {
            getattr(s, "container", "")
            for s in (services or [])
            if getattr(s, "memory", {}).get("alert") is False
        }
        results = []
        try:
            transport = httpx.AsyncHTTPTransport(uds="/var/run/docker.sock")
            async with httpx.AsyncClient(transport=transport, base_url="http://docker", timeout=10) as client:
                for container in (await client.get("/containers/json")).json():
                    cid = container["Id"][:12]
                    name = container["Names"][0].lstrip("/")
                    stats = (await client.get(f"/containers/{cid}/stats?stream=false")).json()
                    mem_stats = stats.get("memory_stats", {})
                    mem_u = mem_stats.get("usage", 0)
                    mem_l = mem_stats.get("limit", 1)
                    # cgroup v1 counts page cache in `usage`. Subtract the
                    # reclaimable file cache (same working-set math as
                    # `docker stats`) or file-heavy services like postgres
                    # pin at ~100% forever and false-positive.
                    cg = mem_stats.get("stats", {})
                    inactive = cg.get("total_inactive_file", cg.get("inactive_file", 0))
                    working = max(mem_u - inactive, 0)
                    if mem_l > 0 and mem_l < 2**62:
                        pct = (working / mem_l) * 100
                        # Early warning at 80% so operators have time to react before
                        # the 90% auto-heal threshold triggers a container restart.
                        severity = (
                            "critical" if pct > 90 else
                            "warning" if pct > 80 else
                            "ok"
                        )
                        ephemeral = bool(EPHEMERAL_RUN_RE.search(name))
                        result = {
                            "container": name,
                            "mem_pct": round(pct, 1),
                            "severity": severity,
                            "needs_healing": pct > 90 and name not in silenced and not ephemeral,
                        }
                        if name in silenced and pct > 90:
                            result["alert_suppressed"] = True
                        elif ephemeral and pct > 90:
                            result["alert_suppressed"] = "ephemeral_run_container"
                        results.append(result)
        except Exception as e:
            results.append({"container": "error", "error": str(e)[:200], "needs_healing": False})
        return results
