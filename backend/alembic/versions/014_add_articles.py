"""Add articles table for AI-generated knowledge articles

Revision ID: add_articles_014
Revises: add_search_history_013
Create Date: 2026-03-23
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "add_articles_014"
down_revision = "add_search_history_013"
branch_labels = None
depends_on = None


def upgrade():
    # Create articles table
    op.create_table(
        "articles",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("document_id", UUID(as_uuid=True), sa.ForeignKey("sowknow.documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("bucket", sa.Enum("public", "confidential", name="documentbucket", create_type=False), nullable=False),
        sa.Column("status", sa.Enum("pending", "generating", "indexed", "error", name="articlestatus"), nullable=False, server_default="pending"),
        sa.Column("language", sa.String(10), nullable=False, server_default="french"),
        sa.Column("source_chunk_ids", JSONB, server_default="[]"),
        sa.Column("tags", JSONB, server_default="[]"),
        sa.Column("categories", JSONB, server_default="[]"),
        sa.Column("entities", JSONB, server_default="[]"),
        sa.Column("confidence", sa.Integer(), server_default="0"),
        sa.Column("llm_provider", sa.String(50), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=True),
        sa.Column("search_language", sa.String(10), nullable=False, server_default="french"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        schema="sowknow",
    )

    # Add pgvector embedding column
    op.execute("ALTER TABLE sowknow.articles ADD COLUMN embedding_vector vector(1024)")

    # Add tsvector column for full-text search
    op.execute("ALTER TABLE sowknow.articles ADD COLUMN search_vector tsvector")

    # Indexes
    op.create_index("ix_articles_document_id", "articles", ["document_id"], schema="sowknow")
    op.create_index("ix_articles_bucket_status", "articles", ["bucket", "status"], schema="sowknow")
    op.create_index("ix_articles_content_hash", "articles", ["content_hash"], schema="sowknow")

    # GIN index for full-text search
    op.execute("""
        CREATE INDEX ix_articles_search_vector_gin
        ON sowknow.articles USING GIN (search_vector)
    """)

    # HNSW index for vector similarity search
    op.execute("""
        CREATE INDEX ix_articles_embedding_vector
        ON sowknow.articles USING hnsw (embedding_vector vector_cosine_ops)
    """)

    # GIN index on JSONB tags for tag-based filtering
    op.execute("""
        CREATE INDEX ix_articles_tags_gin
        ON sowknow.articles USING GIN (tags)
    """)

    # Tsvector auto-update trigger (uses search_language per row)
    op.execute("""
        CREATE OR REPLACE FUNCTION sowknow.articles_search_vector_update() RETURNS trigger AS $$
        BEGIN
            NEW.search_vector :=
                setweight(to_tsvector(NEW.search_language::regconfig, COALESCE(NEW.title, '')), 'A') ||
                setweight(to_tsvector(NEW.search_language::regconfig, COALESCE(NEW.summary, '')), 'B') ||
                setweight(to_tsvector(NEW.search_language::regconfig, COALESCE(NEW.body, '')), 'C');
            NEW.updated_at := NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.execute("""
        CREATE TRIGGER articles_search_vector_trigger
        BEFORE INSERT OR UPDATE OF title, summary, body, search_language
        ON sowknow.articles
        FOR EACH ROW
        EXECUTE FUNCTION sowknow.articles_search_vector_update();
    """)

    # Add article tracking columns to documents table
    op.add_column("documents", sa.Column("article_count", sa.Integer(), server_default="0"), schema="sowknow")
    op.add_column("documents", sa.Column("articles_generated", sa.Boolean(), server_default="false"), schema="sowknow")


def downgrade():
    op.drop_column("documents", "articles_generated", schema="sowknow")
    op.drop_column("documents", "article_count", schema="sowknow")
    op.execute("DROP TRIGGER IF EXISTS articles_search_vector_trigger ON sowknow.articles")
    op.execute("DROP FUNCTION IF EXISTS sowknow.articles_search_vector_update()")
    op.drop_table("articles", schema="sowknow")
    op.execute("DROP TYPE IF EXISTS articlestatus")
