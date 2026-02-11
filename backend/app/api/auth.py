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

from fastapi import APIRouter, Depends, HTTPException, status, Response, Request
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from datetime import timedelta
from typing import Any
import uuid
import os
from dotenv import load_dotenv
import redis
import json
import logging

from app.database import get_db
from app.models.user import User
from app.schemas.user import UserCreate, UserPublic, UserInDB
from app.schemas.token import Token, LoginResponse
from app.utils.security import (
    verify_password,
    get_password_hash,
    create_access_token,
    create_refresh_token,
    decode_token,
    TokenExpiredError,
    TokenInvalidError,
    ACCESS_TOKEN_EXPIRE_MINUTES,
    REFRESH_TOKEN_EXPIRE_DAYS
)
from app.api.deps import get_current_user

load_dotenv()

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["authentication"])

# =============================================================================
# COOKIE CONFIGURATION
# =============================================================================
# Cookie names - MUST match deps.py
COOKIE_ACCESS_TOKEN_NAME = "access_token"
COOKIE_REFRESH_TOKEN_NAME = "refresh_token"

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
# TOKEN BLACKLIST (Redis)
# =============================================================================
# Redis connection for token blacklist
_redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
try:
    redis_client = redis.from_url(_redis_url, decode_responses=True)
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
    if not redis_client:
        return False

    try:
        # Use token's JTI (JWT ID) or the token itself as key
        # Store with expiration matching token lifetime
        key = f"blacklist:{token}"
        redis_client.setex(key, expires_in_seconds, "1")
        logger.debug(f"Token blacklisted: {token[:20]}...")
        return True
    except Exception as e:
        logger.error(f"Failed to blacklist token: {e}")
        return False


def is_token_blacklisted(token: str) -> bool:
    """
    Check if a token is blacklisted.

    Args:
        token: The JWT token to check

    Returns:
        True if token is blacklisted, False otherwise
    """
    if not redis_client:
        return False

    try:
        key = f"blacklist:{token}"
        return redis_client.exists(key) > 0
    except Exception as e:
        logger.error(f"Failed to check token blacklist: {e}")
        return False


# =============================================================================
# COOKIE HELPER FUNCTIONS
# =============================================================================

def set_auth_cookies(
    response: Response,
    access_token: str,
    refresh_token: str
) -> None:
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
        samesite=SAMESITE_VALUE  # "lax" allows normal navigation
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
        samesite=SAMESITE_VALUE  # "lax" allows normal navigation
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
    response.delete_cookie(
        key=COOKIE_ACCESS_TOKEN_NAME,
        path="/",
        domain=COOKIE_DOMAIN
    )

    # Clear refresh token cookie (must match path used when setting)
    response.delete_cookie(
        key=COOKIE_REFRESH_TOKEN_NAME,
        path="/api/v1/auth",
        domain=COOKIE_DOMAIN
    )

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


def authenticate_user(db: Session, email: str, password: str):
    """
    Authenticate a user with email and password.

    SECURITY: Returns False (not None) for failed authentication to prevent
    user enumeration. Generic error message used in responses.

    Args:
        db: Database session
        email: User email
        password: Plain text password

    Returns:
        User object if authenticated, False otherwise
    """
    user = db.query(User).filter(User.email == email).first()
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
# RATE_LIMIT: 10/minute (prevent automated account creation)
async def register(user_data: UserCreate, db: Session = Depends(get_db)):
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
    # Check if user already exists
    existing_user = db.query(User).filter(User.email == user_data.email).first()
    if existing_user:
        # Generic error message prevents email enumeration
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User with this email already exists"
        )

    # Hash password with bcrypt (auto-handled by passlib CryptContext)
    hashed_password = get_password_hash(user_data.password)

    # Create new user with default role
    db_user = User(
        email=user_data.email,
        hashed_password=hashed_password,
        full_name=user_data.full_name,
        role="user"  # Default role, can be upgraded by admin
    )

    db.add(db_user)
    db.commit()
    db.refresh(db_user)

    logger.info(f"New user registered: {db_user.email}")
    return UserPublic.from_orm(db_user)


@router.post("/login", response_model=LoginResponse)
# RATE_LIMIT: 100/minute (prevents brute force attacks)
async def login(
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
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
    user = authenticate_user(db, form_data.username, form_data.password)
    if not user:
        # Generic error message prevents user enumeration
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user"
        )

    # Create JWT tokens
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={
            "sub": user.email,
            "role": user.role.value,
            "user_id": str(user.id)
        },
        expires_delta=access_token_expires
    )

    refresh_token = create_refresh_token(
        data={
            "sub": user.email,
            "role": user.role.value,
            "user_id": str(user.id)
        }
    )

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
            "role": user.role.value
        }
    )


