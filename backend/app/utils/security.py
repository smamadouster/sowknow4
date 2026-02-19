from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from jose import JWTError, jwt, ExpiredSignatureError
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
import os
from dotenv import load_dotenv

from app.database import get_db
from app.models.user import User, UserRole

load_dotenv()

# Security configuration
SECRET_KEY = os.getenv("JWT_SECRET")
if not SECRET_KEY:
    raise ValueError("JWT_SECRET environment variable is required")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "15"))
REFRESH_TOKEN_EXPIRE_DAYS = 7

pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
    bcrypt__default_rounds=12
)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


# Custom JWT exceptions
class TokenExpiredError(Exception):
    """Raised when a JWT token has expired"""
    def __init__(self, message: str = "Token has expired"):
        self.message = message
        super().__init__(self.message)


class TokenInvalidError(Exception):
    """Raised when a JWT token is invalid (tampered, malformed, bad signature, etc.)"""
    def __init__(self, message: str = "Token is invalid"):
        self.message = message
        super().__init__(self.message)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against a hashed password"""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Hash a password"""
    return pwd_context.hash(password)


def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT access token with a 'type': 'access' claim"""
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({"exp": expire, "type": "access"})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def create_refresh_token(data: Dict[str, Any]) -> str:
    """Create a JWT refresh token with a 'type': 'refresh' claim and 7-day expiration"""
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": "refresh"})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def decode_token(token: str, expected_type: Optional[str] = "access") -> Optional[Dict[str, Any]]:
    """
    Decode and validate a JWT token.

    Args:
        token: The JWT token string to decode
        expected_type: Expected token type ('access', 'refresh', or None to skip validation)

    Returns:
        The decoded payload dict on success

    Raises:
        TokenExpiredError: If the token has expired
        TokenInvalidError: If the token is invalid, tampered, malformed, missing 'sub' claim,
                           or has an incorrect 'type' claim
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except ExpiredSignatureError:
        raise TokenExpiredError()
    except JWTError:
        raise TokenInvalidError()

    # Validate that the token contains a 'sub' claim (subject/user identifier)
    if "sub" not in payload:
        raise TokenInvalidError("Token missing 'sub' claim")

    # Validate token type if expected_type is specified
    if expected_type is not None:
        token_type = payload.get("type")
        if token_type != expected_type:
            raise TokenInvalidError(f"Expected token type '{expected_type}', got '{token_type}'")

    return payload


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> User:
    """Get current authenticated user from JWT token"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = decode_token(token, expected_type="access")
    except (TokenExpiredError, TokenInvalidError):
        raise credentials_exception

    email: str = payload.get("sub")
    if email is None:
        raise credentials_exception

    user = db.query(User).filter(User.email == email).first()
    if user is None:
        raise credentials_exception

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user"
        )

    return user


async def require_admin(
    current_user: User = Depends(get_current_user)
) -> User:
    """Require admin or superuser role"""
    if current_user.role not in [UserRole.ADMIN, UserRole.SUPERUSER]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required"
        )
    return current_user


async def require_admin_only(
    current_user: User = Depends(get_current_user)
) -> User:
    """Require admin role only (superuser gets 403)"""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required"
        )
    return current_user
