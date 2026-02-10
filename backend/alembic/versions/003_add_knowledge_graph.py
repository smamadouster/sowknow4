"""Add Knowledge Graph tables for Phase 3

Revision ID: 003
Revises: 002
Create Date: February 10, 2026

This migration adds the Knowledge Graph feature for Phase 3,
including entities, relationships, mentions, and timeline events.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '003'
down_revision = '002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create enums for knowledge graph
    entitytype = sa.Enum('person', 'organization', 'location', 'concept', 'event', 'date', 'product', 'project', 'other', name='entitytype')
    entitytype.create(op.get_bind(), checkfirst=True)

    relationtype = sa.Enum('works_at', 'founded', 'ceo_of', 'employee_of', 'client_of', 'partner_of', 'related_to', 'mentioned_with', 'located_in', 'happened_on', 'created_on', 'references', 'part_of', 'owned_by', 'member_of', 'other', name='relationtype')
    relationtype.create(op.get_bind(), checkfirst=True)

    # Create entities table
    op.create_table(
        'entities',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('name', sa.String(512), nullable=False),
        sa.Column('entity_type', entitytype, nullable=False),
        sa.Column('canonical_id', sa.String(256)),
        sa.Column('aliases', postgresql.JSONB(), server_default='[]'),
        sa.Column('attributes', postgresql.JSONB(), server_default='{}'),
        sa.Column('confidence_score', sa.Integer(), server_default='50'),
        sa.Column('first_seen_at', sa.Date()),
        sa.Column('last_seen_at', sa.Date()),
        sa.Column('document_count', sa.Integer(), server_default='0'),
        sa.Column('relationship_count', sa.Integer(), server_default='0'),
        sa.Column('x_position', sa.Float()),
        sa.Column('y_position', sa.Float()),
        sa.Column('color', sa.String(7)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), onupdate=sa.text('now()'), nullable=False),
        schema='sowknow'
    )
    op.create_index('ix_entities_name', 'entities', ['name'], schema='sowknow')
    op.create_index('ix_entities_type', 'entities', ['entity_type'], schema='sowknow')
    op.create_index('ix_entities_name_type', 'entities', ['name', 'entity_type'], schema='sowknow')

    # Create entity_relationships table
    op.create_table(
        'entity_relationships',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('source_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('sowknow.entities.id', ondelete='CASCADE'), nullable=False),
        sa.Column('target_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('sowknow.entities.id', ondelete='CASCADE'), nullable=False),
        sa.Column('relation_type', relationtype, nullable=False),
        sa.Column('confidence_score', sa.Integer(), server_default='50'),
        sa.Column('attributes', postgresql.JSONB(), server_default='{}'),
        sa.Column('document_count', sa.Integer(), server_default='0'),
        sa.Column('first_seen_at', sa.Date()),
        sa.Column('last_seen_at', sa.Date()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), onupdate=sa.text('now()'), nullable=False),
        schema='sowknow'
    )
    op.create_index('ix_entity_relationships_source', 'entity_relationships', ['source_id'], schema='sowknow')
    op.create_index('ix_entity_relationships_target', 'entity_relationships', ['target_id'], schema='sowknow')
    op.create_index('ix_entity_relationships_type', 'entity_relationships', ['relation_type'], schema='sowknow')

    # Create entity_mentions table
    op.create_table(
        'entity_mentions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('entity_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('sowknow.entities.id', ondelete='CASCADE'), nullable=False),
        sa.Column('document_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('sowknow.documents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('chunk_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('sowknow.document_chunks.id', ondelete='SET NULL')),
        sa.Column('context_text', sa.Text()),
        sa.Column('page_number', sa.Integer()),
        sa.Column('position_start', sa.Integer()),
        sa.Column('position_end', sa.Integer()),
        sa.Column('confidence_score', sa.Integer(), server_default='50'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), onupdate=sa.text('now()'), nullable=False),
        schema='sowknow'
    )
    op.create_index('ix_entity_mentions_entity', 'entity_mentions', ['entity_id'], schema='sowknow')
    op.create_index('ix_entity_mentions_document', 'entity_mentions', ['document_id'], schema='sowknow')
    op.create_index('ix_entity_mentions_entity_document', 'entity_mentions', ['entity_id', 'document_id'], schema='sowknow')

    # Create timeline_events table
    op.create_table(
        'timeline_events',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('title', sa.String(512), nullable=False),
        sa.Column('description', sa.Text()),
        sa.Column('event_date', sa.Date(), nullable=False),
        sa.Column('event_date_precision', sa.String(20)),
        sa.Column('entity_ids', postgresql.JSONB(), server_default='[]'),
        sa.Column('document_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('sowknow.documents.id', ondelete='SET NULL'), nullable=False),
        sa.Column('event_type', sa.String(100)),
        sa.Column('importance', sa.Integer(), server_default='50'),
        sa.Column('color', sa.String(7)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), onupdate=sa.text('now()'), nullable=False),
        schema='sowknow'
    )
    op.create_index('ix_timeline_events_date', 'timeline_events', ['event_date'], schema='sowknow')
    op.create_index('ix_timeline_events_type', 'timeline_events', ['event_type'], schema='sowknow')


def downgrade() -> None:
    # Drop tables in reverse order
    op.drop_table('timeline_events', schema='sowknow')
    op.drop_table('entity_mentions', schema='sowknow')
    op.drop_table('entity_relationships', schema='sowknow')
    op.drop_table('entities', schema='sowknow')

    # Drop enums
    op.execute('DROP TYPE IF EXISTS sowknow.relationtype')
    op.execute('DROP TYPE IF EXISTS sowknow.entitytype')
