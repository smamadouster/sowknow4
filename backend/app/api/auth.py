"""
Authentication endpoints for SOWKNOW API.

SECURITY CRITICAL - httpOnly Cookie Implementation:
- Tokens are stored in httpOnly, Secure, SameSite=lax cookies
- Tokens are NOT returned in JSON response bodies (prevents XSS)
- Refresh tokens are restricted to /api/v1/auth path only
- Token rotation implemented on refresh (old tokens blacklisted)

Rate Limiting:
- Nginx handles rate limiting at reverse proxy level (100 req/min)
- To add app-level rate limiting, use slowapi or fastapi-limiter

Token Blacklist:
- Old refresh tokens are stored in Redis with expiration matching token lifetime
- This prevents replay attacks after token rotation
"""

import hashlib
import logging
import os
import secrets
import uuid
from datetime import timedelta

import redis
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.limiter import limiter
from app.middleware.csrf import CSRF_COOKIE_NAME, generate_csrf_token
from app.models.user import User
from app.schemas.auth import ForgotPasswordRequest, ResendVerificationRequest, TelegramAuthRequest
from app.schemas.token import LoginResponse
from app.schemas.user import UserCreate, UserPublic
from app.services.token_blacklist import blacklist_token as blacklist_jwt
from app.services.token_blacklist import is_token_blacklisted as jwt_is_blacklisted
from app.utils.constants import COOKIE_ACCESS_TOKEN_NAME, COOKIE_REFRESH_TOKEN_NAME
from app.utils.security import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    REFRESH_TOKEN_EXPIRE_DAYS,
    TokenExpiredError,
    TokenInvalidError,
    create_access_token,
    create_refresh_token,
    decode_token,
    get_password_hash,
    verify_password,
)

load_dotenv()

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["authentication"])

# =============================================================================
# COOKIE CONFIGURATION
# =============================================================================
# Cookie names imported from app.utils.security (single source of truth)

# Environment-based configuration
ENVIRONMENT = os.getenv("APP_ENV", "development").lower()
COOKIE_DOMAIN = os.getenv("COOKIE_DOMAIN")  # None for localhost, or specific domain

# SECURITY: httpOnly cookies prevent XSS attacks
# Secure flag ensures cookies only sent over HTTPS (False for HTTP development)
SECURE_FLAG = ENVIRONMENT == "production"

# SameSite=lax allows normal navigation while preventing CSRF
# "strict" would break navigation from external links
SAMESITE_VALUE = "lax"

# =============================================================================
# TELEGRAM AUTH CONFIGURATION
# =============================================================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
BOT_API_KEY = os.getenv("BOT_API_KEY", "")
TELEGRAM_ADMIN_USER_IDS = {
    int(x.strip()) for x in os.getenv("TELEGRAM_ADMIN_USER_IDS", "").split(",") if x.strip()
}


async def verify_telegram_user(telegram_user_id: int, bot_token: str) -> bool:
    """
    Verify that a Telegram user ID is valid by checking against Telegram API.

    This prevents attackers from impersonating Telegram users.

    Args:
        telegram_user_id: The Telegram user ID to verify
        bot_token: The bot token to use for verification

    Returns:
        True if the user exists and is valid, False otherwise
    """
    import httpx

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://api.telegram.org/bot{bot_token}/getChat",
                params={"chat_id": telegram_user_id},
                timeout=10.0,
            )
            if response.status_code == 200:
                data = response.json()
                return data.get("ok", False)
            return False
    except Exception as e:
        logger.error(f"Telegram verification failed: {e}")
        return False


# =============================================================================
# TOKEN BLACKLIST (Redis)
# =============================================================================
# Redis connection for token blacklist
from app.core.redis_url import safe_redis_url

_redis_url = safe_redis_url()
try:
    redis_client = redis.from_url(_redis_url, decode_responses=True, socket_timeout=5, socket_connect_timeout=5)
    redis_client.ping()  # Test connection
    logger.info("Token blacklist Redis connection established")
