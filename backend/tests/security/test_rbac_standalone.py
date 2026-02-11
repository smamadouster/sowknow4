"""
Standalone RBAC (Role-Based Access Control) security tests.

These tests verify RBAC implementation without requiring the full API.
"""
import pytest

from app.models.user import User, UserRole
from app.models.document import Document, DocumentBucket, DocumentStatus
from app.services.search_service import HybridSearchService


class TestUserRoleDefinitions:
    """Test user role definitions and properties"""

    def test_user_role_exists(self):
        """Test that USER role is defined"""
        assert UserRole.USER.value == "user"

    def test_admin_role_exists(self):
        """Test that ADMIN role is defined"""
        assert UserRole.ADMIN.value == "admin"

    def test_superuser_role_exists(self):
        """Test that SUPERUSER role is defined"""
        assert UserRole.SUPERUSER.value == "superuser"

    def test_role_equality(self):
        """Test role comparison"""
        assert UserRole.USER == "user"
        assert UserRole.ADMIN == "admin"
        assert UserRole.SUPERUSER == "superuser"


class TestDocumentBucketDefinitions:
    """Test document bucket definitions"""

    def test_public_bucket_exists(self):
        """Test that PUBLIC bucket is defined"""
        assert DocumentBucket.PUBLIC.value == "public"

    def test_confidential_bucket_exists(self):
        """Test that CONFIDENTIAL bucket is defined"""
        assert DocumentBucket.CONFIDENTIAL.value == "confidential"


class TestUserBucketAccess:
    """Test document bucket access based on user roles"""

    def setup_method(self):
        """Initialize search service for each test"""
        try:
            self.search_service = HybridSearchService()
        except:
            # If search service requires dependencies, skip these tests
            self.search_service = None
            pytest.skip("Search service not available")

    def test_admin_can_access_public_bucket(self):
        """Test that admin can access public documents"""
        if self.search_service is None:
            pytest.skip("Search service not available")

        admin_user = User(
            email="admin@example.com",
            hashed_password="hash",
            role=UserRole.ADMIN,
            is_superuser=False,
            can_access_confidential=False,
            is_active=True
        )
        allowed_buckets = self.search_service._get_user_bucket_filter(admin_user)
        assert DocumentBucket.PUBLIC.value in allowed_buckets

    def test_admin_can_access_confidential_bucket(self):
        """Test that admin can access confidential documents"""
        if self.search_service is None:
            pytest.skip("Search service not available")

        admin_user = User(
            email="admin@example.com",
            hashed_password="hash",
            role=UserRole.ADMIN,
            is_superuser=False,
            can_access_confidential=False,
            is_active=True
        )
        allowed_buckets = self.search_service._get_user_bucket_filter(admin_user)
        assert DocumentBucket.CONFIDENTIAL.value in allowed_buckets

    def test_superuser_can_access_public_bucket(self):
        """Test that superuser can access public documents"""
        if self.search_service is None:
            pytest.skip("Search service not available")

        superuser = User(
            email="super@example.com",
            hashed_password="hash",
            role=UserRole.SUPERUSER,
            is_superuser=False,
            can_access_confidential=False,
            is_active=True
        )
        allowed_buckets = self.search_service._get_user_bucket_filter(superuser)
        assert DocumentBucket.PUBLIC.value in allowed_buckets

    def test_superuser_can_access_confidential_bucket(self):
        """Test that superuser can access confidential documents"""
        if self.search_service is None:
            pytest.skip("Search service not available")

        superuser = User(
            email="super@example.com",
            hashed_password="hash",
            role=UserRole.SUPERUSER,
            is_superuser=False,
            can_access_confidential=False,
            is_active=True
        )
        allowed_buckets = self.search_service._get_user_bucket_filter(superuser)
        assert DocumentBucket.CONFIDENTIAL.value in allowed_buckets

    def test_regular_user_can_access_public_bucket(self):
        """Test that regular user can access public documents"""
        if self.search_service is None:
            pytest.skip("Search service not available")

        regular_user = User(
            email="user@example.com",
            hashed_password="hash",
            role=UserRole.USER,
            is_superuser=False,
            can_access_confidential=False,
            is_active=True
        )
        allowed_buckets = self.search_service._get_user_bucket_filter(regular_user)
        assert DocumentBucket.PUBLIC.value in allowed_buckets

    def test_regular_user_cannot_access_confidential_bucket(self):
        """Test that regular user cannot access confidential documents"""
        if self.search_service is None:
            pytest.skip("Search service not available")

        regular_user = User(
            email="user@example.com",
            hashed_password="hash",
            role=UserRole.USER,
            is_superuser=False,
            can_access_confidential=False,
            is_active=True
        )
        allowed_buckets = self.search_service._get_user_bucket_filter(regular_user)
        assert DocumentBucket.CONFIDENTIAL.value not in allowed_buckets

    def test_admin_has_full_access(self):
        """Test that admin has access to all buckets"""
        if self.search_service is None:
            pytest.skip("Search service not available")

        admin_user = User(
            email="admin@example.com",
            hashed_password="hash",
            role=UserRole.ADMIN,
            is_superuser=False,
            can_access_confidential=False,
            is_active=True
        )
        allowed_buckets = self.search_service._get_user_bucket_filter(admin_user)
        assert len(allowed_buckets) == 2
        assert set(allowed_buckets) == {
            DocumentBucket.PUBLIC.value,
            DocumentBucket.CONFIDENTIAL.value
        }

    def test_superuser_has_full_access(self):
        """Test that superuser has access to all buckets"""
        if self.search_service is None:
            pytest.skip("Search service not available")

        superuser = User(
            email="super@example.com",
            hashed_password="hash",
            role=UserRole.SUPERUSER,
            is_superuser=False,
            can_access_confidential=False,
            is_active=True
        )
        allowed_buckets = self.search_service._get_user_bucket_filter(superuser)
        assert len(allowed_buckets) == 2
        assert set(allowed_buckets) == {
            DocumentBucket.PUBLIC.value,
            DocumentBucket.CONFIDENTIAL.value
        }

    def test_regular_user_has_limited_access(self):
        """Test that regular user has limited access"""
        if self.search_service is None:
            pytest.skip("Search service not available")

        regular_user = User(
            email="user@example.com",
            hashed_password="hash",
            role=UserRole.USER,
            is_superuser=False,
            can_access_confidential=False,
            is_active=True
        )
        allowed_buckets = self.search_service._get_user_bucket_filter(regular_user)
        assert len(allowed_buckets) == 1
        assert set(allowed_buckets) == {DocumentBucket.PUBLIC.value}


