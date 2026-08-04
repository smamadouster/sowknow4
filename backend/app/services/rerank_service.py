"""
Cross-encoder re-ranking client for search results.

The cross-encoder provides fine-grained relevance scoring that complements
RRF fusion. It is optional: if the rerank server is unavailable, results
fall back to RRF-only scoring.

Model: cross-encoder/ms-marco-MiniLM-L-6-v2 (~20MB, fast on CPU)
"""

import asyncio
import logging
import math
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

RERANK_SERVER_URL = os.getenv("RERANK_SERVER_URL", "http://rerank-server:8000")

# Module-level client for connection reuse, scoped to the event loop that
# created it. Celery collection tasks run under asyncio.run() (a NEW loop per
# task), so a plain module-level client bound to the first task's loop raised
# "Future attached to a different loop" on every later task and silently
# degraded reranking to RRF fallback (2026-08-04 — this was why the collection
# gate never discriminated: unrelated docs kept passing).
_client: Optional[httpx.AsyncClient] = None
_client_loop: Optional[asyncio.AbstractEventLoop] = None


def _get_client() -> httpx.AsyncClient:
    global _client, _client_loop
    loop = asyncio.get_running_loop()
    if _client is None or _client_loop is not loop:
        # The previous client belongs to a dead loop (its task finished) — let
        # it be GC'd; its pooled connections die with it.
        _client = httpx.AsyncClient(
            base_url=RERANK_SERVER_URL,
            # 5s was too tight for a CPU-throttled rerank-server: every timeout
            # silently degraded search to RRF-only (2026-07-29). The server is
            # fast (~1s) when not throttled; 15s is the degraded-mode budget.
            timeout=15.0,
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
        )
        _client_loop = loop
    return _client


async def rerank_passages(query: str, passages: list[str]) -> list[tuple[int, float]]:
    """
    Re-rank passages against a query using the cross-encoder.

    Returns a list of (original_index, score) sorted by score descending.
    If the rerank server is unreachable, returns an empty list so the
    caller can fall back to RRF scores.
    """
    if not passages:
        return []

    client = _get_client()
    try:
        response = await client.post("/rerank", json={"query": query, "passages": passages})
        response.raise_for_status()
        data = response.json()
        scores = data.get("scores", [])
        # The cross-encoder returns raw logits (unbounded, roughly -10..+10).
        # Squash through sigmoid so scores share the 0..1 scale of the other
        # relevance signals — blending raw logits into final_score pushed
        # results past the 1.0 cap (P0, 2026-07-28).
        scores = [1.0 / (1.0 + math.exp(-s)) for s in scores]
        indexed = list(enumerate(scores))
        indexed.sort(key=lambda x: x[1], reverse=True)
        return indexed
    except Exception as exc:
        logger.debug("Rerank server unavailable, falling back to RRF: %s", exc)
        return []


async def close_rerank_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
