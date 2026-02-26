"""Add full-text search tsvector columns to document_chunks

Revision ID: 005_add_fulltext_search
Revises: 004_fix_embedding_vector
Create Date: 2026-02-26

NOTE: The production migration chain uses revision 009 (which supersedes this
reference migration). This file is retained as a QA reference artifact that
documents the intended full-text search schema additions.

Adds:
  - search_vector (TSVECTOR) — auto-maintained by trigger
  - search_language (String(10)) — PostgreSQL text-search config name (default: french)

Creates:
  - GIN index ix_chunks_search_vector_gin on search_vector
  - GIN index ix_chunks_metadata_search_gin on metadata jsonb
  - Trigger function update_chunk_search_vector()
  - Trigger chunk_search_vector_update BEFORE INSERT OR UPDATE
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import TSVECTOR

revision = "005_add_fulltext_search"
down_revision = "004_fix_embedding_vector"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add tsvector column for full-text search
    op.add_column(
        "document_chunks",
        sa.Column("search_vector", TSVECTOR(), nullable=True),
        schema="sowknow",
    )

    # 2. Add language column (regconfig name, default: french)
    op.add_column(
        "document_chunks",
        sa.Column(
            "search_language",
            sa.String(10),
            nullable=False,
            server_default="french",
        ),
        schema="sowknow",
    )

    # 3. Backfill existing rows with french text-search configuration
    op.execute(
        """
        UPDATE sowknow.document_chunks
        SET search_vector = to_tsvector('french'::regconfig, COALESCE(chunk_text, ''))
        WHERE search_vector IS NULL;
        """
    )

    # 4. GIN index for fast tsvector lookups
    op.create_index(
        "ix_chunks_search_vector_gin",
        "document_chunks",
        ["search_vector"],
        schema="sowknow",
        postgresql_using="gin",
    )

    # 5. GIN index on metadata JSONB for combined metadata search
    op.create_index(
        "ix_chunks_metadata_search_gin",
        "document_chunks",
        ["metadata"],
        schema="sowknow",
        postgresql_using="gin",
    )

    # 6. Trigger function — auto-updates search_vector before INSERT/UPDATE
    op.execute(
        """
        CREATE OR REPLACE FUNCTION update_chunk_search_vector()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.search_vector := to_tsvector(
                COALESCE(NEW.search_language, 'french')::regconfig,
                COALESCE(NEW.chunk_text, '')
            );
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    # 7. Attach trigger to sowknow.document_chunks
    op.execute(
        """
        CREATE TRIGGER chunk_search_vector_update
        BEFORE INSERT OR UPDATE OF chunk_text, search_language
        ON sowknow.document_chunks
        FOR EACH ROW
        EXECUTE FUNCTION update_chunk_search_vector();
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS chunk_search_vector_update "
        "ON sowknow.document_chunks;"
    )
    op.execute("DROP FUNCTION IF EXISTS update_chunk_search_vector();")
    op.drop_index(
        "ix_chunks_search_vector_gin",
        table_name="document_chunks",
        schema="sowknow",
    )
    op.drop_index(
        "ix_chunks_metadata_search_gin",
        table_name="document_chunks",
        schema="sowknow",
    )
    op.drop_column("document_chunks", "search_language", schema="sowknow")
    op.drop_column("document_chunks", "search_vector", schema="sowknow")
