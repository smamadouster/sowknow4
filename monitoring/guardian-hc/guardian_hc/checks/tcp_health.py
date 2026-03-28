import asyncio


class TcpHealthChecker:
    @staticmethod
    async def check(host: str, port: int, timeout: int = 5) -> dict:
        try:
            _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
            writer.close()
            await writer.wait_closed()
            return {"healthy": True, "host": host, "port": port}
        except Exception as e:
            return {"healthy": False, "host": host, "port": port, "error": str(e)[:200]}
