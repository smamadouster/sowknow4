"""Add Smart Folder v2 models.

Revision ID: 027_add_smart_folder_v2_models
Revises: 026_add_search_feedback
Create Date: 2026-04-27

Creates:
  - smart_folders (refactored)
  - smart_folder_reports
  - milestones
  - pattern_insights

Drops the old smart_folders table if it still exists (it was never
used by the application and has no data).
"""

from alembic import op
from sqlalchemy.dialects import postgresql
import sqlalchemy as sa


revision = "027"
down_revision = "026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop the old unused smart_folders table if it exists
    op.execute("DROP TABLE IF EXISTS sowknow.smart_folders CASCADE")

    # Create new smart_folders table
    op.create_table(
        "smart_folders",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(512), nullable=False, default=""),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("relationship_type", sa.String(50), nullable=True),
        sa.Column("time_range_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("time_range_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("focus_aspects", postgresql.JSONB(), nullable=True, server_default="[]"),
        sa.Column("status", sa.String(50), nullable=False, server_default="draft"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["sowknow.users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["entity_id"], ["sowknow.entities.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        schema="sowknow",
    )
    op.create_index("ix_smart_folders_user_id", "smart_folders", ["user_id"], schema="sowknow")
    op.create_index("ix_smart_folders_entity_id", "smart_folders", ["entity_id"], schema="sowknow")
    op.create_index("ix_smart_folders_status", "smart_folders", ["status"], schema="sowknow")

    # Create smart_folder_reports table
    op.create_table(
        "smart_folder_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("smart_folder_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("generated_content", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("source_asset_ids", postgresql.JSONB(), nullable=True, server_default="[]"),
        sa.Column("citation_index", postgresql.JSONB(), nullable=True, server_default="{}"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("refinement_query", sa.Text(), nullable=True),
        sa.Column("generator_version", sa.String(50), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["smart_folder_id"], ["sowknow.smart_folders.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="sowknow",
    )
    op.create_index(
        "ix_smart_folder_reports_smart_folder_id",
        "smart_folder_reports",
        ["smart_folder_id"],
        schema="sowknow",
    )

    # Create milestones table
    op.create_table(
        "milestones",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("date_precision", sa.String(20), nullable=True, server_default="exact"),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("linked_asset_ids", postgresql.JSONB(), nullable=True, server_default="[]"),
        sa.Column("importance", sa.Integer(), nullable=True, server_default="50"),
        sa.Column("extracted_by", sa.String(50), nullable=True, server_default="manual"),
        sa.Column("confidence", sa.Integer(), nullable=True, server_default="100"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["entity_id"], ["sowknow.entities.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="sowknow",
    )
    op.create_index("ix_milestones_entity_id", "milestones", ["entity_id"], schema="sowknow")
    op.create_index("ix_milestones_date", "milestones", ["date"], schema="sowknow")
    op.create_index(
        "ix_milestones_entity_date", "milestones", ["entity_id", "date"], schema="sowknow"
    )

    # Create pattern_insights table
    op.create_table(
        "pattern_insights",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "insight_type",
            sa.Enum("pattern", "trend", "issue", "learning", name="patterninsighttype"),
            nullable=False,
        ),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("linked_asset_ids", postgresql.JSONB(), nullable=True, server_default="[]"),
        sa.Column("confidence", sa.Integer(), nullable=True, server_default="50"),
        sa.Column("time_range_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("time_range_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("extracted_by", sa.String(50), nullable=True, server_default="manual"),
        sa.Column("trend_data", postgresql.JSONB(), nullable=True, server_default="{}"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["entity_id"], ["sowknow.entities.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="sowknow",
    )
    op.create_index(
        "ix_pattern_insights_entity_id", "pattern_insights", ["entity_id"], schema="sowknow"
    )
    op.create_index(
        "ix_pattern_insights_type", "pattern_insights", ["insight_type"], schema="sowknow"
    )
    op.create_index(
        "ix_pattern_insights_entity_type",
        "pattern_insights",
        ["entity_id", "insight_type"],
        schema="sowknow",
    )


def downgrade() -> None:
    op.drop_table("pattern_insights", schema="sowknow")
    op.drop_table("milestones", schema="sowknow")
    op.drop_table("smart_folder_reports", schema="sowknow")
    op.drop_table("smart_folders", schema="sowknow")

    # Recreate the old smart_folders table for downgrade compatibility
    op.create_table(
        "smart_folders",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("collection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(512), nullable=False, default=""),
        sa.Column("rule_config", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("auto_update", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["collection_id"], ["sowknow.collections.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="sowknow",
    )
    op.create_index(
        "ix_smart_folders_collection_id", "smart_folders", ["collection_id"], schema="sowknow"
    )
