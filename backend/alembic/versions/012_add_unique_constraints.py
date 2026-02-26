"""Add unique constraints on collection_items and entity_mentions.

Revision ID: add_unique_012
Revises: add_smart_folders_011
Create Date: 2026-02-26

P2-10:
- uq_collection_items_collection_document: prevents duplicate document in collection
- uq_entity_mentions_entity_chunk: prevents duplicate entity/chunk mention pair

These constraints enforce data integrity at the DB layer and allow the API
to return 409 Conflict rather than silently inserting duplicates.
"""

from alembic import op


revision = "add_unique_012"
down_revision = "add_smart_folders_011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.table_constraints
                WHERE table_schema   = 'sowknow'
                  AND table_name     = 'collection_items'
                  AND constraint_name = 'uq_collection_items_collection_document'
            ) THEN
                ALTER TABLE sowknow.collection_items
                  ADD CONSTRAINT uq_collection_items_collection_document
                  UNIQUE (collection_id, document_id);
            END IF;
        END $$
    """)
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.table_constraints
                WHERE table_schema   = 'sowknow'
                  AND table_name     = 'entity_mentions'
                  AND constraint_name = 'uq_entity_mentions_entity_chunk'
            ) THEN
                ALTER TABLE sowknow.entity_mentions
                  ADD CONSTRAINT uq_entity_mentions_entity_chunk
                  UNIQUE (entity_id, chunk_id);
            END IF;
        END $$
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE sowknow.entity_mentions
          DROP CONSTRAINT IF EXISTS uq_entity_mentions_entity_chunk
    """)
    op.execute("""
        ALTER TABLE sowknow.collection_items
          DROP CONSTRAINT IF EXISTS uq_collection_items_collection_document
    """)
