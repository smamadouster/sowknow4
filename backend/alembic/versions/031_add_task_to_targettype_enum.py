"""Add task to targettype enum.

Revision ID: 031_add_task_to_targettype_enum
Revises: 030_add_tasks
Create Date: 2026-05-11

Adds 'task' to the sowknow.targettype enum so task tags can be stored.
"""

from alembic import op

revision = "031_add_task_to_targettype_enum"
down_revision = "030_add_tasks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE sowknow.targettype ADD VALUE 'task'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values.
    # To downgrade you would need to recreate the enum, which is destructive.
    # Skipping for safety.
    pass
