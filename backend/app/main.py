import logging
import os
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from threading import Lock
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from slowapi import _rate_limit_exceeded_handler
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
from slowapi.errors import RateLimitExceeded
from sqlalchemy.exc import SQLAlchemyError
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, RedirectResponse, Response

logger = logging.getLogger(__name__)

from app.api import (
    admin,
    articles,
    auth,
    bookmarks,
    chat,
    collections,
    documents,
    graph_rag,
    internal,
    knowledge_graph,
    monitoring,
    notes,
    pipeline_admin,
    push,
    reports,
    search_agent_router,
    search_feedback,
    search_suggest,
    smart_folders,
    spaces,
    subscriptions,
    tags,
    tasks,
    voice,
)
from app.api import health as health_router
from app.api import status as status_router
from app.database import create_all_tables, engine, init_pgvector
from app.limiter import limiter
from app.services.prometheus_metrics import get_metrics

# Load environment variables
load_dotenv()


class ErrorRateTracker:
    """Track 5xx error rates for alerting per PRD requirements."""

    def __init__(self, window_seconds: int = 300):
        self._window_seconds = window_seconds
        self._requests: list = []
        self._lock = Lock()

    def record_request(self, status_code: int, is_server_error: bool) -> None:
        """Record a request for error rate calculation."""
        with self._lock:
            now = time.time()
            self._requests.append(
                {
                    "timestamp": now,
                    "status": status_code,
                    "is_server_error": is_server_error,
                }
            )
            cutoff = now - self._window_seconds
            self._requests = [r for r in self._requests if r["timestamp"] > cutoff]

    def get_error_rate(self) -> float:
        """Get current 5xx error rate percentage over window."""
        with self._lock:
            if not self._requests:
                return 0.0
            server_errors = sum(1 for r in self._requests if r["is_server_error"])
            return (server_errors / len(self._requests)) * 100

    def get_request_count(self) -> int:
        """Get total requests in window."""
        with self._lock:
            return len(self._requests)


_error_rate_tracker = ErrorRateTracker(window_seconds=300)


# ---- Request-ID middleware (T01) ----
class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class ErrorRateMiddleware(BaseHTTPMiddleware):
    """Middleware to track 5xx error rates."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        start_time = time.time()
        response = await call_next(request)
        duration = time.time() - start_time

        is_5xx = 500 <= response.status_code < 600
        _error_rate_tracker.record_request(response.status_code, is_5xx)

        return response


class PrometheusHttpMetricsMiddleware(BaseHTTPMiddleware):
    """Middleware to record HTTP request counts and durations in Prometheus."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        start_time = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - start_time

        method = request.method
        # Use the route path when available to avoid label cardinality blow-up.
        route = request.scope.get("route")
        endpoint = getattr(route, "path", request.url.path) if route is not None else request.url.path
        status = str(response.status_code)

        metrics = get_metrics()
        metrics.counter("sowknow_http_requests_total").inc(
            1, {"method": method, "endpoint": endpoint, "status": status}
        )
        metrics.histogram("sowknow_http_request_duration_seconds").observe(
            duration, {"method": method, "endpoint": endpoint}
        )

        return response


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Startup: Initialize database
    print("Starting up...")
    await init_pgvector()  # Initialize pgvector extension
    await create_all_tables()
    print("Database tables created/verified")

    # Startup: Validate LLM model configuration (block deprecated/free-tier models in production)
    if _is_production:
        from app.core.config import settings

        deprecated_models = {
            d.strip()
            for d in settings.LLM_DEPRECATED_MODELS.split(",")
            if d.strip()
        }
        models_to_check = [
            settings.OPENROUTER_MODEL,
            settings.OPENROUTER_TIER_SIMPLE,
            settings.OPENROUTER_TIER_STANDARD,
            settings.OPENROUTER_TIER_COMPLEX,
        ]
        for model in models_to_check:
            if any(d in model for d in deprecated_models):
                raise RuntimeError(
                    f"CRITICAL: Deprecated/free-tier model '{model}' configured. "
                    f"Aborting startup. Update .env to use production-grade models."
                )
        print("LLM model configuration validated (no deprecated models)")

    # Startup: Confirm shared LLM HTTP client / connection pool is healthy
    try:
        from app.services.llm_http_client import LLMHTTPClient

        client = LLMHTTPClient.get_client()
        print(
            f"LLM HTTP client ready (keepalive={client._limits.max_keepalive_connections}, "
            f"max_connections={client._limits.max_connections})"
        )
    except Exception as exc:
        print(f"LLM HTTP client initialization warning: {exc}")

    # Startup: Register default monitoring alerts (PRD)
    try:
        from app.services.monitoring import setup_default_alerts

        setup_default_alerts()
        print("Default monitoring alerts registered")
    except Exception as exc:
        print(f"Default alert registration warning: {exc}")

    yield

    # Shutdown: release resources gracefully
    print("Shutting down...")
    try:
        await engine.dispose()
        print("Database connection pool disposed")
    except Exception as exc:
        print(f"Error disposing DB pool: {exc}")
    try:
        import redis as _redis

        from app.core.redis_url import safe_redis_url

        _redis.from_url(safe_redis_url()).connection_pool.disconnect()
        print("Redis connection pool closed")
    except Exception as exc:
        print(f"Error closing Redis pool: {exc}")
    try:
        from app.services.openrouter_service import close_redis_client as _close_or_redis

        _close_or_redis()
        print("OpenRouter Redis client closed")
    except Exception as exc:
        print(f"Error closing OpenRouter Redis client: {exc}")
    try:
        from app.services.search_cache import close_redis_client as _close_sc_redis

        _close_sc_redis()
        print("Search cache Redis client closed")
    except Exception as exc:
        print(f"Error closing search cache Redis client: {exc}")
    try:
        from app.services.llm_http_client import LLMHTTPClient

        await LLMHTTPClient.close()
        print("LLM HTTP client closed")
    except Exception as exc:
        print(f"Error closing LLM HTTP client: {exc}")
    print("Shutdown complete")


