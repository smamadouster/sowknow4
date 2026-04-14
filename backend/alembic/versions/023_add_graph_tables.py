"""Add knowledge graph tables (graph_nodes, graph_edges, entity_synonyms)

Revision ID: add_graph_tables_023
Revises: add_pipeline_stages_022
"""
from alembic import op
import sqlalchemy as sa

revision = "add_graph_tables_023"
down_revision = "add_pipeline_stages_022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Nodes ─────────────────────────────────────────────────────────────

    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS sowknow.graph_nodes (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            canonical_name TEXT NOT NULL,
            aliases       TEXT[] DEFAULT '{}',
            node_type     TEXT NOT NULL,
            language      TEXT DEFAULT 'fr',
            metadata      JSONB DEFAULT '{}',
            embedding     vector(1024),
            bucket        TEXT DEFAULT 'public' CHECK (bucket IN ('public', 'confidential')),
            created_at    TIMESTAMPTZ DEFAULT now()
        );
    """))

    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_graph_nodes_type "
        "ON sowknow.graph_nodes (node_type);"
    ))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_graph_nodes_bucket "
        "ON sowknow.graph_nodes (bucket);"
    ))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_graph_nodes_canonical "
        "ON sowknow.graph_nodes USING gin (to_tsvector('simple', canonical_name));"
    ))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_graph_nodes_aliases "
        "ON sowknow.graph_nodes USING gin (aliases);"
    ))
    # IVFFlat index — requires at least some rows to build. Create it only
    # if pgvector is available; skip silently if the extension is missing.
    op.execute(sa.text("""
        DO $$ BEGIN
            CREATE INDEX IF NOT EXISTS idx_graph_nodes_embedding
            ON sowknow.graph_nodes
            USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 50);
        EXCEPTION WHEN undefined_object THEN
            NULL;  -- pgvector not installed; index skipped
        END $$;
    """))

    # ── Edges ─────────────────────────────────────────────────────────────

    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS sowknow.graph_edges (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            source_id           UUID NOT NULL
                REFERENCES sowknow.graph_nodes(id) ON DELETE CASCADE,
            target_id           UUID NOT NULL
                REFERENCES sowknow.graph_nodes(id) ON DELETE CASCADE,
            edge_type           TEXT NOT NULL,
            confidence          REAL DEFAULT 0.5 CHECK (confidence BETWEEN 0 AND 1),
            extraction_method   TEXT NOT NULL,
            source_document_id  UUID,
            source_chunk_id     UUID,
            metadata            JSONB DEFAULT '{}',
            created_at          TIMESTAMPTZ DEFAULT now(),

            UNIQUE (source_id, target_id, edge_type, source_document_id)
        );
    """))

    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_graph_edges_source "
        "ON sowknow.graph_edges (source_id);"
    ))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_graph_edges_target "
        "ON sowknow.graph_edges (target_id);"
    ))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_graph_edges_type "
        "ON sowknow.graph_edges (edge_type);"
    ))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_graph_edges_conf "
        "ON sowknow.graph_edges (confidence);"
    ))

    # ── Entity synonyms (fast surface-form → canonical lookup) ────────────

    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS sowknow.entity_synonyms (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            surface_form  TEXT NOT NULL,
            canonical_id  UUID NOT NULL
                REFERENCES sowknow.graph_nodes(id) ON DELETE CASCADE,
            language      TEXT DEFAULT 'fr',
            UNIQUE (surface_form, canonical_id)
        );
    """))

    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS idx_entity_synonyms_surface "
        "ON sowknow.entity_synonyms (surface_form);"
    ))


def downgrade() -> None:
    op.execute(sa.text("DROP TABLE IF EXISTS sowknow.entity_synonyms;"))
    op.execute(sa.text("DROP TABLE IF EXISTS sowknow.graph_edges;"))
    op.execute(sa.text("DROP TABLE IF EXISTS sowknow.graph_nodes;"))
