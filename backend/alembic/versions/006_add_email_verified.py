"""Add email_verified to users

Revision ID: 006
Revises: add_uploaded_by_001
Create Date: 2026-02-25
"""
from alembic import op
import sqlalchemy as sa

revision = '006'
down_revision = 'add_uploaded_by_001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column('email_verified', sa.Boolean(), nullable=False, server_default='false'),
        schema='sowknow'
    )


def downgrade() -> None:
    op.drop_column('users', 'email_verified', schema='sowknow')
