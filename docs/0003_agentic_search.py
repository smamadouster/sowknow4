"""
Alembic migration — SOWKNOW Agentic Search Schema
Adds:
  - search_history table
  - document_chunks.ts_vector column + GIN index
  - document_chunks.bucket column (inherited from parent document)
  - Composite indexes for hybrid search performance
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, ARRAY, TEXT
import pgvector.sqlalchemy  # noqa: F401  (registers Vector type)


revision = "0003_agentic_search"
down_revision = "0002_documents"
branch_labels = None
depends_on = None


def upgrade():
    # ── Ensure pgvector extension ──────────────────────────────────────────
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # ── Add missing columns to document_chunks ────────────────────────────
    # bucket (denormalized from parent document for query performance)
    op.add_column(
        "document_chunks",
        sa.Column("bucket", sa.String(20), nullable=False, server_default="public"),
    )
    # ts_vector for full-text search
    op.add_column(
        "document_chunks",
        sa.Column("ts_vector", sa.Column("ts_vector", sa.Text()), nullable=True),
    )
    op.execute("""
        ALTER TABLE document_chunks
        ADD COLUMN IF NOT EXISTS ts_vector tsvector
        GENERATED ALWAYS AS (
            to_tsvector('french', coalesce(text, '')) ||
            to_tsvector('english', coalesce(text, ''))
        ) STORED
    """)

    # ── Indexes for hybrid search ──────────────────────────────────────────
    # HNSW index on embedding vector (cosine distance)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_chunks_embedding_hnsw
        ON document_chunks
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    """)
    # GIN index for full-text search
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_chunks_ts_vector_gin
        ON document_chunks
        USING GIN (ts_vector)
    """)
    # Composite index: bucket + document_id (for RBAC-filtered queries)
    op.create_index(
        "idx_chunks_bucket_doc",
        "document_chunks",
        ["bucket", "document_id"],
    )
    # Index on document status for filtering
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_documents_status
        ON documents (status)
        WHERE status = 'indexed'
    """)
    # Trigram index on document title for fuzzy matching
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_documents_title_trgm
        ON documents
        USING GIN (title gin_trgm_ops)
    """)

    # ── Search history table ───────────────────────────────────────────────
    op.create_table(
        "search_history",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("parsed_intent", sa.String(50), nullable=True),
        sa.Column("result_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("has_confidential_results", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("llm_model_used", sa.String(100), nullable=True),
        sa.Column("search_time_ms", sa.Integer(), nullable=True),
        sa.Column("performed_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("idx_search_history_user_time", "search_history", ["user_id", "performed_at"])

    # ── Trigger: auto-populate chunk bucket from parent document ──────────
    op.execute("""
        CREATE OR REPLACE FUNCTION sync_chunk_bucket()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.bucket := (SELECT bucket FROM documents WHERE id = NEW.document_id);
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        DROP TRIGGER IF EXISTS trg_sync_chunk_bucket ON document_chunks;
        CREATE TRIGGER trg_sync_chunk_bucket
        BEFORE INSERT OR UPDATE ON document_chunks
        FOR EACH ROW EXECUTE FUNCTION sync_chunk_bucket();
    """)


def downgrade():
    op.execute("DROP TRIGGER IF EXISTS trg_sync_chunk_bucket ON document_chunks")
    op.execute("DROP FUNCTION IF EXISTS sync_chunk_bucket()")
    op.drop_table("search_history")
    op.drop_index("idx_chunks_embedding_hnsw")
    op.drop_index("idx_chunks_ts_vector_gin")
    op.drop_index("idx_chunks_bucket_doc")
    op.drop_index("idx_documents_status")
    op.drop_index("idx_documents_title_trgm")
    op.drop_column("document_chunks", "bucket")
    op.drop_column("document_chunks", "ts_vector")
