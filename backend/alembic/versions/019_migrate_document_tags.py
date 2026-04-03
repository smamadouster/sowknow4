"""Migrate DocumentTag data to Tag table"""

from alembic import op

revision = "migrate_document_tags_019"
down_revision = "add_bookmarks_notes_spaces_018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO sowknow.tags (id, tag_name, tag_type, target_type, target_id, auto_generated, confidence_score, created_at)
        SELECT
            id,
            tag_name,
            COALESCE(tag_type, 'custom'),
            'document',
            document_id,
            COALESCE(auto_generated, false),
            confidence_score,
            COALESCE(created_at, NOW())
        FROM sowknow.document_tags
        WHERE document_id IS NOT NULL
        ON CONFLICT DO NOTHING
    """)


def downgrade() -> None:
    op.execute("DELETE FROM sowknow.tags WHERE target_type = 'document'")
