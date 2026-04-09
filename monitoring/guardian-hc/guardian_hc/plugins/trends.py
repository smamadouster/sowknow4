"""Trends plugin — metrics collection and trend analysis (Archivist agent)."""

from __future__ import annotations

import subprocess
import time

import structlog

from guardian_hc.plugin import (
    GuardianPlugin, CheckResult, HealResult, Insight,
    CheckContext, AnalysisContext, Severity,
)
from guardian_hc.db import MetricsDB

logger = structlog.get_logger()

DEFAULT_THRESHOLDS = {
    "disk.usage_pct": 85.0,
    "redis.memory_rss_pct": 85.0,
    "pg.connection_pct": 80.0,
    "vps.load1": 6.0,
    "vps.steal_pct": 20.0,
}

PREDICTION_HORIZON = 4.0  # hours

ANOMALY_METRICS = [
    "redis.memory_rss",
    "pg.active_connections",
    "celery.total_queue_depth",
    "disk.usage_pct",
    "backend.response_ms",
]


class TrendsPlugin(GuardianPlugin):
    """Collects metrics to DB and analyzes trends for predictions."""

    name = "trends"
    enabled = True

    def __init__(self, config: dict):
        self._retention_raw_hours = _parse_retention(config.get("retention_raw", "48h"))
        self._retention_hourly_days = _parse_retention(config.get("retention_hourly", "14d")) // 24
        self._redis_host = config.get("redis_host", "redis")
        self._redis_port = config.get("redis_port", 6379)
        self._redis_password = config.get("redis_password", "")
        self._thresholds = dict(DEFAULT_THRESHOLDS)

    async def check(self, context: CheckContext) -> list[CheckResult]:
        """Collect metrics and write to DB. Returns empty list."""
        db: MetricsDB | None = context.metrics_db
        if not db:
            return []

        all_metrics: list[tuple[str, float, str, dict]] = []

        collectors = [
            self._collect_host_metrics,
            self._collect_redis_metrics,
            self._collect_pg_metrics,
            self._collect_celery_metrics,
            self._collect_backend_metrics,
        ]

        for collector in collectors:
            try:
                metrics = await collector()
                all_metrics.extend(metrics)
            except Exception as e:
                logger.warning("trends.collect.error", collector=collector.__name__, error=str(e)[:200])

        if all_metrics:
            try:
                await db.write_batch(all_metrics)
                logger.debug("trends.collected", count=len(all_metrics))
            except Exception as e:
                logger.error("trends.write.error", error=str(e)[:200])

        return []

    async def analyze(self, context: AnalysisContext) -> list[Insight]:
        """Run slope prediction and anomaly detection."""
        db: MetricsDB | None = context.metrics_db
        if not db:
            return []

        insights: list[Insight] = []

        # Slope-based prediction
        for metric, threshold in self._thresholds.items():
            try:
                slope = await db.get_slope(metric, hours=6)
                if slope is None or slope <= 0:
                    continue

                current = await db.get_latest(metric)
                if current is None or current >= threshold:
                    continue

                hours_to_breach = (threshold - current) / slope
                if 0 < hours_to_breach <= PREDICTION_HORIZON:
                    insights.append(Insight(
                        plugin=self.name, insight_type="prediction",
                        severity=Severity.WARNING,
                        summary=f"{metric} will hit {threshold} in ~{hours_to_breach:.1f}h at current rate",
                        metric=metric,
                        current_value=current,
                        predicted_value=threshold,
                        predicted_time_hours=hours_to_breach,
                        recommended_action=_action_for_metric(metric),
                    ))
            except Exception as e:
                logger.warning("trends.slope.error", metric=metric, error=str(e)[:200])

        # Anomaly detection
        for metric in ANOMALY_METRICS:
            try:
                current = await db.get_latest(metric)
                if current is None:
                    continue

                mean, std = await db.get_mean_stddev(metric, hours=24)
                if std == 0:
                    continue

                z_score = abs(current - mean) / std
                if z_score > 2.0:
                    insights.append(Insight(
                        plugin=self.name, insight_type="anomaly",
                        severity=Severity.WARNING,
                        summary=f"{metric} is anomalous: {current:.1f} (mean: {mean:.1f}, z: {z_score:.1f})",
                        metric=metric,
                        current_value=current,
                    ))
            except Exception as e:
                logger.warning("trends.anomaly.error", metric=metric, error=str(e)[:200])

        return insights

    # --- Metric collectors ---

    async def _collect_host_metrics(self) -> list[tuple[str, float, str, dict]]:
        metrics = []
        try:
            proc = subprocess.run(["df", "/"], capture_output=True, text=True, timeout=5)
            lines = proc.stdout.strip().splitlines()
            if len(lines) >= 2:
                parts = lines[1].split()
                usage_pct = float(parts[4].replace("%", ""))
                metrics.append(("disk.usage_pct", usage_pct, "host", {}))
        except Exception:
            pass
        try:
            with open("/proc/loadavg") as f:
                parts = f.read().strip().split()
                metrics.append(("vps.load1", float(parts[0]), "host", {}))
                metrics.append(("vps.load5", float(parts[1]), "host", {}))
                metrics.append(("vps.load15", float(parts[2]), "host", {}))
        except Exception:
            pass
        return metrics

    async def _collect_redis_metrics(self) -> list[tuple[str, float, str, dict]]:
        metrics = []
        try:
            cmd = ["docker", "exec", "sowknow4-redis", "redis-cli"]
            if self._redis_password:
                cmd.extend(["-a", self._redis_password])
            info = subprocess.run(cmd + ["INFO", "memory"], capture_output=True, text=True, timeout=5)
            for line in info.stdout.splitlines():
                if line.startswith("used_memory_rss:"):
                    val = int(line.split(":")[1].strip())
                    metrics.append(("redis.memory_rss", val / (1024 * 1024), "redis", {}))
                elif line.startswith("connected_clients:"):
                    metrics.append(("redis.connected_clients", float(line.split(":")[1].strip()), "redis", {}))
            dbsize = subprocess.run(cmd + ["DBSIZE"], capture_output=True, text=True, timeout=5)
            try:
                count = int(dbsize.stdout.strip().split(":")[-1].strip())
                metrics.append(("redis.dbsize", float(count), "redis", {}))
            except (ValueError, IndexError):
                pass
        except Exception:
            pass
        return metrics

    async def _collect_pg_metrics(self) -> list[tuple[str, float, str, dict]]:
        metrics = []
        try:
            cmd_base = [
                "docker", "exec", "sowknow4-postgres",
                "psql", "-U", "sowknow", "-d", "sowknow4", "-t", "-A", "-c",
            ]
            proc = subprocess.run(
                cmd_base + ["SELECT count(*) FROM pg_stat_activity WHERE datname = current_database();"],
                capture_output=True, text=True, timeout=5,
            )
            metrics.append(("pg.active_connections", float(proc.stdout.strip() or "0"), "postgres", {}))
            proc = subprocess.run(
                cmd_base + ["SELECT count(*) FROM pg_stat_activity WHERE state = 'idle in transaction';"],
                capture_output=True, text=True, timeout=5,
            )
            metrics.append(("pg.idle_in_transaction", float(proc.stdout.strip() or "0"), "postgres", {}))
        except Exception:
            pass
        return metrics

    async def _collect_celery_metrics(self) -> list[tuple[str, float, str, dict]]:
        metrics = []
        try:
            cmd = ["docker", "exec", "sowknow4-redis", "redis-cli"]
            if self._redis_password:
                cmd.extend(["-a", self._redis_password])
            total = 0
            for queue in ["celery", "document_processing", "heavy_processing", "collection_processing"]:
                proc = subprocess.run(cmd + ["LLEN", queue], capture_output=True, text=True, timeout=5)
                try:
                    depth = int(proc.stdout.strip().split()[-1])
                    metrics.append((f"celery.queue.{queue}", float(depth), "celery", {}))
                    total += depth
                except (ValueError, IndexError):
                    pass
            metrics.append(("celery.total_queue_depth", float(total), "celery", {}))
        except Exception:
            pass
        return metrics

    async def _collect_backend_metrics(self) -> list[tuple[str, float, str, dict]]:
        metrics = []
        try:
            import httpx
            start = time.monotonic()
            async with httpx.AsyncClient(timeout=10) as client:
                await client.get("http://backend:8000/api/v1/health")
                elapsed_ms = (time.monotonic() - start) * 1000
                metrics.append(("backend.response_ms", elapsed_ms, "backend", {}))
        except Exception:
            pass
        return metrics


def _parse_retention(s: str) -> int:
    """Parse retention string like '48h' or '14d' into hours."""
    s = s.strip().lower()
    if s.endswith("h"):
        return int(s[:-1])
    if s.endswith("d"):
        return int(s[:-1]) * 24
    return int(s)


def _action_for_metric(metric: str) -> str:
    actions = {
        "disk.usage_pct": "docker_prune_and_log_rotation",
        "redis.memory_rss_pct": "redis_memory_purge",
        "pg.connection_pct": "kill_idle_transactions",
        "vps.load1": "alert_only",
        "vps.steal_pct": "alert_only",
    }
    return actions.get(metric, "alert_only")
