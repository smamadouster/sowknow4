"""Learned skills (additive) — see docs/agent_memory/SPEC.md extension.

Adds a single new empty table (memory_skills) storing runbook skills
distilled from real work (collection runs / resolved incidents). Additive
only; plain CREATE INDEX is safe (no CONCURRENTLY needed).

Revision: 038_learned_skills
"""

from alembic import op
from sqlalchemy.dialects import postgresql
import sqlalchemy as sa

revision = "038_learned_skills"
down_revision = "037_agent_memory"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "memory_skills",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("trigger", sa.Text(), nullable=False),
        sa.Column("steps", postgresql.JSONB(), nullable=True, server_default="[]"),
        sa.Column("validation", postgresql.JSONB(), nullable=True, server_default="[]"),
        sa.Column("source_type", sa.String(30), nullable=False),
        sa.Column("source_ref", sa.String(255), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("version", sa.Integer(), nullable=True, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["sowknow.users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="sowknow",
    )
    op.create_index(
        "ix_memory_skills_status",
        "memory_skills",
        ["status"],
        schema="sowknow",
    )
    op.create_index(
        "ix_memory_skills_owner_id",
        "memory_skills",
        ["owner_id"],
        schema="sowknow",
    )


def downgrade() -> None:
    op.drop_index("ix_memory_skills_owner_id", table_name="memory_skills", schema="sowknow")
    op.drop_index("ix_memory_skills_status", table_name="memory_skills", schema="sowknow")
    op.drop_table("memory_skills", schema="sowknow")
