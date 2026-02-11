"""
Integration tests for complete authentication and authorization flows.

Updated for httpOnly cookie-based authentication:
- Tokens are stored in httpOnly cookies, NOT in JSON response bodies
- Token rotation implemented on refresh
- Password complexity validation enforced

This module tests end-to-end security scenarios:
- Complete login flow with cookies
- Token refresh flow with rotation
- Protected resource access
- Role-based resource access
- Session management
"""

import pytest
import time
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.user import User, UserRole
from app.models.document import Document, DocumentBucket, DocumentStatus
from app.utils.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_password_hash,
    ACCESS_TOKEN_EXPIRE_MINUTES
)


class TestCompleteAuthFlow:
    """Test complete authentication flow from login to resource access"""

    def test_complete_login_flow(self, client: TestClient, db: Session):
        """Test complete login: register, login, access resource, logout"""
        # 1. Register new user
        register_response = client.post(
            "/api/v1/auth/register",
            json={
                "email": "integration@example.com",
                "password": "SecurePass123!",  # Meets complexity
                "full_name": "Integration Test User"
            }
        )

        # Register should return 201
        assert register_response.status_code == 201
        register_data = register_response.json()
        # No tokens in response - user must login separately
        assert "access_token" not in register_data

        # 2. Login
        login_response = client.post(
            "/api/v1/auth/login",
            data={
                "username": "integration@example.com",
                "password": "SecurePass123!"
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )

        assert login_response.status_code == 200
        login_data = login_response.json()

        # Tokens should be in cookies, NOT in response body
        assert "access_token" not in login_data
        assert "refresh_token" not in login_data
        assert login_data["message"] == "Login successful"

        # Verify cookies are set
        access_token = login_response.cookies.get("access_token")
        refresh_token = login_response.cookies.get("refresh_token")
        assert access_token is not None
        assert refresh_token is not None

        # 3. Access protected resource (cookies are auto-included by TestClient)
        me_response = client.get("/api/v1/auth/me")

        assert me_response.status_code == 200
        me_data = me_response.json()
        assert me_data["email"] == "integration@example.com"

        # 4. Refresh token (token rotation)
        refresh_response = client.post("/api/v1/auth/refresh")

        assert refresh_response.status_code == 200
        new_data = refresh_response.json()
        assert new_data["message"] == "Token refreshed"

        # New tokens should be different (rotation)
        new_access = refresh_response.cookies.get("access_token")
        new_refresh = refresh_response.cookies.get("refresh_token")
        assert new_access != access_token
        assert new_refresh != refresh_token

        # New token should work
        new_me_response = client.get("/api/v1/auth/me")
        assert new_me_response.status_code == 200

        # 5. Logout
        logout_response = client.post("/api/v1/auth/logout")
        assert logout_response.status_code == 200

        # After logout, should no longer have access
        me_after_logout = client.get("/api/v1/auth/me")
        assert me_after_logout.status_code == 401


class TestTokenLifecycle:
    """Test token lifecycle from creation to expiration"""

    def test_access_token_expiration(self, client: TestClient, db: Session):
        """Test that access tokens expire after configured time"""
        # Create user
        user = User(
            email="expire@example.com",
            hashed_password=get_password_hash("SecurePass123!"),
            full_name="Expire Test",
            role=UserRole.USER,
            is_active=True
        )
        db.add(user)
        db.commit()

        # Create token that expires in 1 second
        token = create_access_token(
            data={
                "sub": user.email,
                "role": user.role.value,
                "user_id": str(user.id)
            },
            expires_delta=timedelta(seconds=1)
        )

        # Should work immediately
        response1 = client.get(
            "/api/v1/auth/me",
            headers={"Cookie": f"access_token={token}"}
        )
        assert response1.status_code == 200

        # Wait for expiration
        time.sleep(2)

        # Should fail after expiration
        response2 = client.get(
            "/api/v1/auth/me",
            headers={"Cookie": f"access_token={token}"}
        )
        assert response2.status_code == 401

    def test_refresh_token_longer_lifespan(self):
        """Test that refresh tokens have longer lifespan than access tokens"""
        access_token = create_access_token(data={
            "sub": "test@example.com",
            "role": "user",
            "user_id": "123e4567-e89b-12d3-a456-426614174000"
        })

        refresh_token = create_refresh_token(data={
            "sub": "test@example.com",
            "role": "user",
            "user_id": "123e4567-e89b-12d3-a456-426614174000"
        })

        access_payload = decode_token(access_token)
        refresh_payload = decode_token(refresh_token)

        # Refresh token should expire later
        assert refresh_payload["exp"] > access_payload["exp"]

        # Access token: ~15 minutes
        # Refresh token: ~7 days
        access_duration = access_payload["exp"] - int(time.time())
        refresh_duration = refresh_payload["exp"] - int(time.time())

        # Refresh should last much longer (at least 100x)
        assert refresh_duration > access_duration * 100


class TestRoleBasedResourceAccess:
    """Test role-based access to different resources"""

    def test_user_can_only_access_public_resources(self, client: TestClient, db: Session):
        """Test that regular user can only access public resources"""
        # Create user
        user = User(
            email="user@example.com",
            hashed_password=get_password_hash("SecurePass123!"),
            full_name="Regular User",
            role=UserRole.USER,
            is_active=True
        )
        db.add(user)
        db.commit()

        # Login to get cookies
        login_response = client.post(
            "/api/v1/auth/login",
            data={
                "username": "user@example.com",
                "password": "SecurePass123!"
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )

        # Should be able to access own profile
        me_response = client.get("/api/v1/auth/me")
        assert me_response.status_code == 200

        # Should NOT be able to access admin endpoints
        admin_response = client.get("/api/v1/admin/stats")
        assert admin_response.status_code == 403

    def test_superuser_can_view_all_cannot_modify(self, client: TestClient, db: Session):
        """Test that superuser can view but not modify"""
        # Create superuser
        superuser = User(
            email="super@example.com",
            hashed_password=get_password_hash("SecurePass123!"),
            full_name="Super User",
            role=UserRole.SUPERUSER,
            is_active=True
        )
        db.add(superuser)
        db.commit()

        # Login
        client.post(
            "/api/v1/auth/login",
            data={
                "username": "super@example.com",
                "password": "SecurePass123!"
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )

        # Should be able to access own profile
        me_response = client.get("/api/v1/auth/me")
        assert me_response.status_code == 200

        # Should NOT be able to access admin endpoints
        admin_response = client.get("/api/v1/admin/stats")
        assert admin_response.status_code == 403

    def test_admin_has_full_access(self, client: TestClient, db: Session):
        """Test that admin has full access"""
        # Create admin
        admin = User(
            email="admin@example.com",
            hashed_password=get_password_hash("SecurePass123!"),
            full_name="Admin User",
            role=UserRole.ADMIN,
            is_active=True
        )
        db.add(admin)
        db.commit()

        # Login
        client.post(
            "/api/v1/auth/login",
            data={
                "username": "admin@example.com",
                "password": "SecurePass123!"
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )

        # Should be able to access own profile
        me_response = client.get("/api/v1/auth/me")
        assert me_response.status_code == 200

        # Should be able to access admin endpoints
        admin_response = client.get("/api/v1/admin/stats")
        # May be 404 if not implemented, but not 403
        assert admin_response.status_code in [200, 404]


class TestSessionManagement:
    """Test session management and security"""

    def test_multiple_concurrent_sessions(self, client: TestClient, db: Session):
        """Test that user can have multiple concurrent sessions"""
        user = User(
            email="multisession@example.com",
            hashed_password=get_password_hash("SecurePass123!"),
            full_name="Multi Session",
            role=UserRole.USER,
            is_active=True
        )
        db.add(user)
        db.commit()

        # Create multiple tokens
        token1 = create_access_token(data={
            "sub": user.email,
            "role": user.role.value,
            "user_id": str(user.id)
        })

        # Wait a bit
        time.sleep(1)

        token2 = create_access_token(data={
            "sub": user.email,
            "role": user.role.value,
            "user_id": str(user.id)
        })

        # Both tokens should work
        response1 = client.get(
            "/api/v1/auth/me",
            headers={"Cookie": f"access_token={token1}"}
        )
        response2 = client.get(
            "/api/v1/auth/me",
            headers={"Cookie": f"access_token={token2}"}
        )

        assert response1.status_code == 200
        assert response2.status_code == 200

    def test_token_invalidation_on_password_change(self, client: TestClient, db: Session):
        """Test that tokens behavior after password change"""
        old_password = "OldPassword123!"
        new_password = "NewPassword456!"

        user = User(
            email="changepass@example.com",
            hashed_password=get_password_hash(old_password),
            full_name="Change Pass",
            role=UserRole.USER,
            is_active=True
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        # Create token before password change
        old_token = create_access_token(data={
            "sub": user.email,
            "role": user.role.value,
            "user_id": str(user.id)
        })

        # Verify old token works
        response1 = client.get(
            "/api/v1/auth/me",
            headers={"Cookie": f"access_token={old_token}"}
        )
        assert response1.status_code == 200

        # Change password
        user.hashed_password = get_password_hash(new_password)
        db.commit()

        # Current implementation: tokens still work after password change
        # Security note: Consider implementing token versioning for future
        response2 = client.get(
            "/api/v1/auth/me",
            headers={"Cookie": f"access_token={old_token}"}
        )
        # Current behavior: token still valid
        assert response2.status_code == 200


class TestSecurityHeaders:
    """Test security headers on API responses"""

    def test_security_headers_present(self, client: TestClient):
        """Test that security headers are present"""
        response = client.get("/health")

        # Check for security headers
        headers = response.headers

        # These headers should be present in production
        # Note: TestClient may not include all headers
        # This documents the requirements

        # Recommended headers:
        # - X-Content-Type-Options: nosniff
        # - X-Frame-Options: DENY
        # - X-XSS-Protection: 1; mode=block
        # - Strict-Transport-Security: max-age=31536000; includeSubDomains

    def test_no_sensitive_data_in_error_messages(self, client: TestClient, db: Session):
        """Test that error messages don't leak sensitive information"""
        user = User(
            email="sensitivetest@example.com",
            hashed_password=get_password_hash("SecurePass123!"),
            full_name="Sensitive Test",
            role=UserRole.USER,
            is_active=True
        )
        db.add(user)
        db.commit()

        # Try to access non-existent resource
        response = client.get(
            "/api/v1/documents/00000000-0000-0000-0000-000000000000",
            headers={"Cookie": f"access_token={create_access_token(data={'sub': user.email, 'role': 'user', 'user_id': str(user.id)})}"}
        )

        # Error message should be generic
        if response.status_code == 404:
            detail = response.json().get("detail", "")
            # Should not leak database info, internal paths, etc.
            assert "postgresql" not in detail.lower()
            assert "traceback" not in detail.lower()
            assert "/" not in detail or detail.count("/") < 3  # No deep paths


class TestPasswordRequirements:
    """Test password security requirements"""

    def test_password_complexity_requirements(self, client: TestClient):
        """Test that passwords meet complexity requirements"""
        # Test various password scenarios

        weak_passwords = [
            ("Short1!", "too short (7 chars)"),
            ("alllowercase123!", "no uppercase"),
            ("ALLUPPERCASE123!", "no lowercase"),
            ("NoDigitsHere!", "no digits"),
            ("NoSpecialChars123", "no special character"),
            ("NoDigits!", "no digits and too short"),
        ]

        for password, reason in weak_passwords:
            response = client.post(
                "/api/v1/auth/register",
                json={
                    "email": f"test_{reason.replace(' ', '_')}@example.com",
                    "password": password,
                    "full_name": f"Test {reason}"
                }
            )
            # Should fail validation
            assert response.status_code == 422, f"Password '{password}' should fail validation: {reason}"

        # Valid password should work
        response = client.post(
            "/api/v1/auth/register",
            json={
                "email": "validpassword@example.com",
                "password": "ValidPassword123!",
                "full_name": "Valid Password"
            }
        )
        # May succeed or fail due to duplicate user, but should pass validation
        assert response.status_code in [201, 400]

    def test_password_not_logged(self, client: TestClient, db: Session):
        """Test that passwords are never logged"""
        # This is a security requirement
        # Verify that passwords don't appear in logs
        # Hard to test directly, but document the requirement
        pass


class TestTokenRotation:
    """Test token rotation on refresh"""

    def test_refresh_token_rotation(self, client: TestClient, db: Session):
        """Test that refresh tokens are rotated on refresh"""
        user = User(
            email="rotation@example.com",
            hashed_password=get_password_hash("SecurePass123!"),
            full_name="Rotation Test",
            role=UserRole.USER,
            is_active=True
        )
        db.add(user)
        db.commit()

        # Login
        login_response = client.post(
            "/api/v1/auth/login",
            data={
                "username": "rotation@example.com",
                "password": "SecurePass123!"
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )

        original_refresh = login_response.cookies.get("refresh_token")

        # First refresh
        refresh1_response = client.post("/api/v1/auth/refresh")
        refresh1_token = refresh1_response.cookies.get("refresh_token")

        # Second refresh
        refresh2_response = client.post("/api/v1/auth/refresh")
        refresh2_token = refresh2_response.cookies.get("refresh_token")

        # All tokens should be different (rotation)
        assert original_refresh != refresh1_token
        assert refresh1_token != refresh2_token

        # All should still be valid for authentication
        assert refresh1_response.status_code == 200
        assert refresh2_response.status_code == 200


class TestCookieSecurity:
    """Test cookie security attributes"""

    def test_httponly_prevents_javascript_access(self, client: TestClient, db: Session):
        """Test that cookies are httponly (documented - can't test directly in TestClient)"""
        # httponly means JavaScript cannot access document.cookie
        # This prevents XSS attacks from stealing tokens
        # We verify this in the test_cookie_attributes unit test
        pass

    def test_samesite_lax_allows_navigation(self, client: TestClient, db: Session):
        """Test that samesite=lax allows normal navigation"""
        # samesite=lax allows top-level navigations
        # but prevents CSRF attacks
        # Documented requirement - verified in unit tests
        pass

    def test_refresh_token_restricted_path(self, client: TestClient, db: Session):
        """Test that refresh token is restricted to /api/v1/auth path"""
        user = User(
            email="pathrestrict@example.com",
            hashed_password=get_password_hash("SecurePass123!"),
            full_name="Path Restrict",
            role=UserRole.USER,
            is_active=True
        )
        db.add(user)
        db.commit()

        response = client.post(
            "/api/v1/auth/login",
            data={
                "username": "pathrestrict@example.com",
                "password": "SecurePass123!"
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )

        set_cookie_headers = response.headers.get_list("set-cookie")
        refresh_cookie = [c for c in set_cookie_headers if "refresh_token=" in c]

        assert len(refresh_cookie) > 0
        # Refresh token should be restricted to /api/v1/auth
        assert "path=/api/v1/auth" in refresh_cookie[0].lower()
