"""
Authentication dependencies for SOWKNOW API.

This module provides FastAPI dependencies for JWT validation and role-based access control.
Following CLAUDE.md RBAC requirements:
- ADMIN: Full access (view, upload, delete, modify)
- SUPERUSER: View-only access to all documents (cannot upload/delete/modify)
- USER: Public documents only

SECURITY: Supports both cookie-based (httpOnly) and Authorization header authentication.
Cookie-based auth is preferred for better security (httpOnly prevents XSS).
"""

from typing import Optional
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from jose import JWTError
import logging

from app.database import get_db
from app.models.user import User, UserRole
from app.utils.security import decode_token, TokenInvalidError, TokenExpiredError

logger = logging.getLogger(__name__)

# Cookie names (must match auth.py)
COOKIE_ACCESS_TOKEN_NAME = "access_token"

# Support both Authorization header (for backward compatibility) and cookies
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


async def get_token_from_request(request: Request) -> Optional[str]:
    """
    Extract JWT token from either httpOnly cookie or Authorization header.

    SECURITY: Priority order:
    1. httpOnly cookie (preferred, prevents XSS)
    2. Authorization header (for backward compatibility)

    Args:
        request: FastAPI Request object

    Returns:
        JWT token string or None
    """
    # Try httpOnly cookie first (more secure)
    token = request.cookies.get(COOKIE_ACCESS_TOKEN_NAME)
    if token:
        logger.debug("Using token from httpOnly cookie")
        return token

    # Fallback to Authorization header for backward compatibility
    authorization = request.headers.get("Authorization")
    if authorization and authorization.startswith("Bearer "):
        token = authorization.replace("Bearer ", "")
        logger.debug("Using token from Authorization header")
        return token

    return None


