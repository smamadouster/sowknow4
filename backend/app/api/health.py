"""
Health check endpoints for database, Redis, Celery, disk and memory.
"""

from __future__ import annotations

import logging
import os
import shutil

from fastapi import status, APIRouter, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health/celery")
async def celery_health_check():
    """
    Check the health of connected Celery workers.

    Returns:
        200 with worker details when at least one worker is active.
        503 when no active workers are found.
    """
    from app.celery_app import celery_app

    try:
        inspect = celery_app.control.inspect()
        active_workers = inspect.active()
        stats = inspect.stats()
    except Exception as exc:
        logger.warning(f"Celery inspect failed: {exc}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"status": "unhealthy", "message": f"Celery inspect error: {exc}"},
        )

    if not active_workers:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "status": "unhealthy",
                "message": "No active Celery workers found",
                "workers": 0,
                "worker_details": {},
                "queue_stats": {},
            },
        )

    worker_count = len(active_workers)
    worker_details = {
        worker: {"active_tasks": tasks} for worker, tasks in active_workers.items()
    }
    queue_stats = stats or {}

    return {
        "status": "healthy",
        "workers": worker_count,
        "worker_details": worker_details,
        "queue_stats": queue_stats,
    }


@router.get("/health")
async def unified_health_check():
    """
    Unified health check that reports on database, Redis, Celery, disk and memory.

    Returns a summary with component-level status indicators.
    """
    results: dict = {
        "status": "healthy",
        "components": {},
    }

    # ── 1. database ──────────────────────────────────────────────────────────
    try:
        from app.database import get_db

        db = next(get_db())
        db.execute("SELECT 1")  # type: ignore[arg-type]
        results["components"]["database"] = {"status": "healthy"}
    except Exception as exc:
        results["components"]["database"] = {
            "status": "unhealthy",
            "error": str(exc),
        }
        results["status"] = "degraded"
    finally:
        try:
            db.close()
        except Exception:
            pass

    # ── 2. redis ─────────────────────────────────────────────────────────────
    try:
        import redis as _redis

        from app.core.redis_url import safe_redis_url
        r = _redis.from_url(safe_redis_url())
        r.ping()
        results["components"]["redis"] = {"status": "healthy"}
    except Exception as exc:
        results["components"]["redis"] = {
            "status": "unhealthy",
            "error": str(exc),
        }
        results["status"] = "degraded"

    # ── 3. celery ────────────────────────────────────────────────────────────
    try:
        from app.celery_app import celery_app

        active = celery_app.control.inspect().active()
        if active:
            results["components"]["celery"] = {
                "status": "healthy",
                "worker_count": len(active),
            }
        else:
            results["components"]["celery"] = {
                "status": "degraded",
                "message": "No active workers",
            }
            if results["status"] == "healthy":
                results["status"] = "degraded"
    except Exception as exc:
        results["components"]["celery"] = {
            "status": "unhealthy",
            "error": str(exc),
        }
        results["status"] = "degraded"

    # ── 4. disk ──────────────────────────────────────────────────────────────
    try:
        usage = shutil.disk_usage("/")
        free_pct = usage.free / usage.total * 100
        results["components"]["disk"] = {
            "status": "healthy" if free_pct > 10 else "warning",
            "free_percent": round(free_pct, 1),
            "free_gb": round(usage.free / (1024**3), 2),
        }
    except Exception as exc:
        results["components"]["disk"] = {
            "status": "unknown",
            "error": str(exc),
        }

    # ── 5. memory ────────────────────────────────────────────────────────────
    try:
        import psutil  # type: ignore[import]

        mem = psutil.virtual_memory()
        used_pct = mem.percent
        results["components"]["memory"] = {
            "status": "healthy" if used_pct < 85 else "warning",
            "used_percent": used_pct,
            "available_gb": round(mem.available / (1024**3), 2),
        }
    except ImportError:
        results["components"]["memory"] = {
            "status": "unknown",
            "message": "psutil not available",
        }
    except Exception as exc:
        results["components"]["memory"] = {"status": "unknown", "error": str(exc)}

    return results
