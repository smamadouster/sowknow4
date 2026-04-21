"""
SOWKNOW Knowledge Graph — asyncpg Pool Factory
================================================
Creates a direct asyncpg pool from the same DATABASE_URL used by SQLAlchemy.
The graph traversal and extraction services need a raw asyncpg pool (not the
SQLAlchemy ORM layer) because they use hand-crafted recursive CTEs.

Usage in a Celery task:
    from app.services.knowledge_graph.pool import get_graph_pool

    pool = await get_graph_pool()
    extractor = EntityExtractor(pool=pool, ...)
"""

from __future__ import annotations

import os

import asyncpg

_pool: asyncpg.Pool | None = None


def _build_dsn() -> str:
    """Convert DATABASE_URL to a plain asyncpg DSN (no driver prefix)."""
    url = os.getenv("DATABASE_URL", "postgresql://localhost/sowknow")
    # Strip SQLAlchemy driver qualifiers
    url = url.replace("postgresql+asyncpg://", "postgresql://")
    url = url.replace("postgresql+psycopg2://", "postgresql://")
    return url


async def get_graph_pool(min_size: int = 2, max_size: int = 5) -> asyncpg.Pool:
    """
    Return a module-level asyncpg pool, creating it on first call.
    min/max_size are small by default — the graph pool is supplemental
    to the main SQLAlchemy pool.
    """
    global _pool
    if _pool is None or _pool._closed:
        _pool = await asyncpg.create_pool(
            dsn=_build_dsn(),
            min_size=min_size,
            max_size=max_size,
        )
    return _pool


async def close_graph_pool() -> None:
    """Gracefully close the pool (call on app shutdown)."""
    global _pool
    if _pool and not _pool._closed:
        await _pool.close()
        _pool = None
