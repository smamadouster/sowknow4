"""Add uploaded_by to documents

Revision ID: add_uploaded_by_001
Revises: 004
Create Date: 2026-02-25
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'add_uploaded_by_001'
down_revision = '004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'documents',
        sa.Column('uploaded_by', postgresql.UUID(as_uuid=True), nullable=True),
        schema='sowknow'
    )
    op.create_index(
        'ix_documents_uploaded_by',
        'documents',
        ['uploaded_by'],
        schema='sowknow'
    )


def downgrade() -> None:
    op.drop_index('ix_documents_uploaded_by', table_name='documents', schema='sowknow')
    op.drop_column('documents', 'uploaded_by', schema='sowknow')
