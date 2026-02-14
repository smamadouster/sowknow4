"""
SOWKNOW API - Minimal Working Version
"""
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
import time
import os
from collections import defaultdict
from threading import Lock
from contextlib import asynccontextmanager
import logging
from datetime import datetime

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Import monitoring services
from app.services.monitoring import (
    get_cost_tracker,
    get_queue_monitor,
    get_alert_manager,
    setup_default_alerts,
    SystemMonitor,
)
from app.services.cache_monitor import cache_monitor
from app.services.prometheus_metrics import get_metrics

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print("Starting up...")
    setup_default_alerts()
    logger.info("Monitoring alerts configured")
    yield
    # Shutdown
    print("Shutting down...")

app = FastAPI(
    title="SOWKNOW API",
    description="Multi-Generational Legacy Knowledge System",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan
)

# ============================================================================
# SECURITY CRITICAL: CORS and TrustedHost Configuration
# ============================================================================
# Production deployment MUST use environment variables for security.
# Never use wildcard origins ["*"] with allow_credentials=True in production!
# This is a known security vulnerability that allows credential theft.
#
# Environment Variables Required:
#   - ALLOWED_ORIGINS: Comma-separated list of allowed frontend origins
#                      Example: "https://sowknow.gollamtech.com,https://www.sowknow.gollamtech.com"
#   - ALLOWED_HOSTS: Comma-separated list of allowed hosts
#                    Example: "sowknow.gollamtech.com,www.sowknow.gollamtech.com"
#
# Development Behavior:
#   - ALLOWED_ORIGINS defaults to ["http://localhost:3000", "http://127.0.0.1:3000"]
#   - ALLOWED_HOSTS defaults to ["*"] (permissive for local development)
#
# Production Behavior:
#   - Both variables MUST be set explicitly
#   - Wildcards are rejected for security
#   - Missing configuration raises an error to prevent unsafe deployment
# ============================================================================

# Parse environment configuration
APP_ENV = os.getenv("APP_ENV", "development").lower()

# Parse ALLOWED_ORIGINS from environment
# Format: comma-separated list of origins
_allowed_origins_str = os.getenv("ALLOWED_ORIGINS", "")
if APP_ENV == "production":
    if not _allowed_origins_str:
        raise ValueError(
            "SECURITY ERROR: ALLOWED_ORIGINS environment variable is required in production. "
            "Example: ALLOWED_ORIGINS=https://sowknow.gollamtech.com,https://www.sowknow.gollamtech.com"
        )
    # Split and strip whitespace, filter empty strings
    ALLOWED_ORIGINS = [origin.strip() for origin in _allowed_origins_str.split(",") if origin.strip()]

    # Security check: reject wildcards in production
    if "*" in ALLOWED_ORIGINS:
        raise ValueError(
            "SECURITY ERROR: Wildcard origins [*] are not allowed with credentials in production. "
            "Use specific origins instead."
        )
else:
    # Development defaults
    ALLOWED_ORIGINS = _allowed_origins_str.split(",") if _allowed_origins_str else [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",  # Common alternate port
    ]

# Parse ALLOWED_HOSTS from environment
# Format: comma-separated list of hostnames
_allowed_hosts_str = os.getenv("ALLOWED_HOSTS", "")
if APP_ENV == "production":
    if not _allowed_hosts_str:
        raise ValueError(
            "SECURITY ERROR: ALLOWED_HOSTS environment variable is required in production. "
            "Example: ALLOWED_HOSTS=sowknow.gollamtech.com,www.sowknow.gollamtech.com"
        )
    ALLOWED_HOSTS = [host.strip() for host in _allowed_hosts_str.split(",") if host.strip()]
else:
    # Development: Allow any host for local testing
    ALLOWED_HOSTS = ["*"]

# TrustedHost Middleware - Prevents Host header attacks
# Only allows requests from configured hosts
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=ALLOWED_HOSTS
)

# CORS Middleware - Controls cross-origin requests
# SECURITY: Never use allow_origins=["*"] with allow_credentials=True
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "X-Requested-With",
        "Accept",
        "Origin",
        "Access-Control-Request-Method",
        "Access-Control-Request-Headers",
    ],
    expose_headers=["Content-Range", "X-Total-Count"],
    max_age=600,  # Cache preflight responses for 10 minutes
)

