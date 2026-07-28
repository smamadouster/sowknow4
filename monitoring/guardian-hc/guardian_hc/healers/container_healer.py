import asyncio
import httpx


class ContainerHealer:
    async def heal(self, container_name: str, rebuild: bool = False, compose_file: str = "") -> dict:
        try:
            transport = httpx.AsyncHTTPTransport(uds="/var/run/docker.sock")
            async with httpx.AsyncClient(transport=transport, base_url="http://docker", timeout=30) as client:
                resp = await client.get("/containers/json?all=true")
                for c in resp.json():
                    # Exact name match (Docker names carry a leading '/').
                    # Previously a SUBSTRING match: healing "postgres" could
                    # restart mastersre-postgres / ghostshell-postgres, and
                    # "embed-server" matched two different containers
                    # (2026-07-28 P0 incident).
                    if any(n.lstrip("/") == container_name for n in c.get("Names", [])):
                        r = await client.post(f"/containers/{c['Id']}/restart", params={"t": 10})
                        if r.status_code in (200, 204):
                            return {"healed": True, "action": "restarted"}
                        elif rebuild and compose_file:
                            proc = await asyncio.create_subprocess_shell(
                                f"cd $(dirname {compose_file}) && docker compose build --no-cache {container_name} && docker compose up -d {container_name}",
                                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                            )
                            await asyncio.wait_for(proc.communicate(), timeout=300)
                            return {"healed": proc.returncode == 0, "action": "rebuilt"}
            return {"healed": False, "error": "Container not found"}
        except Exception as e:
            return {"healed": False, "error": str(e)[:200]}
