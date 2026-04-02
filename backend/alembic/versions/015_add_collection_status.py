"""Add collection status and build_error columns

Revision ID: add_collection_status_015
Revises: add_articles_014
Create Date: 2026-04-02
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "add_collection_status_015"
down_revision = "add_articles_014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create the enum type first (PostgreSQL requires this before column use)
    collection_status = sa.Enum("building", "ready", "failed", name="collectionstatus")
    collection_status.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "collections",
        sa.Column(
            "status",
            sa.Enum("building", "ready", "failed", name="collectionstatus", create_type=False),
            nullable=False,
            server_default="ready",
        ),
        schema="sowknow",
    )
    op.add_column(
        "collections",
        sa.Column("build_error", sa.String(), nullable=True),
        schema="sowknow",
    )


def downgrade() -> None:
    op.drop_column("collections", "build_error", schema="sowknow")
    op.drop_column("collections", "status", schema="sowknow")
    # Drop the enum type
    sa.Enum(name="collectionstatus").drop(op.get_bind(), checkfirst=True)
