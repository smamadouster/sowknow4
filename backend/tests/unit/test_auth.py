"""
Unit tests for authentication endpoints.

Updated for httpOnly cookie-based authentication:
- Tokens are set in httpOnly cookies, NOT in JSON response body
- Tests must extract tokens from cookies for authenticated requests
- Password complexity validation enforced
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


def test_register_success(client: TestClient):
    """Test successful user registration with password complexity"""
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "newuser@example.com",
            "password": "SecurePassword123!",  # Meets complexity requirements
            "full_name": "New User"
        }
    )

    assert response.status_code == 201
    data = response.json()
    # No tokens in response body - they should be in cookies
    assert "access_token" not in data
    assert "refresh_token" not in data
    assert data["email"] == "newuser@example.com"
    assert data["role"] == "user"


def test_register_password_too_short(client: TestClient):
    """Test registration fails with password shorter than 8 characters"""
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "short@example.com",
            "password": "Short1!",  # Only 7 characters
            "full_name": "Short Password"
        }
    )

    assert response.status_code == 422  # Validation error


def test_register_password_no_uppercase(client: TestClient):
    """Test registration fails with password lacking uppercase letter"""
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "noupper@example.com",
            "password": "lowercase123!",  # No uppercase
            "full_name": "No Uppercase"
        }
    )

    assert response.status_code == 422


def test_register_password_no_lowercase(client: TestClient):
    """Test registration fails with password lacking lowercase letter"""
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "nolower@example.com",
            "password": "UPPERCASE123!",  # No lowercase
            "full_name": "No Lowercase"
        }
    )

    assert response.status_code == 422


def test_register_password_no_digit(client: TestClient):
    """Test registration fails with password lacking digit"""
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "nodigit@example.com",
            "password": "NoDigitsHere!",  # No digits
            "full_name": "No Digits"
        }
    )

    assert response.status_code == 422


def test_register_password_no_special(client: TestClient):
    """Test registration fails with password lacking special character"""
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "nospecial@example.com",
            "password": "NoSpecialChars123",  # No special character
            "full_name": "No Special"
        }
    )

    assert response.status_code == 422


def test_register_duplicate_email(client: TestClient, test_user):
    """Test registration with duplicate email"""
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": test_user.email,
            "password": "SecurePassword123!",
            "full_name": "Duplicate User"
        }
    )

    assert response.status_code == 400


def test_login_success(client: TestClient, db: Session):
    """Test successful login with httpOnly cookies"""
    # First, create a user with known password
    from app.models.user import User
    from app.utils.security import get_password_hash

    password = "SecurePassword123!"
    hashed = get_password_hash(password)
    user = User(
        email="login@example.com",
        hashed_password=hashed,
        full_name="Login User",
        role="user",
        is_active=True
    )
    db.add(user)
    db.commit()

    # Login with form data (OAuth2PasswordRequestForm format)
    response = client.post(
        "/api/v1/auth/login",
        data={
            "username": "login@example.com",
            "password": password
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )

    assert response.status_code == 200
    data = response.json()

    # Tokens should NOT be in response body
    assert "access_token" not in data
    assert "refresh_token" not in data

    # User info should be returned
    assert data["message"] == "Login successful"
    assert data["user"]["email"] == "login@example.com"

    # Cookies should be set
    cookies = response.cookies
    assert "access_token" in cookies
    assert "refresh_token" in cookies


def test_login_invalid_credentials(client: TestClient):
    """Test login with invalid credentials"""
    response = client.post(
        "/api/v1/auth/login",
        data={
            "username": "nonexistent@example.com",
            "password": "anypassword"
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )

    assert response.status_code == 401
    assert "Incorrect email or password" in response.json()["detail"]


def test_login_wrong_password(client: TestClient, test_user):
    """Test login with correct email but wrong password"""
    response = client.post(
        "/api/v1/auth/login",
        data={
            "username": test_user.email,
            "password": "wrongpassword"
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )

    assert response.status_code == 401


def test_get_current_user_with_cookie(client: TestClient, db: Session):
    """Test getting current user info using cookie authentication"""
    # Create user and login
    from app.models.user import User
    from app.utils.security import get_password_hash

    password = "SecurePassword123!"
    hashed = get_password_hash(password)
    user = User(
        email="cookieuser@example.com",
        hashed_password=hashed,
        full_name="Cookie User",
        role="user",
        is_active=True
    )
    db.add(user)
    db.commit()

    # Login to get cookies
    login_response = client.post(
        "/api/v1/auth/login",
        data={
            "username": "cookieuser@example.com",
            "password": password
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )

    # Extract cookies from login response
    access_token = login_response.cookies.get("access_token")

    # Make authenticated request using cookie
    # Note: TestClient automatically includes cookies from previous responses
    me_response = client.get("/api/v1/auth/me")

    assert me_response.status_code == 200
    data = me_response.json()
    assert data["email"] == "cookieuser@example.com"


def test_get_current_user_unauthorized(client: TestClient):
    """Test getting current user without authentication"""
    response = client.get("/api/v1/auth/me")

    assert response.status_code == 401


def test_logout(client: TestClient, db: Session):
    """Test logout clears cookies"""
    # Create and login user
    from app.models.user import User
    from app.utils.security import get_password_hash

    password = "SecurePassword123!"
    hashed = get_password_hash(password)
    user = User(
        email="logoutuser@example.com",
        hashed_password=hashed,
        full_name="Logout User",
        role="user",
        is_active=True
    )
    db.add(user)
    db.commit()

    # Login
    login_response = client.post(
        "/api/v1/auth/login",
        data={
            "username": "logoutuser@example.com",
            "password": password
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    assert login_response.status_code == 200

    # Logout
    logout_response = client.post("/api/v1/auth/logout")
    assert logout_response.status_code == 200
    assert logout_response.json()["message"] == "Logout successful"

    # Should no longer be able to access protected endpoint
    me_response = client.get("/api/v1/auth/me")
    assert me_response.status_code == 401


def test_cookie_attributes(client: TestClient, db: Session):
    """Test that cookies have correct security attributes"""
    from app.models.user import User
    from app.utils.security import get_password_hash

    password = "SecurePassword123!"
    hashed = get_password_hash(password)
    user = User(
        email="cookieattr@example.com",
        hashed_password=hashed,
        full_name="Cookie Attr",
        role="user",
        is_active=True
    )
    db.add(user)
    db.commit()

    response = client.post(
        "/api/v1/auth/login",
        data={
            "username": "cookieattr@example.com",
            "password": password
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )

    # Check cookie attributes (via Set-Cookie headers)
    set_cookie_headers = response.headers.get_list("set-cookie")

    # Access token cookie should be httponly, samesite=lax
    access_cookie = [c for c in set_cookie_headers if "access_token=" in c]
    assert len(access_cookie) > 0
    assert "httponly" in access_cookie[0].lower()
    assert "samesite=lax" in access_cookie[0].lower()

    # Refresh token cookie should be httponly, samesite=lax, path=/api/v1/auth
    refresh_cookie = [c for c in set_cookie_headers if "refresh_token=" in c]
    assert len(refresh_cookie) > 0
    assert "httponly" in refresh_cookie[0].lower()
    assert "samesite=lax" in refresh_cookie[0].lower()
    assert "path=/api/v1/auth" in refresh_cookie[0].lower()


def test_refresh_token_with_cookie(client: TestClient, db: Session):
    """Test token refresh using cookie"""
    from app.models.user import User
    from app.utils.security import get_password_hash, create_refresh_token

    password = "SecurePassword123!"
    hashed = get_password_hash(password)
    user = User(
        email="refreshuser@example.com",
        hashed_password=hashed,
        full_name="Refresh User",
        role="user",
        is_active=True
    )
    db.add(user)
    db.commit()

    # Login to get cookies
    login_response = client.post(
        "/api/v1/auth/login",
        data={
            "username": "refreshuser@example.com",
            "password": password
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )

    # Get the original refresh token
    original_refresh = login_response.cookies.get("refresh_token")

    # Call refresh endpoint (TestClient includes cookies automatically)
    refresh_response = client.post("/api/v1/auth/refresh")

    assert refresh_response.status_code == 200
    data = refresh_response.json()
    assert data["message"] == "Token refreshed"

    # New cookies should be set
    new_access = refresh_response.cookies.get("access_token")
    new_refresh = refresh_response.cookies.get("refresh_token")

    assert new_access is not None
    assert new_refresh is not None

    # New refresh token should be different (token rotation)
    assert new_refresh != original_refresh


def test_refresh_token_without_cookie(client: TestClient):
    """Test refresh fails when no cookie is present"""
    # Clear any existing cookies by creating a new client
    from fastapi.testclient import TestClient
    from app.main import app
    new_client = TestClient(app)

    response = new_client.post("/api/v1/auth/refresh")
    assert response.status_code == 401
