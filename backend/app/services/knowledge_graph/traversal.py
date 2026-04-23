"""
SOWKNOW Knowledge Graph — Traversal Service
=============================================
Bidirectional BFS over PostgreSQL graph tables.
Entity resolution via embedding similarity + synonym table.
No external graph DB required.
"""

from __future__ import annotations

import json
import logging

import asyncpg

from .extraction import _vec_to_str
from .models import (
    ConnectionQuery,
    GraphEdge,
    GraphNode,
    PathResult,
)

logger = logging.getLogger("sowknow.graph")

# Schema prefix — all graph tables live in the sowknow schema
_S = "sowknow"

# ── SQL fragments ─────────────────────────────────────────────────

_RESOLVE_ENTITY_SQL = f"""
-- 1) Exact synonym match
SELECT gn.id, gn.canonical_name, gn.node_type, gn.bucket, 1.0 AS score
FROM {_S}.entity_synonyms es
JOIN {_S}.graph_nodes gn ON gn.id = es.canonical_id
WHERE lower(es.surface_form) = lower($1)

UNION

-- 2) Full-text match on canonical name
SELECT gn.id, gn.canonical_name, gn.node_type, gn.bucket,
       ts_rank(to_tsvector('simple', gn.canonical_name),
               plainto_tsquery('simple', $1))::real AS score
FROM {_S}.graph_nodes gn
WHERE to_tsvector('simple', gn.canonical_name) @@ plainto_tsquery('simple', $1)

ORDER BY score DESC
LIMIT 5;
"""

_RESOLVE_BY_EMBEDDING_SQL = f"""
SELECT id, canonical_name, node_type, bucket,
       1 - (embedding <=> $1::vector) AS score
FROM {_S}.graph_nodes
WHERE embedding IS NOT NULL
ORDER BY embedding <=> $1::vector
LIMIT 3;
"""

_UNIDIRECTIONAL_BFS_SQL = f"""
WITH RECURSIVE paths AS (
    SELECT
        source_id,
        target_id,
        ARRAY[source_id, target_id]   AS path,
        ARRAY[id]                     AS edge_ids,
        1                             AS depth,
        confidence                    AS min_conf
    FROM {_S}.graph_edges
    WHERE source_id = $1
      AND confidence >= $3
      {{bucket_filter}}

    UNION ALL

    SELECT
        p.source_id,
        e.target_id,
        p.path || e.target_id,
        p.edge_ids || e.id,
        p.depth + 1,
        LEAST(p.min_conf, e.confidence)
    FROM paths p
    JOIN {_S}.graph_edges e ON e.source_id = p.target_id
    WHERE p.depth < $4
      AND NOT e.target_id = ANY(p.path)
      AND e.confidence >= $3
      {{bucket_filter_inner}}
)
SELECT
    path       AS full_path,
    edge_ids   AS all_edge_ids,
    depth      AS total_depth,
    min_conf   AS min_confidence
FROM paths
WHERE target_id = $2
ORDER BY depth ASC, min_conf DESC
LIMIT $5;
"""

# Used in the initial SELECT of the recursive CTE (no table alias in scope)
_CONFIDENTIAL_BUCKET_FILTER_INIT = (
    f"AND source_id NOT IN "
    f"(SELECT id FROM {_S}.graph_nodes WHERE bucket = 'confidential') "
    f"AND target_id NOT IN "
    f"(SELECT id FROM {_S}.graph_nodes WHERE bucket = 'confidential')"
)

# Used inside the UNION ALL of the recursive CTE (graph_edges aliased as `e`)
_CONFIDENTIAL_BUCKET_FILTER_RECURSIVE = (
    f"AND e.source_id NOT IN "
    f"(SELECT id FROM {_S}.graph_nodes WHERE bucket = 'confidential') "
    f"AND e.target_id NOT IN "
    f"(SELECT id FROM {_S}.graph_nodes WHERE bucket = 'confidential')"
)


