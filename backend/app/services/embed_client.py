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
_ENCODE_TIMEOUT = 120.0    # e5-large on CPU can take 30-60s per batch
_SINGLE_ENCODE_TIMEOUT = 10.0  # single text should be near-instant
_QUERY_TIMEOUT = 30.0
_HEALTH_TIMEOUT = 5.0
_HEALTH_CACHE_TTL = 30.0

# Retry config for transient failures (embed-server restart, brief overload)
_MAX_RETRIES = 3
_RETRY_BACKOFF = [1.0, 2.0, 4.0]  # seconds


def _base_url() -> str:
    return os.getenv("EMBED_SERVER_URL", "http://embed-server:8000")


def _is_retryable(exc: Exception) -> bool:
    """Return True for transient network errors that may resolve on retry."""
    if isinstance(exc, httpx.ConnectError):
        return True
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, httpx.NetworkError):
        return True
    # Connection refused wrapped in RuntimeError from lower layers
    if "connection refused" in str(exc).lower():
        return True
    if "unreachable" in str(exc).lower():
        return True
    return False


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

    def _clear_health_cache(self) -> None:
        """Force next can_embed call to hit the server again."""
        self._health_ok = None
        self._health_checked_at = 0.0

    def health_check(self) -> dict:
        """Proxy to embed server /health endpoint."""
        try:
            resp = httpx.get(f"{_base_url()}/health", timeout=_HEALTH_TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            return {"status": "error", "detail": str(exc), "model_loaded": False}

    def _post_with_retry(self, endpoint: str, payload: dict, timeout: float) -> dict | list:
        """POST to embed server with transient-failure retry and exponential backoff."""
        url = f"{_base_url()}{endpoint}"
        last_exc: Exception | None = None

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                resp = httpx.post(url, json=payload, timeout=timeout)
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as exc:
                # Non-2xx from server → don't retry, fail fast
                logger.error("EmbedClient.%s: server error %s", endpoint, exc.response.status_code)
                raise RuntimeError(f"Embed server returned {exc.response.status_code}") from exc
            except Exception as exc:
                last_exc = exc
                if _is_retryable(exc) and attempt < _MAX_RETRIES:
                    backoff = _RETRY_BACKOFF[min(attempt - 1, len(_RETRY_BACKOFF) - 1)]
                    logger.warning(
                        "EmbedClient.%s: attempt %d/%d failed (%s), retrying in %.1fs",
                        endpoint, attempt, _MAX_RETRIES, exc, backoff
                    )
                    time.sleep(backoff)
                    # Also clear health cache so parallel callers don't think it's healthy
                    self._clear_health_cache()
                else:
                    break

        logger.error("EmbedClient.%s: server unreachable after %d attempts (%s)", endpoint, _MAX_RETRIES, last_exc)
        raise RuntimeError(f"Embed server unreachable: {last_exc}") from last_exc

    def encode(self, texts: list[str], batch_size: int = 32, show_progress: bool = False) -> list[list[float]]:
        """Generate passage embeddings. Raises on server failure to prevent zero-vector poisoning."""
        if not texts:
            return []
        return self._post_with_retry("/embed", {"texts": texts, "batch_size": batch_size}, _ENCODE_TIMEOUT)

    def encode_single(self, text: str) -> list[float]:
        """Generate a passage embedding for a single text. Raises on server failure."""
        if not text or not text.strip():
            return [0.0] * EMBEDDING_DIM
        result = self._post_with_retry("/embed", {"texts": [text], "batch_size": 1}, _SINGLE_ENCODE_TIMEOUT)
        return result[0]  # type: ignore[index]

    def encode_query(self, text: str) -> list[float]:
        """Generate a query embedding (uses 'query:' prefix internally). Raises on server failure."""
        if not text or not text.strip():
            return [0.0] * EMBEDDING_DIM
        return self._post_with_retry("/embed-query", {"text": text}, _QUERY_TIMEOUT)

    async def encode_async(self, texts: list[str], batch_size: int = 32) -> list[list[float]]:
        """Async wrapper — runs encode() in a thread pool."""
        import asyncio
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.encode, texts, batch_size)


# Module-level singleton — same name as the original so callers change only the import path
embedding_service = EmbedClient()
