"""
Request-scoped TransactionMiddleware (T11)

Automatically commits the session on successful responses (2xx/3xx)
and rolls back on errors (4xx/5xx) or unhandled exceptions.
"""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.database import AsyncSessionLocal


class TransactionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
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