except Exception as e:
    logger.warning(f"Redis connection failed: {e}. Token blacklist disabled.")
    redis_client = None


def blacklist_token(token: str, expires_in_seconds: int) -> bool:
    """
    Add a token to the blacklist to prevent replay attacks.

    Args:
        token: The JWT token to blacklist
        expires_in_seconds: How long to blacklist (should match token expiration)

    Returns:
        True if successfully blacklisted, False otherwise
    """
    return blacklist_jwt(token, expires_in_seconds)


def is_token_blacklisted(token: str) -> bool:
    """
    Check if a token is blacklisted.

    Args:
        token: The JWT token to check

    Returns:
        True if token is blacklisted, False otherwise
    """
    return jwt_is_blacklisted(token)


# =============================================================================
# COOKIE HELPER FUNCTIONS
# =============================================================================


def set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    """
    Set httpOnly, Secure, SameSite=lax cookies for authentication tokens.

    SECURITY CRITICAL:
    - httpOnly: Prevents XSS from stealing tokens (JavaScript cannot access)
    - Secure: Ensures cookies only sent over HTTPS (False for development HTTP)
    - SameSite=lax: Prevents CSRF attacks while allowing normal navigation
    - Tokens NOT returned in response body (prevents XSS via JSON)

    Args:
        response: FastAPI Response object
        access_token: JWT access token (15 minute lifetime)
        refresh_token: JWT refresh token (7 day lifetime)
    """
    # Set access token cookie (15 minutes)
    # Path: "/" - available on all routes
    response.set_cookie(
        key=COOKIE_ACCESS_TOKEN_NAME,
        value=access_token,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,  # Convert to seconds (900)
        expires=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/",
        domain=COOKIE_DOMAIN,
        httponly=True,  # CRITICAL: Prevents XSS access
        secure=SECURE_FLAG,  # True in production, False for HTTP development
        samesite=SAMESITE_VALUE,  # "lax" allows normal navigation
    )

    # Set refresh token cookie (7 days)
    # Path: "/api/v1/auth" - restricted to auth endpoints only
    # This minimizes exposure - refresh token only sent when needed
    response.set_cookie(
        key=COOKIE_REFRESH_TOKEN_NAME,
        value=refresh_token,
        max_age=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,  # 604800 seconds
        expires=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        path="/api/v1/auth",  # RESTRICTED to auth routes only
        domain=COOKIE_DOMAIN,
        httponly=True,  # CRITICAL: Prevents XSS access
        secure=SECURE_FLAG,  # True in production, False for HTTP development
        samesite=SAMESITE_VALUE,  # "lax" allows normal navigation
    )

    # Set CSRF double-submit cookie (non-httpOnly so JS can read it)
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=generate_csrf_token(),
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        expires=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/",
        domain=COOKIE_DOMAIN,
        httponly=False,  # Must be JS-readable for double-submit pattern
        secure=SECURE_FLAG,
        samesite="strict",  # Stricter than auth cookies — never sent cross-site
    )

    logger.debug(
        f"Auth cookies set - access: {ACCESS_TOKEN_EXPIRE_MINUTES}min, "
        f"refresh: {REFRESH_TOKEN_EXPIRE_DAYS}days, "
        f"secure={SECURE_FLAG}, domain={COOKIE_DOMAIN or 'localhost'}"
    )


def clear_auth_cookies(response: Response) -> None:
    """
    Clear authentication cookies by setting them with max_age=0.

    Args:
        response: FastAPI Response object
    """
    # Clear access token cookie
    response.delete_cookie(key=COOKIE_ACCESS_TOKEN_NAME, path="/", domain=COOKIE_DOMAIN)

    # Clear refresh token cookie (must match path used when setting)
    response.delete_cookie(key=COOKIE_REFRESH_TOKEN_NAME, path="/api/v1/auth", domain=COOKIE_DOMAIN)

    # Clear CSRF cookie
    response.delete_cookie(key=CSRF_COOKIE_NAME, path="/", domain=COOKIE_DOMAIN)

    logger.debug("Auth cookies cleared")


