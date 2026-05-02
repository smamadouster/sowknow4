"""
Unit and integration tests for authentication layer.

Covers:
- CSRF middleware exempt paths (refresh must work without CSRF cookie)
- Login / refresh / logout cookie flow
- Token blacklist behaviour
- JWT creation and validation
"""

from __future__ import annotations

import os
import sys
import time
import uuid
from contextlib import asynccontextmanager, contextmanager
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_BACKEND = str(Path(__file__).parent.parent.parent / "backend")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-do-not-use-in-production")
os.environ.setdefault("CELERY_MEMORY_WARNING_MB", "1400")
os.environ.setdefault("REPORTS_DIR", "/tmp/sowknow_test_reports")

# Patch Redis before any app module imports it
_redis_patcher = patch("redis.from_url", return_value=MagicMock())
_redis_patcher.start()

# Now safe to import app modules
from app.utils.security import (  # noqa: E402
    TokenExpiredError,
    TokenInvalidError,
    create_access_token,
    create_refresh_token,
    decode_token,
    get_password_hash,
)
from app.models.user import UserRole  # noqa: E402


def _make_mock_user(**kwargs):
    """Create a mock user with sensible defaults."""
    user = MagicMock()
    user.id = kwargs.get("id", uuid.uuid4())
    user.email = kwargs.get("email", "test@example.com")
    user.hashed_password = kwargs.get("hashed_password", "")
    user.full_name = kwargs.get("full_name", "Test User")
    role = kwargs.get("role", "user")
    user.role = UserRole(role)
    user.is_superuser = kwargs.get("is_superuser", False)
    user.can_access_confidential = kwargs.get("can_access_confidential", False)
    user.is_active = kwargs.get("is_active", True)
    user.email_verified = kwargs.get("email_verified", True)
    return user


@pytest.fixture
def mock_db_session():
    """Return a MagicMock configured like an AsyncSession."""
    session = MagicMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.refresh = MagicMock()
    session.execute = AsyncMock()
    return session


@contextmanager
def _patch_db_for_auth(mock_session):
    """
    Patch all database entry points so auth endpoints use *mock_session*.

    TransactionMiddleware creates request.state.db via AsyncSessionLocal,
    and get_db() yields request.state.db when present.  We must patch both
    the middleware factory and the dependency so nothing touches a real DB.
    """
    @asynccontextmanager
    async def fake_async_session_local():
        yield mock_session

    with (
        patch("app.middleware.transaction.AsyncSessionLocal", fake_async_session_local),
        patch("app.database.get_db", return_value=iter([mock_session])),
        patch("app.api.auth.get_db", return_value=iter([mock_session])),
        patch("app.api.deps.get_db", return_value=iter([mock_session])),
    ):
        yield


# ---------------------------------------------------------------------------
# CSRF Middleware Tests
# ---------------------------------------------------------------------------


def test_csrf_middleware_allows_refresh_without_csrf_cookie():
    """
    POST /api/v1/auth/refresh must succeed even when the csrf_token cookie
    has expired, because the refresh endpoint is in EXEMPT_PATHS.
    """
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.testclient import TestClient
    from app.middleware.csrf import CSRFMiddleware

    async def refresh_endpoint(request: Request) -> JSONResponse:
        return JSONResponse({"access_token": "new"})

    app = Starlette()
    app.add_middleware(CSRFMiddleware)
    app.add_route("/api/v1/auth/refresh", refresh_endpoint, methods=["POST"])

    client = TestClient(app)
    # No csrf_token cookie, no X-CSRF-Token header
    response = client.post("/api/v1/auth/refresh")
    assert response.status_code == 200, response.text