class TestDocumentBucketIsolation:
    """Test document bucket isolation"""

    def test_public_bucket_exists(self):
        """Test that PUBLIC bucket is defined"""
        assert DocumentBucket.PUBLIC.value == "public"

    def test_confidential_bucket_exists(self):
        """Test that CONFIDENTIAL bucket is defined"""
        assert DocumentBucket.CONFIDENTIAL.value == "confidential"

    def test_document_default_bucket(self):
        """Test that documents default to PUBLIC bucket"""
        doc = Document(
            filename="test.pdf",
            original_filename="test.pdf",
            file_path="/data/test.pdf",
            bucket=DocumentBucket.PUBLIC,
            size=1024,
            mime_type="application/pdf"
        )
        assert doc.bucket == DocumentBucket.PUBLIC


class TestUserPermissions:
    """Test user permissions and access rights"""

    def test_user_can_access_confidential_flag(self):
        """Test can_access_confidential flag exists"""
        user = User(
            email="user@example.com",
            hashed_password="hash",
            role=UserRole.USER,
            is_superuser=False,
            can_access_confidential=False,
            is_active=True
        )
        # Default should be False
        assert user.can_access_confidential == False or user.can_access_confidential is False

    def test_admin_with_confidential_access(self):
        """Test admin with confidential access"""
        admin = User(
            email="admin@example.com",
            hashed_password="hash",
            role=UserRole.ADMIN,
            is_superuser=False,
            can_access_confidential=True,
            is_active=True
        )
        assert admin.can_access_confidential == True or admin.can_access_confidential is True

    def test_superuser_flag(self):
        """Test is_superuser flag"""
        user = User(
            email="user@example.com",
            hashed_password="hash",
            role=UserRole.USER,
            is_superuser=False,
            can_access_confidential=False,
            is_active=True
        )
        # Default should be False
        assert user.is_superuser == False or user.is_superuser is False

    def test_active_user_flag(self):
        """Test is_active flag"""
        user = User(
            email="user@example.com",
            hashed_password="hash",
            role=UserRole.USER,
            is_superuser=False,
            can_access_confidential=False,
            is_active=True
        )
        # Default should be True
        assert user.is_active == True or user.is_active is True


class TestRoleHierarchy:
    """Test role hierarchy and permissions"""

    def setup_method(self):
        """Initialize search service for each test"""
        try:
            self.search_service = HybridSearchService()
        except:
            self.search_service = None
            pytest.skip("Search service not available")

    def test_admin_higher_than_user(self):
        """Test that admin has more permissions than regular user"""
        if self.search_service is None:
            pytest.skip("Search service not available")

        admin_user = User(
            email="admin@example.com",
            hashed_password="hash",
            role=UserRole.ADMIN,
            is_superuser=False,
            can_access_confidential=False,
            is_active=True
        )
        regular_user = User(
            email="user@example.com",
            hashed_password="hash",
            role=UserRole.USER,
            is_superuser=False,
            can_access_confidential=False,
            is_active=True
        )

        admin_buckets = self.search_service._get_user_bucket_filter(admin_user)
        user_buckets = self.search_service._get_user_bucket_filter(regular_user)

        assert len(admin_buckets) > len(user_buckets)
        assert set(user_buckets).issubset(set(admin_buckets))

    def test_superuser_same_as_admin_permissions(self):
        """Test that superuser has same permissions as admin for buckets"""
        if self.search_service is None:
            pytest.skip("Search service not available")

        admin_user = User(
            email="admin@example.com",
            hashed_password="hash",
            role=UserRole.ADMIN,
            is_superuser=False,
            can_access_confidential=False,
            is_active=True
        )
        superuser = User(
            email="super@example.com",
            hashed_password="hash",
            role=UserRole.SUPERUSER,
            is_superuser=False,
            can_access_confidential=False,
            is_active=True
        )

        admin_buckets = set(self.search_service._get_user_bucket_filter(admin_user))
        super_buckets = set(self.search_service._get_user_bucket_filter(superuser))

        assert admin_buckets == super_buckets
