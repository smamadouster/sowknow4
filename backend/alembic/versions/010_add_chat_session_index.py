"""Add compound index on chat_messages(session_id, created_at DESC).

Revision ID: add_chat_idx_010
Revises: add_rls_009
Create Date: 2026-02-26

P1-7: The chat history query pattern is:
    SELECT * FROM chat_messages
    WHERE session_id = $1
    ORDER BY created_at DESC
    LIMIT 50

This compound index brings that query from O(n) to O(log n + result_set).
"""

from alembic import op


revision = "add_chat_idx_010"
down_revision = "add_rls_009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_chat_messages_session_created
          ON sowknow.chat_messages (session_id, created_at DESC)
    """)


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS sowknow.ix_chat_messages_session_created"
    )
