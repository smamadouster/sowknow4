"""
HTTP client for the sowknow4-embed-server microservice.

Drop-in replacement for EmbeddingService — same interface:
  encode(texts, batch_size)  →  list[list[float]]
  encode_query(text)         →  list[float]
  encode_single(text)        →  list[float]
  can_embed                  →  bool (property)
  encode_async(texts)        →  Coroutine[list[list[float]]]
  health_check()             →  dict

When the embed server is unreachable the client falls back to zero vectors,
preserving the graceful-degradation behaviour of the original EmbeddingService.
"""

import logging
import os
import time

import httpx

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 1024
_ENCODE_TIMEOUT = 120.0   # large batches can be slow on CPU
_QUERY_TIMEOUT = 30.0
_HEALTH_TIMEOUT = 5.0
_HEALTH_CACHE_TTL = 30.0


def _base_url() -> str:
    return os.getenv("EMBED_SERVER_URL", "http://embed-server:8000")


class EmbedClient:
    """Sync HTTP wrapper around the embed-server FastAPI microservice."""

    def __init__(self):
        self._health_ok: bool | None = None
        self._health_checked_at: float = 0.0

    @property
    def embedding_dim(self) -> int:
        return EMBEDDING_DIM

    @property
    def can_embed(self) -> bool:
        """Return True when the embed server is reachable and healthy (TTL-cached 30s)."""
        now = time.monotonic()
        if self._health_ok is not None and (now - self._health_checked_at) < _HEALTH_CACHE_TTL:
            return self._health_ok
        try:
            resp = httpx.get(f"{_base_url()}/health", timeout=_HEALTH_TIMEOUT)
            self._health_ok = resp.status_code == 200 and resp.json().get("status") == "healthy"
        except Exception:
            self._health_ok = False
        self._health_checked_at = time.monotonic()
        return self._health_ok

    def health_check(self) -> dict:
        """Proxy to embed server /health endpoint."""
        try:
            resp = httpx.get(f"{_base_url()}/health", timeout=_HEALTH_TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            return {"status": "error", "detail": str(exc), "model_loaded": False}

    def encode(self, texts: list[str], batch_size: int = 32, show_progress: bool = False) -> list[list[float]]:
        """Generate passage embeddings. Returns zero vectors on server failure."""
        if not texts:
            return []
        try:
            resp = httpx.post(
                f"{_base_url()}/embed",
                json={"texts": texts, "batch_size": batch_size},
                timeout=_ENCODE_TIMEOUT,
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            logger.warning("EmbedClient.encode: server error %s; returning zero vectors", exc.response.status_code)
            return [[0.0] * EMBEDDING_DIM for _ in texts]
        except Exception as exc:
            logger.warning("EmbedClient.encode: server unreachable (%s); returning zero vectors", exc)
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
                f"{_base_url()}/embed-query",
                json={"text": text},
                timeout=_QUERY_TIMEOUT,
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            logger.warning("EmbedClient.encode_query: server error %s; returning zero vector", exc.response.status_code)
            return [0.0] * EMBEDDING_DIM
        except Exception as exc:
            logger.warning("EmbedClient.encode_query: server unreachable (%s); returning zero vector", exc)
            return [0.0] * EMBEDDING_DIM

    async def encode_async(self, texts: list[str], batch_size: int = 32) -> list[list[float]]:
        """Async wrapper — runs encode() in a thread pool."""
        import asyncio
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.encode, texts, batch_size)


# Module-level singleton — same name as the original so callers change only the import path
embedding_service = EmbedClient()
