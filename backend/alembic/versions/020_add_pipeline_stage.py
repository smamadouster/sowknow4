"""Add pipeline_stage column to documents for granular processing tracking"""

import sqlalchemy as sa
from alembic import op

revision = "add_pipeline_stage_020"
down_revision = "migrate_document_tags_019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add pipeline_stage for granular state machine tracking
    op.add_column(
        "documents",
        sa.Column(
            "pipeline_stage",
            sa.String(30),
            nullable=True,
            server_default="uploaded",
        ),
        schema="sowknow",
    )
    # Error details for the current pipeline stage
    op.add_column(
        "documents",
        sa.Column("pipeline_error", sa.Text(), nullable=True),
        schema="sowknow",
    )
    # How many times the current stage has been retried
    op.add_column(
        "documents",
        sa.Column(
            "pipeline_retry_count",
            sa.Integer(),
            nullable=True,
            server_default="0",
        ),
        schema="sowknow",
    )
    # When the current stage was last attempted
    op.add_column(
        "documents",
        sa.Column("pipeline_last_attempt", sa.DateTime(), nullable=True),
        schema="sowknow",
    )

    # Index for recovery queries (find docs stuck at a stage)
    op.create_index(
        "ix_documents_pipeline_stage",
        "documents",
        ["pipeline_stage", "pipeline_retry_count"],
        schema="sowknow",
    )

    # Backfill existing documents based on their current status + flags
    op.execute("""
        UPDATE sowknow.documents
        SET pipeline_stage = CASE
            WHEN status = 'indexed' AND COALESCE(embedding_generated, false) = true THEN 'indexed'
            WHEN status = 'indexed' AND COALESCE(chunk_count, 0) > 0 THEN 'chunked'
            WHEN status = 'error' THEN 'failed'
            WHEN status = 'processing' AND COALESCE(ocr_processed, false) = true THEN 'ocr_complete'
            WHEN status = 'processing' THEN 'ocr_pending'
            WHEN status = 'pending' THEN 'uploaded'
            ELSE 'uploaded'
        END
    """)


def downgrade() -> None:
    op.drop_index("ix_documents_pipeline_stage", table_name="documents", schema="sowknow")
    op.drop_column("documents", "pipeline_last_attempt", schema="sowknow")
    op.drop_column("documents", "pipeline_retry_count", schema="sowknow")
    op.drop_column("documents", "pipeline_error", schema="sowknow")
    op.drop_column("documents", "pipeline_stage", schema="sowknow")
