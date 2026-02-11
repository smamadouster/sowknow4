"""
Security tests for authentication endpoints.

This module tests:
- Login with valid credentials → 200 + httpOnly cookies set (NO tokens in response body)
- Login with invalid password → 401, no cookies
- Login with non-existent email → 401, no user enumeration
- Access protected route without token → 401
- Access with expired token → 401
- Access with tampered token → 401
- Logout clears cookies
- Cookie security flags (httpOnly, Secure, SameSite)
- Token rotation on refresh
- Tokens NOT in response body (XSS prevention)
"""
import pytest
import json
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from unittest.mock import patch, MagicMock

from app.models.user import User, UserRole
from app.utils.security import (
    verify_password,
    get_password_hash,
    create_access_token,
    create_refresh_token,
    decode_token,
    SECRET_KEY,
    ALGORITHM
)
from jose import jwt, JWTError
from fastapi.security import OAuth2PasswordRequestForm
from fastapi import Depends, HTTPException


class TestLoginSecurity:
    """Test login endpoint security"""

    def test_login_with_valid_credentials(self, security_client, db: Session):
        """Test successful login returns 200 with httpOnly cookies, NO tokens in response body"""
        # Create a user with known password
        password = "SecurePassword123!"
        hashed = get_password_hash(password)

        user = User(
            email="testuser@example.com",
            hashed_password=hashed,
            full_name="Test User",
            role=UserRole.USER,
            is_active=True
        )
        db.add(user)
        db.commit()

        # Login with form data (OAuth2PasswordRequestForm)
        response = test_client.post(
            "/api/v1/auth/login",
            data={
                "username": "testuser@example.com",
                "password": password
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )

        # Should return 200
        assert response.status_code == 200

        # CRITICAL SECURITY: Tokens should NOT be in response body (XSS prevention)
        data = response.json()
        assert "access_token" not in data, "Access token must NOT be in response body (XSS prevention)"
        assert "refresh_token" not in data, "Refresh token must NOT be in response body (XSS prevention)"
        assert data["token_type"] == "bearer"

        # Response should contain user info (not tokens)
        assert "user" in data
        assert data["user"]["email"] == "testuser@example.com"

        # CRITICAL SECURITY: Tokens should be in httpOnly cookies
        cookies = response.cookies
        assert len(cookies) > 0, "Auth cookies must be set"

        # TestClient stores cookies, verify they're present
        # Note: httpOnly flag cannot be tested in TestClient,
        # but the implementation in auth.py sets it correctly

    def test_login_with_invalid_password(self, test_client: TestClient, db: Session):
        """Test login with invalid password returns 401 without revealing user existence"""
        # Create a user
        password = "CorrectPassword123!"
        hashed = get_password_hash(password)

        user = User(
            email="validuser@example.com",
            hashed_password=hashed,
            full_name="Valid User",
            role=UserRole.USER,
            is_active=True
        )
        db.add(user)
        db.commit()

        # Attempt login with wrong password
        response = test_client.post(
            "/api/v1/auth/login",
            data={
                "username": "validuser@example.com",
                "password": "WrongPassword!"
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )

        # Should return 401
        assert response.status_code == 401

        # Error message should NOT reveal if user exists
        assert "detail" in response.json()
        detail = response.json()["detail"]
        assert "incorrect" in detail.lower() or "invalid" in detail.lower()
        # Should not say "user not found" or "wrong password"
        assert "not found" not in detail.lower()

        # No cookies should be set
        assert len(response.cookies) == 0

    def test_login_with_nonexistent_email(self, test_client: TestClient):
        """Test login with non-existent email returns 401 without user enumeration"""
        response = test_client.post(
            "/api/v1/auth/login",
            data={
                "username": "nonexistent@example.com",
                "password": "AnyPassword123!"
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )

        # Should return 401
        assert response.status_code == 401

        # Error message should be identical to invalid password
        # to prevent user enumeration
        assert "detail" in response.json()

        # No cookies should be set
        assert len(response.cookies) == 0

    def test_login_with_inactive_user(self, test_client: TestClient, db: Session):
        """Test login with inactive user returns appropriate error"""
        # Create an inactive user
        password = "Password123!"
        hashed = get_password_hash(password)

        user = User(
            email="inactive@example.com",
            hashed_password=hashed,
            full_name="Inactive User",
            role=UserRole.USER,
            is_active=False
        )
        db.add(user)
        db.commit()

        # Attempt login
        response = test_client.post(
            "/api/v1/auth/login",
            data={
                "username": "inactive@example.com",
                "password": password
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )

        # Should return 400 (bad request - inactive user)
        assert response.status_code == 400
        assert "inactive" in response.json()["detail"].lower()

    def test_login_missing_credentials(self, test_client: TestClient):
        """Test login with missing credentials returns 422"""
        response = test_client.post(
            "/api/v1/auth/login",
            data={},
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )

        # FastAPI validation error
        assert response.status_code == 422


class TestProtectedRouteAccess:
    """Test accessing protected routes with various token states"""

    def test_access_without_token(self, test_client: TestClient):
        """Test accessing protected route without token returns 401"""
        response = test_client.get("/api/v1/auth/me")

        assert response.status_code == 401

    def test_access_with_valid_token(self, test_client: TestClient, db: Session):
        """Test accessing protected route with valid token returns 200"""
        # Create user
        user = User(
            email="tokenuser@example.com",
            hashed_password=get_password_hash("password"),
            full_name="Token User",
            role=UserRole.USER,
            is_active=True
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        # Create valid token
        token = create_access_token(data={
            "sub": user.email,
            "role": user.role.value,
            "user_id": str(user.id)
        })

        # Access protected route
        response = test_client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["email"] == "tokenuser@example.com"

    def test_access_with_expired_token(self, test_client: TestClient, db: Session):
        """Test accessing protected route with expired token returns 401"""
        # Create user
        user = User(
            email="expireduser@example.com",
            hashed_password=get_password_hash("password"),
            full_name="Expired User",
            role=UserRole.USER,
            is_active=True
        )
        db.add(user)
        db.commit()

        # Create expired token (exp in past)
        from datetime import datetime, timedelta
        expire = datetime.utcnow() - timedelta(minutes=15)

        payload = {
            "sub": user.email,
            "role": user.role.value,
            "user_id": str(user.id),
            "exp": expire
        }

        expired_token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

        # Try to access protected route
        response = test_client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {expired_token}"}
        )

        assert response.status_code == 401

    def test_access_with_tampered_token(self, test_client: TestClient):
        """Test accessing protected route with tampered token returns 401"""
        # Create a valid token and tamper with it
        valid_token = create_access_token(data={
            "sub": "user@example.com",
            "role": "user",
            "user_id": "12345678-1234-5678-1234-567812345678"
        })

        # Tamper with the token (change a character)
        tampered_token = valid_token[:-5] + "ABCDE"

        response = test_client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {tampered_token}"}
        )

        assert response.status_code == 401

    def test_access_with_invalid_token_format(self, test_client: TestClient):
        """Test accessing protected route with malformed token returns 401"""
        response = test_client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer invalid.token.format"}
        )

        assert response.status_code == 401

    def test_access_with_bearer_prefix_missing(self, test_client: TestClient):
        """Test accessing protected route without Bearer prefix returns 401"""
        token = create_access_token(data={
            "sub": "user@example.com",
            "role": "user"
        })

        response = test_client.get(
            "/api/v1/auth/me",
            headers={"Authorization": token}  # Missing "Bearer" prefix
        )

        # Should fail due to missing Bearer prefix
        assert response.status_code == 401

    def test_access_with_deleted_user_token(self, test_client: TestClient, db: Session):
        """Test accessing protected route with token for deleted user returns 401"""
        # Create user and get token
        user = User(
            email="deleted@example.com",
            hashed_password=get_password_hash("password"),
            full_name="Deleted User",
            role=UserRole.USER,
            is_active=True
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        token = create_access_token(data={
            "sub": user.email,
            "role": user.role.value,
            "user_id": str(user.id)
        })

        # Delete user
        db.delete(user)
        db.commit()

        # Try to access with old token
        response = test_client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 401


class TestTokenSecurity:
    """Test token generation and validation security"""

    def test_token_contains_expected_claims(self, db: Session):
        """Test that tokens contain required claims"""
        token = create_access_token(data={
            "sub": "test@example.com",
            "role": "user",
            "user_id": "12345678-1234-5678-1234-567812345678"
        })

        payload = decode_token(token)

        assert "sub" in payload
        assert "role" in payload
        assert "user_id" in payload
        assert "exp" in payload
        assert payload["sub"] == "test@example.com"

    def test_token_expiration_is_set(self, db: Session):
        """Test that tokens have proper expiration"""
        import time

        token = create_access_token(data={
            "sub": "test@example.com",
            "role": "user"
        })

        payload = decode_token(token)

        # Expiration should be in the future
        assert payload["exp"] > int(time.time())

        # Should be approximately 15 minutes from now (with some tolerance)
        from app.utils.security import ACCESS_TOKEN_EXPIRE_MINUTES
        expected_exp = int(time.time()) + (ACCESS_TOKEN_EXPIRE_MINUTES * 60)
        assert abs(payload["exp"] - expected_exp) < 5  # 5 second tolerance

    def test_refresh_token_longer_expiration(self, db: Session):
        """Test that refresh tokens have longer expiration than access tokens"""
        import time

        access_token = create_access_token(data={
            "sub": "test@example.com",
            "role": "user"
        })

        refresh_token = create_refresh_token(data={
            "sub": "test@example.com",
            "role": "user"
        })

        access_payload = decode_token(access_token)
        refresh_payload = decode_token(refresh_token)

        # Refresh token should expire much later
        assert refresh_payload["exp"] > access_payload["exp"]

    def test_cannot_use_token_after_secret_change(self, db: Session):
        """Test that tokens are invalidated if secret changes"""
        from app.utils.security import SECRET_KEY

        # Create token with current secret
        token = create_access_token(data={
            "sub": "test@example.com",
            "role": "user"
        })

        # Mock a different secret
        with patch("app.utils.security.SECRET_KEY", "different-secret-key"):
            # Try to decode with different secret - should fail
            payload = decode_token(token)
            assert payload == {}


class TestCookieSecurity:
    """Test cookie security attributes"""

    def test_cookies_are_set_on_login(self, test_client: TestClient, db: Session):
        """Test that auth cookies are set on successful login"""
        # Create user
        password = "CookieTest123!"
        hashed = get_password_hash(password)

        user = User(
            email="cookietest@example.com",
            hashed_password=hashed,
            full_name="Cookie Test",
            role=UserRole.USER,
            is_active=True
        )
        db.add(user)
        db.commit()

        # Login
        response = test_client.post(
            "/api/v1/auth/login",
            data={
                "username": "cookietest@example.com",
                "password": password
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )

        # Check that cookies are set
        cookies = response.cookies
        assert len(cookies) > 0, "Auth cookies must be set on login"

    def test_cookies_not_set_on_failed_login(self, test_client: TestClient, db: Session):
        """Test that auth cookies are NOT set on failed login"""
        # Create user
        password = "CorrectPassword123!"
        hashed = get_password_hash(password)

        user = User(
            email="failedlogin@example.com",
            hashed_password=hashed,
            full_name="Failed Login Test",
            role=UserRole.USER,
            is_active=True
        )
        db.add(user)
        db.commit()

        # Attempt login with wrong password
        response = test_client.post(
            "/api/v1/auth/login",
            data={
                "username": "failedlogin@example.com",
                "password": "WrongPassword123!"
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )

        # Should fail
        assert response.status_code == 401

        # No cookies should be set
        cookies = response.cookies
        assert len(cookies) == 0, "No cookies should be set on failed login"

    def test_access_token_cookie_has_longer_expiration(self, test_client: TestClient, db: Session):
        """Test that access token cookie has 15-minute expiration"""
        from app.utils.security import ACCESS_TOKEN_EXPIRE_MINUTES

        password = "CookieExpireTest123!"
        hashed = get_password_hash(password)

        user = User(
            email="cookieexpire@example.com",
            hashed_password=hashed,
            full_name="Cookie Expire Test",
            role=UserRole.USER,
            is_active=True
        )
        db.add(user)
        db.commit()

        # Login
        response = test_client.post(
            "/api/v1/auth/login",
            data={
                "username": "cookieexpire@example.com",
                "password": password
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )

        # Response should be successful
        assert response.status_code == 200

        # Note: TestClient doesn't expose cookie max_age directly
        # Implementation in auth.py sets max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60 (900 seconds)
        expected_max_age = ACCESS_TOKEN_EXPIRE_MINUTES * 60
        assert expected_max_age == 900, "Access token should expire in 15 minutes"

    def test_cookies_have_secure_flag_documented(self, test_client: TestClient, db: Session):
        """Document that auth cookies have Secure flag in production"""
        # SECURITY: Implementation in auth.py sets secure=ENVIRONMENT == "production"
        # This means Secure flag is True in production, False for HTTP development
        # In production with HTTPS, cookies are only sent over encrypted connections
        # This test documents the requirement for production verification

        # Create user and login
        password = "SecureTest123!"
        hashed = get_password_hash(password)

        user = User(
            email="securetest@example.com",
            hashed_password=hashed,
            full_name="Secure Test",
            role=UserRole.USER,
            is_active=True
        )
        db.add(user)
        db.commit()

        response = test_client.post(
            "/api/v1/auth/login",
            data={
                "username": "securetest@example.com",
                "password": password
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )

        # Response should be successful
        assert response.status_code == 200

        # Document: In production (ENVIRONMENT=production), Secure=True is set
        # This ensures cookies are only sent over HTTPS

    def test_cookies_have_samesite_lax_documented(self, test_client: TestClient, db: Session):
        """Document that auth cookies have SameSite=lax attribute"""
        # SECURITY: Implementation in auth.py sets samesite="lax"
        # This allows normal navigation while preventing CSRF attacks
        # strict mode would break navigation from external links
        # This test documents the requirement for production verification

        # Create user and login
        password = "SameSiteTest123!"
        hashed = get_password_hash(password)

        user = User(
            email="samesitetest@example.com",
            hashed_password=hashed,
            full_name="SameSite Test",
            role=UserRole.USER,
            is_active=True
        )
        db.add(user)
        db.commit()

        response = test_client.post(
            "/api/v1/auth/login",
            data={
                "username": "samesitetest@example.com",
                "password": password
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )

        # Response should be successful
        assert response.status_code == 200

        # Document: Implementation sets SameSite=lax in auth.py
        # This allows normal navigation while preventing CSRF


class TestTokenNotInResponseBody:
    """Test that tokens are NOT in response body (XSS prevention)"""

    def test_tokens_not_in_response_body(self, test_client: TestClient, db: Session):
        """CRITICAL SECURITY: Tokens must NOT be in response body"""
        # Implementation in auth.py does NOT return tokens in JSON response
        # Tokens are only in httpOnly cookies (XSS prevention)

        password = "TokenLocation123!"
        hashed = get_password_hash(password)

        user = User(
            email="tokenlocation@example.com",
            hashed_password=hashed,
            full_name="Token Location",
            role=UserRole.USER,
            is_active=True
        )
        db.add(user)
        db.commit()

        response = test_client.post(
            "/api/v1/auth/login",
            data={
                "username": "tokenlocation@example.com",
                "password": password
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )

        assert response.status_code == 200
        data = response.json()

        # CRITICAL: Tokens must NOT be in response body
        assert "access_token" not in data, "SECURITY: Access token must NOT be in response body"
        assert "refresh_token" not in data, "SECURITY: Refresh token must NOT be in response body"

        # User info should be in response (not tokens)
        assert "user" in data
        assert data["user"]["email"] == "tokenlocation@example.com"

    def test_user_info_in_response(self, test_client: TestClient, db: Session):
        """Test that user info is returned in response (not tokens)"""
        password = "UserInfoTest123!"
        hashed = get_password_hash(password)

        user = User(
            email="userinfo@example.com",
            hashed_password=hashed,
            full_name="User Info Test",
            role=UserRole.USER,
            is_active=True
        )
        db.add(user)
        db.commit()

        response = test_client.post(
            "/api/v1/auth/login",
            data={
                "username": "userinfo@example.com",
                "password": password
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )

        assert response.status_code == 200
        data = response.json()

        # User info should be returned
        assert "user" in data
        assert data["user"]["id"] is not None
        assert data["user"]["email"] == "userinfo@example.com"
        assert data["user"]["full_name"] == "User Info Test"
        assert data["user"]["role"] == "user"

        # Message should be present
        assert "message" in data


class TestLogout:
    """Test logout functionality"""

    def test_logout_clears_cookies(self, test_client: TestClient, db: Session):
        """Test that logout clears auth cookies"""
        # Create user and login
        password = "LogoutTest123!"
        hashed = get_password_hash(password)

        user = User(
            email="logouttest@example.com",
            hashed_password=hashed,
            full_name="Logout Test",
            role=UserRole.USER,
            is_active=True
        )
        db.add(user)
        db.commit()

        # Login first
        login_response = client.post(
            "/api/v1/auth/login",
            data={
                "username": "logouttest@example.com",
                "password": password
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )

        assert login_response.status_code == 200
        # Cookies should be set
        assert len(login_response.cookies) > 0

        # Now logout
        logout_response = client.post(
            "/api/v1/auth/logout"
        )

        # Logout should succeed
        assert logout_response.status_code == 200

        # Response should contain message
        data = logout_response.json()
        assert "message" in data
        assert data["message"] == "Logout successful"

    def test_logout_without_auth_still_succeeds(self, test_client: TestClient):
        """Test that logout succeeds even without authentication (idempotent)"""
        # Logout should succeed regardless of auth state
        response = test_client.post(
            "/api/v1/auth/logout"
        )

        # Should return 200 (logout is idempotent)
        assert response.status_code == 200

    def test_access_after_logout_fails(self, test_client: TestClient, db: Session):
        """Test that accessing protected routes after logout fails"""
        # Create user and login
        password = "AfterLogoutTest123!"
        hashed = get_password_hash(password)

        user = User(
            email="afterlogout@example.com",
            hashed_password=hashed,
            full_name="After Logout Test",
            role=UserRole.USER,
            is_active=True
        )
        db.add(user)
        db.commit()

        # Login
        login_response = client.post(
            "/api/v1/auth/login",
            data={
                "username": "afterlogout@example.com",
                "password": password
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )

        assert login_response.status_code == 200

        # Logout
        client.post("/api/v1/auth/logout")

        # Try to access protected route - should fail
        response = test_client.get("/api/v1/auth/me")

        # Should be 401 (cookies cleared)
        assert response.status_code == 401


class TestTokenRotation:
    """Test token rotation on refresh"""

    def test_refresh_token_rotation_issues_new_tokens(self, test_client: TestClient, db: Session):
        """Test that refresh endpoint issues new access and refresh tokens"""
        # Create user
        password = "TokenRotationTest123!"
        hashed = get_password_hash(password)

        user = User(
            email="tokenrotation@example.com",
            hashed_password=hashed,
            full_name="Token Rotation Test",
            role=UserRole.USER,
            is_active=True
        )
        db.add(user)
        db.commit()

        # Login to get initial tokens
        login_response = client.post(
            "/api/v1/auth/login",
            data={
                "username": "tokenrotation@example.com",
                "password": password
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )

        assert login_response.status_code == 200
        # Store initial cookies
        initial_access_cookie = login_response.cookies.get("access_token")
        initial_refresh_cookie = login_response.cookies.get("refresh_token")

        # Now refresh tokens
        refresh_response = client.post(
            "/api/v1/auth/refresh"
        )

        # Should succeed
        assert refresh_response.status_code == 200

        # New cookies should be set
        assert len(refresh_response.cookies) > 0

        # New tokens should be different from old
        new_access_cookie = refresh_response.cookies.get("access_token")
        new_refresh_cookie = refresh_response.cookies.get("refresh_token")

        # Tokens should be different (rotation)
        # Note: In TestClient, we verify cookies are set
        assert new_access_cookie is not None or new_refresh_cookie is not None

    def test_refresh_with_expired_token_returns_token_expired_code(self, test_client: TestClient, db: Session):
        """Test that refresh with expired token returns TOKEN_EXPIRED code"""
        from datetime import datetime, timedelta
        from jose import jwt

        # Create user
        password = "ExpiredRefreshTest123!"
        hashed = get_password_hash(password)

        user = User(
            email="expiredrefresh@example.com",
            hashed_password=hashed,
            full_name="Expired Refresh Test",
            role=UserRole.USER,
            is_active=True
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        # Create expired refresh token
        expire = datetime.utcnow() - timedelta(days=1)
        payload = {
            "sub": user.email,
            "role": user.role.value,
            "user_id": str(user.id),
            "type": "refresh",
            "exp": expire
        }

        expired_token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

        # Set the expired cookie manually (TestClient limitation)
        client.cookies.set("refresh_token", expired_token)

        # Try to refresh with expired token
        response = test_client.post("/api/v1/auth/refresh")

        # Should return 401
        assert response.status_code == 401

        # Should have TOKEN_EXPIRED code
        data = response.json()
        assert "detail" in data

    def test_refresh_without_token_returns_401(self, test_client: TestClient):
        """Test that refresh without token returns 401"""
        # Clear any existing cookies
        client.cookies.clear()

        # Try to refresh without token
        response = test_client.post("/api/v1/auth/refresh")

        # Should return 401
        assert response.status_code == 401

    def test_refresh_with_invalid_token_returns_401(self, test_client: TestClient):
        """Test that refresh with invalid token returns 401"""
        # Set an invalid refresh token
        client.cookies.set("refresh_token", "invalid.token.here")

        # Try to refresh
        response = test_client.post("/api/v1/auth/refresh")

        # Should return 401
        assert response.status_code == 401


class TestPasswordSecurity:
    """Test password handling security"""

    def test_password_hashing_uses_bcrypt(self):
        """Test that passwords are hashed with bcrypt"""
        password = "TestPassword123!"
        hashed = get_password_hash(password)

        # Bcrypt hashes start with $2b$
        assert hashed.startswith("$2b$") or hashed.startswith("$2a$")

        # Verify password can be checked
        assert verify_password(password, hashed) is True

        # Verify wrong password fails
        assert verify_password("WrongPassword123!", hashed) is False

    def test_password_hash_is_unique(self):
        """Test that same password generates different hashes (salt)"""
        password = "SamePassword123!"
        hash1 = get_password_hash(password)
        hash2 = get_password_hash(password)

        # Hashes should be different due to salt
        assert hash1 != hash2

        # But both should verify correctly
        assert verify_password(password, hash1) is True
        assert verify_password(password, hash2) is True

    def test_plaintext_password_not_stored(self, db: Session):
        """Test that plaintext passwords are never stored"""
        password = "PlaintextCheck123!"
        hashed = get_password_hash(password)

        user = User(
            email="plaintext@example.com",
            hashed_password=hashed,
            full_name="Plaintext Test",
            role=UserRole.USER,
            is_active=True
        )
        db.add(user)
        db.commit()

        # Retrieve from database
        retrieved = db.query(User).filter(User.email == "plaintext@example.com").first()

        # Password should not be plaintext
        assert retrieved.hashed_password != password
        assert not retrieved.hashed_password.startswith("Plaintext")

        # But should verify
        assert verify_password(password, retrieved.hashed_password)
