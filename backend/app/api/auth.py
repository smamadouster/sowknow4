from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from datetime import timedelta
from typing import Any
import uuid

from app.database import get_db
from app.models.user import User
from app.schemas.user import UserCreate, UserPublic, UserInDB
from app.schemas.token import Token
from app.utils.security import (
    verify_password,
    get_password_hash,
    create_access_token,
    create_refresh_token,
    decode_token,
    ACCESS_TOKEN_EXPIRE_MINUTES
)

router = APIRouter(prefix="/auth", tags=["authentication"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

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

@router.post("/login", response_model=Token)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    """Login and get access token"""
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
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "refresh_token": refresh_token
    }

@router.post("/refresh", response_model=Token)
async def refresh_token(refresh_token: str):
    """Refresh access token using refresh token"""
    payload = decode_token(refresh_token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token"
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
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "refresh_token": refresh_token  # Return same refresh token
    }

@router.get("/me", response_model=UserPublic)
async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
):
    """Get current user information"""
    payload = decode_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )

    email = payload.get("sub")
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    return UserPublic.from_orm(user)


# Pydantic schema for Telegram auth request
from pydantic import BaseModel

class TelegramAuthRequest(BaseModel):
    telegram_user_id: int
    username: str = None
    first_name: str = None
    last_name: str = None
    language_code: str = "en"


@router.post("/telegram", response_model=Token)
async def telegram_auth(auth_data: TelegramAuthRequest, db: Session = Depends(get_db)):
    """
    Authenticate or create a user via Telegram.

    This endpoint is called by the Telegram bot when a user starts a conversation.
    It creates a new user if one doesn't exist, or returns an existing user.
    Returns JWT tokens for API authentication.
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

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "refresh_token": refresh_token
    }
