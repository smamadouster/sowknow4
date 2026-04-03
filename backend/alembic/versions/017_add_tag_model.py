"""Add generalized Tag model"""

from alembic import op
import sqlalchemy as sa

revision = "add_tags_017"
down_revision = "add_article_id_016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tags",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("tag_name", sa.String(255), nullable=False),
        sa.Column("tag_type", sa.Enum("topic", "entity", "project", "importance", "custom",
                                       name="tagtype", schema="sowknow"), nullable=False),
        sa.Column("target_type", sa.Enum("document", "bookmark", "note", "space",
                                          name="targettype", schema="sowknow"), nullable=False),
        sa.Column("target_id", sa.CHAR(36), nullable=False),
        sa.Column("auto_generated", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("confidence_score", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        schema="sowknow",
    )
    op.create_index("ix_tags_target", "tags", ["target_type", "target_id"], schema="sowknow")
    op.create_index("ix_tags_name", "tags", ["tag_name"], schema="sowknow")
    op.create_index("ix_tags_type_name", "tags", ["tag_type", "tag_name"], schema="sowknow")


def downgrade() -> None:
    op.drop_table("tags", schema="sowknow")
    op.execute("DROP TYPE IF EXISTS sowknow.tagtype")
    op.execute("DROP TYPE IF EXISTS sowknow.targettype")
