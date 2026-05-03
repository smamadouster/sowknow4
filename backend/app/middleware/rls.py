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
from dataclasses import dataclass

from jose import JWTError, jwt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request
from starlette.responses import Response

from app.utils.security import ALGORITHM, SECRET_KEY

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RLSContext:
    user_id: str = ""
    user_role: str = ""
    client_ip: str = ""


def extract_rls_context(request: Request) -> RLSContext:
    """Extract request metadata used by PostgreSQL RLS policies."""
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
            user_id = str(payload.get("user_id") or "")
            user_role = payload.get("role", "")
        except JWTError:
            pass

    return RLSContext(user_id=user_id, user_role=user_role, client_ip=client_ip)


async def apply_rls_context(session: AsyncSession, context: RLSContext) -> None:
    """Apply RLS variables on the same DB session that will execute request queries."""
    try:
        await session.execute(
            text(
                "SELECT set_config('app.user_id',   :uid,  true), "
                "       set_config('app.user_role', :role, true), "
                "       set_config('app.client_ip', :ip,   true)"
            ),
            {"uid": context.user_id, "role": context.user_role, "ip": context.client_ip},
        )
    except Exception:
        logger.debug("RLS context set failed (non-fatal)", exc_info=True)


async def set_rls_context(request: Request, call_next) -> Response:
    """HTTP middleware that stores RLS context for request-scoped DB sessions."""
    request.state.rls_context = extract_rls_context(request)

    response = await call_next(request)
    return response
