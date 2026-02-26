"""Add is_confidential to collections; compound index (user_id, is_confidential).

Revision ID: add_coll_confidential_008
Revises: add_audit_logs_007
Create Date: 2026-02-26

P1-6:
- Adds is_confidential boolean column (default FALSE) to collections
- Adds compound index ix_collections_user_confidential
- Backfills: marks any collection containing confidential docs as is_confidential=TRUE
"""

from alembic import op
import sqlalchemy as sa


revision = "add_coll_confidential_008"
down_revision = "add_audit_logs_007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add column (idempotent)
    op.execute("""
        ALTER TABLE sowknow.collections
          ADD COLUMN IF NOT EXISTS is_confidential boolean NOT NULL DEFAULT false
    """)

    # Set default on existing column (may already have default)
    op.execute("""
        ALTER TABLE sowknow.collections
          ALTER COLUMN is_confidential SET DEFAULT false
    """)

    # Compound index
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_collections_user_confidential
          ON sowknow.collections (user_id, is_confidential)
    """)

    # Backfill: flag collections that contain confidential documents
    op.execute("""
        UPDATE sowknow.collections c
        SET is_confidential = TRUE
        WHERE EXISTS (
            SELECT 1
            FROM sowknow.collection_items ci
            JOIN sowknow.documents d ON ci.document_id = d.id
            WHERE ci.collection_id = c.id
              AND d.bucket::text IN ('confidential', 'CONFIDENTIAL')
        )
    """)


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS sowknow.ix_collections_user_confidential"
    )
    op.execute(
        "ALTER TABLE sowknow.collections "
        "DROP COLUMN IF EXISTS is_confidential"
    )
