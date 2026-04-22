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

logger = logging.getLogger(__name__)

EMBEDDING_TTL = 3600  # 1 hour
RESULT_TTL = 60       # 1 minute

_redis_client: _redis.Redis | None = None


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


class SearchCache:
    """Lightweight cache for search embeddings and results."""

    @staticmethod
    def _embedding_key(query: str) -> str:
        h = hashlib.sha256(query.lower().strip().encode()).hexdigest()[:16]
        return f"sowknow:search:emb:{h}"

    @staticmethod
    def _result_key(query: str, user_role: str, top_k: int, buckets_hash: str) -> str:
        h = hashlib.sha256(
            f"{query.lower().strip()}:{user_role}:{top_k}:{buckets_hash}".encode()
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
                return json.loads(raw)
        except Exception as exc:
            logger.debug("search_cache get_embedding error: %s", exc)
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
                return json.loads(raw)
        except Exception as exc:
            logger.debug("search_cache get_result error: %s", exc)
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
