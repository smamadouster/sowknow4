"""
Guardian HC -- Ollama health check.

Verifies the shared Ollama instance is reachable and lists loaded models.
"""

import httpx


class OllamaChecker:
    def __init__(self, config: dict = None):
        self.url = (config or {}).get("url", "http://host.docker.internal:11434")

    async def check(self) -> dict:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{self.url}/api/tags")
                resp.raise_for_status()
                models = [m.get("name") for m in resp.json().get("models", [])]
                return {"status": "healthy", "models": models, "needs_healing": False}
        except Exception as e:
            return {"status": "unavailable", "error": str(e)[:200], "needs_healing": True}
