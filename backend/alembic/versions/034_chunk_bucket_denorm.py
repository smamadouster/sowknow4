"""Denormalize bucket onto document_chunks for index-native ACL filtering

Root cause context (P0 incident 2026-07-28): the semantic search ACL filter
JOINed documents to filter on d.bucket, which made the planner abandon the
HNSW vector index and exact-sort 1.1M vectors. The candidate-pool CTE (code
fix in search_service.py) restored index usage, but the structural fix is to
have bucket on the same table as the vector so the filter is index-native
(and pgvector 0.8 iterative_scan can serve filtered ANN directly).

- Adds sowknow.document_chunks.bucket (backfilled from documents)
- Keeps it in sync with triggers (chunk insert + document bucket change)
- B-tree index on bucket, built CONCURRENTLY (never a blocking index build
  on this table again — see incident notes in migration 010)

Revision: 034_chunk_bucket_denorm
"""

from alembic import op
import sqlalchemy as sa

revision = "034_chunk_bucket_denorm"
down_revision = "033_dedupe_chunks_unique_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "document_chunks",
        sa.Column("bucket", sa.String(length=20), nullable=True),
        schema="sowknow",
    )
    # Backfill from parent documents (1.4M rows — single pass, indexed join)
    op.execute(
        """
        UPDATE sowknow.document_chunks dc
        SET bucket = d.bucket::text
        FROM sowknow.documents d
        WHERE dc.document_id = d.id
          AND dc.bucket IS NULL
        """
    )
    op.execute(
        "ALTER TABLE sowknow.document_chunks ALTER COLUMN bucket SET NOT NULL"
    )
    op.execute(
        "ALTER TABLE sowknow.document_chunks ALTER COLUMN bucket SET DEFAULT 'public'"
    )

    # CONCURRENTLY — a blocking build on this table is what killed the HNSW
    # index last time (migration 010 lesson)
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_document_chunks_bucket "
            "ON sowknow.document_chunks (bucket)"
        )

    # Keep chunk.bucket in sync on insert / document_id change
    op.execute(
        """
        CREATE OR REPLACE FUNCTION sowknow_set_chunk_bucket() RETURNS trigger AS $$
        BEGIN
            SELECT bucket::text INTO NEW.bucket FROM sowknow.documents WHERE id = NEW.document_id;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER chunk_bucket_sync
        BEFORE INSERT OR UPDATE OF document_id ON sowknow.document_chunks
        FOR EACH ROW EXECUTE FUNCTION sowknow_set_chunk_bucket();
        """
    )

    # Propagate document bucket changes to its chunks
    op.execute(
        """
        CREATE OR REPLACE FUNCTION sowknow_propagate_doc_bucket() RETURNS trigger AS $$
        BEGIN
            IF NEW.bucket IS DISTINCT FROM OLD.bucket THEN
                UPDATE sowknow.document_chunks SET bucket = NEW.bucket::text
                WHERE document_id = NEW.id;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER document_bucket_propagate
        AFTER UPDATE OF bucket ON sowknow.documents
        FOR EACH ROW EXECUTE FUNCTION sowknow_propagate_doc_bucket();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS document_bucket_propagate ON sowknow.documents")
    op.execute("DROP TRIGGER IF EXISTS chunk_bucket_sync ON sowknow.document_chunks")
    op.execute("DROP FUNCTION IF EXISTS sowknow_propagate_doc_bucket()")
    op.execute("DROP FUNCTION IF EXISTS sowknow_set_chunk_bucket()")
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS sowknow.ix_document_chunks_bucket")
    op.drop_column("document_chunks", "bucket", schema="sowknow")
