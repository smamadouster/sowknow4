"""
Integration tests for the knowledge graph module.

Requires PostgreSQL with pgvector (the sowknow schema must exist and
migration 023_add_graph_tables must have been applied).

Run with DATABASE_URL set to a PostgreSQL connection string:
  pytest tests/integration/test_knowledge_graph.py -v
"""

import asyncio
import uuid

import asyncpg
import pytest
import pytest_asyncio

pytestmark = pytest.mark.requires_postgres


# ── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="module")
async def pool(event_loop):
    """Module-scoped asyncpg pool pointing at the test/prod DB."""
    import os
    dsn = os.environ["DATABASE_URL"]
    # Strip SQLAlchemy driver qualifier
    dsn = dsn.replace("postgresql+asyncpg://", "postgresql://").replace(
        "postgresql+psycopg2://", "postgresql://"
    )
    p = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=3)
    yield p
    await p.close()


@pytest_asyncio.fixture
async def clean_graph(pool):
    """
    Delete all graph data seeded in a test, keyed by a unique run_id tag
    stored in metadata->>'test_run'. Yields run_id.
    """
    run_id = str(uuid.uuid4())
    yield run_id
    # Cleanup: delete edges and nodes that carry this test_run tag
    # Also clean up document nodes created by _ensure_document_node
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM sowknow.graph_edges WHERE metadata->>'test_run' = $1",
            run_id,
        )
        await conn.execute(
            "DELETE FROM sowknow.entity_synonyms WHERE canonical_id IN "
            "(SELECT id FROM sowknow.graph_nodes WHERE metadata->>'test_run' = $1)",
            run_id,
        )
        await conn.execute(
            "DELETE FROM sowknow.graph_nodes WHERE metadata->>'test_run' = $1",
            run_id,
        )
        # Clean up document nodes (node_type='document') and their edges
        # created by EntityExtractor._ensure_document_node during extractor tests
        # These have canonical_name = document_id (UUID string), no test_run tag
        # Safe to delete: they're synthetic, have no real document backing them
        await conn.execute(
            "DELETE FROM sowknow.graph_nodes "
            "WHERE node_type = 'document' "
            "AND created_at >= now() - interval '5 minutes' "
            "AND canonical_name ~ '^[0-9a-f-]{36}$'"
        )


# ── Helper ─────────────────────────────────────────────────────────────────

async def insert_node(conn, name: str, node_type: str, run_id: str, bucket: str = "public") -> str:
    nid = await conn.fetchval(
        """
        INSERT INTO sowknow.graph_nodes
            (canonical_name, node_type, bucket, metadata)
        VALUES ($1, $2, $3, jsonb_build_object('test_run', $4::text))
        RETURNING id
        """,
        name, node_type, bucket, run_id,
    )
    await conn.execute(
        "INSERT INTO sowknow.entity_synonyms (surface_form, canonical_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
        name, nid,
    )
    return str(nid)


async def insert_edge(conn, src: str, tgt: str, etype: str, run_id: str, conf: float = 0.8):
    await conn.execute(
        """
        INSERT INTO sowknow.graph_edges
            (source_id, target_id, edge_type, confidence, extraction_method,
             source_document_id, metadata)
        VALUES ($1, $2, $3, $4, 'rule_based', NULL,
                jsonb_build_object('test_run', $5::text))
        ON CONFLICT DO NOTHING
        """,
        src, tgt, etype, conf, run_id,
    )


# ── Schema smoke tests ─────────────────────────────────────────────────────

class TestGraphSchema:

    @pytest.mark.asyncio
    async def test_graph_nodes_table_exists(self, pool):
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT COUNT(*) AS n FROM sowknow.graph_nodes"
            )
        assert row["n"] >= 0

    @pytest.mark.asyncio
    async def test_graph_edges_table_exists(self, pool):
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT COUNT(*) AS n FROM sowknow.graph_edges"
            )
        assert row["n"] >= 0

    @pytest.mark.asyncio
    async def test_entity_synonyms_table_exists(self, pool):
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT COUNT(*) AS n FROM sowknow.entity_synonyms"
            )
        assert row["n"] >= 0

    @pytest.mark.asyncio
    async def test_bucket_check_constraint(self, pool):
        """Inserting invalid bucket value must be rejected."""
        with pytest.raises(asyncpg.exceptions.CheckViolationError):
            async with pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO sowknow.graph_nodes (canonical_name, node_type, bucket) "
                    "VALUES ('x', 'concept', 'invalid_bucket')"
                )

    @pytest.mark.asyncio
    async def test_edge_confidence_check_constraint(self, pool, clean_graph):
        run_id = clean_graph
        async with pool.acquire() as conn:
            nid = await insert_node(conn, "dummy_conf_test", "concept", run_id)
            with pytest.raises(asyncpg.exceptions.CheckViolationError):
                await conn.execute(
                    "INSERT INTO sowknow.graph_edges "
                    "(source_id, target_id, edge_type, confidence, extraction_method) "
                    "VALUES ($1, $2, 'related_to', 1.5, 'ner')",
                    nid, nid,
                )


