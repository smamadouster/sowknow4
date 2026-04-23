"""Tune HNSW ef_search for better recall

Revision ID: 024
Revises: add_graph_tables_023
Create Date: 2026-04-22

Ensures HNSW indexes exist on embedding columns and sets the database-
level default for hnsw.ef_search to 100 for better recall.
"""

from alembic import op

revision = "024"
down_revision = "add_graph_tables_023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Ensure HNSW index exists on document_chunks (migrate from ivfflat if needed)
    op.execute(
        "DROP INDEX IF EXISTS sowknow.ix_document_chunks_embedding_vector"
    )
    op.execute(
        "DROP INDEX IF EXISTS ix_document_chunks_embedding_vector"
    )
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_document_chunks_embedding_hnsw
        ON sowknow.document_chunks
        USING hnsw (embedding_vector vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    """)

    # Ensure HNSW index exists on articles (migrate from ivfflat if needed)
    op.execute(
        "DROP INDEX IF EXISTS sowknow.ix_articles_embedding_vector"
    )
    op.execute(
        "DROP INDEX IF EXISTS ix_articles_embedding_vector"
    )
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_articles_embedding_hnsw
        ON sowknow.articles
        USING hnsw (embedding_vector vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    """)

    # Set database-level default for HNSW ef_search
    op.execute("ALTER DATABASE sowknow SET hnsw.ef_search = 100")


def downgrade() -> None:
    op.execute("ALTER DATABASE sowknow SET hnsw.ef_search = 40")
