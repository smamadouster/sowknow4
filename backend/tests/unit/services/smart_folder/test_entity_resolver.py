import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge_graph import Entity, EntityType
from app.services.smart_folder.entity_resolver import EntityResolverService, ResolutionResult


class TestEntityResolverService:
    """Unit tests for EntityResolverService."""

    @pytest.fixture
    def resolver(self):
        return EntityResolverService()

    @pytest.fixture
    def mock_db(self):
        return MagicMock(spec=AsyncSession)

    def _make_entity(self, name: str, aliases: list[str] | None = None) -> Entity:
        e = Entity(
            id=uuid.uuid4(),
            name=name,
            entity_type=EntityType.ORGANIZATION,
            aliases=aliases or [],
        )
        return e

    @pytest.mark.asyncio
    async def test_exact_match(self, resolver, mock_db):
        """Test exact case-insensitive match."""
        entity = self._make_entity("Bank A")
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [entity]
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute.return_value = mock_result

        result = await resolver.resolve(mock_db, "bank a")

        assert result.match_type == "exact"
        assert result.entity == entity
        assert result.confidence == 100.0

    @pytest.mark.asyncio
    async def test_alias_match(self, resolver, mock_db):
        """Test alias match via JSONB."""
        entity = self._make_entity("Bank A Ltd", aliases=["Bank A"])
        # First call (exact) returns []
        # Second call (alias) returns entity
        # Third+ calls for fuzzy fetch rows, then entity fetch
        def _make_result(entities):
            mock_scalars = MagicMock()
            mock_scalars.all.return_value = entities
            mock_result = MagicMock()
            mock_result.scalars.return_value = mock_scalars
            mock_result.all.return_value = []
            return mock_result

        mock_db.execute.side_effect = [
            _make_result([]),            # exact
            _make_result([entity]),      # alias
            _make_result([]),            # fuzzy all_stmt
        ]

        result = await resolver.resolve(mock_db, "Bank A")

        assert result.match_type == "alias"
        assert result.entity == entity
        assert result.confidence == 95.0

    @pytest.mark.asyncio
    async def test_no_match(self, resolver, mock_db):
        """Test when no entity matches."""
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_result.all.return_value = []
        mock_db.execute.return_value = mock_result

        result = await resolver.resolve(mock_db, "Unknown Entity XYZ")

        assert result.match_type == "none"
        assert result.entity is None

    @pytest.mark.asyncio
    async def test_empty_name(self, resolver, mock_db):
        """Test resolution with empty name."""
        result = await resolver.resolve(mock_db, "")

        assert result.match_type == "none"
        assert result.entity is None
