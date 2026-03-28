import httpx


class MemoryHealer:
    async def heal(self, container_name: str) -> dict:
        try:
            transport = httpx.AsyncHTTPTransport(uds="/var/run/docker.sock")
            async with httpx.AsyncClient(transport=transport, base_url="http://docker", timeout=15) as client:
                resp = await client.get("/containers/json")
                for c in resp.json():
                    if any(container_name in n for n in c.get("Names", [])):
                        r = await client.post(f"/containers/{c['Id']}/restart", params={"t": 10})
                        return {"healed": r.status_code in (200, 204), "action": "memory restart"}
            return {"healed": False, "error": "Container not found"}
        except Exception as e:
            return {"healed": False, "error": str(e)[:200]}
