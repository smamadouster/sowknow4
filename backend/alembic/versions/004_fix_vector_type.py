"""Fix vector column type — add 'embedding' vector(1024) column

Revision ID: fix_vector_type_004
Revises: 012
Create Date: 2026-02-26

Adds a properly-named 'embedding' vector(1024) column to document_chunks.
The original schema used 'embedding_vector'; this migration adds the
canonical 'embedding' column used by the semantic_search() function.
"""

from alembic import op


revision = "fix_vector_type_004"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE sowknow.document_chunks "
        "ADD COLUMN IF NOT EXISTS embedding vector(1024)"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE sowknow.document_chunks "
        "DROP COLUMN IF EXISTS embedding"
    )
