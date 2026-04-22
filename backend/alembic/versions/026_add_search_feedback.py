"""Add search feedback table for relevance learning

Revision ID: 026
Revises: 025
Create Date: 2026-04-22

Stores user thumbs-up/down/dismiss feedback on search results
to enable future ranking improvements.
"""

from alembic import op
import sqlalchemy as sa

revision = "026"
down_revision = "025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "search_feedback",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("query_hash", sa.Text(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("chunk_id", sa.UUID(), nullable=True),
        sa.Column(
            "feedback_type",
            sa.Enum("thumbs_up", "thumbs_down", "dismiss", name="feedback_type"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        schema="sowknow",
    )
    op.create_index(
        "idx_search_feedback_user_query",
        "search_feedback",
        ["user_id", "query_hash"],
        schema="sowknow",
    )
    op.create_index(
        "idx_search_feedback_document",
        "search_feedback",
        ["document_id", "feedback_type"],
        schema="sowknow",
    )


def downgrade() -> None:
    op.drop_index("idx_search_feedback_document", table_name="search_feedback", schema="sowknow")
    op.drop_index("idx_search_feedback_user_query", table_name="search_feedback", schema="sowknow")
    op.drop_table("search_feedback", schema="sowknow")
    op.execute("DROP TYPE IF EXISTS feedback_type")