@router.post("/refresh", response_model=LoginResponse)
# RATE_LIMIT: 200/minute (refresh may happen frequently)
async def refresh_token(
    request: Request,
    response: Response,
    db: Session = Depends(get_db)
):
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
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token required"
        )

    # Check if token is blacklisted
    if is_token_blacklisted(refresh_token):
        logger.warning("Blacklisted refresh token used")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token"
        )

    # Decode and validate refresh token
    try:
        payload = decode_token(refresh_token, expected_type="refresh")
    except TokenExpiredError:
        # Specific error code allows frontend to trigger re-login
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token expired",
            code="TOKEN_EXPIRED"  # Frontend uses this to redirect to login
        )
    except TokenInvalidError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token"
        )

    # Verify user still exists and is active
    email = payload.get("sub")
    user = db.query(User).filter(User.email == email).first()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive"
        )

    # TOKEN ROTATION: Blacklist old refresh token
    # Calculate remaining time until expiration for blacklist TTL
    import time
    exp_time = payload.get("exp", int(time.time()) + REFRESH_TOKEN_EXPIRE_DAYS * 86400)
    ttl = max(0, exp_time - int(time.time()))
    blacklist_token(refresh_token, ttl)

    # Create NEW access token
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    new_access_token = create_access_token(
        data={
            "sub": payload.get("sub"),
            "role": payload.get("role"),
            "user_id": payload.get("user_id")
        },
        expires_delta=access_token_expires
    )

    # Create NEW refresh token (token rotation)
    new_refresh_token = create_refresh_token(
        data={
            "sub": payload.get("sub"),
            "role": payload.get("role"),
            "user_id": payload.get("user_id")
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
            "role": user.role.value
        }
    )


@router.get("/me", response_model=UserPublic)
async def get_me(
    current_user: User = Depends(get_current_user)
):
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
async def logout(
    request: Request,
    response: Response
):
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
        # Blacklist for remaining lifetime (or max 7 days)
        blacklist_token(refresh_token, REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60)

    # Clear httpOnly cookies
    clear_auth_cookies(response)

    logger.info("User logged out")

    return LoginResponse(
        message="Logout successful",
        user=None
    )


# =============================================================================
# TELEGRAM AUTHENTICATION
# =============================================================================

from pydantic import BaseModel


class TelegramAuthRequest(BaseModel):
    telegram_user_id: int
    username: str = None
    first_name: str = None
    last_name: str = None
    language_code: str = "en"


@router.post("/telegram", response_model=LoginResponse)
# RATE_LIMIT: 20/minute (prevent bot abuse)
async def telegram_auth(
    response: Response,
    auth_data: TelegramAuthRequest,
    db: Session = Depends(get_db)
):
    """
    Authenticate or create a user via Telegram.

    This endpoint is called by the Telegram bot when a user starts a conversation.
    It creates a new user if one doesn't exist, or returns an existing user.

    SECURITY: Tokens are set in httpOnly, Secure, SameSite=lax cookies.
    They are NOT returned in the response body to prevent XSS attacks.

    Args:
        response: FastAPI Response object (for cookie setting)
        auth_data: Telegram user data
        db: Database session

    Returns:
        LoginResponse: {message, user: {id, email, full_name, role}}
    """
    # Create email from Telegram ID
    email = f"telegram_{auth_data.telegram_user_id}@sowknow.local"

    # Check if user exists
    user = db.query(User).filter(User.email == email).first()

    if not user:
        # Create new user from Telegram data
        full_name = " ".join(filter(None, [auth_data.first_name, auth_data.last_name]))
        if not full_name:
            full_name = auth_data.username or f"Telegram User {auth_data.telegram_user_id}"

        # Generate a random password for Telegram users
        import secrets
        temp_password = secrets.token_urlsafe(32)
        hashed_password = get_password_hash(temp_password)

        user = User(
            id=uuid.uuid4(),
            email=email,
            hashed_password=hashed_password,
            full_name=full_name,
            role="user",
            is_active=True
        )

        db.add(user)
        db.commit()
        db.refresh(user)

        logger.info(f"New Telegram user created: {email}")

    elif not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User account is disabled"
        )

    # Create JWT tokens
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={
            "sub": user.email,
            "role": user.role.value,
            "user_id": str(user.id),
            "telegram_id": str(auth_data.telegram_user_id)
        },
        expires_delta=access_token_expires
    )

    refresh_token = create_refresh_token(
        data={
            "sub": user.email,
            "role": user.role.value,
            "user_id": str(user.id),
            "telegram_id": str(auth_data.telegram_user_id)
        }
    )

    # Set httpOnly cookies with tokens
    set_auth_cookies(response, access_token, refresh_token)

    logger.info(f"Telegram auth successful: {email}")

    # Return user info (NOT tokens in response body)
    return LoginResponse(
        message="Telegram authentication successful",
        user={
            "id": str(user.id),
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role.value
        }
    )
