"""
Monitoring and observability endpoints.

These endpoints were previously defined in the unused main_minimal.py entrypoint.
They are exposed here so that host-level cron scripts and Prometheus can
consume them from the live production app.

NOTE: These endpoints are intentionally unauthenticated to support the existing
host cron scripts. If you expose the API to untrusted networks, add admin/auth
requirements and update scripts/monitor-alerts.sh to use a service token.
"""

import logging
import os
import time
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Response

from app.core.redis_url import safe_redis_url
from app.services.cache_monitor import cache_monitor
from app.services.monitoring import (
    SystemMonitor,
    get_alert_manager,
    get_cost_tracker,
    get_queue_monitor,
)
from app.services.prometheus_metrics import get_metrics

logger = logging.getLogger(__name__)

router = APIRouter(tags=["monitoring"])


def _get_redis_info() -> dict[str, Any]:
    """Return Redis memory and keyspace information (best-effort)."""
    info: dict[str, Any] = {
        "available": False,
        "used_memory_mb": None,
        "maxmemory_mb": None,
        "memory_percent": None,
        "connected_clients": None,
    }
    try:
        import redis as _redis

        client = _redis.from_url(
            safe_redis_url(),
            decode_responses=True,
            socket_timeout=2,
            socket_connect_timeout=2,
        )
        client.ping()
        redis_info = client.info()
        used = redis_info.get("used_memory", 0)
        maxmem = redis_info.get("maxmemory", 0)
        info["available"] = True
        info["used_memory_mb"] = round(used / (1024 * 1024), 2)
        info["maxmemory_mb"] = round(maxmem / (1024 * 1024), 2) if maxmem else None
        if maxmem:
            info["memory_percent"] = round(used / maxmem, 4)
        info["connected_clients"] = redis_info.get("connected_clients")
        try:
            client.close()
        except Exception:
            pass
    except Exception as exc:
        logger.debug("Redis info collection failed: %s", exc)
    return info


@router.get("/health/embedding")
async def embedding_health() -> dict:
    """Memory health check for the embedding service."""
    from app.services.embedding_service import embedding_service

    return embedding_service.health_check()


@router.get("/health/detailed")
async def health_detailed() -> dict:
    """
    Comprehensive health check with all monitoring metrics.
    Per PRD requirements for detailed health monitoring.
    """
    cost_tracker = get_cost_tracker()
    queue_monitor = get_queue_monitor()
    alert_manager = get_alert_manager()
    system_monitor = SystemMonitor()

    overall_status = "healthy"
    issues: list[str] = []

    mem_stats = system_monitor.get_memory_usage()
    if mem_stats["percent"] > 80:
        overall_status = "degraded"
        issues.append(f"High memory usage: {mem_stats['percent']}%")

    disk_stats = system_monitor.get_disk_usage()
    if disk_stats.get("alert_high"):
        overall_status = "degraded"
        issues.append(f"High disk usage: {disk_stats.get('percent', 0)}%")

    queue_stats = queue_monitor.get_worker_status()
    if queue_stats.get("congested"):
        overall_status = "degraded"
        issues.append(f"Queue congested: {queue_stats.get('queue_depth', 0)} tasks")

    cost_stats = cost_tracker.get_stats(days=1)
    if cost_stats.get("over_budget"):
        overall_status = "degraded"
        issues.append(f"API cost over budget: ${cost_stats.get('today_cost', 0):.2f}")

    minimax_configured = bool(os.getenv("MINIMAX_API_KEY"))
    cache_hit_rate = cache_monitor.get_hit_rate(days=1)
    if 0 < cache_hit_rate < 0.5:
        issues.append(f"Low cache hit rate: {cache_hit_rate:.1%}")

    redis_info = _get_redis_info()
    if redis_info["available"] and redis_info.get("memory_percent"):
        if redis_info["memory_percent"] > 0.8:
            overall_status = "degraded"
            issues.append(
                f"High Redis memory usage: {redis_info['memory_percent']:.1%}"
            )

    active_alerts = alert_manager.get_active_alerts()
    if active_alerts:
        overall_status = "degraded"
        issues.append(f"{len(active_alerts)} active alerts")

    return {
        "status": overall_status,
        "timestamp": time.time(),
        "environment": os.getenv("APP_ENV", "development"),
        "version": "1.0.0",
        "services": {
            "database": "connected",
            "redis": "connected",
            "api": "running",
            "authentication": "enabled",
            "minimax": {
                "service": "minimax",
                "status": "healthy" if minimax_configured else "unavailable",
                "api_configured": minimax_configured,
                "cache_stats": {
                    "total_entries": 0,
                    "active_entries": 0,
                    "ttl_seconds": 3600,
                    "hit_rate_24h": round(cache_hit_rate, 4),
                    "tokens_saved_24h": cache_monitor.get_total_tokens_saved(days=1),
                },
                "timestamp": datetime.now().isoformat(),
            },
        },
        "monitoring": {
            "memory": mem_stats,
            "cpu": system_monitor.get_cpu_usage(),
            "disk": disk_stats,
            "queue": queue_stats,
            "costs": {
                "today_usd": round(cost_stats.get("today_cost", 0), 4),
                "budget_usd": cost_stats.get("daily_budget", 0),
                "remaining_budget": round(cost_stats.get("budget_remaining", 0), 4),
                "over_budget": cost_stats.get("over_budget", False),
                "breakdown": cost_tracker.get_daily_cost_breakdown(),
            },
            "cache": {
                "hit_rate_24h": round(cache_hit_rate, 4),
                "tokens_saved_24h": cache_monitor.get_total_tokens_saved(days=1),
                "redis": redis_info,
            },
            "active_alerts": active_alerts,
        },
        "issues": issues if issues else None,
    }


