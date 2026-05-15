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
import random
import time

import httpx

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 1024
_ENCODE_TIMEOUT = 300.0    # e5-large on CPU can take 30-120s per batch; give headroom under load
_SINGLE_ENCODE_TIMEOUT = 10.0  # single text should be near-instant
_QUERY_TIMEOUT = 30.0
_HEALTH_TIMEOUT = 5.0
_HEALTH_CACHE_TTL = 30.0

# Retry config for transient failures (embed-server restart, brief overload)
_MAX_RETRIES = 3
_RETRY_BACKOFF = [1.0, 2.0, 4.0]  # seconds

# Circuit-breaker config: fast-fail when embed server is consistently unhealthy
_CIRCUIT_FAILURE_THRESHOLD = 5
_CIRCUIT_OPEN_DURATION = 60.0  # seconds

# Adaptive circuit-breaker: lower threshold when all servers are overloaded
_ADAPTIVE_QUEUE_DEPTH_THRESHOLD = 10
_ADAPTIVE_FAILURE_THRESHOLD = 3

# Health-data freshness for load-aware routing
_HEALTH_DATA_FRESHNESS = 5.0  # seconds


def _base_urls() -> list[str]:
    """Parse EMBED_SERVER_URL as comma-separated list for round-robin load balancing."""
    raw = os.getenv("EMBED_SERVER_URL", "http://embed-server:8000")
    return [u.strip() for u in raw.split(",") if u.strip()]


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
    """Sync HTTP wrapper around the embed-server FastAPI microservice.

    Includes a simple circuit breaker: after _CIRCUIT_FAILURE_THRESHOLD consecutive
    failures, all requests fast-fail for _CIRCUIT_OPEN_DURATION seconds to prevent
    hammering an already-overloaded embed server.

    Uses a persistent httpx.Client for connection pooling to avoid the TCP
    setup/teardown overhead on every embedding call.
    """

    def __init__(self):
        self._health_ok: bool | None = None
        self._health_checked_at: float = 0.0
        self._consecutive_failures = 0
        self._circuit_open_until: float = 0.0
        self._client = httpx.Client(http2=False, timeout=httpx.Timeout(_ENCODE_TIMEOUT))
        self._health_client = httpx.Client(http2=False, timeout=httpx.Timeout(_HEALTH_TIMEOUT))
        # Per-server health state for queue-depth-aware routing
        self._server_health: dict[str, dict] = {}

    @property
    def embedding_dim(self) -> int:
        return EMBEDDING_DIM

    def _update_server_health(self, url: str, health_ok: bool, queue_depth: int = 0) -> None:
        """Store parsed health data for a single embed server."""
        self._server_health[url] = {
            "health_ok": health_ok,
            "queue_depth": queue_depth,
            "checked_at": time.monotonic(),
        }

    def _pick_url(self, attempt: int = 1) -> str:
        """Pick a server URL, preferring the least-loaded healthy server.

        First attempt: pick the URL with the lowest queue_depth among servers
        with fresh health data.  If no fresh data is available, fall back to
        random selection so load is spread across all servers.

        Subsequent retries: rotate round-robin, skipping servers whose circuit
        is open or whose queue_depth exceeds the overload threshold.
        """
        urls = _base_urls()
        now = time.monotonic()

        if attempt == 1:
            # Prefer least-loaded server with fresh health data
            fresh = {
                url: data for url, data in self._server_health.items()
                if data.get("checked_at", 0) > now - _HEALTH_DATA_FRESHNESS
                and data.get("health_ok", False)
                and data.get("queue_depth", 0) < _ADAPTIVE_QUEUE_DEPTH_THRESHOLD
            }
            if fresh:
                return min(fresh, key=lambda u: fresh[u]["queue_depth"])
            # No fresh data → random spread
            return random.choice(urls)

        # Retry: round-robin rotation, skipping unhealthy/overloaded servers
        idx = (attempt - 1) % len(urls)
        candidate = urls[idx]
        data = self._server_health.get(candidate, {})
        if (
            not data.get("health_ok", True)
            or data.get("queue_depth", 0) >= _ADAPTIVE_QUEUE_DEPTH_THRESHOLD
        ):
            # Try to find any healthy server
            for url in urls:
                ud = self._server_health.get(url, {})
                if ud.get("health_ok", True) and ud.get("queue_depth", 0) < _ADAPTIVE_QUEUE_DEPTH_THRESHOLD:
                    return url
        return candidate

    @property
    def can_embed(self) -> bool:
        """Return True when at least one embed server is reachable and healthy (TTL-cached 30s).

        Checks all configured servers and returns True on the first healthy response.
        Respects the circuit breaker: if the circuit is open we skip the network
        call and fast-fail, preventing health-check storms against an overloaded
        embed server.
        """
        # Fast-fail when circuit is open — don't hammer a dying server
        if time.monotonic() < self._circuit_open_until:
            return False

        now = time.monotonic()
        if self._health_ok is not None and (now - self._health_checked_at) < _HEALTH_CACHE_TTL:
            return self._health_ok

        urls = _base_urls()
        any_healthy = False
        for url in urls:
            try:
                resp = self._health_client.get(f"{url}/health")
                if resp.status_code == 200:
                    body = resp.json()
                    healthy = body.get("status") == "healthy"
                    queue_depth = body.get("queue_depth", 0)
                    self._update_server_health(url, healthy, queue_depth)
                    if healthy:
                        any_healthy = True
                        self._record_success()
                else:
                    self._update_server_health(url, False)
            except Exception:
                self._update_server_health(url, False)

        self._health_ok = any_healthy
        self._health_checked_at = now
        if not any_healthy:
            self._record_failure()
        return any_healthy

    def _clear_health_cache(self) -> None:
        """Force next can_embed call to hit the server again."""
        self._health_ok = None
        self._health_checked_at = 0.0

    def health_check(self) -> dict:
        """Proxy to embed server /health endpoint (least-loaded server)."""
        try:
            url = self._pick_url(attempt=1)
            resp = self._health_client.get(f"{url}/health")
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            return {"status": "error", "detail": str(exc), "model_loaded": False}

    def _circuit_breaker_check(self) -> None:
        """Fast-fail if the circuit breaker is open."""
        if time.monotonic() < self._circuit_open_until:
            remaining = int(self._circuit_open_until - time.monotonic())
            raise RuntimeError(f"Embed server circuit breaker OPEN (cooldown {remaining}s)")

    def _adaptive_failure_threshold(self) -> int:
        """Lower failure threshold when all servers are overloaded."""
        now = time.monotonic()
        fresh_overloaded = [
            data for url, data in self._server_health.items()
            if data.get("checked_at", 0) > now - _HEALTH_DATA_FRESHNESS
            and data.get("queue_depth", 0) > _ADAPTIVE_QUEUE_DEPTH_THRESHOLD
        ]
        all_overloaded = len(fresh_overloaded) >= len(_base_urls())
        return _ADAPTIVE_FAILURE_THRESHOLD if all_overloaded else _CIRCUIT_FAILURE_THRESHOLD

    def _record_failure(self) -> None:
        """Increment consecutive failures and trip the circuit breaker if threshold reached."""
        self._consecutive_failures += 1
        threshold = self._adaptive_failure_threshold()
        if self._consecutive_failures >= threshold:
            self._circuit_open_until = time.monotonic() + _CIRCUIT_OPEN_DURATION
            # Gather queue depths for structured logging
            depths = {
                url: data.get("queue_depth", 0)
                for url, data in self._server_health.items()
            }
            logger.warning(
                "embed_circuit_open url=%s queue_depths=%s consecutive_failures=%d threshold=%d cooldown=%.0fs",
                _base_urls()[0] if _base_urls() else "none",
                depths,
                self._consecutive_failures,
                threshold,
                _CIRCUIT_OPEN_DURATION,
            )

    def _record_success(self) -> None:
        """Reset consecutive failures on any successful request."""
        if self._consecutive_failures > 0:
            self._consecutive_failures = 0
            logger.info("EmbedClient circuit breaker RESET after success")

    def _post_with_retry(self, endpoint: str, payload: dict, timeout: float) -> dict | list:
        """POST to embed server with per-attempt failover, transient-failure retry,
        exponential backoff, and circuit-breaker protection.

        On each retry we rotate to the next configured server so a slow/overloaded
        server doesn't block all requests.
        """
        self._circuit_breaker_check()
        urls = _base_urls()
        last_exc: Exception | None = None

        for attempt in range(1, _MAX_RETRIES + 1):
            url = f"{self._pick_url(attempt)}{endpoint}"
            try:
                resp = self._client.post(url, json=payload)
                resp.raise_for_status()
                self._record_success()
                return resp.json()
            except httpx.HTTPStatusError as exc:
                # Non-2xx from server → don't retry, fail fast
                logger.error("EmbedClient.%s: server error %s", endpoint, exc.response.status_code)
                self._record_failure()
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

        self._record_failure()
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