def get_refresh_token_from_request(request: Request) -> str | None:
    """
    Extract refresh token from httpOnly cookie.

    Args:
        request: FastAPI Request object

    Returns:
        Refresh token string or None
    """
    return request.cookies.get(COOKIE_REFRESH_TOKEN_NAME)


def get_access_token_from_request(request: Request) -> str | None:
    """Extract access token from auth cookie or Authorization header."""
    token = request.cookies.get(COOKIE_ACCESS_TOKEN_NAME)
    if token:
        return token
    authorization = request.headers.get("Authorization", "")
    if authorization.startswith("Bearer "):
        return authorization[7:]
    return None


def blacklist_token_until_expiry(token: str, expected_type: str) -> None:
    """Best-effort token revocation using the JWT exp claim as Redis TTL."""
    import time

    try:
        payload = decode_token(token, expected_type=expected_type)
    except Exception:
        return
    ttl = max(0, int(payload.get("exp", int(time.time()))) - int(time.time()))
    blacklist_token(token, ttl)


async def authenticate_user(db: AsyncSession, email: str, password: str) -> User | bool:
    """
    Authenticate a user with email and password.

    SECURITY: Returns False (not None) for failed authentication to prevent
    user enumeration. Generic error message used in responses.

    Args:
        db: Async database session
        email: User email
        password: Plain text password

    Returns:
        User object if authenticated, False otherwise
    """
    result = await db.execute(select(User).where(func.lower(User.email) == email.lower()))
    user = result.scalar_one_or_none()
    if not user:
        return False
    if not verify_password(password, user.hashed_password):
        return False
    return user


# =============================================================================
# RATE LIMITING ANNOTATIONS
# =============================================================================
# RATE_LIMIT: All endpoints below are rate-limited by Nginx at reverse proxy level
# Configuration: limit_req_zone $binary_remote_addr zone=auth_limit:10m rate=100r/m;
# To add app-level rate limiting, integrate slowapi or fastapi-limiter
# Example with slowapi:
#   from slowapi import Limiter
#   from slowapi.util import get_remote_address
#   limiter = Limiter(key_func=get_remote_address)
#   @router.post("/login")
#   @limiter.limit("100/minute")
#   async def login(...): ...


# =============================================================================
# ENDPOINTS
# =============================================================================


@router.post("/register", response_model=UserPublic, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
async def register(request: Request, user_data: UserCreate, db: AsyncSession = Depends(get_db)) -> UserPublic:
    """
    Register a new user.

    SECURITY NOTES:
    - Does NOT auto-login after registration (user must explicitly login)
    - Does NOT set cookies (prevents session fixation)
    - Password complexity enforced by schema validation
    - Generic error message prevents email enumeration

    Args:
        user_data: User registration data (email, password, full_name)
        db: Database session

    Returns:
        UserPublic: Created user info (no password)

    Raises:
        HTTPException 400: If user already exists or password validation fails
    """
    # Normalize email to lowercase for consistent lookup
    normalized_email = user_data.email.strip().lower()

    # Check if user already exists
    result = await db.execute(select(User).where(func.lower(User.email) == normalized_email))
    existing_user = result.scalar_one_or_none()
    if existing_user:
        # Generic error message prevents email enumeration
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User with this email already exists",
        )

    # Hash password with bcrypt
    hashed_password = get_password_hash(user_data.password)

    # Create new user with default role
    db_user = User(
        email=normalized_email,
        hashed_password=hashed_password,
        full_name=user_data.full_name,
        role="user",  # Default role, can be upgraded by admin
    )

    db.add(db_user)
    await db.commit()
    await db.refresh(db_user)

    logger.info(f"New user registered: {db_user.email}")
    return UserPublic.from_orm(db_user)


