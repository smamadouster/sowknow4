"""Add bookmarks, notes, spaces, space_items, space_rules tables"""

from alembic import op
import sqlalchemy as sa

revision = "add_bookmarks_notes_spaces_018"
down_revision = "add_tags_017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Bookmarks
    op.create_table(
        "bookmarks",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("user_id", sa.CHAR(36), sa.ForeignKey("sowknow.users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("favicon_url", sa.String(2048), nullable=True),
        sa.Column("bucket", sa.Enum("public", "confidential", name="bookmarkbucket", schema="sowknow"), nullable=False, server_default="public"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        schema="sowknow",
    )
    op.create_index("ix_bookmarks_user_id", "bookmarks", ["user_id"], schema="sowknow")

    # Notes
    op.create_table(
        "notes",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("user_id", sa.CHAR(36), sa.ForeignKey("sowknow.users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("bucket", sa.Enum("public", "confidential", name="notebucket", schema="sowknow"), nullable=False, server_default="public"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        schema="sowknow",
    )
    op.create_index("ix_notes_user_id", "notes", ["user_id"], schema="sowknow")

    # Spaces
    op.create_table(
        "spaces",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("user_id", sa.CHAR(36), sa.ForeignKey("sowknow.users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(512), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("icon", sa.String(64), nullable=True),
        sa.Column("bucket", sa.Enum("public", "confidential", name="spacebucket", schema="sowknow"), nullable=False, server_default="public"),
        sa.Column("is_pinned", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        schema="sowknow",
    )
    op.create_index("ix_spaces_user_id", "spaces", ["user_id"], schema="sowknow")

    # Space Items
    op.create_table(
        "space_items",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("space_id", sa.CHAR(36), sa.ForeignKey("sowknow.spaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("item_type", sa.Enum("document", "bookmark", "note", name="spaceitemtype", schema="sowknow"), nullable=False),
        sa.Column("document_id", sa.CHAR(36), sa.ForeignKey("sowknow.documents.id", ondelete="CASCADE"), nullable=True),
        sa.Column("bookmark_id", sa.CHAR(36), sa.ForeignKey("sowknow.bookmarks.id", ondelete="CASCADE"), nullable=True),
        sa.Column("note_id", sa.CHAR(36), sa.ForeignKey("sowknow.notes.id", ondelete="CASCADE"), nullable=True),
        sa.Column("added_by", sa.String(16), nullable=False, server_default="user"),
        sa.Column("added_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("is_excluded", sa.Boolean(), nullable=False, server_default="false"),
        schema="sowknow",
    )
    op.create_index("ix_space_items_space_id", "space_items", ["space_id"], schema="sowknow")

    # Space Rules
    op.create_table(
        "space_rules",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("space_id", sa.CHAR(36), sa.ForeignKey("sowknow.spaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rule_type", sa.Enum("tag", "keyword", name="spaceruletype", schema="sowknow"), nullable=False),
        sa.Column("rule_value", sa.String(512), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        schema="sowknow",
    )
    op.create_index("ix_space_rules_space_id", "space_rules", ["space_id"], schema="sowknow")


def downgrade() -> None:
    op.drop_table("space_rules", schema="sowknow")
    op.drop_table("space_items", schema="sowknow")
    op.drop_table("spaces", schema="sowknow")
    op.drop_table("notes", schema="sowknow")
    op.drop_table("bookmarks", schema="sowknow")
    for enum_name in ["bookmarkbucket", "notebucket", "spacebucket", "spaceitemtype", "spaceruletype"]:
        op.execute(f"DROP TYPE IF EXISTS sowknow.{enum_name}")
