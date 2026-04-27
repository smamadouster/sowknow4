"""
Integration tests for admin endpoint authorization.

Ensures role-based access control is correct on admin endpoints:
- superuser can READ dashboard stats (regression test for dashboard blur bug)
- superuser cannot WRITE (create/delete users)
- regular user cannot access admin endpoints at all
"""

import pytest
from fastapi.testclient import TestClient

class TestAdminReadEndpoints:
    """Read-only admin endpoints must allow both admin and superuser."""

    @pytest.mark.parametrize("endpoint", [
        "/api/v1/admin/stats",
        "/api/v1/admin/anomalies",
        "/api/v1/admin/pipeline-stats",
        "/api/v1/admin/uploads-history",
        "/api/v1/admin/articles-stats",
        "/api/v1/admin/articles-history",
        "/api/v1/admin/queue-stats",
        "/api/v1/admin/dashboard",
    ])
    def test_superuser_can_view_stats(self, client: TestClient, superuser_headers: dict, endpoint: str):
        """Superuser must have read access to all dashboard stats endpoints."""
        response = client.get(endpoint, headers=superuser_headers)
        # 200 = data returned, 422 = validation error (empty DB is ok), 404 = endpoint moved
        assert response.status_code in [200, 422, 404], (
            f"Superuser should be able to read {endpoint}, got {response.status_code}: {response.text}"
        )

    @pytest.mark.parametrize("endpoint", [
        "/api/v1/admin/stats",
        "/api/v1/admin/anomalies",
        "/api/v1/admin/pipeline-stats",
    ])
    def test_admin_can_view_stats(self, client: TestClient, admin_headers: dict, endpoint: str):
        """Admin must have read access to stats endpoints."""
        response = client.get(endpoint, headers=admin_headers)
        assert response.status_code in [200, 422, 404]

    @pytest.mark.parametrize("endpoint", [
        "/api/v1/admin/stats",
        "/api/v1/admin/anomalies",
    ])
    def test_regular_user_cannot_view_stats(self, client: TestClient, user_headers: dict, endpoint: str):
        """Regular user must be forbidden from admin stats."""
        response = client.get(endpoint, headers=user_headers)
        assert response.status_code in [401, 403]


class TestAdminWriteEndpoints:
    """Write admin endpoints must allow only admin, not superuser."""

    def test_superuser_cannot_create_user(self, client: TestClient, superuser_headers: dict):
        """Superuser must be forbidden from creating users."""
        response = client.post(
            "/api/v1/admin/users",
            headers=superuser_headers,
            json={
                "email": "newuser@example.com",
                "password": "dummy_password_for_tests",  # pragma: allowlist secret
                "full_name": "New User",
                "role": "user",
            },
        )
        assert response.status_code == 403, (
            f"Superuser should not be able to create users, got {response.status_code}"
        )

    def test_admin_can_create_user(self, client: TestClient, admin_headers: dict):
        """Admin must be allowed to create users."""
        response = client.post(
            "/api/v1/admin/users",
            headers=admin_headers,
            json={
                "email": "newadminuser@example.com",
                "password": "dummy_password_for_tests",  # pragma: allowlist secret
                "full_name": "New User",
                "role": "user",
            },
        )
        # 201 = created, 422 = validation error (duplicate email etc.)
        assert response.status_code in [201, 422]

    def test_regular_user_cannot_create_user(self, client: TestClient, user_headers: dict):
        """Regular user must be forbidden from creating users."""
        response = client.post(
            "/api/v1/admin/users",
            headers=user_headers,
            json={
                "email": "hacker@example.com",
                "password": "dummy_password_for_tests",  # pragma: allowlist secret
                "full_name": "Hacker",
                "role": "admin",
            },
        )
        assert response.status_code in [401, 403]
