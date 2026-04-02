"""
Tests for async collection creation pipeline.
Covers: status transitions, Celery task dispatch, error handling.
"""
import pytest
from app.models.collection import Collection, CollectionStatus


class TestCollectionStatusEnum:
    """CollectionStatus enum must exist with building/ready/failed values."""

    def test_status_enum_has_building(self):
        assert CollectionStatus.BUILDING.value == "building"

    def test_status_enum_has_ready(self):
        assert CollectionStatus.READY.value == "ready"

    def test_status_enum_has_failed(self):
        assert CollectionStatus.FAILED.value == "failed"

    def test_collection_model_has_status_field(self, db):
        """Collection model must have a status column."""
        from app.models.user import User, UserRole

        user = db.query(User).first()
        if not user:
            user = User(
                email="status_test@example.com",
                hashed_password="hashed",  # pragma: allowlist secret
                full_name="Status Test",
                role=UserRole.USER,
                is_active=True,
            )
            db.add(user)
            db.commit()
            db.refresh(user)

        collection = Collection(
            user_id=user.id,
            name="Status Test",
            query="test",
            collection_type="smart",
            visibility="private",
            status=CollectionStatus.BUILDING,
            document_count=0,
        )
        db.add(collection)
        db.commit()
        db.refresh(collection)

        assert collection.status == CollectionStatus.BUILDING

    def test_collection_status_default_is_ready(self, db):
        """Existing collections without explicit status should default to ready."""
        from app.models.user import User, UserRole

        user = db.query(User).first()
        if not user:
            user = User(
                email="default_status@example.com",
                hashed_password="hashed",  # pragma: allowlist secret
                full_name="Default Status",
                role=UserRole.USER,
                is_active=True,
            )
            db.add(user)
            db.commit()
            db.refresh(user)

        collection = Collection(
            user_id=user.id,
            name="Default Status Test",
            query="test",
            collection_type="smart",
            visibility="private",
            document_count=0,
        )
        db.add(collection)
        db.commit()
        db.refresh(collection)

        assert collection.status == CollectionStatus.READY
