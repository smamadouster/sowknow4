"""Add pipeline_stages table with backfill

Revision ID: add_pipeline_stages_022
Revises: add_voice_audio_support_021
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "add_pipeline_stages_022"
down_revision = "add_voice_audio_support_021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create enum types
    op.execute(sa.text("""
        DO $$ BEGIN
            CREATE TYPE sowknow.stageenum AS ENUM (
                'uploaded', 'ocr', 'chunked', 'embedded', 'indexed', 'articles', 'entities'
            );
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """))

    op.execute(sa.text("""
        DO $$ BEGIN
            CREATE TYPE sowknow.stagestatus AS ENUM (
                'pending', 'running', 'completed', 'failed', 'skipped'
            );
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """))

    # Create pipeline_stages table
    op.create_table(
        "pipeline_stages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "document_id",
            UUID(as_uuid=True),
            sa.ForeignKey("sowknow.documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("stage", sa.Enum("uploaded", "ocr", "chunked", "embedded", "indexed", "articles", "entities", name="stageenum", schema="sowknow"), nullable=False),
        sa.Column("status", sa.Enum("pending", "running", "completed", "failed", "skipped", name="stagestatus", schema="sowknow"), nullable=False, server_default="pending"),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("worker_id", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="sowknow",
    )

    # Indexes
    op.create_index(
        "ix_pipeline_stages_document_id",
        "pipeline_stages",
        ["document_id"],
        schema="sowknow",
    )
    op.create_index(
        "ix_pipeline_stages_doc_stage",
        "pipeline_stages",
        ["document_id", "stage"],
        unique=True,
        schema="sowknow",
    )
    op.create_index(
        "ix_pipeline_stages_status",
        "pipeline_stages",
        ["status"],
        schema="sowknow",
    )
    op.create_index(
        "ix_pipeline_stages_stuck",
        "pipeline_stages",
        ["status", "started_at"],
        schema="sowknow",
    )

    # -------------------------------------------------------------------------
    # Backfill — idempotent via ON CONFLICT DO NOTHING
    # -------------------------------------------------------------------------

    # (a) Documents with status='indexed', chunk_count>0, and chunks with
    #     embedding_vector → all stages UPLOADED through INDEXED as 'completed'.
    #     ARTICLES 'completed' if articles_generated=True, else 'pending'.
    #     ENTITIES always 'pending'.
    op.execute(sa.text("""
        INSERT INTO sowknow.pipeline_stages
            (id, document_id, stage, status, created_at, updated_at)
        SELECT
            gen_random_uuid(),
            d.id,
            s.stage::sowknow.stageenum,
            'completed'::sowknow.stagestatus,
            now(),
            now()
        FROM sowknow.documents d
        CROSS JOIN (
            VALUES ('uploaded'), ('ocr'), ('chunked'), ('embedded'), ('indexed')
        ) AS s(stage)
        WHERE d.status = 'indexed'
          AND d.chunk_count > 0
          AND EXISTS (
              SELECT 1 FROM sowknow.document_chunks dc
              WHERE dc.document_id = d.id
                AND dc.embedding_vector IS NOT NULL
          )
        ON CONFLICT DO NOTHING;
    """))

    # ARTICLES stage for fully-indexed docs
    op.execute(sa.text("""
        INSERT INTO sowknow.pipeline_stages
            (id, document_id, stage, status, created_at, updated_at)
        SELECT
            gen_random_uuid(),
            d.id,
            'articles'::sowknow.stageenum,
            CASE WHEN d.articles_generated THEN 'completed' ELSE 'pending' END::sowknow.stagestatus,
            now(),
            now()
        FROM sowknow.documents d
        WHERE d.status = 'indexed'
          AND d.chunk_count > 0
          AND EXISTS (
              SELECT 1 FROM sowknow.document_chunks dc
              WHERE dc.document_id = d.id
                AND dc.embedding_vector IS NOT NULL
          )
        ON CONFLICT DO NOTHING;
    """))

    # ENTITIES stage for fully-indexed docs (always pending)
    op.execute(sa.text("""
        INSERT INTO sowknow.pipeline_stages
            (id, document_id, stage, status, created_at, updated_at)
        SELECT
            gen_random_uuid(),
            d.id,
            'entities'::sowknow.stageenum,
            'pending'::sowknow.stagestatus,
            now(),
            now()
        FROM sowknow.documents d
        WHERE d.status = 'indexed'
          AND d.chunk_count > 0
          AND EXISTS (
              SELECT 1 FROM sowknow.document_chunks dc
              WHERE dc.document_id = d.id
                AND dc.embedding_vector IS NOT NULL
          )
        ON CONFLICT DO NOTHING;
    """))

    # (b) Documents with status='indexed', chunk_count>0, NO chunks with
    #     embedding_vector → UPLOADED/OCR/CHUNKED as 'completed', EMBEDDED as 'pending'.
    op.execute(sa.text("""
        INSERT INTO sowknow.pipeline_stages
            (id, document_id, stage, status, created_at, updated_at)
        SELECT
            gen_random_uuid(),
            d.id,
            s.stage::sowknow.stageenum,
            'completed'::sowknow.stagestatus,
            now(),
            now()
        FROM sowknow.documents d
        CROSS JOIN (
            VALUES ('uploaded'), ('ocr'), ('chunked')
        ) AS s(stage)
        WHERE d.status = 'indexed'
          AND d.chunk_count > 0
          AND NOT EXISTS (
              SELECT 1 FROM sowknow.document_chunks dc
              WHERE dc.document_id = d.id
                AND dc.embedding_vector IS NOT NULL
          )
        ON CONFLICT DO NOTHING;
    """))

    op.execute(sa.text("""
        INSERT INTO sowknow.pipeline_stages
            (id, document_id, stage, status, created_at, updated_at)
        SELECT
            gen_random_uuid(),
            d.id,
            'embedded'::sowknow.stageenum,
            'pending'::sowknow.stagestatus,
            now(),
            now()
        FROM sowknow.documents d
        WHERE d.status = 'indexed'
          AND d.chunk_count > 0
          AND NOT EXISTS (
              SELECT 1 FROM sowknow.document_chunks dc
              WHERE dc.document_id = d.id
                AND dc.embedding_vector IS NOT NULL
          )
        ON CONFLICT DO NOTHING;
    """))

    # (c) Documents with status='error' → map pipeline_stage to appropriate
    #     stage and mark as 'failed'.
    #     Mapping: ocr_pending/ocr_complete → ocr
    #              chunking/chunked → chunked
    #              embedding → embedded
    #              failed / anything else → ocr (default)
    op.execute(sa.text("""
        INSERT INTO sowknow.pipeline_stages
            (id, document_id, stage, status, created_at, updated_at)
        SELECT
            gen_random_uuid(),
            d.id,
            CASE d.pipeline_stage
                WHEN 'ocr_pending'  THEN 'ocr'
                WHEN 'ocr_complete' THEN 'ocr'
                WHEN 'chunking'     THEN 'chunked'
                WHEN 'chunked'      THEN 'chunked'
                WHEN 'embedding'    THEN 'embedded'
                ELSE 'ocr'
            END::sowknow.stageenum,
            'failed'::sowknow.stagestatus,
            now(),
            now()
        FROM sowknow.documents d
        WHERE d.status = 'error'
        ON CONFLICT DO NOTHING;
    """))

    # (d) Documents with status in ('pending','processing','uploading') →
    #     UPLOADED as 'completed', OCR as 'pending'.
    op.execute(sa.text("""
        INSERT INTO sowknow.pipeline_stages
            (id, document_id, stage, status, created_at, updated_at)
        SELECT
            gen_random_uuid(),
            d.id,
            'uploaded'::sowknow.stageenum,
            'completed'::sowknow.stagestatus,
            now(),
            now()
        FROM sowknow.documents d
        WHERE d.status IN ('pending', 'processing', 'uploading')
        ON CONFLICT DO NOTHING;
    """))

    op.execute(sa.text("""
        INSERT INTO sowknow.pipeline_stages
            (id, document_id, stage, status, created_at, updated_at)
        SELECT
            gen_random_uuid(),
            d.id,
            'ocr'::sowknow.stageenum,
            'pending'::sowknow.stagestatus,
            now(),
            now()
        FROM sowknow.documents d
        WHERE d.status IN ('pending', 'processing', 'uploading')
        ON CONFLICT DO NOTHING;
    """))


def downgrade() -> None:
    op.drop_index("ix_pipeline_stages_stuck", table_name="pipeline_stages", schema="sowknow")
    op.drop_index("ix_pipeline_stages_status", table_name="pipeline_stages", schema="sowknow")
    op.drop_index("ix_pipeline_stages_doc_stage", table_name="pipeline_stages", schema="sowknow")
    op.drop_index("ix_pipeline_stages_document_id", table_name="pipeline_stages", schema="sowknow")
    op.drop_table("pipeline_stages", schema="sowknow")

    op.execute(sa.text("DROP TYPE IF EXISTS sowknow.stagestatus;"))
    op.execute(sa.text("DROP TYPE IF EXISTS sowknow.stageenum;"))