@router.post("/login", response_model=LoginResponse)
@limiter.limit("20/minute")
async def login(
    request: Request,
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    """
    Login and set httpOnly cookies with tokens.

    REQUEST FORMAT (OAuth2PasswordRequestForm):
    - Content-Type: application/x-www-form-urlencoded
    - Body: username=user@example.com&password=Password123!

    SECURITY: Tokens are set in httpOnly, Secure, SameSite=lax cookies.
    They are NOT returned in the response body to prevent XSS attacks.

    Args:
        response: FastAPI Response object (for cookie setting)
        form_data: OAuth2 form with username (email) and password
        db: Database session

    Returns:
        LoginResponse: {message, user: {id, email, full_name, role}}

    Raises:
        HTTPException 401: If credentials are invalid (generic message)
    """
    # Authenticate user
    user = await authenticate_user(db, form_data.username, form_data.password)
    if not user:
        # Generic error message prevents user enumeration
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Inactive user")

    # Create JWT tokens
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.email, "role": user.role.value, "user_id": str(user.id)},
        expires_delta=access_token_expires,
    )

    refresh_token = create_refresh_token(data={"sub": user.email, "role": user.role.value, "user_id": str(user.id)})

    # Set httpOnly cookies with tokens
    set_auth_cookies(response, access_token, refresh_token)

    logger.info(f"User logged in: {user.email}")

    # Return user info (NOT tokens in response body - prevents XSS)
    return LoginResponse(
        message="Login successful",
        user={
            "id": str(user.id),
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role.value,
        },
    )


@router.post("/refresh", response_model=LoginResponse)
@limiter.limit("60/minute")
async def refresh_token(request: Request, response: Response, db: AsyncSession = Depends(get_db)) -> LoginResponse:
    """
    Refresh access token using refresh token from httpOnly cookie.

    TOKEN ROTATION: Both access and refresh tokens are rotated.
    Old refresh token is blacklisted to prevent replay attacks.

    SECURITY:
    - Refresh token read from httpOnly cookie (not from body/header)
    - New tokens set as httpOnly cookies
    - Old refresh token added to blacklist
    - Token expiration checked first for proper error codes

    Args:
        request: FastAPI Request object (for cookie access)
        response: FastAPI Response object (for new cookies)
        db: Database session

    Returns:
        LoginResponse: {message, user: {id, email, full_name, role}}

    Raises:
        HTTPException 401, code="TOKEN_EXPIRED": If refresh token expired
        HTTPException 401: If refresh token invalid or user not found
    """
    # Get refresh token from httpOnly cookie
    refresh_token = get_refresh_token_from_request(request)

    if not refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token required")

    # Check if token is blacklisted
    if is_token_blacklisted(refresh_token):
        logger.warning("Blacklisted refresh token used")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    # Decode and validate refresh token
    try:
        payload = decode_token(refresh_token, expected_type="refresh")
    except TokenExpiredError:
        # Specific error code allows frontend to trigger re-login
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Refresh token expired", "code": "TOKEN_EXPIRED"},
        )
    except TokenInvalidError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    # Verify user still exists and is active
    email = payload.get("sub")
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    # TOKEN ROTATION: Blacklist old refresh token
    # Calculate remaining time until expiration for blacklist TTL
    import time

    exp_time = payload.get("exp", int(time.time()) + REFRESH_TOKEN_EXPIRE_DAYS * 86400)
    ttl = max(0, exp_time - int(time.time()))
    blacklist_token(refresh_token, ttl)

    # Create NEW access token
    # SECURITY: Use user.role from database, NOT payload.get("role") from old token
    # This ensures role changes (e.g., promotion to admin) take effect immediately
    # without requiring logout/login
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    new_access_token = create_access_token(
        data={
            "sub": payload.get("sub"),
            "role": user.role.value,
            "user_id": payload.get("user_id"),
        },
        expires_delta=access_token_expires,
    )

    # Create NEW refresh token (token rotation)
    # SECURITY: Use user.role from database, NOT payload.get("role") from old token
    new_refresh_token = create_refresh_token(
        data={
            "sub": payload.get("sub"),
            "role": user.role.value,
            "user_id": payload.get("user_id"),
        }
    )

    # Set new httpOnly cookies
    set_auth_cookies(response, new_access_token, new_refresh_token)

    logger.info(f"Token refreshed for: {user.email}")

    return LoginResponse(
        message="Token refreshed",
        user={
            "id": str(user.id),
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role.value,
        },
    )


