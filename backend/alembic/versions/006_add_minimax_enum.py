"""Add minimax, openai, anthropic, mistral values to llmprovider enum

Revision ID: add_minimax_enum_006
Revises: add_vector_fts_005
Create Date: 2026-02-26

P0-5: Extends the llmprovider enum with the external provider values needed
for document analysis routing (OpenRouter providers).
"""

from alembic import op


revision = "add_minimax_enum_006"
down_revision = "add_vector_fts_005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for value in ("minimax", "openai", "anthropic", "mistral"):
        op.execute(
            f"ALTER TYPE sowknow.llmprovider ADD VALUE IF NOT EXISTS '{value}'"
        )


def downgrade() -> None:
    # PostgreSQL does not support removing enum values without full type recreation.
    pass
