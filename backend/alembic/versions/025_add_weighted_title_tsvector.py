"""Add weighted title tsvector for field-boosted search

Revision ID: 025
Revises: 024
Create Date: 2026-04-22

Adds a generated tsvector column on documents.title with weight 'A',
enabling title-boosted full-text search in combination with chunk
body search.
"""

from alembic import op
import sqlalchemy as sa

revision = "025"
down_revision = "024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add generated tsvector column on documents
    op.execute("""
        ALTER TABLE sowknow.documents
        ADD COLUMN IF NOT EXISTS title_search_vector TSVECTOR
        GENERATED ALWAYS AS (
            setweight(to_tsvector('simple', COALESCE(title, '')), 'A') ||
            setweight(to_tsvector('simple', COALESCE(original_filename, '')), 'A')
        ) STORED
    """)

    # GIN index for fast full-text lookup
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_documents_title_search
        ON sowknow.documents USING GIN (title_search_vector)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS sowknow.idx_documents_title_search")
    op.execute("ALTER TABLE sowknow.documents DROP COLUMN IF EXISTS title_search_vector")