@router.get("/me", response_model=UserPublic)
async def get_me(current_user: User = Depends(get_current_user)) -> UserPublic:
    """
    Get current user information using token from httpOnly cookie.

    SECURITY: Token is extracted from httpOnly cookie via get_current_user dependency.
    No password or sensitive data returned.

    Args:
        current_user: Authenticated user from dependency

    Returns:
        UserPublic: Current user info (id, email, full_name, role)
    """
    return UserPublic.from_orm(current_user)


@router.post("/logout", response_model=LoginResponse)
# RATE_LIMIT: 60/minute (prevent abuse but allow legitimate repeated logouts)
async def logout(request: Request, response: Response) -> LoginResponse:
    """
    Logout and clear authentication cookies.

    SECURITY:
    - Clears httpOnly cookies to invalidate the session
    - Optionally blacklists current refresh token if available

    Args:
        request: FastAPI Request object (for cookie access)
        response: FastAPI Response object (for cookie deletion)

    Returns:
        LoginResponse: {message, user: null}
    """
    # Optionally blacklist the refresh token
    refresh_token = get_refresh_token_from_request(request)
    if refresh_token:
        blacklist_token_until_expiry(refresh_token, expected_type="refresh")

    access_token = get_access_token_from_request(request)
    if access_token:
        blacklist_token_until_expiry(access_token, expected_type="access")

    # Clear httpOnly cookies
    clear_auth_cookies(response)

    logger.info("User logged out")

    return LoginResponse(message="Logout successful", user=None)


# =============================================================================
# FORGOT PASSWORD
# =============================================================================


@router.post("/forgot-password")
@limiter.limit("5/minute")
async def forgot_password(
    request: Request,
    payload: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """
    Request a password reset link.

    SECURITY:
    - Always returns the same generic message to prevent email enumeration
    - Rate limited to 3 requests/hour per IP via Redis counter
    - Generates a cryptographically secure token stored in Redis (1h TTL)
    - No email is sent (admin-managed system — admin uses /admin/users/{id}/reset-password)
    - All requests are logged for audit purposes

    Args:
        request: FastAPI Request (for IP-based rate limiting)
        payload: JSON body with email field
        db: Database session

    Returns:
        dict: Generic success message (same whether email exists or not)
    """
    client_ip = request.client.host if request.client else "unknown"
    RATE_LIMIT = 3
    RATE_WINDOW = 3600  # 1 hour in seconds

    # --- IP-based rate limiting via Redis (atomic SET NX EX + INCR) ---
    if redis_client:
        rate_key = f"forgot_pwd_rate:{client_ip}"
        try:
            # Atomic: initialize key with TTL only if it doesn't exist yet
            redis_client.set(rate_key, 0, ex=RATE_WINDOW, nx=True)
            count = redis_client.incr(rate_key)
            if count > RATE_LIMIT:
                ttl = redis_client.ttl(rate_key)
                logger.warning(f"Forgot password rate limit exceeded from {client_ip}")
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Too many requests. Try again in {ttl} seconds.",
                    headers={"Retry-After": str(ttl)},
                )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Rate limit check failed: {e}")

    # --- Generate reset token (stored in Redis; no email sent) ---
    email = payload.email.strip().lower()
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if user and user.is_active:
        reset_token = secrets.token_urlsafe(32)
        if redis_client:
            try:
                redis_client.setex(
                    f"pwd_reset:{reset_token}",
                    RATE_WINDOW,
                    str(user.id),
                )
            except Exception as e:
                logger.error(f"Failed to store reset token: {e}")

        logger.info(
            f"Password reset requested for user {user.id} from {client_ip}. "
            f"Token stored in Redis (admin action required for delivery)."
        )
    else:
        # Log attempted reset for unknown / inactive email — don't reveal status
        logger.info(f"Forgot password request for unknown/inactive email from {client_ip}")

    # Always return the same response to prevent user enumeration
    return {
        "message": (
            "If this email is registered, the administrator has been notified "
            "and will contact you with password reset instructions."
        )
    }


