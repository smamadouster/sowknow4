"""Agent Memory data-model foundation (draft v0.1 — docs/agent_memory/SPEC.md)

Additive only. Adds:

- ALTER chat_sessions: memory_enabled (nullable-safe, default false) so the
  distillation opt-in flag exists. No behavior change — off by default.
- CREATE memory_atoms (L1), memory_scenarios (L2), memory_profiles (L3),
  memory_asset_bindings.

All tables are new/empty — plain CREATE INDEX is safe (no CONCURRENTLY
needed). Every table carries its own `visibility` (default `private`) so
nothing leaks by default and the document ACL hot path (bucket on
document_chunks) is untouched.

Revision: 037_agent_memory
"""

from alembic import op
from sqlalchemy.dialects import postgresql
import sqlalchemy as sa

revision = "037_agent_memory"
down_revision = "036_search_vector_unaccent"
branch_labels = None
depends_on = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    # ------------------------------------------------------------------
    # chat_sessions.memory_enabled (additive, default false)
    # ------------------------------------------------------------------
    op.add_column(
        "chat_sessions",
        sa.Column(
            "memory_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        schema="sowknow",
    )

    # ------------------------------------------------------------------
    # memory_atoms (L1)
    # ------------------------------------------------------------------
    op.create_table(
        "memory_atoms",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Integer(), nullable=True, server_default="50"),
        sa.Column("source_message_ids", postgresql.JSONB(), nullable=True, server_default="[]"),
        sa.Column("source_session_ids", postgresql.JSONB(), nullable=True, server_default="[]"),
        sa.Column("entity_ids", postgresql.JSONB(), nullable=True, server_default="[]"),
        sa.Column("search_vector", postgresql.TSVECTOR(), nullable=True),
        sa.Column("visibility", sa.String(20), nullable=False, server_default="private"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["owner_id"], ["sowknow.users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="sowknow",
    )
    op.create_index(
        "ix_memory_atoms_user_status",
        "memory_atoms",
        ["owner_id", "status"],
        schema="sowknow",
    )
    op.create_index(
        "ix_memory_atoms_owner_kind",
        "memory_atoms",
        ["owner_id", "kind"],
        schema="sowknow",
    )
    op.create_index(
        "ix_memory_atoms_owner_id",
        "memory_atoms",
        ["owner_id"],
        schema="sowknow",
    )

    # ------------------------------------------------------------------
    # memory_scenarios (L2)
    # ------------------------------------------------------------------
    op.create_table(
        "memory_scenarios",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("scope", sa.String(255), nullable=True),
        sa.Column("atom_ids", postgresql.JSONB(), nullable=True, server_default="[]"),
        sa.Column("source_session_ids", postgresql.JSONB(), nullable=True, server_default="[]"),
        sa.Column("search_vector", postgresql.TSVECTOR(), nullable=True),
        sa.Column("visibility", sa.String(20), nullable=False, server_default="private"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["owner_id"], ["sowknow.users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="sowknow",
    )
    op.create_index(
        "ix_memory_scenarios_user_status",
        "memory_scenarios",
        ["owner_id", "status"],
        schema="sowknow",
    )
    op.create_index(
        "ix_memory_scenarios_owner_id",
        "memory_scenarios",
        ["owner_id"],
        schema="sowknow",
    )

    # ------------------------------------------------------------------
    # memory_profiles (L3)
    # ------------------------------------------------------------------
    op.create_table(
        "memory_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("persona", postgresql.JSONB(), nullable=True, server_default="{}"),
        sa.Column("stable_patterns", postgresql.JSONB(), nullable=True, server_default="[]"),
        sa.Column("version", sa.Integer(), nullable=True, server_default="1"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["owner_id"], ["sowknow.users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id"),
        schema="sowknow",
    )

    # ------------------------------------------------------------------
    # memory_asset_bindings
    # ------------------------------------------------------------------
    op.create_table(
        "memory_asset_bindings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_scope", sa.String(100), nullable=False),
        sa.Column("asset_type", sa.String(20), nullable=False),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("usage_count", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["owner_id"], ["sowknow.users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="sowknow",
    )
    op.create_index(
        "ix_memory_bindings_scope",
        "memory_asset_bindings",
        ["agent_scope", "asset_type", "asset_id"],
        schema="sowknow",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_memory_bindings_scope",
        table_name="memory_asset_bindings",
        schema="sowknow",
    )
    op.drop_table("memory_asset_bindings", schema="sowknow")
    op.drop_table("memory_profiles", schema="sowknow")
    op.drop_index(
        "ix_memory_scenarios_owner_id",
        table_name="memory_scenarios",
        schema="sowknow",
    )
    op.drop_index(
        "ix_memory_scenarios_user_status",
        table_name="memory_scenarios",
        schema="sowknow",
    )
    op.drop_table("memory_scenarios", schema="sowknow")
    op.drop_index(
        "ix_memory_atoms_owner_id",
        table_name="memory_atoms",
        schema="sowknow",
    )
    op.drop_index(
        "ix_memory_atoms_owner_kind",
        table_name="memory_atoms",
        schema="sowknow",
    )
    op.drop_index(
        "ix_memory_atoms_user_status",
        table_name="memory_atoms",
        schema="sowknow",
    )
    op.drop_table("memory_atoms", schema="sowknow")
    op.drop_column("chat_sessions", "memory_enabled", schema="sowknow")
