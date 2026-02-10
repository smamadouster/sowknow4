"""Initial schema with documents, chat, and processing tables

Revision ID: 001
Revises:
Create Date: 2026-02-09

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create pgvector extension
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')

    # Create sowknow schema if not exists
    op.execute('CREATE SCHEMA IF NOT EXISTS sowknow')

    # Create documents table
    op.create_table(
        'documents',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('filename', sa.String(512), nullable=False),
        sa.Column('original_filename', sa.String(512), nullable=False),
        sa.Column('file_path', sa.String(1024), nullable=False),
        sa.Column('bucket', sa.Enum('public', 'confidential', name='documentbucket'), nullable=False, server_default='public'),
        sa.Column('status', sa.Enum('pending', 'uploading', 'processing', 'indexed', 'error', name='documentstatus'), nullable=False, server_default='pending'),
        sa.Column('size', sa.BigInteger(), nullable=False),
        sa.Column('mime_type', sa.String(256), nullable=False),
        sa.Column('language', sa.Enum('fr', 'en', 'multi', 'unknown', name='documentlanguage')),
        sa.Column('page_count', sa.Integer()),
        sa.Column('ocr_processed', sa.Boolean(), server_default='false'),
        sa.Column('embedding_generated', sa.Boolean(), server_default='false'),
        sa.Column('chunk_count', sa.Integer(), server_default='0'),
        sa.Column('metadata', postgresql.JSONB(), server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), onupdate=sa.text('now()'), nullable=False),
        schema='sowknow'
    )
    op.create_index('ix_documents_bucket_status', 'documents', ['bucket', 'status'], schema='sowknow')
    op.create_index('ix_documents_created_at', 'documents', ['created_at'], schema='sowknow')
    op.create_index('ix_documents_language', 'documents', ['language'], schema='sowknow')
    op.create_index('ix_documents_bucket', 'documents', ['bucket'], schema='sowknow')
    op.create_index('ix_documents_status', 'documents', ['status'], schema='sowknow')

    # Create document_tags table
    op.create_table(
        'document_tags',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('document_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('sowknow.documents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('tag_name', sa.String(256), nullable=False),
        sa.Column('tag_type', sa.String(100)),
        sa.Column('auto_generated', sa.Boolean(), server_default='false'),
        sa.Column('confidence_score', sa.Integer()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), onupdate=sa.text('now()'), nullable=False),
        schema='sowknow'
    )
    op.create_index('ix_document_tags_tag_name', 'document_tags', ['tag_name'], schema='sowknow')
    op.create_index('ix_document_tags_tag_type', 'document_tags', ['tag_type'], schema='sowknow')

    # Create document_chunks table with vector column for embeddings
    op.create_table(
        'document_chunks',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('document_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('sowknow.documents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('chunk_index', sa.Integer(), nullable=False),
        sa.Column('chunk_text', sa.Text(), nullable=False),
        sa.Column('embedding', postgresql.ARRAY(sa.Float(), dimensions=1024)),  # Vector for embeddings
        sa.Column('token_count', sa.Integer()),
        sa.Column('page_number', sa.Integer()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), onupdate=sa.text('now()'), nullable=False),
        schema='sowknow'
    )
    op.create_index('ix_document_chunks_document_id', 'document_chunks', ['document_id'], schema='sowknow')
    op.create_index('ix_document_chunks_chunk_index', 'document_chunks', ['document_id', 'chunk_index'], schema='sowknow')

    # Create chat_sessions table
    op.create_table(
        'chat_sessions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('sowknow.users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('title', sa.String(512), nullable=False),
        sa.Column('document_scope', postgresql.JSONB(), server_default='[]'),
        sa.Column('model_preference', sa.String(50)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), onupdate=sa.text('now()'), nullable=False),
        schema='sowknow'
    )

    # Create chat_messages table
    op.create_table(
        'chat_messages',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('session_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('sowknow.chat_sessions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('role', sa.Enum('user', 'assistant', 'system', name='messagerole'), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('llm_used', sa.Enum('kimi', 'ollama', name='llmprovider')),
        sa.Column('sources', postgresql.JSONB()),
        sa.Column('confidence_score', sa.Integer()),
        sa.Column('prompt_tokens', sa.Integer()),
        sa.Column('completion_tokens', sa.Integer()),
        sa.Column('total_tokens', sa.Integer()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), onupdate=sa.text('now()'), nullable=False),
        schema='sowknow'
    )

    # Create processing_queue table
    op.create_table(
        'processing_queue',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('document_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('sowknow.documents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('task_type', sa.Enum('ocr_processing', 'text_extraction', 'chunking', 'embedding_generation', 'indexing', name='tasktype'), nullable=False),
        sa.Column('status', sa.Enum('pending', 'in_progress', 'completed', 'failed', 'cancelled', name='taskstatus'), nullable=False, server_default='pending'),
        sa.Column('celery_task_id', sa.String(255)),
        sa.Column('started_at', sa.DateTime(timezone=True)),
        sa.Column('completed_at', sa.DateTime(timezone=True)),
        sa.Column('retry_count', sa.Integer(), server_default='0'),
        sa.Column('error_message', sa.Text()),
        sa.Column('error_details', sa.Text()),
        sa.Column('total_steps', sa.Integer()),
        sa.Column('completed_steps', sa.Integer(), server_default='0'),
        sa.Column('progress_percentage', sa.Integer(), server_default='0'),
        sa.Column('priority', sa.Integer(), server_default='5'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), onupdate=sa.text('now()'), nullable=False),
        schema='sowknow'
    )
    op.create_index('ix_processing_queue_status', 'processing_queue', ['status'], schema='sowknow')
    op.create_index('ix_processing_queue_celery_task_id', 'processing_queue', ['celery_task_id'], schema='sowknow')


def downgrade() -> None:
    # Drop tables in reverse order
    op.drop_table('processing_queue', schema='sowknow')
    op.drop_table('chat_messages', schema='sowknow')
    op.drop_table('chat_sessions', schema='sowknow')
    op.drop_table('document_chunks', schema='sowknow')
    op.drop_table('document_tags', schema='sowknow')
    op.drop_table('documents', schema='sowknow')

    # Drop enums
    op.execute('DROP TYPE IF EXISTS sowknow.documentbucket')
    op.execute('DROP TYPE IF EXISTS sowknow.documentstatus')
    op.execute('DROP TYPE IF EXISTS sowknow.documentlanguage')
    op.execute('DROP TYPE IF EXISTS sowknow.messagerole')
    op.execute('DROP TYPE IF EXISTS sowknow.llmprovider')
    op.execute('DROP TYPE IF EXISTS sowknow.tasktype')
    op.execute('DROP TYPE IF EXISTS sowknow.taskstatus')