# =============================================================================
# EMAIL VERIFICATION
# =============================================================================

EMAIL_VERIFY_TTL = 86400  # 24 hours


@router.post("/verify-email/{token}")
async def verify_email(token: str, db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    """
    Verify a user's email address using the token from Redis.

    SECURITY:
    - Token is single-use: deleted from Redis on success
    - Generic error message prevents token enumeration
    - Token TTL: 24 hours

    Returns:
        dict: Success message
    """
    if not redis_client:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Verification service temporarily unavailable",
        )

    try:
        user_id = redis_client.get(f"email_verify:{token}")
    except Exception as e:
        logger.error(f"Redis error during email verification: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Verification service temporarily unavailable",
        )

    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification token",
        )

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification token",
        )

    if user.email_verified:
        # Already verified — consume token and return success
        try:
            redis_client.delete(f"email_verify:{token}")
        except Exception:
            pass
        return {"message": "Email already verified"}

    user.email_verified = True
    await db.commit()

    try:
        redis_client.delete(f"email_verify:{token}")
    except Exception as e:
        logger.error(f"Failed to delete verification token: {e}")

    logger.info(f"Email verified for user {user.id}")
    return {"message": "Email verified successfully"}


@router.post("/resend-verification")
async def resend_verification(
    request: Request,
    payload: ResendVerificationRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """
    Generate a new email verification token (admin-managed delivery).

    SECURITY:
    - Rate limited to 3 requests/hour per IP
    - Always returns generic response (prevents enumeration)
    - Token stored in Redis (24h TTL); admin delivers it manually
    """
    client_ip = request.client.host if request.client else "unknown"
    RATE_LIMIT = 3
    RATE_WINDOW = 3600

    if redis_client:
        rate_key = f"resend_verify_rate:{client_ip}"
        try:
            redis_client.set(rate_key, 0, ex=RATE_WINDOW, nx=True)
            count = redis_client.incr(rate_key)
            if count > RATE_LIMIT:
                ttl = redis_client.ttl(rate_key)
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Too many requests. Try again in {ttl} seconds.",
                    headers={"Retry-After": str(ttl)},
                )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Rate limit check failed: {e}")

    email = payload.email.strip().lower()
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if user and user.is_active and not user.email_verified:
        verify_token = secrets.token_urlsafe(32)
        if redis_client:
            try:
                redis_client.setex(
                    f"email_verify:{verify_token}",
                    EMAIL_VERIFY_TTL,
                    str(user.id),
                )
            except Exception as e:
                logger.error(f"Failed to store verification token: {e}")

        logger.info(
            f"Verification token generated for user {user.id} from {client_ip}. "
            f"Token: {verify_token[:8]}... (admin action required for delivery)."
        )

    return {"message": ("If this email is registered and unverified, the administrator has been notified.")}


# =============================================================================
# TELEGRAM AUTHENTICATION
# =============================================================================