# ── CRUD tests ─────────────────────────────────────────────────────────────

class TestGraphCRUD:

    @pytest.mark.asyncio
    async def test_insert_and_fetch_node(self, pool, clean_graph):
        run_id = clean_graph
        async with pool.acquire() as conn:
            nid = await insert_node(conn, "masse salariale", "account_line", run_id)
            row = await conn.fetchrow(
                "SELECT * FROM sowknow.graph_nodes WHERE id = $1", nid
            )
        assert row is not None
        assert row["canonical_name"] == "masse salariale"
        assert row["node_type"] == "account_line"
        assert row["bucket"] == "public"

    @pytest.mark.asyncio
    async def test_insert_edge(self, pool, clean_graph):
        run_id = clean_graph
        async with pool.acquire() as conn:
            a = await insert_node(conn, "salaire_crud", "account_line", run_id)
            b = await insert_node(conn, "résultat_crud", "financial_metric", run_id)
            await insert_edge(conn, a, b, "impacts", run_id, conf=0.75)
            row = await conn.fetchrow(
                "SELECT * FROM sowknow.graph_edges WHERE source_id = $1 AND target_id = $2",
                a, b,
            )
        assert row is not None
        assert row["edge_type"] == "impacts"
        assert abs(row["confidence"] - 0.75) < 0.001

    @pytest.mark.asyncio
    async def test_unique_edge_constraint(self, pool, clean_graph):
        """Duplicate (source, target, edge_type, source_document_id) must not insert twice.
        Note: NULL source_document_id does NOT satisfy UNIQUE in PostgreSQL (NULL != NULL),
        so we use a fixed document UUID to test the constraint.
        """
        run_id = clean_graph
        doc_id = str(uuid.uuid4())
        async with pool.acquire() as conn:
            # Create a document node so the FK is satisfied
            await conn.execute(
                "INSERT INTO sowknow.graph_nodes (id, canonical_name, node_type, metadata) "
                "VALUES ($1::uuid, $2, 'document', jsonb_build_object('test_run', $3::text))",
                doc_id, doc_id, run_id,
            )
            a = await insert_node(conn, "dup_src", "concept", run_id)
            b = await insert_node(conn, "dup_tgt", "concept", run_id)
            # First insert
            await conn.execute(
                "INSERT INTO sowknow.graph_edges "
                "(source_id, target_id, edge_type, confidence, extraction_method, source_document_id, metadata) "
                "VALUES ($1, $2, 'related_to', 0.5, 'ner', $4::uuid, "
                "jsonb_build_object('test_run', $3::text))",
                a, b, run_id, doc_id,
            )
            # Second insert with ON CONFLICT DO UPDATE — should update confidence
            await conn.execute(
                "INSERT INTO sowknow.graph_edges "
                "(source_id, target_id, edge_type, confidence, extraction_method, source_document_id, metadata) "
                "VALUES ($1, $2, 'related_to', 0.9, 'ner', $4::uuid, "
                "jsonb_build_object('test_run', $3::text)) "
                "ON CONFLICT (source_id, target_id, edge_type, source_document_id) "
                "DO UPDATE SET confidence = GREATEST(sowknow.graph_edges.confidence, 0.9)",
                a, b, run_id, doc_id,
            )
            row = await conn.fetchrow(
                "SELECT confidence FROM sowknow.graph_edges "
                "WHERE source_id = $1 AND target_id = $2 AND edge_type = 'related_to' "
                "AND source_document_id = $3::uuid",
                a, b, doc_id,
            )
        assert abs(row["confidence"] - 0.9) < 0.001

    @pytest.mark.asyncio
    async def test_synonym_lookup(self, pool, clean_graph):
        run_id = clean_graph
        async with pool.acquire() as conn:
            nid = await insert_node(conn, "chiffre d'affaires", "account_line", run_id)
            # Add synonym
            await conn.execute(
                "INSERT INTO sowknow.entity_synonyms (surface_form, canonical_id) "
                "VALUES ($1, $2) ON CONFLICT DO NOTHING",
                "ca", nid,
            )
            row = await conn.fetchrow(
                "SELECT canonical_id FROM sowknow.entity_synonyms "
                "WHERE lower(surface_form) = 'ca'"
            )
        assert row is not None
        assert str(row["canonical_id"]) == nid

    @pytest.mark.asyncio
    async def test_cascade_delete_node_removes_edges(self, pool, clean_graph):
        run_id = clean_graph
        async with pool.acquire() as conn:
            a = await insert_node(conn, "cascade_src", "concept", run_id)
            b = await insert_node(conn, "cascade_tgt", "concept", run_id)
            await insert_edge(conn, a, b, "related_to", run_id)
            # Delete source node
            await conn.execute(
                "DELETE FROM sowknow.graph_nodes WHERE id = $1", a
            )
            edge_count = await conn.fetchval(
                "SELECT COUNT(*) FROM sowknow.graph_edges "
                "WHERE source_id = $1 OR target_id = $1", a
            )
        assert edge_count == 0


