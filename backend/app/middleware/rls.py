"""
RLS context middleware (P2-9)

Sets PostgreSQL session variables before each request so that Row-Level
Security policies on sowknow.documents and sowknow.collections can filter
rows based on the authenticated user.

Variables set per request:
  app.user_id   — UUID of the authenticated user (empty string if anonymous)
  app.user_role — Role of the authenticated user (empty string if anonymous)
  app.client_ip — Originating IP address (for audit log)
"""
import logging

from jose import JWTError, jwt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.database import AsyncSessionLocal
from app.utils.security import SECRET_KEY, ALGORITHM

logger = logging.getLogger(__name__)


async def set_rls_context(request: Request, call_next):
    """HTTP middleware that injects RLS session variables."""
    user_id = ""
    user_role = ""
    client_ip = request.client.host if request.client else ""

    # Extract JWT from httpOnly cookie or Authorization header
    token: str | None = request.cookies.get("access_token")
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]

    if token:
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            user_id = payload.get("sub", "")
            user_role = payload.get("role", "")
        except JWTError:
            pass

    # Set PostgreSQL session variables for RLS:
    #   SET app.user_id   = '<user_id>'
    #   SET app.user_role = '<role>'
    async with AsyncSessionLocal() as session:
        try:
            await session.execute(
                __import__("sqlalchemy").text(
                    "SELECT set_config('app.user_id',   :uid,  true), "
                    "       set_config('app.user_role', :role, true), "
                    "       set_config('app.client_ip', :ip,   true)"
                ),
                {"uid": user_id, "role": user_role, "ip": client_ip},
            )
            await session.commit()
        except Exception:
            logger.debug("RLS context set failed (non-fatal)", exc_info=True)

    response = await call_next(request)
    return response
