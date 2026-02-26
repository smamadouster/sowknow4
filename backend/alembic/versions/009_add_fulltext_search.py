"""Add full-text search tsvector support to document_chunks

Adds search_vector (TSVECTOR) and search_language (String) columns to
sowknow.document_chunks, backfills existing rows, creates a GIN index for
fast full-text search, and installs a trigger that auto-updates search_vector
on INSERT or UPDATE of chunk_text / search_language.

Revision ID: 009
Revises: 008
Create Date: 2026-02-25
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add tsvector column
    op.add_column(
        "document_chunks",
        sa.Column("search_vector", postgresql.TSVECTOR(), nullable=True),
        schema="sowknow",
    )

    # 2. Add language column (default: french — system default)
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

    # 3. Backfill existing rows using the french text search configuration
    op.execute(
        """
        UPDATE sowknow.document_chunks
        SET search_vector = to_tsvector('french'::regconfig, COALESCE(chunk_text, ''))
        WHERE search_vector IS NULL;
        """
    )

    # 4. GIN index for fast full-text search
    op.create_index(
        "ix_document_chunks_search_vector_gin",
        "document_chunks",
        ["search_vector"],
        schema="sowknow",
        postgresql_using="gin",
    )

    # 5. Trigger function — auto-updates search_vector before INSERT/UPDATE
    #    Named with sowknow_ prefix to avoid clashes with other schemas.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION sowknow_update_chunk_search_vector()
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

    # 6. Attach trigger to sowknow.document_chunks
    op.execute(
        """
        CREATE TRIGGER chunk_search_vector_update
        BEFORE INSERT OR UPDATE OF chunk_text, search_language
        ON sowknow.document_chunks
        FOR EACH ROW
        EXECUTE FUNCTION sowknow_update_chunk_search_vector();
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS chunk_search_vector_update ON sowknow.document_chunks;"
    )
    op.execute("DROP FUNCTION IF EXISTS sowknow_update_chunk_search_vector();")
    op.drop_index(
        "ix_document_chunks_search_vector_gin",
        table_name="document_chunks",
        schema="sowknow",
    )
    op.drop_column("document_chunks", "search_language", schema="sowknow")
    op.drop_column("document_chunks", "search_vector", schema="sowknow")
