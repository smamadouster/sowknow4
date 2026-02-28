"""
Comprehensive health check endpoints (PRD §11.4).

/api/v1/health        — checks all infrastructure components
/api/v1/health/celery — Celery worker status
"""

import asyncio
import logging
import os
from datetime import UTC, datetime
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy import text

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["health"])

_CHECK_TIMEOUT = 5.0


async def _check_database() -> str:
    try:
        from app.database import engine

        async with engine.connect() as conn:
            await asyncio.wait_for(
                conn.execute(text("SELECT 1")),
                timeout=_CHECK_TIMEOUT,
            )
        return "ok"
    except Exception as exc:
        logger.warning("Health check: database failed: %s", exc)
        return "error"


async def _check_redis() -> str:
    try:
        import redis as _redis

        from app.core.redis_url import safe_redis_url

        r = _redis.from_url(safe_redis_url(), socket_timeout=int(_CHECK_TIMEOUT))
        r.ping()
        return "ok"
    except Exception as exc:
        logger.warning("Health check: redis failed: %s", exc)
        return "error"


async def _check_vault() -> str:
    try:
        vault_addr = os.getenv("VAULT_ADDR", "http://vault:8200")
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{vault_addr}/v1/sys/health",
                timeout=_CHECK_TIMEOUT,
            )
            # 200=active, 429=standby, 472=DR secondary, 473=perf standby
            if resp.status_code in (200, 429, 472, 473):
                return "ok"
            return "error"
    except Exception as exc:
        logger.warning("Health check: vault failed: %s", exc)
        return "unavailable"


async def _check_nats() -> str:
    try:
        import nats as nats_client

        nats_url = os.getenv("NATS_URL", "nats://nats:4222")
        nc = await asyncio.wait_for(
            nats_client.connect(nats_url),
            timeout=_CHECK_TIMEOUT,
        )
        await nc.close()
        return "ok"
    except Exception as exc:
        logger.warning("Health check: nats failed: %s", exc)
        return "unavailable"


async def _check_ollama() -> str:
    try:
        ollama_url = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434")
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{ollama_url}/api/tags",
                timeout=_CHECK_TIMEOUT,
            )
            if resp.status_code == 200:
                return "ok"
            return "error"
    except Exception as exc:
        logger.warning("Health check: ollama failed: %s", exc)
        return "unavailable"


@router.get("", include_in_schema=False)
async def comprehensive_health() -> JSONResponse:
    """
    PRD §11.4 comprehensive health check.

    Runs all infrastructure checks concurrently. Returns flat status
    object with per-component results. HTTP 503 when critical services
    (database, redis) are down; 200 otherwise.
    """
    results = await asyncio.gather(
        _check_database(),
        _check_redis(),
        _check_vault(),
        _check_nats(),
        _check_ollama(),
        return_exceptions=True,
    )

    db = results[0] if isinstance(results[0], str) else "error"
    redis_s = results[1] if isinstance(results[1], str) else "error"
    vault_s = results[2] if isinstance(results[2], str) else "unavailable"
    nats_s = results[3] if isinstance(results[3], str) else "unavailable"
    ollama_s = results[4] if isinstance(results[4], str) else "unavailable"

    critical_ok = db == "ok" and redis_s == "ok"
    all_ok = all(s == "ok" for s in [db, redis_s, vault_s, nats_s, ollama_s])

    if all_ok:
        overall = "ok"
    elif critical_ok:
        overall = "degraded"
    else:
        overall = "error"

    response = {
        "status": overall,
        "database": db,
        "redis": redis_s,
        "vault": vault_s,
        "nats": nats_s,
        "ollama": ollama_s,
        "checked_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    http_code = status.HTTP_200_OK if critical_ok else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(content=response, status_code=http_code)


@router.get("/celery", include_in_schema=False)
async def celery_health_check() -> dict[str, Any]:
    """
    Check Celery worker availability.

    Returns 200 when at least one worker is active, 503 otherwise.
    """
    from app.celery_app import celery_app

    try:
        inspect = celery_app.control.inspect(timeout=5.0)
        active_workers = inspect.active() or {}
        reserved = inspect.reserved() or {}

        worker_count = len(active_workers)
        if worker_count == 0:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="No active Celery workers found",
            )

        total_active = sum(len(tasks) for tasks in active_workers.values())
        total_reserved = sum(len(tasks) for tasks in reserved.values())

        return {
            "status": "healthy",
            "workers": worker_count,
            "active_tasks": total_active,
            "reserved_tasks": total_reserved,
            "worker_names": list(active_workers.keys()),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Celery health check failed: {str(exc)}",
        )