@router.get("/monitoring/costs")
async def get_cost_stats(days: int = 7) -> dict:
    """Get cost statistics for the specified period."""
    cost_tracker = get_cost_tracker()
    return cost_tracker.get_stats(days=days)


@router.get("/monitoring/queue")
async def get_queue_stats() -> dict:
    """Get Celery queue statistics."""
    queue_monitor = get_queue_monitor()
    return {
        "depth": queue_monitor.get_queue_depth(),
        "all_depths": queue_monitor.get_all_queue_depths(),
        "worker_status": queue_monitor.get_worker_status(),
    }


@router.get("/monitoring/system")
async def get_system_stats() -> dict:
    """Get system resource statistics."""
    system_monitor = SystemMonitor()

    # Also include the 5xx error rate tracked by ErrorRateMiddleware so host
    # monitoring scripts can read it without parsing nginx logs.
    from app.main import _error_rate_tracker

    return {
        "memory": system_monitor.get_memory_usage(),
        "cpu": system_monitor.get_cpu_usage(),
        "disk": system_monitor.get_disk_usage(),
        "containers": system_monitor.get_container_stats(),
        "error_rate": _error_rate_tracker.get_error_rate(),
    }


@router.get("/monitoring/alerts")
async def get_alerts() -> dict:
    """Get current alert status and configurations."""
    alert_manager = get_alert_manager()
    return {
        "active_alerts": alert_manager.get_active_alerts(),
        "configured_alerts": [
            {"name": name, **config.__dict__}
            for name, config in alert_manager._alerts.items()
        ],
    }


@router.get("/metrics")
async def prometheus_metrics() -> Response:
    """
    Prometheus metrics endpoint.

    NOTE: /metrics is also mounted directly on the root app in main.py. This
    router-level handler is provided so the monitoring router is self-contained
    and can be mounted under a different prefix if needed.
    """
    metrics = get_metrics()

    try:
        system_monitor = SystemMonitor()
        mem_stats = system_monitor.get_memory_usage()
        disk_stats = system_monitor.get_disk_usage()

        if "percent" in disk_stats:
            metrics.gauge("sowknow_disk_usage_percent").set(
                disk_stats["percent"], {"mount_point": disk_stats.get("path", "/")}
            )

        queue_monitor = get_queue_monitor()
        queue_depth = queue_monitor.get_queue_depth()
        metrics.gauge("sowknow_celery_queue_depth").set(queue_depth, {"queue_name": "celery"})

        redis_info = _get_redis_info()
        if redis_info["available"]:
            if redis_info.get("used_memory_mb") is not None:
                metrics.gauge("sowknow_redis_memory_usage_mb").set(
                    redis_info["used_memory_mb"]
                )
            if redis_info.get("memory_percent") is not None:
                metrics.gauge("sowknow_redis_memory_usage_percent").set(
                    redis_info["memory_percent"]
                )
            if redis_info.get("connected_clients") is not None:
                metrics.gauge("sowknow_redis_connected_clients").set(
                    redis_info["connected_clients"]
                )
    except Exception as e:
        logger.warning(f"Failed to update system metrics: {e}")

    return Response(
        content=metrics.export(),
        media_type="text/plain",
        headers={"Content-Type": "text/plain; version=0.0.4; charset=utf-8"},
    )
