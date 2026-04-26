"""
HTTP client for the sowknow4-embed-server microservice.

Drop-in replacement for EmbeddingService — same interface:
  encode(texts, batch_size)  →  list[list[float]]
  encode_query(text)         →  list[float]
  encode_single(text)        →  list[float]
  can_embed                  →  bool (property)
  encode_async(texts)        →  Coroutine[list[list[float]]]
  health_check()             →  dict

When the embed server is unreachable the client raises RuntimeError so callers
can retry or fail fast rather than silently poisoning the index with zero vectors.
"""

import logging
import os
import time

import httpx

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 1024
_ENCODE_TIMEOUT = 30.0     # batches on healthy embed-server finish in <5s
_SINGLE_ENCODE_TIMEOUT = 10.0  # single text should be near-instant
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
        """Generate passage embeddings. Raises on server failure to prevent zero-vector poisoning."""
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
            logger.error("EmbedClient.encode: server error %s", exc.response.status_code)
            raise RuntimeError(f"Embed server returned {exc.response.status_code}") from exc
        except Exception as exc:
            logger.error("EmbedClient.encode: server unreachable (%s)", exc)
            raise RuntimeError(f"Embed server unreachable: {exc}") from exc

    def encode_single(self, text: str) -> list[float]:
        """Generate a passage embedding for a single text. Raises on server failure."""
        if not text or not text.strip():
            return [0.0] * EMBEDDING_DIM
        try:
            resp = httpx.post(
                f"{_base_url()}/embed",
                json={"texts": [text], "batch_size": 1},
                timeout=_SINGLE_ENCODE_TIMEOUT,
            )
            resp.raise_for_status()
            return resp.json()[0]
        except httpx.HTTPStatusError as exc:
            logger.error("EmbedClient.encode_single: server error %s", exc.response.status_code)
            raise RuntimeError(f"Embed server returned {exc.response.status_code}") from exc
        except Exception as exc:
            logger.error("EmbedClient.encode_single: server unreachable (%s)", exc)
            raise RuntimeError(f"Embed server unreachable: {exc}") from exc

    def encode_query(self, text: str) -> list[float]:
        """Generate a query embedding (uses 'query:' prefix internally). Raises on server failure."""
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
            logger.error("EmbedClient.encode_query: server error %s", exc.response.status_code)
            raise RuntimeError(f"Embed server returned {exc.response.status_code}") from exc
        except Exception as exc:
            logger.error("EmbedClient.encode_query: server unreachable (%s)", exc)
            raise RuntimeError(f"Embed server unreachable: {exc}") from exc

    async def encode_async(self, texts: list[str], batch_size: int = 32) -> list[list[float]]:
        """Async wrapper — runs encode() in a thread pool."""
        import asyncio
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.encode, texts, batch_size)


# Module-level singleton — same name as the original so callers change only the import path
embedding_service = EmbedClient()
