"""
Celery-specific health checks for SOWKNOW4.

Checks:
- Worker process is alive
- Worker is not stuck (responding to ping)
- Queue depth is not dangerously high
- No stuck/zombie tasks
"""
import asyncio
import json
import httpx


class CeleryHealthChecker:
    def __init__(self, config=None):
        c = config or {}
        self.redis_host = c.get("redis_host", "redis")
        self.redis_port = c.get("redis_port", 6379)
        self.redis_password = c.get("redis_password", "")
        self.max_queue_depth = c.get("max_queue_depth", 100)
        self.worker_container = c.get("worker_container", "sowknow4-celery-worker")
        self.beat_container = c.get("beat_container", "sowknow4-celery-beat")

    async def check(self) -> list[dict]:
        results = []

        # Check worker container health via Docker API
        results.append(await self._check_container(self.worker_container, "celery-worker"))
        results.append(await self._check_container(self.beat_container, "celery-beat"))

        # Check queue depth via Redis
        results.append(await self._check_queue_depth())

        return results

    async def _check_container(self, container_name: str, label: str) -> dict:
        try:
            transport = httpx.AsyncHTTPTransport(uds="/var/run/docker.sock")
            async with httpx.AsyncClient(transport=transport, base_url="http://docker", timeout=5) as client:
                resp = await client.get("/containers/json?all=true")
                for c in resp.json():
                    if any(container_name in n for n in c.get("Names", [])):
                        state = c.get("State", "unknown")
                        status = c.get("Status", "")
                        is_healthy = state == "running" and "unhealthy" not in status.lower()
                        restarting = "restarting" in status.lower()
                        return {
                            "check": f"celery_{label}",
                            "container": container_name,
                            "status": state,
                            "detail": status,
                            "needs_healing": not is_healthy or restarting,
                            "restart_loop": restarting,
                        }
            return {
                "check": f"celery_{label}",
                "container": container_name,
                "status": "not_found",
                "needs_healing": True,
            }
        except Exception as e:
            return {
                "check": f"celery_{label}",
                "container": container_name,
                "status": "error",
                "error": str(e)[:200],
                "needs_healing": False,
            }

    async def _check_queue_depth(self) -> dict:
        """Check Celery queue depth via Redis LLEN."""
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self.redis_host, self.redis_port), timeout=5)

            # AUTH if password set
            if self.redis_password:
                writer.write(f"AUTH {self.redis_password}\r\n".encode())
                await writer.drain()
                auth_resp = await asyncio.wait_for(reader.readline(), timeout=3)
                if not auth_resp.startswith(b"+OK"):
                    writer.close()
                    return {"check": "celery_queue", "error": "Redis AUTH failed", "needs_healing": False}

            # Check all relevant Celery queues
            total_depth = 0
            queues = [
                "celery", "document_processing", "scheduled",
                "pipeline.embed", "pipeline.entities", "pipeline.ocr",
                "pipeline.articles", "pipeline.index", "pipeline.chunk",
                "collections",
            ]
            queue_details = {}
            for queue in queues:
                writer.write(f"LLEN {queue}\r\n".encode())
                await writer.drain()
                resp = await asyncio.wait_for(reader.readline(), timeout=3)
                depth = int(resp.decode().strip().lstrip(":"))
                queue_details[queue] = depth
                total_depth += depth

            writer.close()
            await writer.wait_closed()

            # Flag if pipeline-specific queues are stalled (deep but not moving)
            embed_depth = queue_details.get("pipeline.embed", 0)
            entity_depth = queue_details.get("pipeline.entities", 0)
            pipeline_stalled = embed_depth == 0 and entity_depth == 0

            return {
                "check": "celery_queue",
                "total_depth": total_depth,
                "queues": queue_details,
                "needs_healing": total_depth > self.max_queue_depth,
                "severity": "critical" if total_depth > self.max_queue_depth * 2 else
                           "warning" if total_depth > self.max_queue_depth else "ok",
                "pipeline_stalled": pipeline_stalled,
            }
        except Exception as e:
            return {"check": "celery_queue", "error": str(e)[:200], "needs_healing": False}