def test_csrf_middleware_blocks_non_exempt_post_without_csrf():
    """
    POST to a non-exempt endpoint without CSRF cookie+header must return 403.
    """
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.testclient import TestClient
    from app.middleware.csrf import CSRFMiddleware

    async def protected_endpoint(request: Request) -> JSONResponse:
        return JSONResponse({"ok": True})

    app = Starlette()
    app.add_middleware(CSRFMiddleware)
    app.add_route("/api/v1/protected", protected_endpoint, methods=["POST"])

    client = TestClient(app)
    response = client.post("/api/v1/protected")
    assert response.status_code == 403
    assert response.json()["detail"] == "CSRF token missing"


def test_csrf_middleware_allows_post_with_valid_csrf():
    """
    POST with matching csrf_token cookie and X-CSRF-Token header succeeds.
    """
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.testclient import TestClient
    from app.middleware.csrf import CSRFMiddleware

    async def protected_endpoint(request: Request) -> JSONResponse:
        return JSONResponse({"ok": True})

    app = Starlette()
    app.add_middleware(CSRFMiddleware)
    app.add_route("/api/v1/protected", protected_endpoint, methods=["POST"])

    client = TestClient(app)
    client.cookies.set("csrf_token", "test-csrf")
    response = client.post("/api/v1/protected", headers={"X-CSRF-Token": "test-csrf"})
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# JWT Security Tests
# ---------------------------------------------------------------------------


def test_create_and_decode_access_token():
    """Access tokens must encode type='access' and be decodable."""
    token = create_access_token(data={"sub": "user@example.com", "role": "user"})
    payload = decode_token(token)
    assert payload["sub"] == "user@example.com"
    assert payload["role"] == "user"
    assert payload["type"] == "access"


def test_create_and_decode_refresh_token():
    """Refresh tokens must encode type='refresh'."""
    token = create_refresh_token(data={"sub": "user@example.com", "role": "user"})
    payload = decode_token(token, expected_type="refresh")
    assert payload["sub"] == "user@example.com"
    assert payload["type"] == "refresh"


def test_decode_token_rejects_wrong_type():
    """Decoding an access token as refresh must raise TokenInvalidError."""
    token = create_access_token(data={"sub": "user@example.com"})
    with pytest.raises(TokenInvalidError):
        decode_token(token, expected_type="refresh")


def test_expired_token_raises_token_expired_error():
    """A token with past exp claim must raise TokenExpiredError."""
    token = create_access_token(
        data={"sub": "user@example.com"},
        expires_delta=timedelta(seconds=-1),
    )
    with pytest.raises(TokenExpiredError):
        decode_token(token)


# ---------------------------------------------------------------------------
# Auth Endpoint Tests (with mocked DB)
# ---------------------------------------------------------------------------


def test_login_returns_cookies_and_user(mock_db_session):
    """
    POST /api/v1/auth/login must set httpOnly cookies and return user info.
    """
    from fastapi.testclient import TestClient
    from app.main import app

    hashed = get_password_hash("Secret123!")
    user = _make_mock_user(email="alice@example.com", hashed_password=hashed)

    # Mock database query
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = user
    mock_db_session.execute.return_value = mock_result

    with _patch_db_for_auth(mock_db_session):
        client = TestClient(app)
        response = client.post(
            "/api/v1/auth/login",
            data={"username": "alice@example.com", "password": "Secret123!"},
        )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["user"]["email"] == "alice@example.com"

    # Cookies must be present
    cookies = response.cookies
    assert "access_token" in cookies
    assert "refresh_token" in cookies
    assert "csrf_token" in cookies

    # access_token must be httpOnly
    access_cookie = [c for c in response.headers.get_list("set-cookie") if "access_token" in c][0]
    assert "httponly" in access_cookie.lower()


