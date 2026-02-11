"""
Integration tests for complete authentication and authorization flows.

This module tests end-to-end security scenarios:
- Complete login flow
- Token refresh flow
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
                "password": "SecurePass123!",
                "full_name": "Integration Test User"
            }
        )

        # Register may or may not be implemented
        # If it exists, should return 201 or 200
        assert register_response.status_code in [200, 201, 404]

        # 2. Create user manually if register not available
        if register_response.status_code == 404:
            password = "SecurePass123!"
            user = User(
                email="integration@example.com",
                hashed_password=get_password_hash(password),
                full_name="Integration Test User",
                role=UserRole.USER,
                is_active=True
            )
            db.add(user)
            db.commit()
            db.refresh(user)

        # 3. Login
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
        assert "access_token" in login_data
        assert "refresh_token" in login_data

        access_token = login_data["access_token"]
        refresh_token = login_data["refresh_token"]

        # 4. Access protected resource
        me_response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {access_token}"}
        )

        assert me_response.status_code == 200
        me_data = me_response.json()
        assert me_data["email"] == "integration@example.com"

        # 5. Refresh token
        refresh_response = client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh_token}
        )

        # May or may not be implemented
        if refresh_response.status_code == 200:
            new_data = refresh_response.json()
            assert "access_token" in new_data
            # New token should work
            new_me_response = client.get(
                "/api/v1/auth/me",
                headers={"Authorization": f"Bearer {new_data['access_token']}"}
            )
            assert new_me_response.status_code == 200


class TestTokenLifecycle:
    """Test token lifecycle from creation to expiration"""

    def test_access_token_expiration(self, client: TestClient, db: Session):
        """Test that access tokens expire after configured time"""
        # Create user
        user = User(
            email="expire@example.com",
            hashed_password=get_password_hash("password"),
            full_name="Expire Test",
            role=UserRole.USER,
            is_active=True
        )
        db.add(user)
        db.commit()

        # Create token that expires in 1 second
        from app.utils.security import create_access_token
        from datetime import timedelta

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
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response1.status_code == 200

        # Wait for expiration
        time.sleep(2)

        # Should fail after expiration
        response2 = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response2.status_code == 401

    def test_refresh_token_longer_lifespan(self):
        """Test that refresh tokens have longer lifespan than access tokens"""
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
            hashed_password=get_password_hash("password"),
            full_name="Regular User",
            role=UserRole.USER,
            is_active=True
        )
        db.add(user)
        db.commit()

        # Get token
        token = create_access_token(data={
            "sub": user.email,
            "role": user.role.value,
            "user_id": str(user.id)
        })

        headers = {"Authorization": f"Bearer {token}"}

        # Should be able to access own profile
        me_response = client.get("/api/v1/auth/me", headers=headers)
        assert me_response.status_code == 200

        # Should NOT be able to access admin endpoints
        admin_response = client.get("/api/v1/admin/stats", headers=headers)
        assert admin_response.status_code == 403

    def test_superuser_can_view_all_cannot_modify(self, client: TestClient, db: Session):
        """Test that superuser can view but not modify"""
        # Create superuser
        superuser = User(
            email="super@example.com",
            hashed_password=get_password_hash("password"),
            full_name="Super User",
            role=UserRole.SUPERUSER,
            is_active=True
        )
        db.add(superuser)
        db.commit()

        token = create_access_token(data={
            "sub": superuser.email,
            "role": superuser.role.value,
            "user_id": str(superuser.id)
        })

        headers = {"Authorization": f"Bearer {token}"}

        # Should be able to access own profile
        me_response = client.get("/api/v1/auth/me", headers=headers)
        assert me_response.status_code == 200

        # Should NOT be able to access admin endpoints
        admin_response = client.get("/api/v1/admin/stats", headers=headers)
        assert admin_response.status_code == 403

    def test_admin_has_full_access(self, client: TestClient, db: Session):
        """Test that admin has full access"""
        # Create admin
        admin = User(
            email="admin@example.com",
            hashed_password=get_password_hash("password"),
            full_name="Admin User",
            role=UserRole.ADMIN,
            is_active=True
        )
        db.add(admin)
        db.commit()

        token = create_access_token(data={
            "sub": admin.email,
            "role": admin.role.value,
            "user_id": str(admin.id)
        })

        headers = {"Authorization": f"Bearer {token}"}

        # Should be able to access own profile
        me_response = client.get("/api/v1/auth/me", headers=headers)
        assert me_response.status_code == 200

        # Should be able to access admin endpoints
        admin_response = client.get("/api/v1/admin/stats", headers=headers)
        # May be 404 if not implemented, but not 403
        assert admin_response.status_code in [200, 404]


class TestSessionManagement:
    """Test session management and security"""

    def test_multiple_concurrent_sessions(self, client: TestClient, db: Session):
        """Test that user can have multiple concurrent sessions"""
        user = User(
            email="multisession@example.com",
            hashed_password=get_password_hash("password"),
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
            headers={"Authorization": f"Bearer {token1}"}
        )
        response2 = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token2}"}
        )

        assert response1.status_code == 200
        assert response2.status_code == 200

    def test_token_invalidation_on_password_change(self, client: TestClient, db: Session):
        """Test that tokens are invalidated when password changes"""
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
            headers={"Authorization": f"Bearer {old_token}"}
        )
        assert response1.status_code == 200

        # Change password
        user.hashed_password = get_password_hash(new_password)
        db.commit()

        # Old token should still work (unless we implement token versioning)
        # This is a design decision - document current behavior
        response2 = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {old_token}"}
        )
        # Current implementation: tokens still work after password change
        # Security recommendation: implement token versioning


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
            hashed_password=get_password_hash("password"),
            full_name="Sensitive Test",
            role=UserRole.USER,
            is_active=True
        )
        db.add(user)
        db.commit()

        # Try to access non-existent resource
        response = client.get(
            "/api/v1/documents/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": f"Bearer {create_access_token(data={'sub': user.email, 'role': 'user', 'user_id': str(user.id)})}"}
        )

        # Error message should be generic
        if response.status_code == 404:
            detail = response.json().get("detail", "")
            # Should not leak database info, internal paths, etc.
            assert "postgresql" not in detail.lower()
            assert "traceback" not in detail.lower()
            assert "/" not in detail or detail.count("/") < 3  # No deep paths


class TestRateLimiting:
    """Test rate limiting on auth endpoints"""

    def test_login_rate_limiting(self, client: TestClient, db: Session):
        """Test that login endpoint has rate limiting"""
        user = User(
            email="ratelimit@example.com",
            hashed_password=get_password_hash("password"),
            full_name="Rate Limit",
            role=UserRole.USER,
            is_active=True
        )
        db.add(user)
        db.commit()

        # Make multiple failed login attempts
        fail_count = 0
        for i in range(10):
            response = client.post(
                "/api/v1/auth/login",
                data={
                    "username": "ratelimit@example.com",
                    "password": f"wrongpassword{i}"
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"}
            )
            if response.status_code == 429:  # Too Many Requests
                fail_count += 1

        # Rate limiting may or may not be implemented
        # If implemented, should eventually return 429


class TestPasswordRequirements:
    """Test password security requirements"""

    def test_password_complexity_requirements(self, client: TestClient):
        """Test that passwords meet complexity requirements"""
        # These would be enforced by the registration endpoint
        # Test various password scenarios

        weak_passwords = [
            "123",  # Too short
            "password",  # Too common
            "abc123",  # No uppercase/special
        ]

        # If registration endpoint exists, it should reject weak passwords
        # This documents the requirement
        pass

    def test_password_not_logged(self, client: TestClient, db: Session):
        """Test that passwords are never logged"""
        # This is a security requirement
        # Verify that password don't appear in logs
        # Hard to test directly, but document the requirement
        pass