app = FastAPI(
    title="SOWKNOW API",
    description="Multi-Generational Legacy Knowledge System",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

# Attach rate limiter to app state (T04)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

_is_production = os.getenv("APP_ENV", "development").lower() == "production"


def _error_response(
    error_type: str, message: str, detail: str | None, http_status: int
) -> JSONResponse:
    """Build a consistent error envelope."""
    body: dict = {
        "error": {
            "type": error_type,
            "message": message,
            "detail": detail if not _is_production else None,
            "timestamp": time.time(),
        }
    }
    return JSONResponse(status_code=http_status, content=body)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Return 400 with structured error for invalid request bodies / query params."""
    return _error_response(
        error_type="validation_error",
        message="Request validation failed",
        detail=str(exc.errors()),
        http_status=status.HTTP_400_BAD_REQUEST,
    )


@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_exception_handler(
    request: Request, exc: SQLAlchemyError
) -> JSONResponse:
    """Return 503 on database errors to avoid leaking SQL details."""
    logger.exception(
        "SQLAlchemy error while handling %s %s", request.method, request.url.path
    )
    return _error_response(
        error_type="database_error",
        message="A database error occurred. Please try again later.",
        detail=str(exc) if not _is_production else None,
        http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all handler so unhandled exceptions never leak tracebacks."""
    return _error_response(
        error_type="internal_error",
        message="An unexpected error occurred.",
        detail=str(exc) if not _is_production else None,
        http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
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
    ALLOWED_ORIGINS = [
        origin.strip() for origin in _allowed_origins_str.split(",") if origin.strip()
    ]

    # Security check: reject wildcards in production
    if "*" in ALLOWED_ORIGINS:
        raise ValueError(
            "SECURITY ERROR: Wildcard origins [*] are not allowed with credentials in production. "
            "Use specific origins instead."
        )
else:
    # Development defaults
    ALLOWED_ORIGINS = (
        _allowed_origins_str.split(",")
        if _allowed_origins_str
        else [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:3001",  # Common alternate port
        ]
    )

# Parse ALLOWED_HOSTS from environment
# Format: comma-separated list of hostnames
_allowed_hosts_str = os.getenv("ALLOWED_HOSTS", "")
if APP_ENV == "production":
    if not _allowed_hosts_str:
        raise ValueError(
            "SECURITY ERROR: ALLOWED_HOSTS environment variable is required in production. "
            "Example: ALLOWED_HOSTS=sowknow.gollamtech.com,www.sowknow.gollamtech.com"
        )
    ALLOWED_HOSTS = [
        host.strip() for host in _allowed_hosts_str.split(",") if host.strip()
    ]
else:
    # Development: Allow any host for local testing
    ALLOWED_HOSTS = ["*"]

# TrustedHost Middleware - Prevents Host header attacks
# Only allows requests from configured hosts
app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)

# ProxyHeaders Middleware - Trust X-Forwarded-* headers from nginx.
# SEC-05: Direct backend access is blocked at the network level, so all
# requests reaching the app come through the reverse proxy.  Wrapping the
# app after TrustedHostMiddleware means this runs first on each request,
# populating request.client and request.url from forwarded headers before
# rate-limiting, CSRF and logging need the real client IP.
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")

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
        "X-CSRF-Token",
        "Accept",
        "Origin",
        "Access-Control-Request-Method",
        "Access-Control-Request-Headers",
    ],
    expose_headers=["Content-Range", "X-Total-Count", "X-CSRF-Token"],
    max_age=600,  # Cache preflight responses for 10 minutes
)

