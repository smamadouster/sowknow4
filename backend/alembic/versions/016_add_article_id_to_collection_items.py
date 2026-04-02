"""Add article_id to collection_items

Revision ID: add_article_id_016
Revises: add_collection_status_015
Create Date: 2026-04-02
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision = "add_article_id_016"
down_revision = "add_collection_status_015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "collection_items",
        sa.Column("article_id", UUID(as_uuid=True), nullable=True),
        schema="sowknow",
    )
    op.create_index(
        "ix_collection_items_article_id",
        "collection_items",
        ["article_id"],
        schema="sowknow",
    )
    op.create_foreign_key(
        "fk_collection_items_article_id",
        "collection_items",
        "articles",
        ["article_id"],
        ["id"],
        source_schema="sowknow",
        referent_schema="sowknow",
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_collection_items_article_id",
        "collection_items",
        schema="sowknow",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_collection_items_article_id",
        table_name="collection_items",
        schema="sowknow",
    )
    op.drop_column("collection_items", "article_id", schema="sowknow")
