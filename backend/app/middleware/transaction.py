"""
Request-scoped TransactionMiddleware (T11)

Automatically commits the session on successful responses (2xx/3xx)
and rolls back on errors (4xx/5xx) or unhandled exceptions.

StreamingResponse endpoints are EXCLUDED because BaseHTTPMiddleware exits
before the response body is fully consumed, so the session would be closed
while the generator is still running.
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.database import AsyncSessionLocal


# Endpoints that return StreamingResponse and must manage their own session.
_STREAMING_PATHS = {
    "/api/v1/search/stream",
}


class TransactionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        # Skip auto-commit/rollback for streaming endpoints — the generator
        # captures the session and may outlive the middleware scope.
        if request.url.path in _STREAMING_PATHS:
            return await call_next(request)

        async with AsyncSessionLocal() as session:
            request.state.db = session
            try:
                response = await call_next(request)
                if response.status_code < 400:
                    await session.commit()
                else:
                    await session.rollback()
                return response
            except Exception:
                await session.rollback()
                raise
