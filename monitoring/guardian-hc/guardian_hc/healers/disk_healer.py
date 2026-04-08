import asyncio
import json
import httpx


class DiskHealer:
    def __init__(self, config=None):
        self.config = config or {}

    async def heal(self) -> dict:
        cleaned = []
        try:
            if self.config.get("auto_clean", {}).get("docker_prune", True):
                transport = httpx.AsyncHTTPTransport(uds="/var/run/docker.sock")
                async with httpx.AsyncClient(transport=transport, base_url="http://docker", timeout=30) as client:
                    await client.post("/containers/prune")
                    await client.post("/images/prune", params={"filters": json.dumps({"dangling": ["true"]})})
                cleaned.append("Docker pruned")

            max_size = self.config.get("auto_clean", {}).get("log_max_size", "50M")
            await (await asyncio.create_subprocess_shell(
                f"find /var/log -name '*.log' -size +{max_size} -delete", stdout=asyncio.subprocess.PIPE
            )).communicate()
            cleaned.append("Large logs removed")

            return {"healed": True, "actions": cleaned}
        except Exception as e:
            return {"healed": False, "error": str(e)[:200], "partial": cleaned}
