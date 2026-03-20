"""Add search_history table and search indexes

Revision ID: add_search_history_013
Revises: 012, add_unique_012
Create Date: 2026-03-20
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "add_search_history_013"
down_revision = ("012", "add_unique_012")
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "search_history",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("sowknow.users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("parsed_intent", sa.String(50), nullable=True),
        sa.Column("result_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("has_confidential_results", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("llm_model_used", sa.String(100), nullable=True),
        sa.Column("search_time_ms", sa.Integer(), nullable=True),
        sa.Column("performed_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        schema="sowknow",
    )
    op.create_index(
        "idx_search_history_user_time",
        "search_history",
        ["user_id", "performed_at"],
        schema="sowknow",
    )

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_documents_status_indexed
        ON sowknow.documents (status)
        WHERE status = 'indexed'
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_documents_title_trgm
        ON sowknow.documents
        USING GIN (title gin_trgm_ops)
    """)


def downgrade():
    op.execute("DROP INDEX IF EXISTS sowknow.idx_documents_title_trgm")
    op.execute("DROP INDEX IF EXISTS sowknow.idx_documents_status_indexed")
    op.drop_index("idx_search_history_user_time", table_name="search_history", schema="sowknow")
    op.drop_table("search_history", schema="sowknow")
