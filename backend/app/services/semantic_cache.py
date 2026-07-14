"""Semantic (embedding-based) cache for LLM responses.

Intercepts near-duplicate family queries (e.g., "documents sur mon grand-père"
vs "montre-moi les papiers de grand-père") using cosine similarity over query
embeddings. Complements the existing exact-match Redis cache in
openrouter_service.py.

Entries are scoped by collection/workspace so that invalidation only removes
entries affected by a document or collection mutation, rather than flushing the
entire semantic cache.

Blueprint reference: §6.2 Semantic Caching Layer
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from typing import Any, Optional

import numpy as np

from app.services.embed_client import embedding_service
from app.utils.query_normalizer import normalise_query

logger = logging.getLogger(__name__)

SEMANTIC_CACHE_TTL = int(os.getenv("SEMANTIC_CACHE_TTL_SECONDS", "1800"))  # 30 minutes default
SIMILARITY_THRESHOLD = 0.90
REDIS_KEY_PREFIX = "sowknow:semantic_cache"
GLOBAL_INDEX_KEY = f"{REDIS_KEY_PREFIX}:index"


def _index_key(collection_id: str | None) -> str:
    """Return the Redis sorted-set index key for a given collection scope."""
    if collection_id:
        return f"{REDIS_KEY_PREFIX}:index:{collection_id}"
    return GLOBAL_INDEX_KEY


def _entry_key(model: str, tier: str, emb_hash: str, collection_id: str | None) -> str:
    """Build a scoped Redis hash key for a cached response."""
    scope = collection_id or "global"
    return f"{REDIS_KEY_PREFIX}:{scope}:{model}:{tier}:{emb_hash}"


class SemanticCache:
    """Two-tier cache: exact match (handled elsewhere) + semantic similarity."""

    def __init__(self, redis_client: Any | None = None) -> None:
        self._redis = redis_client

    def _get_redis(self) -> Any:
        if self._redis is not None:
            return self._redis
        # Lazy import to avoid circular deps at module load time
        from app.services.openrouter_service import _get_redis_client

        return _get_redis_client()

    def _embedding_key(self, query_embedding: list[float]) -> str:
        """Hash an embedding vector into a short cache key."""
        arr = np.array(query_embedding, dtype=np.float32)
        hash_bytes = np.packbits((arr > 0).astype(np.uint8)).tobytes()
        return hashlib.sha256(hash_bytes).hexdigest()[:16]

    def _compute_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        """Cosine similarity between two vectors."""
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))

    async def get(
        self,
        query: str,
        model: str,
        tier: str,
        collection_id: str | None = None,
    ) -> Optional[str]:
        """
        Look up a semantically similar cached response within a collection scope.

        Returns the cached response string if cosine similarity >= threshold,
        otherwise None.
        """
        if not embedding_service.can_embed:
            return None

        redis = self._get_redis()
        if redis is None:
            return None

        normalised_query = normalise_query(query)
        if not normalised_query:
            return None

        try:
            emb = embedding_service.encode_query(normalised_query)
        except Exception as exc:
            logger.warning("Semantic cache embedding failed: %s", exc)
            return None

        query_vec = np.array(emb, dtype=np.float32)
        index = _index_key(collection_id)

        # Scan candidate keys from the scoped sorted index.  In the common case
        # this index is much smaller than the former global index, so the linear
        # scan stays fast.  For very large collections consider Redis vector
        # search (RediSearch) as a future upgrade.
        try:
            candidates = redis.zrevrange(index, 0, 1000, withscores=False)
        except Exception as exc:
            logger.warning("Semantic cache index read failed: %s", exc)
            return None

        best_score = 0.0
        best_key = None

        for cand in candidates:
            stored = redis.hget(cand, "embedding")
            if not stored:
                continue
            try:
                stored_vec = np.array(json.loads(stored), dtype=np.float32)
                sim = self._compute_similarity(query_vec, stored_vec)
                if sim > best_score:
                    best_score = sim
                    best_key = cand
            except Exception:
                continue

        if best_score >= SIMILARITY_THRESHOLD:
            cached = redis.hget(best_key, "response")
            if cached:
                logger.info(
                    "Semantic cache HIT (sim=%.3f) query=%s model=%s tier=%s collection=%s",
                    best_score,
                    query[:60],
                    model,
                    tier,
                    collection_id or "global",
                )
                try:
                    from app.services.prometheus_metrics import get_metrics

                    get_metrics().counter("sowknow_cache_hits_total").inc(
                        labels={"cache_type": "semantic"}
                    )
                except Exception as exc:
                    logger.debug("Failed to record semantic cache hit metric: %s", exc)
                return cached.decode("utf-8") if isinstance(cached, bytes) else cached

        try:
            from app.services.prometheus_metrics import get_metrics

            get_metrics().counter("sowknow_cache_misses_total").inc(
                labels={"cache_type": "semantic"}
            )
        except Exception as exc:
            logger.debug("Failed to record semantic cache miss metric: %s", exc)

        return None

    async def set(
        self,
        query: str,
        model: str,
        tier: str,
        response: str,
        collection_id: str | None = None,
    ) -> None:
        """Store a response in the scoped semantic cache."""
        if not embedding_service.can_embed:
            return

        redis = self._get_redis()
        if redis is None:
            return

        normalised_query = normalise_query(query)
        if not normalised_query:
            return

        try:
            emb = embedding_service.encode_query(normalised_query)
        except Exception as exc:
            logger.warning("Semantic cache set embedding failed: %s", exc)
            return

        key = _entry_key(model, tier, self._embedding_key(emb), collection_id)
        index = _index_key(collection_id)
        pipe = redis.pipeline()
        pipe.hset(
            key,
            mapping={
                "embedding": json.dumps(emb),
                "response": response,
                "query": normalised_query,
            },
        )
        pipe.expire(key, SEMANTIC_CACHE_TTL)
        pipe.zadd(index, {key: time.time()})
        # Keep the index from growing unbounded if a collection receives many
        # distinct queries.
        pipe.expire(index, SEMANTIC_CACHE_TTL)
        try:
            pipe.execute()
        except Exception as exc:
            logger.warning("Semantic cache SET failed: %s", exc)
            return

        logger.debug(
            "Semantic cache SET query=%s model=%s tier=%s collection=%s",
            query[:60],
            model,
            tier,
            collection_id or "global",
        )

    async def invalidate_for_collection(self, collection_id: str | None = None) -> int:
        """Invalidate semantic cache entries linked to a collection.

        If ``collection_id`` is None, only the global (non-collection) entries
        are cleared.  This replaces the previous behaviour of scanning and
        deleting every semantic-cache key in Redis.
        """
        redis = self._get_redis()
        if redis is None:
            return 0

        index = _index_key(collection_id)
        try:
            keys = redis.zrange(index, 0, -1)
        except Exception as exc:
            logger.warning("Semantic cache invalidation index read failed: %s", exc)
            return 0

        deleted_count = len(keys) if keys else 0
        if keys:
            try:
                redis.delete(*keys)
            except Exception as exc:
                logger.warning("Semantic cache invalidation delete failed: %s", exc)
                return 0

        try:
            redis.delete(index)
        except Exception as exc:
            logger.warning("Semantic cache invalidation index delete failed: %s", exc)

        logger.info(
            "Semantic cache invalidated %d entries for collection=%s",
            deleted_count,
            collection_id or "global",
        )
        return deleted_count


# Singleton instance
semantic_cache = SemanticCache()


async def invalidate_document_caches(collection_id: str | None = None) -> dict[str, Any]:
    """Invalidate all LLM and search caches after document mutation.

    Implements blueprint §6.3 cache invalidation policy:
      - Document uploaded  → invalidate search result cache + semantic cache
      - Document deleted   → invalidate exact + semantic cache

    Args:
        collection_id: Optional collection scope. If None, invalidates global
            semantic cache and all search result caches.

    Returns:
        Dict with operation outcomes (for observability / logging).
    """
    results: dict[str, Any] = {}

    # Tier 2: Semantic cache (now scoped by collection)
    try:
        deleted = await semantic_cache.invalidate_for_collection(collection_id)
        results["semantic_deleted"] = deleted
    except Exception as exc:
        logger.warning("Semantic cache invalidation failed: %s", exc)
        results["semantic_error"] = str(exc)

    # Search result cache (exact-match on query hashes)
    try:
        from app.services.search_cache import SearchCache

        SearchCache.invalidate_results()
        results["search"] = "invalidated"
    except Exception as exc:
        logger.warning("Search cache invalidation failed: %s", exc)
        results["search_error"] = str(exc)

    return results