class GraphTraversalService:
    """
    Find multi-hop paths between any two entities in the SOWKNOW
    knowledge graph, using PostgreSQL recursive CTEs.
    """

    def __init__(self, pool: asyncpg.Pool, embedding_fn=None):
        """
        Args:
            pool: asyncpg connection pool (your existing DB pool).
            embedding_fn: async callable(text) -> list[float].
                          Should use the same multilingual-e5-large model
                          as the RAG pipeline for consistency.
        """
        self._pool = pool
        self._embed = embedding_fn

    # ── Entity resolution ─────────────────────────────────────────

    async def resolve_entity(
        self, name: str, *, include_confidential: bool = False
    ) -> str | None:
        """
        Map a natural-language entity name to a graph_nodes.id.
        Strategy: synonym table → full-text → embedding similarity.
        """
        async with self._pool.acquire() as conn:
            # Text-based resolution first (fast)
            rows = await conn.fetch(_RESOLVE_ENTITY_SQL, name)

            if not include_confidential:
                rows = [r for r in rows if r["bucket"] != "confidential"]

            if rows:
                logger.info(
                    "Resolved '%s' → %s (score=%.2f)",
                    name, rows[0]["canonical_name"], rows[0]["score"],
                )
                return str(rows[0]["id"])

            # Fall back to embedding similarity
            if self._embed:
                vec = await self._embed(name)
                rows = await conn.fetch(
                    _RESOLVE_BY_EMBEDDING_SQL, _vec_to_str(vec)
                )
                if not include_confidential:
                    rows = [r for r in rows if r["bucket"] != "confidential"]
                if rows and rows[0]["score"] >= 0.75:
                    logger.info(
                        "Resolved '%s' → %s via embedding (score=%.2f)",
                        name, rows[0]["canonical_name"], rows[0]["score"],
                    )
                    return str(rows[0]["id"])

        logger.warning("Could not resolve entity: '%s'", name)
        return None

    # ── Path finding ──────────────────────────────────────────────

    async def find_connections(
        self, query: ConnectionQuery, *, max_results: int = 10
    ) -> list[PathResult]:
        """
        Find all paths between two entities up to `query.max_depth` hops.
        Returns paths ranked by (shortest first, highest confidence).
        """
        start_id = await self.resolve_entity(
            query.start_entity,
            include_confidential=query.include_confidential,
        )
        end_id = await self.resolve_entity(
            query.end_entity,
            include_confidential=query.include_confidential,
        )

        if not start_id or not end_id:
            missing = []
            if not start_id:
                missing.append(query.start_entity)
            if not end_id:
                missing.append(query.end_entity)
            logger.warning("Unresolved entities: %s", missing)
            return []

        if start_id == end_id:
            logger.info("Start and end resolve to the same node.")
            return []

        if query.include_confidential:
            bucket_init = bucket_recursive = ""
        else:
            bucket_init = _CONFIDENTIAL_BUCKET_FILTER_INIT
            bucket_recursive = _CONFIDENTIAL_BUCKET_FILTER_RECURSIVE

        sql = _UNIDIRECTIONAL_BFS_SQL.format(
            bucket_filter=bucket_init,
            bucket_filter_inner=bucket_recursive,
        )

        async with self._pool.acquire() as conn:
            raw_paths = await conn.fetch(
                sql,
                start_id,
                end_id,
                query.min_confidence,
                query.max_depth,
                max_results,
            )

            if not raw_paths:
                logger.info(
                    "No path found between '%s' and '%s' within %d hops.",
                    query.start_entity, query.end_entity, query.max_depth,
                )
                return []

            results = []
            for row in raw_paths:
                node_ids = row["full_path"]
                edge_ids = row["all_edge_ids"]

                nodes = await conn.fetch(
                    f"SELECT * FROM {_S}.graph_nodes WHERE id = ANY($1::uuid[])",
                    node_ids,
                )
                edges = await conn.fetch(
                    f"SELECT * FROM {_S}.graph_edges WHERE id = ANY($1::uuid[])",
                    edge_ids,
                )

                node_map = {str(n["id"]): n for n in nodes}
                edge_map = {str(e["id"]): e for e in edges}

                ordered_nodes = [
                    _row_to_node(node_map[str(nid)]) for nid in node_ids
                ]
                ordered_edges = [
                    _row_to_edge(edge_map[str(eid)]) for eid in edge_ids
                ]

                doc_ids = list(
                    {str(e.source_document_id) for e in ordered_edges if e.source_document_id}
                )

                results.append(
                    PathResult(
                        nodes=ordered_nodes,
                        edges=ordered_edges,
                        hop_count=row["total_depth"],
                        min_confidence=row["min_confidence"],
                        supporting_document_ids=doc_ids,
                    )
                )

            logger.info(
                "Found %d path(s) between '%s' and '%s'.",
                len(results), query.start_entity, query.end_entity,
            )
            return results

    # ── Neighbourhood exploration ─────────────────────────────────

    async def get_neighbours(
        self,
        entity_name: str,
        *,
        max_depth: int = 1,
        include_confidential: bool = False,
    ) -> list[dict]:
        """
        Return all nodes within `max_depth` hops of an entity.
        Useful for "show me everything related to X".
        """
        node_id = await self.resolve_entity(
            entity_name, include_confidential=include_confidential
        )
        if not node_id:
            return []

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                WITH RECURSIVE neighbourhood AS (
                    SELECT target_id AS node_id, 1 AS depth
                    FROM {_S}.graph_edges WHERE source_id = $1
                    UNION
                    SELECT source_id AS node_id, 1 AS depth
                    FROM {_S}.graph_edges WHERE target_id = $1

                    UNION ALL

                    SELECT
                        CASE WHEN e.source_id = n.node_id
                             THEN e.target_id ELSE e.source_id END,
                        n.depth + 1
                    FROM neighbourhood n
                    JOIN {_S}.graph_edges e
                        ON e.source_id = n.node_id OR e.target_id = n.node_id
                    WHERE n.depth < $2
                )
                SELECT DISTINCT gn.*
                FROM neighbourhood nb
                JOIN {_S}.graph_nodes gn ON gn.id = nb.node_id
                WHERE ($3 OR gn.bucket != 'confidential')
                LIMIT 100;
                """,
                node_id,
                max_depth,
                include_confidential,
            )
            return [dict(r) for r in rows]


# ── Helpers ───────────────────────────────────────────────────────

def _parse_jsonb(value) -> dict:
    """asyncpg may return JSONB as a string or as a dict; normalise to dict."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return {}
    return value if isinstance(value, dict) else {}


def _row_to_node(row) -> GraphNode:
    return GraphNode(
        id=str(row["id"]),
        canonical_name=row["canonical_name"],
        aliases=row.get("aliases", []) or [],
        node_type=row["node_type"],
        language=row.get("language", "fr") or "fr",
        metadata=_parse_jsonb(row.get("metadata")),
        bucket=row.get("bucket", "public") or "public",
        created_at=row["created_at"],
    )


def _row_to_edge(row) -> GraphEdge:
    return GraphEdge(
        id=str(row["id"]),
        source_id=str(row["source_id"]),
        target_id=str(row["target_id"]),
        edge_type=row["edge_type"],
        confidence=row["confidence"],
        extraction_method=row["extraction_method"],
        source_document_id=str(row["source_document_id"]) if row.get("source_document_id") else None,
        source_chunk_id=str(row["source_chunk_id"]) if row.get("source_chunk_id") else None,
        metadata=_parse_jsonb(row.get("metadata")),
        created_at=row["created_at"],
    )
