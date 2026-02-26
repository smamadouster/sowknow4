"""Add IVFFlat vector index, tsvector_content generated column, GIN index,
and semantic_search / hybrid_search SQL functions.

Revision ID: add_vector_fts_005
Revises: fix_vector_type_004
Create Date: 2026-02-26

P0-2: IVFFlat index on document_chunks.embedding
P0-3: tsvector_content GENERATED STORED column + GIN index
P0-2/P0-3: semantic_search() and hybrid_search() functions
"""

from alembic import op


revision = "add_vector_fts_005"
down_revision = "fix_vector_type_004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # IVFFlat index on embedding
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_document_chunks_embedding_ivfflat
          ON sowknow.document_chunks
          USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)
    """)

    # tsvector_content generated column
    op.execute("""
        ALTER TABLE sowknow.document_chunks
          ADD COLUMN IF NOT EXISTS tsvector_content tsvector
            GENERATED ALWAYS AS (
              to_tsvector('french', coalesce(chunk_text, ''))
            ) STORED
    """)

    # GIN index on tsvector_content
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_document_chunks_tsvector
          ON sowknow.document_chunks USING gin (tsvector_content)
    """)

    # semantic_search function
    op.execute("""
        CREATE OR REPLACE FUNCTION sowknow.semantic_search(
            query_embedding vector(1024),
            match_count     int     DEFAULT 10,
            match_threshold float   DEFAULT 0.5
        )
        RETURNS TABLE (
            chunk_id    uuid,
            document_id uuid,
            chunk_text  text,
            similarity  float
        )
        LANGUAGE sql STABLE
        AS $func$
            SELECT
                dc.id AS chunk_id,
                dc.document_id,
                dc.chunk_text,
                (1 - (dc.embedding <=> query_embedding))::float AS similarity
            FROM sowknow.document_chunks dc
            WHERE dc.embedding IS NOT NULL
              AND (1 - (dc.embedding <=> query_embedding)) >= match_threshold
            ORDER BY dc.embedding <=> query_embedding
            LIMIT match_count;
        $func$
    """)

    # hybrid_search function
    op.execute("""
        CREATE OR REPLACE FUNCTION sowknow.hybrid_search(
            query_embedding  vector(1024),
            query_text       text,
            match_count      int     DEFAULT 10,
            match_threshold  float   DEFAULT 0.3,
            vector_weight    float   DEFAULT 0.7,
            fts_weight       float   DEFAULT 0.3
        )
        RETURNS TABLE (
            chunk_id       uuid,
            document_id    uuid,
            chunk_text     text,
            combined_score float
        )
        LANGUAGE sql STABLE
        AS $func$
            SELECT
                dc.id AS chunk_id,
                dc.document_id,
                dc.chunk_text,
                (
                    vector_weight * CASE WHEN dc.embedding IS NOT NULL
                        THEN (1 - (dc.embedding <=> query_embedding)) ELSE 0 END
                  + fts_weight   * ts_rank(
                        coalesce(dc.tsvector_content, to_tsvector('')),
                        websearch_to_tsquery('french', query_text))
                )::float AS combined_score
            FROM sowknow.document_chunks dc
            WHERE (dc.embedding IS NOT NULL)
               OR (dc.tsvector_content @@ websearch_to_tsquery('french', query_text))
            ORDER BY combined_score DESC
            LIMIT match_count;
        $func$
    """)


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS sowknow.hybrid_search CASCADE")
    op.execute("DROP FUNCTION IF EXISTS sowknow.semantic_search CASCADE")
    op.execute("DROP INDEX IF EXISTS sowknow.ix_document_chunks_tsvector")
    op.execute(
        "ALTER TABLE sowknow.document_chunks "
        "DROP COLUMN IF EXISTS tsvector_content"
    )
    op.execute(
        "DROP INDEX IF EXISTS sowknow.ix_document_chunks_embedding_ivfflat"
    )
