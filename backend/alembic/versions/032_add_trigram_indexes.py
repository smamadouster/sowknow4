"""Add trigram indexes for fast ILIKE search

Revision ID: 032_add_trigram_indexes
Revises: 031_add_task_to_targettype_enum
Create Date: 2026-05-15

Adds GIN trigram indexes on documents.filename, documents.original_filename
and document_chunks.chunk_text so that ILIKE patterns and similarity()
can use index scans instead of sequential scans on large deployments.
"""

from alembic import op

revision = "032_add_trigram_indexes"
down_revision = "031_add_task_to_targettype_enum"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_documents_filename_trgm
        ON sowknow.documents USING GIN (filename gin_trgm_ops)
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_documents_original_filename_trgm
        ON sowknow.documents USING GIN (original_filename gin_trgm_ops)
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_document_chunks_chunk_text_trgm
        ON sowknow.document_chunks USING GIN (chunk_text gin_trgm_ops)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS sowknow.idx_document_chunks_chunk_text_trgm")
    op.execute("DROP INDEX IF EXISTS sowknow.idx_documents_original_filename_trgm")
    op.execute("DROP INDEX IF EXISTS sowknow.idx_documents_filename_trgm")