async def get_current_user(
    request: Request,
    db: Session = Depends(get_db)
) -> User:
    """
    Extract and validate JWT token from cookie or header, return User object.

    Args:
        request: FastAPI Request object (for cookie/header access)
        db: Database session

    Returns:
        User: Authenticated user object

    Raises:
        HTTPException 401: If token is invalid, expired, or user not found/inactive
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # Get token from cookie or header
    token = await get_token_from_request(request)
    if not token:
        logger.warning("Authentication failed: No token found in cookie or header")
        raise credentials_exception

    # Decode token with proper exception handling
    try:
        payload = decode_token(token)
    except TokenExpiredError:
        logger.warning(f"Authentication failed: Token expired")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except TokenInvalidError as e:
        logger.warning(f"Authentication failed: Invalid token - {str(e)}")
        raise credentials_exception
    except Exception as e:
        logger.warning(f"Authentication failed: Token decode error - {str(e)}")
        raise credentials_exception
    
    if not payload:
        logger.warning(f"Authentication failed: Invalid token")
        raise credentials_exception

    # Extract user identifier
    email: Optional[str] = payload.get("sub")
    if email is None:
        logger.warning(f"Authentication failed: Token missing subject")
        raise credentials_exception

    # Lookup user in database
    user = db.query(User).filter(User.email == email).first()
    if user is None:
        logger.warning(f"Authentication failed: User not found for email {email}")
        raise credentials_exception

    # Check if user is active
    if not user.is_active:
        logger.warning(f"Authentication failed: User {email} is inactive")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Inactive user"
        )

    logger.debug(f"User authenticated: {email} (role: {user.role})")
    return user


async def require_admin(
    current_user: User = Depends(get_current_user)
) -> User:
    """
    Require ADMIN role for access.

    Use this dependency for endpoints that only administrators should access.

    Args:
        current_user: Authenticated user from get_current_user

    Returns:
        User: The authenticated admin user

    Raises:
        HTTPException 403: If user is not an ADMIN
    """
    if current_user.role != UserRole.ADMIN:
        logger.warning(
            f"Authorization failed: User {current_user.email} "
            f"(role: {current_user.role}) attempted admin-only access"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator access required"
        )

    return current_user


async def require_superuser_or_admin(
    current_user: User = Depends(get_current_user)
) -> User:
    """
    Require SUPERUSER or ADMIN role for access.

    Use this dependency for endpoints that allow viewing but NOT modifying.
    Both SUPERUSER and ADMIN can view, but only ADMIN can modify.

    Args:
        current_user: Authenticated user from get_current_user

    Returns:
        User: The authenticated user (must be SUPERUSER or ADMIN)

    Raises:
        HTTPException 403: If user is neither SUPERUSER nor ADMIN
    """
    if current_user.role not in (UserRole.SUPERUSER, UserRole.ADMIN):
        logger.warning(
            f"Authorization failed: User {current_user.email} "
            f"(role: {current_user.role}) attempted privileged view access"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Elevated privileges required"
        )

    return current_user


async def require_admin_only(
    current_user: User = Depends(get_current_user)
) -> User:
    """
    Require ADMIN role for modifying operations.

    Use this dependency for endpoints that perform modifications (upload, delete, update).
    SUPERUSER can view but CANNOT modify - this enforces that constraint.

    Args:
        current_user: Authenticated user from get_current_user

    Returns:
        User: The authenticated admin user

    Raises:
        HTTPException 403: If user is not an ADMIN (SUPERUSER is rejected)
    """
    if current_user.role != UserRole.ADMIN:
        logger.warning(
            f"Authorization failed: User {current_user.email} "
            f"(role: {current_user.role}) attempted modification "
            f"(SUPERUSER view-only restriction enforced)"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator access required for modifications"
        )

    return current_user


async def require_confidential_access(
    current_user: User = Depends(get_current_user)
) -> User:
    """
    Require confidential access permission.

    Use this dependency for endpoints that access confidential documents.
    Users must have can_access_confidential flag set to True.

    Args:
        current_user: Authenticated user from get_current_user

    Returns:
        User: The authenticated user with confidential access

    Raises:
        HTTPException 403: If user lacks confidential access permission
    """
    if not current_user.can_access_confidential:
        logger.warning(
            f"Authorization failed: User {current_user.email} "
            f"(role: {current_user.role}) attempted confidential access "
            f"without permission"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Confidential access required"
        )

    return current_user


async def require_confidential_access_or_admin(
    current_user: User = Depends(get_current_user)
) -> User:
    """
    Require confidential access permission OR admin role.

    Use this dependency for endpoints where either:
    - User has explicit confidential access permission, OR
    - User is an administrator

    Args:
        current_user: Authenticated user from get_current_user

    Returns:
        User: The authenticated user with appropriate access

    Raises:
        HTTPException 403: If user lacks both confidential access and admin role
    """
    if not (current_user.can_access_confidential or current_user.role == UserRole.ADMIN):
        logger.warning(
            f"Authorization failed: User {current_user.email} "
            f"(role: {current_user.role}) attempted confidential access "
            f"without permission or admin role"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Confidential access or administrator role required"
        )

    return current_user


def require_role(*allowed_roles: UserRole):
    """
    Factory function that creates a role-based authorization dependency.

    Use this to create custom role requirements for endpoints.
    The returned dependency checks if the authenticated user's role
    is among the allowed roles.

    Args:
        *allowed_roles: Variable number of UserRole enum values that are permitted

    Returns:
        A FastAPI dependency function that validates user roles

    Example:
        # Allow only ADMIN
        @app.get("/admin-only")
        async def admin_only(user: User = Depends(require_role(UserRole.ADMIN))):
            ...

        # Allow ADMIN or SUPERUSER
        @app.get("/privileged")
        async def privileged(user: User = Depends(require_role(UserRole.ADMIN, UserRole.SUPERUSER))):
            ...

        # Allow all authenticated users
        @app.get("/any-authenticated")
        async def any_auth(user: User = Depends(require_role(UserRole.USER, UserRole.SUPERUSER, UserRole.ADMIN))):
            ...
    """
    async def role_checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            logger.warning(
                f"Authorization failed: User {current_user.email} "
                f"(role: {current_user.role}) attempted access - "
                f"allowed roles: {[r.value for r in allowed_roles]}"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required role(s): {', '.join([r.value for r in allowed_roles])}"
            )
        return current_user

    return role_checker


# =============================================================================
# Convenience shortcuts for common role requirements
# =============================================================================

# Alias for any authenticated user (no role restriction)
require_any_authenticated = get_current_user

# ADMIN only (full access: view, upload, delete, modify)
# Use this for write operations that SUPERUSER should NOT perform
require_write_access = require_admin_only
