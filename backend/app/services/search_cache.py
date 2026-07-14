"""
Search-specific caching layer on top of Redis.

Caches:
- Query embeddings (TTL 1h) — same text → same embedding
- Search results (TTL 60s) — repeated queries within 1 minute
"""

import hashlib
import json
import logging
from typing import Optional

import redis as _redis

from app.core.redis_url import safe_redis_url
from app.utils.query_normalizer import normalise_query

logger = logging.getLogger(__name__)

EMBEDDING_TTL = 3600  # 1 hour
RESULT_TTL = 60       # 1 minute

_redis_client: _redis.Redis | None = None


def close_redis_client() -> None:
    """Close the module-level Redis client singleton (lifespan shutdown)."""
    global _redis_client
    if _redis_client is not None:
        try:
            _redis_client.close()
        except Exception:
            pass
        _redis_client = None


def _get_redis() -> _redis.Redis | None:
    """Lazy-initialise and return a Redis client. Returns None on failure."""
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    try:
        _redis_client = _redis.from_url(
            safe_redis_url(),
            decode_responses=True,
            socket_timeout=5,
            socket_connect_timeout=5,
        )
        _redis_client.ping()
        return _redis_client
    except Exception:
        logger.warning("search_cache: Redis unavailable — caching disabled")
        _redis_client = None
        return None


def _record_cache_metric(cache_type: str, hit: bool) -> None:
    """Record a cache hit or miss in Prometheus counters (best-effort)."""
    try:
        from app.services.prometheus_metrics import get_metrics

        metric_name = "sowknow_cache_hits_total" if hit else "sowknow_cache_misses_total"
        get_metrics().counter(metric_name).inc(labels={"cache_type": cache_type})
    except Exception as exc:
        logger.debug("Failed to record search cache metric: %s", exc)


class SearchCache:
    """Lightweight cache for search embeddings and results."""

    @staticmethod
    def _embedding_key(query: str) -> str:
        h = hashlib.sha256(normalise_query(query).encode()).hexdigest()[:16]
        return f"sowknow:search:emb:{h}"

    @staticmethod
    def _result_key(query: str, user_role: str, top_k: int, buckets_hash: str) -> str:
        h = hashlib.sha256(
            f"{normalise_query(query)}:{user_role}:{top_k}:{buckets_hash}".encode()
        ).hexdigest()[:16]
        return f"sowknow:search:res:{h}"

    @classmethod
    def get_embedding(cls, query: str) -> Optional[list[float]]:
        """Retrieve cached embedding for a query."""
        redis = _get_redis()
        if not redis:
            return None
        try:
            raw = redis.get(cls._embedding_key(query))
            if raw:
                _record_cache_metric("search_embedding", hit=True)
                return json.loads(raw)
        except Exception as exc:
            logger.debug("search_cache get_embedding error: %s", exc)
        _record_cache_metric("search_embedding", hit=False)
        return None

    @classmethod
    def set_embedding(cls, query: str, embedding: list[float]) -> None:
        """Cache embedding for a query."""
        redis = _get_redis()
        if not redis:
            return
        try:
            redis.setex(cls._embedding_key(query), EMBEDDING_TTL, json.dumps(embedding))
        except Exception as exc:
            logger.debug("search_cache set_embedding error: %s", exc)

    @classmethod
    def get_result(cls, query: str, user_role: str, top_k: int, buckets: list[str]) -> Optional[dict]:
        """Retrieve cached search result."""
        redis = _get_redis()
        if not redis:
            return None
        try:
            buckets_hash = hashlib.sha256(
                ",".join(sorted(buckets)).encode()
            ).hexdigest()[:8]
            raw = redis.get(cls._result_key(query, user_role, top_k, buckets_hash))
            if raw:
                _record_cache_metric("search_result", hit=True)
                return json.loads(raw)
        except Exception as exc:
            logger.debug("search_cache get_result error: %s", exc)
        _record_cache_metric("search_result", hit=False)
        return None

    @classmethod
    def set_result(cls, query: str, user_role: str, top_k: int, buckets: list[str], result: dict) -> None:
        """Cache search result."""
        redis = _get_redis()
        if not redis:
            return
        try:
            buckets_hash = hashlib.sha256(
                ",".join(sorted(buckets)).encode()
            ).hexdigest()[:8]
            redis.setex(
                cls._result_key(query, user_role, top_k, buckets_hash),
                RESULT_TTL,
                json.dumps(result, default=str),
            )
        except Exception as exc:
            logger.debug("search_cache set_result error: %s", exc)

    # ── Collection build cache ──
    INTENT_TTL = 3600      # 1 hour
    GATHER_TTL = 300       # 5 minutes

    @classmethod
    def _collection_intent_key(cls, query: str) -> str:
        h = hashlib.sha256(normalise_query(query).encode()).hexdigest()[:16]
        return f"sowknow:collection:intent:{h}"

    @classmethod
    def _collection_gather_key(cls, query: str, user_role: str) -> str:
        h = hashlib.sha256(
            f"{normalise_query(query)}:{user_role}".encode()
        ).hexdigest()[:16]
        return f"sowknow:collection:gather:{h}"

    @classmethod
    def get_collection_intent(cls, query: str) -> dict | None:
        """Retrieve cached parsed intent for collection builds."""
        redis = _get_redis()
        if not redis:
            return None
        try:
            raw = redis.get(cls._collection_intent_key(query))
            if raw:
                _record_cache_metric("collection_intent", hit=True)
                return json.loads(raw)
        except Exception as exc:
            logger.debug("search_cache get_collection_intent error: %s", exc)
        _record_cache_metric("collection_intent", hit=False)
        return None

    @classmethod
    def set_collection_intent(cls, query: str, intent_data: dict) -> None:
        """Cache parsed intent for collection builds."""
        redis = _get_redis()
        if not redis:
            return
        try:
            redis.setex(
                cls._collection_intent_key(query),
                cls.INTENT_TTL,
                json.dumps(intent_data, default=str),
            )
        except Exception as exc:
            logger.debug("search_cache set_collection_intent error: %s", exc)

    @classmethod
    def get_collection_gather(cls, query: str, user_role: str) -> list[dict] | None:
        """Retrieve cached gather results for collection builds."""
        redis = _get_redis()
        if not redis:
            return None
        try:
            raw = redis.get(cls._collection_gather_key(query, user_role))
            if raw:
                _record_cache_metric("collection_gather", hit=True)
                return json.loads(raw)
        except Exception as exc:
            logger.debug("search_cache get_collection_gather error: %s", exc)
        _record_cache_metric("collection_gather", hit=False)
        return None

    @classmethod
    def set_collection_gather(cls, query: str, user_role: str, results: list[dict]) -> None:
        """Cache gather results for collection builds."""
        redis = _get_redis()
        if not redis:
            return
        try:
            redis.setex(
                cls._collection_gather_key(query, user_role),
                cls.GATHER_TTL,
                json.dumps(results, default=str),
            )
        except Exception as exc:
            logger.debug("search_cache set_collection_gather error: %s", exc)

    @classmethod
    def invalidate_results(cls) -> None:
        """Invalidate all search result caches (e.g., after document upload)."""
        redis = _get_redis()
        if not redis:
            return
        try:
            for key in redis.scan_iter(match="sowknow:search:res:*"):
                redis.delete(key)
            logger.info("search_cache: invalidated all result caches")
        except Exception as exc:
            logger.warning("search_cache invalidate_results error: %s", exc)
