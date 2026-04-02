"""
CSRF protection via double-submit cookie pattern.

Defence-in-depth layer on top of SameSite=lax cookies.  On login/refresh the
backend sets a non-httpOnly ``csrf_token`` cookie.  The frontend reads it and
echoes the value back in an ``X-CSRF-Token`` header on every state-changing
request.  This middleware rejects requests where the two don't match.
"""

import hmac
import logging
import secrets

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

CSRF_COOKIE_NAME = "csrf_token"
CSRF_HEADER_NAME = "X-CSRF-Token"

SAFE_METHODS: set[str] = {"GET", "HEAD", "OPTIONS", "TRACE"}

# Paths exempt from CSRF validation.
#
# SECURITY RATIONALE:
# - login / register / forgot-password: No existing session to steal. Primary
#   protection against login-CSRF is SameSite=lax on the access_token cookie,
#   which prevents cross-origin POST from carrying cookies.
# - telegram: Machine-to-machine auth (not browser-initiated).
# - health: Read-only endpoints (GET only; POST would be caught by SAFE_METHODS).
EXEMPT_PATHS: set[str] = {
    "/api/v1/auth/login",
    "/api/v1/auth/register",
    "/api/v1/auth/logout",
    "/api/v1/auth/telegram",
    "/api/v1/auth/forgot-password",
    "/api/v1/auth/resend-verification",
    "/health",
    "/api/health",
    "/health/celery",
}

# Paths that start with these prefixes are also exempt (e.g. /api/v1/auth/verify-email/<token>)
EXEMPT_PREFIXES = ("/api/v1/auth/verify-email/", "/api/v1/internal/")


def generate_csrf_token() -> str:
    """Generate a cryptographically secure CSRF token (43 chars, URL-safe)."""
    return secrets.token_urlsafe(32)


class CSRFMiddleware(BaseHTTPMiddleware):
    """
    Validate double-submit CSRF cookie on unsafe HTTP methods.

    The ``csrf_token`` cookie is set by the login / refresh endpoints
    (non-httpOnly so the frontend JS can read it).  This middleware
    checks that the ``X-CSRF-Token`` request header matches it.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Safe methods never mutate state — skip.
        if request.method in SAFE_METHODS:
            return await call_next(request)

        # Exempt paths (login, register, health, etc.) — skip.
        path = request.url.path.rstrip("/")
        if path in EXEMPT_PATHS or path.startswith(EXEMPT_PREFIXES):
            return await call_next(request)

        # Bearer-token requests (machine-to-machine, e.g. Telegram bot) are not
        # vulnerable to CSRF because the token is not auto-attached by the browser.
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            return await call_next(request)

        # --- Double-submit cookie validation ---
        cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
        header_token = request.headers.get(CSRF_HEADER_NAME)

        if not cookie_token or not header_token:
            logger.warning(
                "CSRF token missing — cookie=%s header=%s path=%s",
                bool(cookie_token),
                bool(header_token),
                path,
            )
            return JSONResponse(
                status_code=403,
                content={"detail": "CSRF token missing"},
            )

        if not hmac.compare_digest(cookie_token, header_token):
            logger.warning("CSRF token mismatch on %s", path)
            return JSONResponse(
                status_code=403,
                content={"detail": "CSRF token invalid"},
            )

        return await call_next(request)
