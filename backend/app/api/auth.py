from fastapi import APIRouter, Depends, HTTPException, status, Response
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from datetime import timedelta
from typing import Any
import uuid

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
    ACCESS_TOKEN_EXPIRE_MINUTES,
    REFRESH_TOKEN_EXPIRE_DAYS
)
from app.api.deps import get_current_user

router = APIRouter(prefix="/auth", tags=["authentication"])

# Cookie configuration
COOKIE_ACCESS_TOKEN_NAME = "access_token"
COOKIE_REFRESH_TOKEN_NAME = "refresh_token"

# In production, these should be set based on environment
COOKIE_SECURE = True  # True for HTTPS
COOKIE_SAMESITE = "strict"  # Prevents CSRF attacks
COOKIE_DOMAIN = None  # None means current domain only

def set_auth_cookies(
    response: Response,
    access_token: str,
    refresh_token: str
) -> None:
    """
    Set httpOnly, Secure, SameSite cookies for authentication tokens.

    SECURITY CRITICAL:
    - httpOnly: Prevents XSS from stealing tokens
    - Secure: Ensures cookies only sent over HTTPS
    - SameSite=strict: Prevents CSRF attacks
    """
    # Set access token cookie (15 minutes)
    response.set_cookie(
        key=COOKIE_ACCESS_TOKEN_NAME,
        value=access_token,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,  # Convert to seconds
        expires=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/",
        domain=COOKIE_DOMAIN,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE
    )

    # Set refresh token cookie (7 days)
    response.set_cookie(
        key=COOKIE_REFRESH_TOKEN_NAME,
        value=refresh_token,
        max_age=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,  # Convert to seconds
        expires=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        path="/",
        domain=COOKIE_DOMAIN,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE
    )

def clear_auth_cookies(response: Response) -> None:
    """Clear authentication cookies."""
    response.delete_cookie(
        key=COOKIE_ACCESS_TOKEN_NAME,
        path="/",
        domain=COOKIE_DOMAIN
    )
    response.delete_cookie(
        key=COOKIE_REFRESH_TOKEN_NAME,
        path="/",
        domain=COOKIE_DOMAIN
    )

def get_token_from_cookies(request: Any) -> tuple[str | None, str | None]:
    """
    Extract tokens from cookies.
    Returns (access_token, refresh_token)
    """
    access_token = request.cookies.get(COOKIE_ACCESS_TOKEN_NAME)
    refresh_token = request.cookies.get(COOKIE_REFRESH_TOKEN_NAME)
    return access_token, refresh_token

def authenticate_user(db: Session, email: str, password: str):
    """Authenticate a user with email and password"""
    user = db.query(User).filter(User.email == email).first()
    if not user:
        return False
    if not verify_password(password, user.hashed_password):
        return False
    return user

@router.post("/register", response_model=UserPublic, status_code=status.HTTP_201_CREATED)
async def register(user_data: UserCreate, db: Session = Depends(get_db)):
    """Register a new user"""
    # Check if user already exists
    existing_user = db.query(User).filter(User.email == user_data.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User with this email already exists"
        )
    
    # Create new user
    hashed_password = get_password_hash(user_data.password)
    db_user = User(
        email=user_data.email,
        hashed_password=hashed_password,
        full_name=user_data.full_name,
        role="user"
    )
    
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    
    return UserPublic.from_orm(db_user)

@router.post("/login", response_model=LoginResponse)
async def login(
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    """
    Login and set httpOnly cookies with tokens.

    SECURITY: Tokens are set in httpOnly, Secure, SameSite cookies.
    They are NOT returned in the response body to prevent XSS attacks.
    """
    user = authenticate_user(db, form_data.username, form_data.password)
    if not user:
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

    # Create tokens
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={
            "sub": user.email,
            "role": user.role,
            "user_id": str(user.id)
        },
        expires_delta=access_token_expires
    )

    refresh_token = create_refresh_token(
        data={
            "sub": user.email,
            "role": user.role,
            "user_id": str(user.id)
        }
    )

    # Set httpOnly cookies with tokens
    set_auth_cookies(response, access_token, refresh_token)

    # Return user info (NOT tokens in response body)
    return LoginResponse(
        message="Login successful",
        user={
            "id": str(user.id),
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role
        }
    )

@router.post("/refresh", response_model=LoginResponse)
async def refresh_token(
    response: Response,
    refresh_token: str | None = None,
    db: Session = Depends(get_db)
):
    """
    Refresh access token using refresh token from cookie or request body.

    SECURITY: New tokens are set in httpOnly cookies.
    The refresh token can be provided via cookie or request body for compatibility.
    """
    # Try to get refresh token from cookies if not provided in body
    if not refresh_token:
        # For cookie-based refresh, we need to access the request
        from fastapi import Request
        request: Request = response.scope.get("request")
        if request:
            refresh_token = request.cookies.get(COOKIE_REFRESH_TOKEN_NAME)

    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token required"
        )

    payload = decode_token(refresh_token)
    if not payload:
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

    # Create new access token
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={
            "sub": payload.get("sub"),
            "role": payload.get("role"),
            "user_id": payload.get("user_id")
        },
        expires_delta=access_token_expires
    )

    # Set new access token cookie
    response.set_cookie(
        key=COOKIE_ACCESS_TOKEN_NAME,
        value=access_token,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        expires=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/",
        domain=COOKIE_DOMAIN,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE
    )

    return LoginResponse(
        message="Token refreshed successfully",
        user={
            "id": str(user.id),
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role
        }
    )

@router.get("/me", response_model=UserPublic)
async def get_me(
    current_user: User = Depends(get_current_user)
):
    """
    Get current user information using token from httpOnly cookie.

    SECURITY: Token is extracted from httpOnly cookie via get_current_user dependency.
    """
    return UserPublic.from_orm(current_user)

@router.post("/logout", response_model=LoginResponse)
async def logout(response: Response):
    """
    Logout and clear authentication cookies.

    SECURITY: Clears httpOnly cookies to invalidate the session.
    """
    clear_auth_cookies(response)

    return LoginResponse(
        message="Logout successful",
        user=None
    )


# Pydantic schema for Telegram auth request
from pydantic import BaseModel

class TelegramAuthRequest(BaseModel):
    telegram_user_id: int
    username: str = None
    first_name: str = None
    last_name: str = None
    language_code: str = "en"


@router.post("/telegram", response_model=LoginResponse)
async def telegram_auth(
    response: Response,
    auth_data: TelegramAuthRequest,
    db: Session = Depends(get_db)
):
    """
    Authenticate or create a user via Telegram.

    This endpoint is called by the Telegram bot when a user starts a conversation.
    It creates a new user if one doesn't exist, or returns an existing user.

    SECURITY: Tokens are set in httpOnly, Secure, SameSite cookies.
    They are NOT returned in the response body to prevent XSS attacks.
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
            "role": user.role,
            "user_id": str(user.id),
            "telegram_id": str(auth_data.telegram_user_id)
        },
        expires_delta=access_token_expires
    )

    refresh_token = create_refresh_token(
        data={
            "sub": user.email,
            "role": user.role,
            "user_id": str(user.id),
            "telegram_id": str(auth_data.telegram_user_id)
        }
    )

    # Set httpOnly cookies with tokens
    set_auth_cookies(response, access_token, refresh_token)

    # Return user info (NOT tokens in response body)
    return LoginResponse(
        message="Telegram authentication successful",
        user={
            "id": str(user.id),
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role
        }
    )
