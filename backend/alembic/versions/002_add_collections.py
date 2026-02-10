"""Add Smart Collections tables

Revision ID: 002
Revises: 001
Create Date: 2026-02-10

This migration adds the Smart Collections feature, allowing users to create
collections from natural language queries with AI-generated summaries and
follow-up Q&A capabilities.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create enums for collections
    collectionvisibility = sa.Enum('private', 'shared', 'public', name='collectionvisibility')
    collectionvisibility.create(op.get_bind(), checkfirst=True)

    collectiontype = sa.Enum('smart', 'manual', 'folder', name='collectiontype')
    collectiontype.create(op.get_bind(), checkfirst=True)

    # Create collections table
    op.create_table(
        'collections',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('sowknow.users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(512), nullable=False),
        sa.Column('description', sa.Text()),
        sa.Column('collection_type', collectiontype, nullable=False, server_default='smart'),
        sa.Column('visibility', collectionvisibility, nullable=False, server_default='private'),
        sa.Column('query', sa.Text(), nullable=False),
        sa.Column('parsed_intent', postgresql.JSONB(), server_default='{}'),
        sa.Column('ai_summary', sa.Text()),
        sa.Column('ai_keywords', postgresql.JSONB(), server_default='[]'),
        sa.Column('ai_entities', postgresql.JSONB(), server_default='[]'),
        sa.Column('filter_criteria', postgresql.JSONB(), server_default='{}'),
        sa.Column('document_count', sa.Integer(), server_default='0'),
        sa.Column('last_refreshed_at', sa.String()),
        sa.Column('chat_session_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('sowknow.chat_sessions.id', ondelete='SET NULL')),
        sa.Column('cache_key', sa.String(256)),
        sa.Column('is_pinned', sa.Boolean(), server_default='false'),
        sa.Column('is_favorite', sa.Boolean(), server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), onupdate=sa.text('now()'), nullable=False),
        schema='sowknow'
    )
    op.create_index('ix_collections_user_id', 'collections', ['user_id'], schema='sowknow')
    op.create_index('ix_collections_visibility_pinned', 'collections', ['visibility', 'is_pinned'], schema='sowknow')
    op.create_index('ix_collections_created_at', 'collections', ['created_at'], schema='sowknow')
    op.create_index('ix_collections_type', 'collections', ['collection_type'], schema='sowknow')
    op.create_index('ix_collections_name', 'collections', ['name'], schema='sowknow')

    # Create collection_items table
    op.create_table(
        'collection_items',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('collection_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('sowknow.collections.id', ondelete='CASCADE'), nullable=False),
        sa.Column('document_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('sowknow.documents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('relevance_score', sa.Integer(), server_default='50'),
        sa.Column('order_index', sa.Integer(), server_default='0'),
        sa.Column('notes', sa.Text()),
        sa.Column('is_highlighted', sa.Boolean(), server_default='false'),
        sa.Column('added_by', sa.String(256)),
        sa.Column('added_reason', sa.Text()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), onupdate=sa.text('now()'), nullable=False),
        schema='sowknow'
    )
    op.create_index('ix_collection_items_collection_id', 'collection_items', ['collection_id'], schema='sowknow')
    op.create_index('ix_collection_items_document_id', 'collection_items', ['document_id'], schema='sowknow')
    op.create_index('ix_collection_items_relevance', 'collection_items', ['collection_id', 'relevance_score'], schema='sowknow')

    # Create collection_chat_sessions table
    op.create_table(
        'collection_chat_sessions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('collection_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('sowknow.collections.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('sowknow.users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('session_name', sa.String(512)),
        sa.Column('message_count', sa.Integer(), server_default='0'),
        sa.Column('llm_used', sa.String(50)),
        sa.Column('total_tokens_used', sa.Integer(), server_default='0'),
        sa.Column('cache_hits', sa.Integer(), server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), onupdate=sa.text('now()'), nullable=False),
        schema='sowknow'
    )
    op.create_index('ix_collection_chat_sessions_collection_id', 'collection_chat_sessions', ['collection_id'], schema='sowknow')
    op.create_index('ix_collection_chat_sessions_user_id', 'collection_chat_sessions', ['user_id'], schema='sowknow')

    # Update chat_sessions table to add collection relationship
    # Note: SQLite doesn't support ALTER TABLE with ADD COLUMN in a transaction
    # but PostgreSQL does, so this should work
    try:
        op.add_column(
            'chat_sessions',
            sa.Column('collection_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('sowknow.collections.id', ondelete='SET NULL')),
            schema='sowknow'
        )
    except Exception:
        # Column might already exist in some cases
        pass


def downgrade() -> None:
    # Drop tables in reverse order
    op.drop_table('collection_chat_sessions', schema='sowknow')
    op.drop_table('collection_items', schema='sowknow')
    op.drop_table('collections', schema='sowknow')

    # Remove collection_id from chat_sessions if it exists
    try:
        op.drop_column('chat_sessions', 'collection_id', schema='sowknow')
    except Exception:
        pass

    # Drop enums
    op.execute('DROP TYPE IF EXISTS sowknow.collectionvisibility')
    op.execute('DROP TYPE IF EXISTS sowknow.collectiontype')
