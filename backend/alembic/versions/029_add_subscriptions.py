"""Add subscriptions table.

Revision ID: 029_add_subscriptions
Revises: 028_add_pipeline_sweeper_indexes
Create Date: 2026-05-10

Adds:
  - sowknow.subscriptions table with user-linked subscription tracking
  - billing_cycle enum column (monthly / yearly)
  - subscription_status enum column (active / unused)
  - reminder_sent_for_date to avoid duplicate email reminders
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "029_add_subscriptions"
down_revision = "028_add_pipeline_sweeper_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "subscriptions",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("domain", sa.String(512), nullable=True),
        sa.Column("price", sa.Numeric(12, 2), nullable=False),
        sa.Column("billing_cycle", sa.String(20), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("last_payment", sa.Date(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("color", sa.String(128), nullable=True),
        sa.Column("reminder_sent_for_date", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["sowknow.users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="sowknow",
    )
    op.create_index("ix_subscriptions_user_id", "subscriptions", ["user_id"], schema="sowknow")


def downgrade() -> None:
    op.drop_index("ix_subscriptions_user_id", table_name="subscriptions", schema="sowknow")
    op.drop_table("subscriptions", schema="sowknow")