def test_refresh_endpoint_rotates_tokens(mock_db_session):
    """
    POST /api/v1/auth/refresh with a valid refresh cookie must return new
    access/refresh cookies and blacklist the old refresh token.
    """
    from fastapi.testclient import TestClient
    from app.main import app

    user = _make_mock_user(email="alice@example.com")

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = user
    mock_db_session.execute.return_value = mock_result

    refresh_token = create_refresh_token(data={"sub": "alice@example.com", "user_id": str(user.id)})

    with _patch_db_for_auth(mock_db_session), patch("app.api.auth.blacklist_token") as mock_blacklist:
        client = TestClient(app)
        client.cookies.set("refresh_token", refresh_token, path="/api/v1/auth")
        response = client.post("/api/v1/auth/refresh")

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["user"]["email"] == "alice@example.com"

    # New cookies should be set
    cookies = response.cookies
    assert "access_token" in cookies
    assert "refresh_token" in cookies

    # Old refresh token must be blacklisted
    mock_blacklist.assert_called_once()


def test_refresh_without_csrf_cookie_succeeds(mock_db_session):
    """
    After the CSRF fix, /api/v1/auth/refresh must work even when the
    csrf_token cookie has expired (no CSRF header needed).
    """
    from fastapi.testclient import TestClient
    from app.main import app

    user = _make_mock_user(email="bob@example.com")

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = user
    mock_db_session.execute.return_value = mock_result

    refresh_token = create_refresh_token(data={"sub": "bob@example.com", "user_id": str(user.id)})

    with _patch_db_for_auth(mock_db_session), patch("app.api.auth.blacklist_token"):
        client = TestClient(app)
        client.cookies.set("refresh_token", refresh_token, path="/api/v1/auth")
        # Intentionally no csrf_token cookie and no X-CSRF-Token header
        response = client.post("/api/v1/auth/refresh")

    assert response.status_code == 200, response.text


def test_logout_clears_cookies_and_blacklists_tokens(mock_db_session):
    """
    POST /api/v1/auth/logout must clear cookies and blacklist tokens.
    """
    from fastapi.testclient import TestClient
    from app.main import app

    user = _make_mock_user(email="alice@example.com")

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = user
    mock_db_session.execute.return_value = mock_result

    access_token = create_access_token(data={"sub": "alice@example.com"})
    refresh_token = create_refresh_token(data={"sub": "alice@example.com", "user_id": str(user.id)})

    with _patch_db_for_auth(mock_db_session), patch("app.api.auth.blacklist_token") as mock_blacklist:
        client = TestClient(app)
        client.cookies.set("access_token", access_token)
        client.cookies.set("refresh_token", refresh_token, path="/api/v1/auth")
        response = client.post("/api/v1/auth/logout")

    assert response.status_code == 200, response.text

    # Cookies should be cleared (max-age=0)
    set_cookies = response.headers.get_list("set-cookie")
    cleared = [c for c in set_cookies if "max-age=0" in c.lower()]
    assert len(cleared) >= 2  # access_token + refresh_token + csrf_token

    # Both tokens blacklisted
    assert mock_blacklist.call_count == 2


def test_me_endpoint_returns_current_user(mock_db_session):
    """
    GET /api/v1/auth/me with valid access_token cookie must return user info.
    """
    from fastapi.testclient import TestClient
    from app.main import app

    user = _make_mock_user(email="alice@example.com", role="admin")

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = user
    mock_db_session.execute.return_value = mock_result

    access_token = create_access_token(data={"sub": "alice@example.com", "role": "admin"})

    with _patch_db_for_auth(mock_db_session):
        client = TestClient(app)
        client.cookies.set("access_token", access_token)
        response = client.get("/api/v1/auth/me")

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["email"] == "alice@example.com"
    assert data["role"] == "admin"


def test_me_endpoint_rejects_blacklisted_token(mock_db_session):
    """
    GET /api/v1/auth/me with a blacklisted token must return 401.
    """
    from fastapi.testclient import TestClient
    from app.main import app

    access_token = create_access_token(data={"sub": "alice@example.com"})

    with _patch_db_for_auth(mock_db_session), patch("app.api.deps.is_token_blacklisted", return_value=True):
        client = TestClient(app)
        client.cookies.set("access_token", access_token)
        response = client.get("/api/v1/auth/me")

    assert response.status_code == 401
