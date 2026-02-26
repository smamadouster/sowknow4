"""Add failed_celery_tasks dead-letter queue table

Revision ID: 007
Revises: 006
Create Date: 2026-02-25
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "failed_celery_tasks",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("task_name", sa.String(256), nullable=False),
        sa.Column("task_id", sa.String(256), nullable=False),
        sa.Column("args", postgresql.JSONB(), nullable=True),
        sa.Column("kwargs", postgresql.JSONB(), nullable=True),
        sa.Column("exception_type", sa.String(256), nullable=True),
        sa.Column("exception_message", sa.Text(), nullable=True),
        sa.Column("traceback", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "metadata", postgresql.JSONB(), nullable=True, server_default="{}"
        ),
        sa.Column(
            "failed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="sowknow",
    )
    op.create_index(
        "ix_failed_celery_tasks_task_name",
        "failed_celery_tasks",
        ["task_name"],
        schema="sowknow",
    )
    op.create_index(
        "ix_failed_celery_tasks_task_id",
        "failed_celery_tasks",
        ["task_id"],
        unique=True,
        schema="sowknow",
    )
    op.create_index(
        "ix_failed_celery_tasks_failed_at",
        "failed_celery_tasks",
        ["failed_at"],
        schema="sowknow",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_failed_celery_tasks_failed_at",
        table_name="failed_celery_tasks",
        schema="sowknow",
    )
    op.drop_index(
        "ix_failed_celery_tasks_task_id",
        table_name="failed_celery_tasks",
        schema="sowknow",
    )
    op.drop_index(
        "ix_failed_celery_tasks_task_name",
        table_name="failed_celery_tasks",
        schema="sowknow",
    )
    op.drop_table("failed_celery_tasks", schema="sowknow")
