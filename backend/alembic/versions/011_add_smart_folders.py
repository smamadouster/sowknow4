"""Create smart_folders table with rule_config JSONB and FK to collections.

Revision ID: add_smart_folders_011
Revises: add_chat_idx_010
Create Date: 2026-02-26

P1-8: Smart folders are dynamic, rule-based subsets of a collection.
  - rule_config: JSONB configuration for automated filtering rules
  - auto_update: whether to re-sync automatically when documents change
  - last_synced_at: timestamp of last rule evaluation
  - FK to collections with ON DELETE CASCADE
"""

from alembic import op
import sqlalchemy as sa


revision = "add_smart_folders_011"
down_revision = "add_chat_idx_010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS sowknow.smart_folders (
            id             uuid         NOT NULL DEFAULT gen_random_uuid()
                                        PRIMARY KEY,
            collection_id  uuid         NOT NULL
                                        REFERENCES sowknow.collections(id)
                                        ON DELETE CASCADE,
            name           varchar(512) NOT NULL DEFAULT '',
            rule_config    jsonb        NOT NULL DEFAULT '{}',
            auto_update    boolean      NOT NULL DEFAULT true,
            last_synced_at timestamptz,
            created_at     timestamptz  NOT NULL DEFAULT now(),
            updated_at     timestamptz  NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_smart_folders_collection_id
          ON sowknow.smart_folders (collection_id)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS sowknow.smart_folders")