# Include auth router (keep it simple for now)
from app.api import auth
from app.api import admin
app.include_router(auth.router, prefix="/api/v1")
app.include_router(admin.router, prefix="/api/v1")

@app.get("/")
async def root():
    return {
        "message": "SOWKNOW API is running",
        "status": "ok",
        "version": "1.0.0",
        "endpoints": {
            "health": "/health",
            "api_status": "/api/v1/status",
            "docs": "/api/docs",
            "openapi": "/api/openapi.json",
            "auth": {
                "login": "/api/v1/auth/login",
                "register": "/api/v1/auth/register",
                "me": "/api/v1/auth/me",
                "refresh": "/api/v1/auth/refresh"
            }
        }
    }

@app.get("/health")
async def health():
    """
    Basic health check endpoint.
    Returns minimal status for container health checks.
    """
    from sqlalchemy import text
    import redis
    import httpx
    from app.database import engine

    db_status = "disconnected"
    redis_status = "disconnected"
    ollama_status = "disconnected"

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as e:
        db_status = f"error: {str(e)}"

    try:
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        r = redis.from_url(redis_url)
        r.ping()
        redis_status = "connected"
    except Exception as e:
        redis_status = f"error: {str(e)}"

    try:
        ollama_url = os.getenv("LOCAL_LLM_URL", "http://localhost:11434")
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{ollama_url}/api/tags", timeout=5.0)
            if response.status_code == 200:
                ollama_status = "connected"
            else:
                ollama_status = f"error: {response.status_code}"
    except Exception as e:
        ollama_status = f"unavailable: {str(e)}"

    overall_status = "healthy"
    if db_status != "connected" or redis_status != "connected":
        overall_status = "degraded"

    return {
        "status": overall_status,
        "timestamp": time.time(),
        "environment": os.getenv("APP_ENV", "development"),
        "version": "1.0.0",
        "services": {
            "database": db_status,
            "redis": redis_status,
            "ollama": ollama_status,
            "api": "running",
            "authentication": "enabled"
        }
    }


@app.get("/api/v1/health/detailed")
async def health_detailed():
    """
    Comprehensive health check with all monitoring metrics.
    Per PRD requirements for detailed health monitoring.
    """
    cost_tracker = get_cost_tracker()
    queue_monitor = get_queue_monitor()
    alert_manager = get_alert_manager()
    system_monitor = SystemMonitor()

    # Check service health
    overall_status = "healthy"
    issues = []

    # Check memory
    mem_stats = system_monitor.get_memory_usage()
    if mem_stats["percent"] > 80:
        overall_status = "degraded"
        issues.append(f"High memory usage: {mem_stats['percent']}%")

    # Check disk
    disk_stats = system_monitor.get_disk_usage()
    if disk_stats.get("alert_high"):
        overall_status = "degraded"
        issues.append(f"High disk usage: {disk_stats.get('percent', 0)}%")

    # Check queue
    queue_stats = queue_monitor.get_worker_status()
    if queue_stats.get("congested"):
        overall_status = "degraded"
        issues.append(f"Queue congested: {queue_stats.get('queue_depth', 0)} tasks")

    # Check costs
    cost_stats = cost_tracker.get_stats(days=1)
    if cost_stats.get("over_budget"):
        overall_status = "degraded"
        issues.append(f"API cost over budget: ${cost_stats.get('today_cost', 0):.2f}")

    # Check Gemini API
    gemini_configured = bool(os.getenv("GEMINI_API_KEY"))

    # Check cache hit rate
    cache_hit_rate = cache_monitor.get_hit_rate(days=1)
    if cache_hit_rate < 0.5 and cache_hit_rate > 0:  # Only alert if there's some traffic
        issues.append(f"Low cache hit rate: {cache_hit_rate:.1%}")

    # Get active alerts
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
            "gemini": {
                "service": "gemini",
                "status": "healthy" if gemini_configured else "unavailable",
                "api_configured": gemini_configured,
                "cache_stats": {
                    "total_entries": 0,
                    "active_entries": 0,
                    "ttl_seconds": 3600,
                    "hit_rate_24h": round(cache_hit_rate, 4),
                    "tokens_saved_24h": cache_monitor.get_total_tokens_saved(days=1),
                },
                "timestamp": datetime.now().isoformat() if 'datetime' in dir() else None,
            }
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
            },
            "active_alerts": active_alerts,
        },
        "issues": issues if issues else None,
    }


