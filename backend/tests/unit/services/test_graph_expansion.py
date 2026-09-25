import uuid
from unittest.mock import MagicMock

import pytest
pytest.skip("Disabled during Ollama removal (Sep 4)", allow_module_level=True)
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.document import DocumentChunk
from app.models.knowledge_graph import Entity, EntityRelationship, EntityType, RelationType
from app.services.search_agent import graph_expansion_chunks
from app.services.search_models import ParsedIntent, QueryIntent


def _intent(intent: QueryIntent, entities: list[str] | None = None) -> ParsedIntent:
    return ParsedIntent(intent=intent, confidence=0.9, entities=entities or [])


def _scalars_result(rows: list) -> MagicMock:
    scalars = MagicMock()
    scalars.all.return_value = rows
    result = MagicMock()
    result.scalars.return_value = scalars
    return result


def _rows_result(rows: list) -> MagicMock:
    result = MagicMock()
    result.all.return_value = rows
    return result


class TestGraphExpansionChunks:
    @pytest.fixture
    def mock_db(self):
        return MagicMock(spec=AsyncSession)

    @pytest.fixture(autouse=True)
    def _enable_flag(self, monkeypatch):
        monkeypatch.setattr(settings, "SEARCH_GRAPH_EXPANSION_ENABLED", True)

    @pytest.mark.asyncio
    async def test_flag_disabled_returns_empty(self, mock_db, monkeypatch):
        monkeypatch.setattr(settings, "SEARCH_GRAPH_EXPANSION_ENABLED", False)
        result = await graph_expansion_chunks(
            mock_db, _intent(QueryIntent.ENTITY_SEARCH, ["Mamadou Sow"]), ["public"], 30
        )
        assert result == []
        mock_db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_entity_intent_returns_empty(self, mock_db):
        result = await graph_expansion_chunks(mock_db, _intent(QueryIntent.FACTUAL, ["Mamadou Sow"]), ["public"], 30)
        assert result == []
        mock_db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_entities_returns_empty(self, mock_db):
        result = await graph_expansion_chunks(mock_db, _intent(QueryIntent.ENTITY_SEARCH, []), ["public"], 30)
        assert result == []
        mock_db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_happy_path_returns_zero_scored_graph_chunks(self, mock_db):
        entity = Entity(id=uuid.uuid4(), name="Mamadou Sow", entity_type=EntityType.PERSON, document_count=10)
        neighbor_id = uuid.uuid4()
        rel = EntityRelationship(
            id=uuid.uuid4(),
            source_id=entity.id,
            target_id=neighbor_id,
            relation_type=RelationType.RELATED_TO,
            confidence_score=80,
        )
        chunk = DocumentChunk(
            id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            chunk_index=3,
            chunk_text="x" * 60,
            bucket="public",
            page_number=2,
        )

        mock_db.execute.side_effect = [
            _scalars_result([entity]),  # entity match
            _scalars_result([rel]),  # 1-hop relationships
            _rows_result([(chunk, "facture.pdf")]),  # mention chunks
        ]

        result = await graph_expansion_chunks(
            mock_db, _intent(QueryIntent.ENTITY_SEARCH, ["Mamadou Sow"]), ["public"], 30
        )

        assert len(result) == 1
        rc = result[0]
        assert rc.chunk_id == chunk.id
        assert rc.match_source == "graph"
        assert rc.semantic_score == 0.0
        assert rc.fts_rank == 0.0
        assert rc.rrf_score == 0.0
        assert rc.document_title == "facture.pdf"
        assert rc.document_type == "pdf"

    @pytest.mark.asyncio
    async def test_duplicate_mentions_deduped_and_capped(self, mock_db):
        entity = Entity(id=uuid.uuid4(), name="BICIS", entity_type=EntityType.ORGANIZATION, document_count=5)
        chunk = DocumentChunk(
            id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            chunk_index=0,
            chunk_text="y" * 60,
            bucket="public",
            page_number=None,
        )
        mock_db.execute.side_effect = [
            _scalars_result([entity]),
            _scalars_result([]),
            _rows_result([(chunk, "releve.pdf"), (chunk, "releve.pdf")]),
        ]

        result = await graph_expansion_chunks(mock_db, _intent(QueryIntent.CROSS_REF, ["BICIS"]), ["public"], 30)

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_document_level_fallback_when_chunk_links_missing(self, mock_db):
        entity = Entity(id=uuid.uuid4(), name="Mamadou Sow", entity_type=EntityType.PERSON, document_count=10)
        doc_id = uuid.uuid4()
        other_doc_id = uuid.uuid4()
        chunks_same_doc = [
            DocumentChunk(
                id=uuid.uuid4(), document_id=doc_id, chunk_index=i,
                chunk_text="x" * 60, bucket="public", page_number=None,
            )
            for i in range(5)
        ]
        chunk_other_doc = DocumentChunk(
            id=uuid.uuid4(), document_id=other_doc_id, chunk_index=0,
            chunk_text="y" * 60, bucket="public", page_number=None,
        )

        mock_db.execute.side_effect = [
            _scalars_result([entity]),  # entity match
            _scalars_result([]),  # 1-hop relationships
            _rows_result([]),  # no chunk-linked mentions (chunk_id NULL in prod)
            _rows_result([(c, "dossier.pdf") for c in chunks_same_doc] + [(chunk_other_doc, "autre.pdf")]),
        ]

        result = await graph_expansion_chunks(
            mock_db, _intent(QueryIntent.ENTITY_SEARCH, ["Mamadou Sow"]), ["public"], 30
        )

        # per-document cap of 3 + 1 chunk from the other doc
        assert len(result) == 4
        assert sum(1 for rc in result if rc.document_id == doc_id) == 3
        assert all(rc.match_source == "graph" for rc in result)

    @pytest.mark.asyncio
    async def test_db_error_is_fail_open(self, mock_db):
        mock_db.execute.side_effect = RuntimeError("db down")
        result = await graph_expansion_chunks(
            mock_db, _intent(QueryIntent.ENTITY_SEARCH, ["Mamadou Sow"]), ["public"], 30
        )
        assert result == []
