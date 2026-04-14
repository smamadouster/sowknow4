"""
HTTP client for the sowknow4-embed-server microservice.

Drop-in replacement for EmbeddingService — same interface:
  encode(texts, batch_size)  →  list[list[float]]
  encode_query(text)         →  list[float]
  encode_single(text)        →  list[float]
  can_embed                  →  bool (property)
  encode_async(texts)        →  Coroutine[list[list[float]]]

When the embed server is unreachable the client falls back to zero vectors,
preserving the graceful-degradation behaviour of the original EmbeddingService.
"""

import logging
import os

import httpx

logger = logging.getLogger(__name__)

EMBED_SERVER_URL = os.getenv("EMBED_SERVER_URL", "http://embed-server:8000")
EMBEDDING_DIM = 1024
_ENCODE_TIMEOUT = 120.0   # large batches can be slow on CPU
_QUERY_TIMEOUT = 30.0
_HEALTH_TIMEOUT = 5.0


class EmbedClient:
    """Sync HTTP wrapper around the embed-server FastAPI microservice."""

    @property
    def embedding_dim(self) -> int:
        return EMBEDDING_DIM

    @property
    def can_embed(self) -> bool:
        """Return True when the embed server is reachable and healthy."""
        try:
            resp = httpx.get(f"{EMBED_SERVER_URL}/health", timeout=_HEALTH_TIMEOUT)
            return resp.status_code == 200 and resp.json().get("status") == "healthy"
        except Exception:
            return False

    def encode(self, texts: list[str], batch_size: int = 32, show_progress: bool = False) -> list[list[float]]:
        """Generate passage embeddings. Returns zero vectors on server failure."""
        if not texts:
            return []
        try:
            resp = httpx.post(
                f"{EMBED_SERVER_URL}/embed",
                json={"texts": texts, "batch_size": batch_size},
                timeout=_ENCODE_TIMEOUT,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.warning("EmbedClient.encode: server unavailable (%s); returning zero vectors", exc)
            return [[0.0] * EMBEDDING_DIM for _ in texts]

    def encode_single(self, text: str) -> list[float]:
        """Generate a passage embedding for a single text."""
        if not text or not text.strip():
            return [0.0] * EMBEDDING_DIM
        result = self.encode([text])
        return result[0] if result else [0.0] * EMBEDDING_DIM

    def encode_query(self, text: str) -> list[float]:
        """Generate a query embedding (uses 'query:' prefix internally)."""
        if not text or not text.strip():
            return [0.0] * EMBEDDING_DIM
        try:
            resp = httpx.post(
                f"{EMBED_SERVER_URL}/embed-query",
                json={"text": text},
                timeout=_QUERY_TIMEOUT,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.warning("EmbedClient.encode_query: server unavailable (%s); returning zero vector", exc)
            return [0.0] * EMBEDDING_DIM

    async def encode_async(self, texts: list[str], batch_size: int = 32) -> list[list[float]]:
        """Async wrapper — runs encode() in a thread pool."""
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.encode, texts, batch_size)


# Module-level singleton — same name as the original so callers change only the import path
embedding_service = EmbedClient()