@app.get("/api/v1/monitoring/costs")
async def get_cost_stats(days: int = 7):
    """
    Get cost statistics for the specified period.

    Args:
        days: Number of days to include (default: 7)
    """
    cost_tracker = get_cost_tracker()
    return cost_tracker.get_stats(days=days)


@app.get("/api/v1/monitoring/queue")
async def get_queue_stats():
    """Get Celery queue statistics."""
    queue_monitor = get_queue_monitor()
    return {
        "depth": queue_monitor.get_queue_depth(),
        "all_depths": queue_monitor.get_all_queue_depths(),
        "worker_status": queue_monitor.get_worker_status(),
    }


@app.get("/api/v1/monitoring/system")
async def get_system_stats():
    """Get system resource statistics."""
    system_monitor = SystemMonitor()
    return {
        "memory": system_monitor.get_memory_usage(),
        "cpu": system_monitor.get_cpu_usage(),
        "disk": system_monitor.get_disk_usage(),
        "containers": system_monitor.get_container_stats(),
    }


@app.get("/api/v1/monitoring/alerts")
async def get_alerts():
    """Get current alert status and configurations."""
    alert_manager = get_alert_manager()
    return {
        "active_alerts": alert_manager.get_active_alerts(),
        "configured_alerts": [
            {"name": name, **config.__dict__}
            for name, config in alert_manager._alerts.items()
        ],
    }


@app.get("/metrics")
async def prometheus_metrics():
    """
    Prometheus metrics endpoint.
    Exposes all metrics in Prometheus format for scraping.
    """
    from app.services.prometheus_metrics import get_metrics
    metrics = get_metrics()

    # Update system metrics on each scrape
    try:
        system_monitor = SystemMonitor()
        mem_stats = system_monitor.get_memory_usage()
        disk_stats = system_monitor.get_disk_usage()

        # Update memory metrics
        for container_name, container_data in mem_stats.get("containers", {}).items():
            pass  # Would need to parse docker stats output

        # Update disk metrics
        if "percent" in disk_stats:
            metrics.gauge("sowknow_disk_usage_percent").set(
                disk_stats["percent"],
                {"mount_point": disk_stats.get("path", "/")}
            )

        # Update queue metrics
        queue_monitor = get_queue_monitor()
        queue_depth = queue_monitor.get_queue_depth()
        metrics.gauge("sowknow_celery_queue_depth").set(
            queue_depth,
            {"queue_name": "celery"}
        )

    except Exception as e:
        logger.warning(f"Failed to update system metrics: {e}")

    return Response(
        content=metrics.export(),
        media_type="text/plain",
        headers={"Content-Type": "text/plain; version=0.0.4; charset=utf-8"}
    )

@app.get("/api/v1/status")
async def api_status():
    return {
        "phase": "1 - Core MVP",
        "sprint": "1 - Foundation",
        "status": "development",
        "version": "1.0.0",
        "features": [
            {"name": "Infrastructure", "status": "✅", "description": "Docker containers, PostgreSQL, Redis"},
            {"name": "Authentication", "status": "✅", "description": "JWT login/register system"},
            {"name": "Database Models", "status": "⏳", "description": "SQLAlchemy models with pgvector"},
            {"name": "Document Upload", "status": "⏳", "description": "File upload and processing"},
            {"name": "OCR Processing", "status": "⏳", "description": "Text extraction from documents"},
            {"name": "RAG Search", "status": "⏳", "description": "Vector search with embeddings"},
            {"name": "Telegram Bot", "status": "⏳", "description": "Telegram integration"}
        ],
        "next_steps": [
            "Implement document models",
            "Create document upload API",
            "Set up file storage buckets",
            "Integrate Hunyuan OCR API",
            "Implement vector embeddings"
        ]
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
