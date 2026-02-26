"""Upgrade vector index from IVFFlat to HNSW for better performance

Revision ID: 010
Revises: 009
Create Date: 2026-02-25

HNSW (Hierarchical Navigable Small World) provides:
- Better recall at equivalent query time vs IVFFlat
- No need to specify lists parameter upfront
- Scales well beyond 1M vectors
"""

from alembic import op

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop existing IVFFlat index
    op.execute(
        "DROP INDEX IF EXISTS sowknow.ix_document_chunks_embedding_vector"
    )
    op.execute(
        "DROP INDEX IF EXISTS ix_document_chunks_embedding_vector"
    )

    # Create HNSW index for better ANN search performance
    # m=16: max connections per layer (higher = better recall, more memory)
    # ef_construction=64: size of dynamic candidate list during construction
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_document_chunks_embedding_hnsw
        ON sowknow.document_chunks
        USING hnsw (embedding_vector vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    """)


def downgrade() -> None:
    # Drop HNSW index
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_embedding_hnsw")

    # Restore IVFFlat index
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_document_chunks_embedding_vector
        ON sowknow.document_chunks
        USING ivfflat (embedding_vector vector_cosine_ops)
        WITH (lists = 100)
    """)
