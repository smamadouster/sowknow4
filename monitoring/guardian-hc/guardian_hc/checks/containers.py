import httpx


class ContainerChecker:
    async def check(self, container_name: str) -> dict:
        try:
            transport = httpx.AsyncHTTPTransport(uds="/var/run/docker.sock")
            async with httpx.AsyncClient(transport=transport, base_url="http://docker", timeout=5) as client:
                resp = await client.get("/containers/json?all=true")
                for c in resp.json():
                    if any(container_name in n for n in c.get("Names", [])):
                        return {"status": c.get("State", "unknown"), "container": container_name, "id": c["Id"][:12]}
            return {"status": "not_found", "container": container_name}
        except Exception as e:
            return {"status": "error", "container": container_name, "error": str(e)[:200]}