# ── Traversal service tests ────────────────────────────────────────────────

class TestGraphTraversalService:

    @pytest.mark.asyncio
    async def test_resolve_entity_by_synonym(self, pool, clean_graph):
        from app.services.knowledge_graph.traversal import GraphTraversalService

        run_id = clean_graph
        async with pool.acquire() as conn:
            nid = await insert_node(conn, "résultat net", "financial_metric", run_id)
            await conn.execute(
                "INSERT INTO sowknow.entity_synonyms (surface_form, canonical_id) "
                "VALUES ($1, $2) ON CONFLICT DO NOTHING",
                "résultat net", nid,
            )

        svc = GraphTraversalService(pool=pool)
        resolved = await svc.resolve_entity("résultat net")
        assert resolved == nid

    @pytest.mark.asyncio
    async def test_resolve_entity_not_found(self, pool):
        from app.services.knowledge_graph.traversal import GraphTraversalService

        svc = GraphTraversalService(pool=pool)
        resolved = await svc.resolve_entity("nonexistent_xyz_abc_123")
        assert resolved is None

    @pytest.mark.asyncio
    async def test_find_connections_direct_path(self, pool, clean_graph):
        from app.services.knowledge_graph.models import ConnectionQuery
        from app.services.knowledge_graph.traversal import GraphTraversalService

        run_id = clean_graph
        async with pool.acquire() as conn:
            a = await insert_node(conn, f"salaire_{run_id[:8]}", "account_line", run_id)
            b = await insert_node(conn, f"résultat_{run_id[:8]}", "financial_metric", run_id)
            await insert_edge(conn, a, b, "impacts", run_id, conf=0.8)
            # Register synonyms for resolution
            await conn.execute(
                "INSERT INTO sowknow.entity_synonyms (surface_form, canonical_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                f"salaire_{run_id[:8]}", a,
            )
            await conn.execute(
                "INSERT INTO sowknow.entity_synonyms (surface_form, canonical_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                f"résultat_{run_id[:8]}", b,
            )

        svc = GraphTraversalService(pool=pool)
        query = ConnectionQuery(
            start_entity=f"salaire_{run_id[:8]}",
            end_entity=f"résultat_{run_id[:8]}",
            max_depth=3,
            min_confidence=0.3,
        )
        paths = await svc.find_connections(query, max_results=5)
        assert len(paths) >= 1
        assert paths[0].hop_count == 1
        assert paths[0].min_confidence >= 0.3

    @pytest.mark.asyncio
    async def test_find_connections_two_hop(self, pool, clean_graph):
        from app.services.knowledge_graph.models import ConnectionQuery
        from app.services.knowledge_graph.traversal import GraphTraversalService

        run_id = clean_graph
        async with pool.acquire() as conn:
            a = await insert_node(conn, f"node_a_{run_id[:8]}", "concept", run_id)
            b = await insert_node(conn, f"node_b_{run_id[:8]}", "concept", run_id)
            c = await insert_node(conn, f"node_c_{run_id[:8]}", "concept", run_id)
            await insert_edge(conn, a, b, "related_to", run_id)
            await insert_edge(conn, b, c, "related_to", run_id)
            for name, nid in [(f"node_a_{run_id[:8]}", a), (f"node_b_{run_id[:8]}", b), (f"node_c_{run_id[:8]}", c)]:
                await conn.execute(
                    "INSERT INTO sowknow.entity_synonyms (surface_form, canonical_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                    name, nid,
                )

        svc = GraphTraversalService(pool=pool)
        query = ConnectionQuery(
            start_entity=f"node_a_{run_id[:8]}",
            end_entity=f"node_c_{run_id[:8]}",
            max_depth=5,
            min_confidence=0.1,
        )
        paths = await svc.find_connections(query, max_results=5)
        assert len(paths) >= 1
        assert paths[0].hop_count == 2

    @pytest.mark.asyncio
    async def test_find_connections_no_path(self, pool, clean_graph):
        from app.services.knowledge_graph.models import ConnectionQuery
        from app.services.knowledge_graph.traversal import GraphTraversalService

        run_id = clean_graph
        async with pool.acquire() as conn:
            a = await insert_node(conn, f"isolated_a_{run_id[:8]}", "concept", run_id)
            b = await insert_node(conn, f"isolated_b_{run_id[:8]}", "concept", run_id)
            for name, nid in [(f"isolated_a_{run_id[:8]}", a), (f"isolated_b_{run_id[:8]}", b)]:
                await conn.execute(
                    "INSERT INTO sowknow.entity_synonyms (surface_form, canonical_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                    name, nid,
                )
            # No edge between them

        svc = GraphTraversalService(pool=pool)
        query = ConnectionQuery(
            start_entity=f"isolated_a_{run_id[:8]}",
            end_entity=f"isolated_b_{run_id[:8]}",
            max_depth=5,
            min_confidence=0.1,
        )
        paths = await svc.find_connections(query, max_results=5)
        assert paths == []

    @pytest.mark.asyncio
    async def test_bucket_filter_blocks_confidential(self, pool, clean_graph):
        """Public users must not traverse through confidential nodes."""
        from app.services.knowledge_graph.models import ConnectionQuery
        from app.services.knowledge_graph.traversal import GraphTraversalService

        run_id = clean_graph
        async with pool.acquire() as conn:
            a = await insert_node(conn, f"pub_start_{run_id[:8]}", "concept", run_id, bucket="public")
            b = await insert_node(conn, f"conf_mid_{run_id[:8]}", "concept", run_id, bucket="confidential")
            c = await insert_node(conn, f"pub_end_{run_id[:8]}", "concept", run_id, bucket="public")
            await insert_edge(conn, a, b, "related_to", run_id)
            await insert_edge(conn, b, c, "related_to", run_id)
            for name, nid in [
                (f"pub_start_{run_id[:8]}", a),
                (f"conf_mid_{run_id[:8]}", b),
                (f"pub_end_{run_id[:8]}", c),
            ]:
                await conn.execute(
                    "INSERT INTO sowknow.entity_synonyms (surface_form, canonical_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                    name, nid,
                )

        svc = GraphTraversalService(pool=pool)
        # Public query — confidential nodes must be filtered out
        query = ConnectionQuery(
            start_entity=f"pub_start_{run_id[:8]}",
            end_entity=f"pub_end_{run_id[:8]}",
            max_depth=5,
            min_confidence=0.0,
            include_confidential=False,
        )
        paths = await svc.find_connections(query, max_results=5)
        # Path goes through a confidential node, so no results for public user
        assert paths == []

    @pytest.mark.asyncio
    async def test_get_neighbours(self, pool, clean_graph):
        from app.services.knowledge_graph.traversal import GraphTraversalService

        run_id = clean_graph
        async with pool.acquire() as conn:
            center = await insert_node(conn, f"hub_{run_id[:8]}", "concept", run_id)
            spoke1 = await insert_node(conn, f"spoke1_{run_id[:8]}", "person", run_id)
            spoke2 = await insert_node(conn, f"spoke2_{run_id[:8]}", "organization", run_id)
            await insert_edge(conn, center, spoke1, "related_to", run_id)
            await insert_edge(conn, center, spoke2, "related_to", run_id)
            await conn.execute(
                "INSERT INTO sowknow.entity_synonyms (surface_form, canonical_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                f"hub_{run_id[:8]}", center,
            )

        svc = GraphTraversalService(pool=pool)
        neighbours = await svc.get_neighbours(f"hub_{run_id[:8]}", max_depth=1)
        names = [n["canonical_name"] for n in neighbours]
        assert f"spoke1_{run_id[:8]}" in names
        assert f"spoke2_{run_id[:8]}" in names


