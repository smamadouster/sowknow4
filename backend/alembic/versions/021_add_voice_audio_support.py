"""Add voice/audio support columns and note_audio table

Revision ID: 021
Revises: 020
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add audio columns to documents table
    op.add_column("documents", sa.Column("audio_file_path", sa.Text(), nullable=True), schema="sowknow")
    op.add_column("documents", sa.Column("audio_duration_seconds", sa.Float(), nullable=True), schema="sowknow")
    op.add_column("documents", sa.Column("detected_language", sa.String(5), nullable=True), schema="sowknow")

    # Create note_audio table
    op.create_table(
        "note_audio",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("note_id", UUID(as_uuid=True), sa.ForeignKey("sowknow.notes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("transcript", sa.Text(), nullable=True),
        sa.Column("detected_language", sa.String(5), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        schema="sowknow",
    )
    op.create_index("idx_note_audio_note_id", "note_audio", ["note_id"], schema="sowknow")


def downgrade() -> None:
    op.drop_index("idx_note_audio_note_id", table_name="note_audio", schema="sowknow")
    op.drop_table("note_audio", schema="sowknow")
    op.drop_column("documents", "detected_language", schema="sowknow")
    op.drop_column("documents", "audio_duration_seconds", schema="sowknow")
    op.drop_column("documents", "audio_file_path", schema="sowknow")
