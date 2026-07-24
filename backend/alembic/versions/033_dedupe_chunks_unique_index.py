"""Deduplicate document_chunks and enforce (document_id, chunk_index) uniqueness

Revision ID: 033_dedupe_chunks_unique_index
Revises: 032_add_trigram_indexes
Create Date: 2026-07-24

The chunk stage does DELETE-all + INSERT-all per document.  When the sweeper
reset a "stuck" chunk stage while the original task was still running (stuck
threshold disagreed with the real Celery time limit), two executions
interleaved and produced duplicated chunks — 4325 duplicate
(document_id, chunk_index) pairs existed in production on 2026-07-24.

This migration removes the duplicates (keeping, per pair, the row that has
an embedding, then the most recently updated) and adds a unique constraint
so the race can never write duplicates again.
"""

from alembic import op

revision = "033_dedupe_chunks_unique_index"
down_revision = "032_add_trigram_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Remove duplicate chunks, keeping the best row per (document_id, chunk_index):
    #    prefer rows that already carry an embedding, then the most recently updated.
    op.execute("""
        WITH ranked AS (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY document_id, chunk_index
                       ORDER BY (embedding_vector IS NOT NULL) DESC,
                                updated_at DESC NULLS LAST,
                                id
                   ) AS rn
            FROM sowknow.document_chunks
        )
        DELETE FROM sowknow.document_chunks
        WHERE id IN (SELECT id FROM ranked WHERE rn > 1)
    """)

    # 2. Enforce uniqueness going forward.
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_document_chunks_doc_index
        ON sowknow.document_chunks (document_id, chunk_index)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS sowknow.uq_document_chunks_doc_index")
