"""Sentinel plugin — silent failure detection (Watcher agent)."""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone, timedelta

import httpx
import structlog

from guardian_hc.plugin import (
    GuardianPlugin, CheckResult, HealResult, CheckContext, Severity,
)
from guardian_hc.healers.container_healer import ContainerHealer

logger = structlog.get_logger()


class SentinelPlugin(GuardianPlugin):
    """Detects services that are 'green but broken' — running but not working."""

    name = "sentinel"
    enabled = True

    STALENESS_THRESHOLD_MINUTES = 5
    QUEUE_GROWTH_CHECKS_THRESHOLD = 3

    def __init__(self, config: dict):
        self._backend_url = config.get("backend_url", "http://backend:8000")
        self._redis_host = config.get("redis_host", "redis")
        self._redis_port = config.get("redis_port", 6379)
        self._redis_password = config.get("redis_password", "")
        self._queue_history: list[int] = []

    async def check(self, context: CheckContext) -> list[CheckResult]:
        results: list[CheckResult] = []
        checks = [
            self._check_stale_data,
            self._check_queue_drain,
            self._check_frontend_api_bridge,
        ]
        for check_fn in checks:
            try:
                check_results = await check_fn(context)
                results.extend(check_results)
            except Exception as e:
                logger.error("sentinel.check.error", check=check_fn.__name__, error=str(e)[:200])
        return results

    async def heal(self, result: CheckResult) -> HealResult | None:
        hint = result.heal_hint or ""
        if hint == "restart_backend":
            healer = ContainerHealer()
            h = await healer.heal("sowknow4-backend")
            return HealResult(
                plugin=self.name, target="sowknow4-backend",
                action="restarted", success=h.get("healed", False),
            )
        if hint == "restart_celery_workers":
            healer = ContainerHealer()
            success = True
            for container in ["sowknow4-celery-light", "sowknow4-celery-heavy"]:
                h = await healer.heal(container)
                if not h.get("healed"):
                    success = False
            return HealResult(
                plugin=self.name, target="celery-workers",
                action="restarted", success=success,
            )
        return None

    async def _check_stale_data(self, ctx: CheckContext) -> list[CheckResult]:
        """Detect backend returning 200 but with stale data."""
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(f"{self._backend_url}/api/v1/health/deep")
                if resp.status_code != 200:
                    return []

                data = resp.json()
                last_write = data.get("last_write")
                if not last_write:
                    return []

                last_dt = datetime.fromisoformat(last_write)
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)

                age_minutes = (datetime.now(timezone.utc) - last_dt).total_seconds() / 60

                if age_minutes > self.STALENESS_THRESHOLD_MINUTES:
                    return [CheckResult(
                        plugin=self.name, module="Storage Layer",
                        check_name="stale_data", status="fail",
                        severity=Severity.HIGH,
                        summary=f"Last DB write was {age_minutes:.0f}min ago (threshold: {self.STALENESS_THRESHOLD_MINUTES}min)",
                        details={"last_write": last_write, "age_minutes": age_minutes},
                        needs_healing=True, heal_hint="restart_backend",
                    )]
                return []
        except Exception as e:
            logger.warning("sentinel.stale_data.error", error=str(e)[:200])
            return []

    async def _check_queue_drain(self, ctx: CheckContext) -> list[CheckResult]:
        """Detect queues growing but not draining."""
        try:
            cmd = ["docker", "exec", "sowknow4-redis", "redis-cli"]
            if self._redis_password:
                cmd.extend(["-a", self._redis_password])

            total = 0
            for queue in ["celery", "document_processing", "heavy_processing", "collection_processing"]:
                proc = subprocess.run(
                    cmd + ["LLEN", queue], capture_output=True, text=True, timeout=5,
                )
                try:
                    total += int(proc.stdout.strip().split()[-1])
                except (ValueError, IndexError):
                    pass

            self._queue_history.append(total)
            if len(self._queue_history) > 6:
                self._queue_history.pop(0)

            if len(self._queue_history) >= self.QUEUE_GROWTH_CHECKS_THRESHOLD:
                recent = self._queue_history[-self.QUEUE_GROWTH_CHECKS_THRESHOLD:]
                monotonic_growth = all(recent[i] < recent[i + 1] for i in range(len(recent) - 1))
                if monotonic_growth and recent[-1] > 10:
                    return [CheckResult(
                        plugin=self.name, module="Document Pipeline",
                        check_name="queue_not_draining", status="fail",
                        severity=Severity.HIGH,
                        summary=f"Queue depth growing: {recent[0]} -> {recent[-1]} over {len(recent)} checks",
                        details={"history": recent, "current": total},
                        needs_healing=True, heal_hint="restart_celery_workers",
                    )]

            return []
        except Exception as e:
            logger.warning("sentinel.queue_drain.error", error=str(e)[:200])
            return []

    async def _check_frontend_api_bridge(self, ctx: CheckContext) -> list[CheckResult]:
        """Detect frontend up but API calls returning 502/503."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                try:
                    fe_resp = await client.get("http://frontend:3000/")
                    frontend_up = fe_resp.status_code == 200
                except Exception:
                    frontend_up = False

                if not frontend_up:
                    return []

                try:
                    api_resp = await client.get(f"{self._backend_url}/api/v1/health")
                    if api_resp.status_code in (502, 503):
                        return [CheckResult(
                            plugin=self.name, module="Infrastructure",
                            check_name="frontend_api_bridge", status="fail",
                            severity=Severity.HIGH,
                            summary=f"Frontend up but API returning {api_resp.status_code}",
                            needs_healing=True, heal_hint="restart_backend",
                        )]
                except Exception:
                    pass

            return []
        except Exception as e:
            logger.warning("sentinel.frontend_bridge.error", error=str(e)[:200])
            return []