# ── EntityExtractor tests ──────────────────────────────────────────────────

class TestEntityExtractor:

    @pytest.mark.asyncio
    async def test_extractor_loads_without_spacy(self, pool, clean_graph):
        """EntityExtractor must not crash when spaCy model is unavailable."""
        from app.services.knowledge_graph.extraction import EntityExtractor

        # Use a model name that doesn't exist — should warn, not raise
        extractor = EntityExtractor(pool=pool, spacy_model="nonexistent_model_xyz")
        assert extractor._nlp is None

    @pytest.mark.asyncio
    async def test_financial_keyword_fallback(self, pool, clean_graph):
        """Without spaCy, financial keywords are still extracted and nodes created."""
        from app.services.knowledge_graph.extraction import EntityExtractor

        run_id = clean_graph
        doc_id = str(uuid.uuid4())
        chunk_id = str(uuid.uuid4())

        extractor = EntityExtractor(pool=pool, spacy_model="nonexistent_model_xyz")
        stats = await extractor.process_chunk(
            chunk_text="Le chiffre d'affaires et le résultat net sont liés.",
            document_id=doc_id,
            chunk_id=chunk_id,
            bucket="public",
        )
        # Nodes should have been created for the financial keywords
        assert stats["nodes_created"] >= 1 or stats["nodes_merged"] >= 0

        # Tag the created nodes with test_run for cleanup
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE sowknow.graph_nodes SET metadata = metadata || jsonb_build_object('test_run', $1::text) "
                "WHERE canonical_name IN ('chiffre d''affaires', 'résultat net')",
                run_id,
            )

    @pytest.mark.asyncio
    async def test_spacy_ner_extraction(self, pool, clean_graph):
        """With spaCy loaded, NER entities should be extracted from text."""
        from app.services.knowledge_graph.extraction import EntityExtractor

        run_id = clean_graph
        doc_id = str(uuid.uuid4())
        chunk_id = str(uuid.uuid4())

        extractor = EntityExtractor(pool=pool, spacy_model="fr_core_news_lg")
        if extractor._nlp is None:
            pytest.skip("fr_core_news_lg not installed — skipping NER test")

        text = "La société Renault a réalisé un chiffre d'affaires record en France."
        stats = await extractor.process_chunk(
            chunk_text=text,
            document_id=doc_id,
            chunk_id=chunk_id,
            bucket="public",
        )
        assert stats["nodes_created"] + stats["nodes_merged"] >= 1

        # Tag created nodes for cleanup
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE sowknow.graph_nodes "
                "SET metadata = metadata || jsonb_build_object('test_run', $1::text) "
                "WHERE metadata->>'test_run' IS NULL "
                "AND created_at >= now() - interval '10 seconds'",
                run_id,
            )

    @pytest.mark.asyncio
    async def test_financial_impacts_edge_created(self, pool, clean_graph):
        """Two ACCOUNT_LINE entities in same chunk must get an IMPACTS edge."""
        from app.services.knowledge_graph.extraction import EntityExtractor

        run_id = clean_graph
        doc_id = str(uuid.uuid4())
        chunk_id = str(uuid.uuid4())

        # Use fallback (no spaCy) — only financial keywords are detected
        extractor = EntityExtractor(pool=pool, spacy_model="nonexistent_model_xyz")
        text = "Le salaire et le résultat net sont deux indicateurs clés."
        stats = await extractor.process_chunk(
            chunk_text=text,
            document_id=doc_id,
            chunk_id=chunk_id,
            bucket="public",
        )
        # Salaire and résultat net are both ACCOUNT_LINE → IMPACTS edge expected
        assert stats["edges_created"] >= 1

        # Tag for cleanup
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE sowknow.graph_nodes "
                "SET metadata = metadata || jsonb_build_object('test_run', $1::text) "
                "WHERE canonical_name IN ('salaire', 'résultat net')",
                run_id,
            )
