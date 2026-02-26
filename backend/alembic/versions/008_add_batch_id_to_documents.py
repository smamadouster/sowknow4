"""Add batch_id column to documents table for batch-upload tracking

Revision ID: 008
Revises: 007
Create Date: 2026-02-25
"""

from alembic import op
import sqlalchemy as sa

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("batch_id", sa.String(64), nullable=True),
        schema="sowknow",
    )
    op.create_index(
        "ix_documents_batch_id",
        "documents",
        ["batch_id"],
        schema="sowknow",
    )


def downgrade() -> None:
    op.drop_index("ix_documents_batch_id", table_name="documents", schema="sowknow")
    op.drop_column("documents", "batch_id", schema="sowknow")
