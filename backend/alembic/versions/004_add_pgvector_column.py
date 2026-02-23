"""Add vector column for embeddings with pgvector

Revision ID: 004
Revises: 003
Create Date: 2026-02-23

This migration adds a proper pgvector vector(1024) column to document_chunks
and backfills existing embeddings from JSONB metadata.

Changes:
- Add embedding vector column using pgvector type
- Backfill from JSONB metadata->embedding if exists
- Add index on vector column for fast similarity search
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

try:
    from pgvector.sqlalchemy import Vector
except ImportError:
    Vector = None

# revision identifiers, used by Alembic.
revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Ensure pgvector extension is available
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Add vector column for embeddings
    # Using vector(1024) from pgvector for proper cosine distance operations
    if Vector is not None:
        op.add_column(
            "document_chunks",
            sa.Column(
                "embedding_vector",
                Vector(1024),  # pgvector type
                nullable=True,
            ),
            schema="sowknow",
        )
    else:
        # Fallback for environments without pgvector
        op.add_column(
            "document_chunks",
            sa.Column(
                "embedding_vector",
                postgresql.ARRAY(sa.Float, dimensions=1024),
                nullable=True,
            ),
            schema="sowknow",
        )

    # Backfill existing embeddings from JSONB metadata
    # This handles the case where embeddings were stored in metadata->embedding
    op.execute("""
        UPDATE sowknow.document_chunks
        SET embedding_vector = (
            SELECT vector
            FROM jsonb_array_elements(metadata->'embedding') AS elem
            WITH ORDINALITY
            ORDER BY ordinality
            LIMIT 1
        )::vector
        WHERE metadata ? 'embedding'
        AND metadata->'embedding' IS NOT NULL
        AND jsonb_typeof(metadata->'embedding') = 'array'
        AND (metadata->>'embedding')::jsonb != 'null'::jsonb
    """)

    # For single embedding stored as object in metadata
    op.execute("""
        UPDATE sowknow.document_chunks
        SET embedding_vector = (
            SELECT vector
            FROM jsonb_array_elements(
                CASE 
                    WHEN jsonb_typeof(metadata->'embedding') = 'array' THEN metadata->'embedding'
                    ELSE jsonb_build_array(metadata->'embedding')
                END
            ) AS elem
            WITH ORDINALITY
            ORDER BY ordinality
            LIMIT 1
        )::vector
        WHERE embedding_vector IS NULL
        AND metadata ? 'embedding'
    """)

    # Alternative simpler backfill using string parsing
    # This handles embeddings stored as JSON arrays of floats
    op.execute("""
        UPDATE sowknow.document_chunks
        SET embedding_vector = 
            ('[' || 
                replace(
                    replace(
                        replace(
                            (metadata->>'embedding')::text,
                            '[', ''
                        ),
                        ']', ''
                    ),
                    ' ',
                    ','
                )
            || ']')::vector
        WHERE embedding_vector IS NULL
        AND metadata ? 'embedding'
        AND metadata->>'embedding' IS NOT NULL
    """)

    # Create IVFFlat index for faster vector similarity search
    # IVFFlat is good for datasets < 1M vectors
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_document_chunks_embedding_vector 
        ON sowknow.document_chunks 
        USING ivfflat (embedding_vector vector_cosine_ops)
        WITH (lists = 100)
    """)


def downgrade() -> None:
    # Drop the index
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_embedding_vector")

    # Remove the vector column
    op.drop_column("document_chunks", "embedding_vector", schema="sowknow")
