import httpx


class HttpHealthChecker:
    @staticmethod
    async def check(url: str, timeout: int = 10) -> dict:
        if not url:
            return {"healthy": False, "error": "No URL"}
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(url)
                return {"healthy": resp.status_code == 200, "status_code": resp.status_code, "url": url}
        except Exception as e:
            return {"healthy": False, "url": url, "error": str(e)[:200]}
