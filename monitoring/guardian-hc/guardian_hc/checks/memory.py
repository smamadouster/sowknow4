import httpx


class MemoryChecker:
    async def check(self, services: list) -> list[dict]:
        results = []
        try:
            transport = httpx.AsyncHTTPTransport(uds="/var/run/docker.sock")
            async with httpx.AsyncClient(transport=transport, base_url="http://docker", timeout=10) as client:
                for container in (await client.get("/containers/json")).json():
                    cid = container["Id"][:12]
                    name = container["Names"][0].lstrip("/")
                    stats = (await client.get(f"/containers/{cid}/stats?stream=false")).json()
                    mem_u = stats.get("memory_stats", {}).get("usage", 0)
                    mem_l = stats.get("memory_stats", {}).get("limit", 1)
                    if mem_l > 0 and mem_l < 2**62:
                        pct = (mem_u / mem_l) * 100
                        # Early warning at 80% so operators have time to react before
                        # the 90% auto-heal threshold triggers a container restart.
                        severity = (
                            "critical" if pct > 90 else
                            "warning" if pct > 80 else
                            "ok"
                        )
                        results.append({
                            "container": name,
                            "mem_pct": round(pct, 1),
                            "severity": severity,
                            "needs_healing": pct > 90,
                        })
        except Exception as e:
            results.append({"container": "error", "error": str(e)[:200], "needs_healing": False})
        return results
