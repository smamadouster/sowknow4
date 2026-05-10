"""Add tasks table.

Revision ID: 030_add_tasks
Revises: 029_add_subscriptions
Create Date: 2026-05-10

Adds:
  - sowknow.tasks table with user-linked task tracking
  - status enum column (pending / in_progress / completed / cancelled)
  - priority enum column (low / medium / high)
  - due_date and alarm_at for scheduling
  - alarm_triggered boolean to avoid duplicate notifications
  - notes field for task-internal notes
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "030_add_tasks"
down_revision = "029_add_subscriptions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tasks",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("priority", sa.String(20), nullable=False),
        sa.Column("due_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("alarm_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("alarm_triggered", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("bucket", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["sowknow.users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="sowknow",
    )
    op.create_index("ix_tasks_user_id", "tasks", ["user_id"], schema="sowknow")


def downgrade() -> None:
    op.drop_index("ix_tasks_user_id", table_name="tasks", schema="sowknow")
    op.drop_table("tasks", schema="sowknow")
