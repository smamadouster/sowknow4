"""
Tests for async collection creation pipeline.
Covers: status transitions, Celery task dispatch, error handling.
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from uuid import uuid4
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


class TestCreateCollectionShell:
    """create_collection_shell must create a DB row with status=BUILDING and no LLM calls."""

    @pytest.mark.asyncio
    async def test_shell_creates_building_status(self, db):
        """Shell creation sets status to BUILDING."""
        from app.models.user import User, UserRole
        from app.schemas.collection import CollectionCreate
        from app.services.collection_service import collection_service

        user = db.query(User).first()
        if not user:
            user = User(
                email="shell_test@example.com",
                hashed_password="hashed",  # pragma: allowlist secret
                full_name="Shell Test",
                role=UserRole.ADMIN,
                is_active=True,
            )
            db.add(user)
            db.commit()
            db.refresh(user)

        data = CollectionCreate(
            name="Shell Test Collection",
            query="Find all financial documents",
            collection_type="smart",
            visibility="private",
        )

        # Mock async db methods since the fixture provides a sync session
        mock_db = MagicMock(wraps=db)
        mock_db.commit = AsyncMock(side_effect=lambda: db.commit())
        mock_db.refresh = AsyncMock(side_effect=lambda obj: db.refresh(obj))

        collection = await collection_service.create_collection_shell(
            collection_data=data, user=user, db=mock_db
        )

        assert collection.id is not None
        assert collection.status == CollectionStatus.BUILDING
        assert collection.name == "Shell Test Collection"
        assert collection.query == "Find all financial documents"
        assert collection.document_count == 0
        assert collection.ai_summary is None

    @pytest.mark.asyncio
    async def test_shell_does_not_call_llm(self, db):
        """Shell creation must NOT call any LLM service."""
        from app.models.user import User, UserRole
        from app.schemas.collection import CollectionCreate
        from app.services.collection_service import collection_service

        user = db.query(User).first()
        if not user:
            user = User(
                email="no_llm@example.com",
                hashed_password="hashed",  # pragma: allowlist secret
                full_name="No LLM",
                role=UserRole.ADMIN,
                is_active=True,
            )
            db.add(user)
            db.commit()
            db.refresh(user)

        data = CollectionCreate(
            name="No LLM Test",
            query="Find contracts",
            collection_type="smart",
            visibility="private",
        )

        # Mock async db methods since the fixture provides a sync session
        mock_db = MagicMock(wraps=db)
        mock_db.commit = AsyncMock(side_effect=lambda: db.commit())
        mock_db.refresh = AsyncMock(side_effect=lambda obj: db.refresh(obj))

        with patch.object(
            collection_service.intent_parser, "parse_intent", new_callable=AsyncMock
        ) as mock_intent, patch.object(
            collection_service.search_service, "hybrid_search", new_callable=AsyncMock
        ) as mock_search:
            await collection_service.create_collection_shell(
                collection_data=data, user=user, db=mock_db
            )
            mock_intent.assert_not_called()
            mock_search.assert_not_called()
