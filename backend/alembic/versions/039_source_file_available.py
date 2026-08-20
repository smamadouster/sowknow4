"""Add source_file_available flag to documents (additive).

Marks documents whose source binary is missing on disk so the download /
preview endpoints can return a clear 410 instead of a generic 404, and the
frontend can hide the download button.

The 3,485 documents imported 2026-01-22 → 2026-01-29 via a legacy flow carry
``file_path`` values under ``storage/documents/...`` (a retired layout). Their
binaries are not in any mounted volume nor in backups, so they are flagged
unavailable. New documents default to available.

Revision: 039_source_file_available
"""

from alembic import op
import sqlalchemy as sa

revision = "039_source_file_available"
down_revision = "038_learned_skills"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column(
            "source_file_available",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        schema="sowknow",
    )
    op.execute("UPDATE sowknow.documents SET source_file_available = false WHERE file_path LIKE 'storage/%'")


def downgrade() -> None:
    op.drop_column("documents", "source_file_available", schema="sowknow")
