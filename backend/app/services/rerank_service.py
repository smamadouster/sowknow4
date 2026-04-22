"""
Cross-encoder re-ranking client for search results.

The cross-encoder provides fine-grained relevance scoring that complements
RRF fusion. It is optional: if the rerank server is unavailable, results
fall back to RRF-only scoring.

Model: cross-encoder/ms-marco-MiniLM-L-6-v2 (~20MB, fast on CPU)
"""

import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

RERANK_SERVER_URL = os.getenv("RERANK_SERVER_URL", "http://rerank-server:8000")

# Module-level client for connection reuse
_client: Optional[httpx.AsyncClient] = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            base_url=RERANK_SERVER_URL,
            timeout=5.0,
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
        )
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
