"""Add composite indexes for pipeline sweeper queries.

Revision ID: 028_add_pipeline_sweeper_indexes
Revises: 027_add_smart_folder_v2_models
Create Date: 2026-04-29

Adds:
  - ix_pipeline_stages_stage_status_started on (stage, status, started_at)
  - ix_pipeline_stages_stage_status on (stage, status)

These speed up the sweeper queries that filter by stage + status
without scanning the full status index.
"""

from alembic import op
import sqlalchemy as sa

revision = "028_add_pipeline_sweeper_indexes"
down_revision = "027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_pipeline_stages_stage_status_started",
        "pipeline_stages",
        ["stage", "status", "started_at"],
        schema="sowknow",
    )
    op.create_index(
        "ix_pipeline_stages_stage_status",
        "pipeline_stages",
        ["stage", "status"],
        schema="sowknow",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_pipeline_stages_stage_status_started",
        table_name="pipeline_stages",
        schema="sowknow",
    )
    op.drop_index(
        "ix_pipeline_stages_stage_status",
        table_name="pipeline_stages",
        schema="sowknow",
    )
