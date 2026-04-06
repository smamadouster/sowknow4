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
                'uploaded', 'ocr', 'chunked', 'embedded', 'indexed', 'articles', 'entities', 'enriched'
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

    # Create pipeline_stages table using raw SQL to avoid SQLAlchemy's
    # enum creation issues with schema-qualified types
    op.execute(sa.text("""
        CREATE TABLE sowknow.pipeline_stages (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            document_id UUID NOT NULL REFERENCES sowknow.documents(id) ON DELETE CASCADE,
            stage sowknow.stageenum NOT NULL,
            status sowknow.stagestatus NOT NULL DEFAULT 'pending',
            attempt INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 3,
            started_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            error_message TEXT,
            worker_id VARCHAR(255),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """))

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