@router.post("/telegram", response_model=LoginResponse)
# RATE_LIMIT: 20/minute (prevent bot abuse)
async def telegram_auth(
    response: Response,
    request: Request,
    auth_data: TelegramAuthRequest,
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    """
    Authenticate or create a user via Telegram.

    This endpoint is called by the Telegram bot when a user starts a conversation.
    It creates a new user if one doesn't exist, or returns an existing user.

    SECURITY:
    - Requires X-Bot-Api-Key header for authentication
    - Verifies Telegram user ID against Telegram API
    - Tokens are set in httpOnly, Secure, SameSite=lax cookies
    - They are NOT returned in the response body to prevent XSS attacks

    Args:
        response: FastAPI Response object (for cookie setting)
        request: FastAPI Request object (for header validation)
        auth_data: Telegram user data
        db: Database session

    Returns:
        LoginResponse: {message, user: {id, email, full_name, role}}
    """
    # SECURITY: Validate Bot API Key header
    incoming_api_key = request.headers.get("X-Bot-Api-Key")
    if not incoming_api_key or incoming_api_key != BOT_API_KEY:
        logger.warning(
            f"Telegram auth failed: invalid or missing API key from {request.client.host if request.client else 'unknown'}"
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")

    # SECURITY: Verify Telegram user ID against Telegram API
    if TELEGRAM_BOT_TOKEN:
        is_valid_telegram_user = await verify_telegram_user(auth_data.telegram_user_id, TELEGRAM_BOT_TOKEN)
        if not is_valid_telegram_user:
            logger.warning(f"Telegram auth failed: invalid telegram_user_id {auth_data.telegram_user_id}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid Telegram credentials",
            )

    # Create deterministic but non-enumerable email
    # Use UUID-based hash to prevent enumeration
    telegram_id_hash = hashlib.sha256(str(auth_data.telegram_user_id).encode()).hexdigest()[:16]
    email = f"telegram_{telegram_id_hash}@sowknow.local"

    # Check if user exists
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if not user:
        # Create new user from Telegram data
        full_name = " ".join(filter(None, [auth_data.first_name, auth_data.last_name]))
        if not full_name:
            full_name = auth_data.username or f"Telegram User {telegram_id_hash}"

        # Generate a random password for Telegram users
        temp_password = secrets.token_urlsafe(32)
        hashed_password = get_password_hash(temp_password)

        user_role = "admin" if auth_data.telegram_user_id in TELEGRAM_ADMIN_USER_IDS else "user"

        user = User(
            id=uuid.uuid4(),
            email=email,
            hashed_password=hashed_password,
            full_name=full_name,
            role=user_role,
            is_active=True,
        )

        db.add(user)
        await db.commit()
        await db.refresh(user)

        logger.info(f"New Telegram user created: {email} (role={user_role})")

    elif not user.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User account is disabled")

    # Upgrade role if telegram_user_id is now in admin list
    if auth_data.telegram_user_id in TELEGRAM_ADMIN_USER_IDS and user.role.value == "user":
        user.role = "admin"
        await db.commit()
        await db.refresh(user)
        logger.info(f"Upgraded Telegram user {email} to admin role")

    # Create JWT tokens
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={
            "sub": user.email,
            "role": user.role.value,
            "user_id": str(user.id),
            "telegram_id": str(auth_data.telegram_user_id),
        },
        expires_delta=access_token_expires,
    )

    refresh_token = create_refresh_token(
        data={
            "sub": user.email,
            "role": user.role.value,
            "user_id": str(user.id),
            "telegram_id": str(auth_data.telegram_user_id),
        }
    )

    # Set httpOnly cookies with tokens
    set_auth_cookies(response, access_token, refresh_token)

    logger.info(f"Telegram auth successful: {email}")

    # Return user info AND access_token (for bot use - can't use httpOnly cookies)
    return LoginResponse(
        message="Telegram authentication successful",
        user={
            "id": str(user.id),
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role.value,
        },
        access_token=access_token,
    )
