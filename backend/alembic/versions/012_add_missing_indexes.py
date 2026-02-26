"""Add missing indexes and unique constraints

Revision ID: 012
Revises: 011
Create Date: 2026-02-26

Adds two things the schema was missing:

1. Compound index on chat_messages(session_id, created_at DESC)
   - chat_messages has no index on session_id; every history load
     currently does a full table scan
   - descending order matches the .order_by(created_at.desc()) query
     pattern used in chat_service.py

2. Unique constraint on collection_items(collection_id, document_id)
   - prevents the same document from being added to a collection twice
   - API should return 409 on duplicate add rather than silently inserting
"""

from alembic import op

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Compound index for fast session history retrieval
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_chat_messages_session_created
        ON sowknow.chat_messages (session_id, created_at DESC)
    """)

    # 2. Unique constraint — one document per collection slot
    op.create_unique_constraint(
        "uq_collection_items_collection_document",
        "collection_items",
        ["collection_id", "document_id"],
        schema="sowknow",
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_collection_items_collection_document",
        "collection_items",
        schema="sowknow",
        type_="unique",
    )
    op.execute("DROP INDEX IF EXISTS ix_chat_messages_session_created")