# Request-ID Middleware — injects X-Request-ID into every response (T01)
app.add_middleware(RequestIDMiddleware)

# CSRF Middleware — double-submit cookie validation on state-changing requests (FP8)
from app.middleware.csrf import CSRFMiddleware  # noqa: E402

app.add_middleware(CSRFMiddleware)

# Transaction Middleware — auto-commit on 2xx, rollback on 4xx/5xx (T11)
from app.middleware.transaction import TransactionMiddleware

app.add_middleware(TransactionMiddleware)

# RLS context middleware (P2-9) — sets app.user_id / app.user_role session vars
from app.middleware.rls import set_rls_context  # noqa: E402

app.add_middleware(BaseHTTPMiddleware, dispatch=set_rls_context)

# Error Rate Tracking Middleware - Tracks 5xx errors per PRD
app.add_middleware(ErrorRateMiddleware)

# Prometheus HTTP metrics middleware - records request counts and durations
app.add_middleware(PrometheusHttpMetricsMiddleware)

# Include routers
app.include_router(auth.router, prefix="/api/v1")
app.include_router(admin.router, prefix="/api/v1")
app.include_router(bookmarks.router, prefix="/api/v1")
app.include_router(notes.router, prefix="/api/v1")
app.include_router(spaces.router, prefix="/api/v1")
app.include_router(documents.router, prefix="/api/v1")
app.include_router(articles.router, prefix="/api/v1")
app.include_router(collections.router, prefix="/api/v1")
app.include_router(smart_folders.router, prefix="/api/v1")
app.include_router(knowledge_graph.router, prefix="/api/v1")
app.include_router(graph_rag.router, prefix="/api/v1")
app.include_router(search_agent_router.router, prefix="/api/v1")
app.include_router(search_suggest.router, prefix="/api/v1")
app.include_router(search_feedback.router, prefix="/api/v1")
app.include_router(chat.router, prefix="/api/v1")
app.include_router(internal.router, prefix="/api/v1")
app.include_router(tags.router, prefix="/api/v1")
app.include_router(voice.router, prefix="/api/v1")
app.include_router(health_router.router, prefix="/api/v1")
app.include_router(status_router.router, prefix="/api/v1")
app.include_router(subscriptions.router, prefix="/api/v1")
app.include_router(tasks.router, prefix="/api/v1")
app.include_router(push.router, prefix="/api/v1")
app.include_router(pipeline_admin.router, prefix="/api/v1")
app.include_router(reports.router, prefix="/api/v1")
app.include_router(monitoring.router, prefix="/api/v1")


@app.get("/health", include_in_schema=False)
async def root_health() -> RedirectResponse:
    """Redirect root /health to the canonical /api/v1/health endpoint."""
    return RedirectResponse(url="/api/v1/health", status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@app.get("/")
async def root() -> dict[str, Any]:
    return {
        "message": "SOWKNOW API is running",
        "status": "ok",
        "version": "1.0.0",
        "endpoints": {
            "health": "/api/v1/health",
            "api_status": "/api/v1/status",
            "docs": "/api/docs",
            "openapi": "/api/openapi.json",
            "auth": {
                "login": "/api/v1/auth/login",
                "register": "/api/v1/auth/register",
                "me": "/api/v1/auth/me",
                "refresh": "/api/v1/auth/refresh",
            },
            "admin": {
                "users": "/api/v1/admin/users",
                "user_detail": "/api/v1/admin/users/{id}",
                "stats": "/api/v1/admin/stats",
                "audit": "/api/v1/admin/audit",
                "dashboard": "/api/v1/admin/dashboard",
            },
        },
    }


@app.get("/metrics", include_in_schema=False)
async def prometheus_metrics() -> Response:
    """Prometheus metrics endpoint for scraping."""
    metrics = get_metrics()
    return Response(
        content=metrics.export(),
        media_type="text/plain",
        headers={"Content-Type": "text/plain; version=0.0.4; charset=utf-8"},
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)  # nosec B104
