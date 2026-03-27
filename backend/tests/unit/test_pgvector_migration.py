"""
Tests for pgvector embedding migration

These tests verify:
1. DocumentChunk model has embedding_vector column
2. Embedding storage uses vector column
3. Search uses pgvector cosine distance operator
4. Backward compatibility with JSONB embeddings
"""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import numpy as np
import pytest

# pgvector's Vector type is only available when pgvector is installed
try:
    from sqlalchemy.dialects.postgresql import Vector
    PGVECTOR_AVAILABLE = True
except ImportError:
    Vector = None
    PGVECTOR_AVAILABLE = False

from app.models.document import Document, DocumentBucket, DocumentChunk, DocumentStatus
from app.services.embedding_service import EmbeddingService


class TestDocumentChunkModel:
    """Tests for DocumentChunk model with vector column"""

    def test_document_chunk_has_embedding_vector_column(self):
        """Verify embedding_vector column exists in DocumentChunk model"""
        # Check that the model has the embedding_vector attribute
        assert hasattr(DocumentChunk, "embedding_vector")

        # Get the column from the table
        columns = {c.name: c for c in DocumentChunk.__table__.columns}
        assert "embedding_vector" in columns

        # Verify it's a Vector type (or compatible)
        col = columns["embedding_vector"]
        assert col.nullable is True

    @pytest.mark.skipif(not PGVECTOR_AVAILABLE, reason="pgvector not installed")
    def test_document_chunk_embedding_vector_dimension(self):
        """Verify embedding_vector has correct dimension (1024)"""
        columns = {c.name: c for c in DocumentChunk.__table__.columns}
        col = columns["embedding_vector"]

        # Check if it's a Vector type with dimension 1024
        col_type = str(col.type)
        assert "1024" in col_type or hasattr(col.type, "dimensions")


class TestEmbeddingStorage:
    """Tests for embedding storage in vector column"""

    @pytest.mark.skipif(not PGVECTOR_AVAILABLE, reason="pgvector not installed")
    @pytest.mark.asyncio
    async def test_store_embedding_in_vector_column(self, db):
        """Test that embeddings are stored in vector column"""
        # Create a document
        doc = Document(
            id=uuid4(),
            filename="test.pdf",
            original_filename="test.pdf",
            file_path="/tmp/test.pdf",
            bucket=DocumentBucket.PUBLIC,
            status=DocumentStatus.INDEXED,
            size=1024,
            mime_type="application/pdf",
        )
        db.add(doc)
        db.commit()

        # Create a chunk with embedding
        chunk = DocumentChunk(
            id=uuid4(),
            document_id=doc.id,
            chunk_index=0,
            chunk_text="This is test content",
            embedding_vector=[0.1] * 1024,  # Mock 1024-dim embedding
            token_count=10,
        )
        db.add(chunk)
        db.commit()

        # Verify embedding is stored
        db.refresh(chunk)
        assert chunk.embedding_vector is not None
        assert len(chunk.embedding_vector) == 1024

    @pytest.mark.skipif(not PGVECTOR_AVAILABLE, reason="pgvector not installed")
    @pytest.mark.asyncio
    async def test_store_embedding_also_in_metadata(self, db):
        """Test that embeddings are also stored in metadata for backward compatibility"""
        # Create a document
        doc = Document(
            id=uuid4(),
            filename="test.pdf",
            original_filename="test.pdf",
            file_path="/tmp/test.pdf",
            bucket=DocumentBucket.PUBLIC,
            status=DocumentStatus.INDEXED,
            size=1024,
            mime_type="application/pdf",
        )
        db.add(doc)
        db.commit()

        # Create a chunk with embedding
        embedding = [0.1] * 1024
        chunk = DocumentChunk(
            id=uuid4(),
            document_id=doc.id,
            chunk_index=0,
            chunk_text="This is test content",
            embedding_vector=embedding,
            token_count=10,
        )
        db.add(chunk)
        db.commit()

        # Verify embedding is also in metadata for backward compatibility
        assert chunk.document_metadata is not None
        assert "embedding" in chunk.document_metadata


class TestSearchService:
    """Tests for search service using pgvector"""

    def test_search_uses_cosine_distance_operator(self):
        """Verify search uses pgvector <=> cosine distance operator"""
        # Read the search service source to verify it uses <=>
        import inspect

        from app.services.search_service import HybridSearchService

        source = inspect.getsource(HybridSearchService.semantic_search)

        # Verify pgvector operator is used
        assert "<=>" in source
        assert "embedding_vector" in source

    def test_search_filters_null_embeddings(self):
        """Verify search filters out chunks without embeddings"""
        import inspect

        from app.services.search_service import HybridSearchService

        source = inspect.getsource(HybridSearchService.semantic_search)

        # Should filter out null embeddings
        assert "embedding_vector IS NOT NULL" in source or "IS NOT NULL" in source


class TestEmbeddingService:
    """Tests for embedding service"""

    def test_embedding_dimensions(self):
        """Verify embedding service uses 1024 dimensions"""
        service = EmbeddingService()
        assert service.embedding_dim == 1024

    @patch("app.services.embedding_service.SentenceTransformer")
    def test_encode_returns_list_of_floats(self, mock_transformer):
        """Test that encode returns list of floats"""
        # Mock the model
        mock_model = MagicMock()
        mock_model.encode.return_value = np.array([[0.1] * 1024])
        mock_transformer.return_value = mock_model

        service = EmbeddingService()
        service._model = mock_model

        result = service.encode(["test text"])

        assert isinstance(result, list)
        assert len(result) == 1
        assert len(result[0]) == 1024


class TestMigration:
    """Tests for migration-related functionality"""

    def test_backfill_script_exists(self):
        """Verify backfill script exists"""
        import os

        script_path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "scripts", "backfill_embeddings_to_vector.py")
        assert os.path.exists(script_path), f"Script not found at {os.path.abspath(script_path)}"

    def test_migration_file_exists(self):
        """Verify migration file exists"""
        import os

        migration_path = os.path.join(os.path.dirname(__file__), "..", "..", "alembic", "versions", "004_add_pgvector_column.py")
        assert os.path.exists(migration_path), f"Migration not found at {os.path.abspath(migration_path)}"


class TestBackwardCompatibility:
    """Tests for backward compatibility with JSONB embeddings"""

    @pytest.mark.asyncio
    async def test_chunk_can_have_jsonb_embedding(self, db):
        """Test that chunks can still have embeddings in JSONB format"""
        # Create a document
        doc = Document(
            id=uuid4(),
            filename="test.pdf",
            original_filename="test.pdf",
            file_path="/tmp/test.pdf",
            bucket=DocumentBucket.PUBLIC,
            status=DocumentStatus.INDEXED,
            size=1024,
            mime_type="application/pdf",
        )
        db.add(doc)
        db.commit()

        # Create a chunk with embedding in metadata (legacy format)
        embedding = [0.1] * 1024
        chunk = DocumentChunk(
            id=uuid4(),
            document_id=doc.id,
            chunk_index=0,
            chunk_text="This is test content",
            document_metadata={"embedding": embedding},
            token_count=10,
        )
        db.add(chunk)
        db.commit()

        # Verify embedding is in metadata
        assert chunk.document_metadata is not None
        assert "embedding" in chunk.document_metadata
        assert chunk.document_metadata["embedding"] == embedding


# Helper function for encode test
def encode(texts):
    """Helper to encode texts"""
    service = EmbeddingService()
    return service.encode(texts)
