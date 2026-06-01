"""Semantic (embedding-based) cache for LLM responses.

Intercepts near-duplicate family queries (e.g., "documents sur mon grand-père"
vs "montre-moi les papiers de grand-père") using cosine similarity over query
embeddings. Complements the existing exact-match Redis cache in
openrouter_service.py.

Blueprint reference: §6.2 Semantic Caching Layer
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any, Optional

import numpy as np

from app.services.embed_client import embedding_service

logger = logging.getLogger(__name__)

SEMANTIC_CACHE_TTL = 1800  # 30 minutes
SIMILARITY_THRESHOLD = 0.90
REDIS_KEY_PREFIX = "sowknow:semantic_cache"
INDEX_KEY = f"{REDIS_KEY_PREFIX}:index"


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
    ) -> Optional[str]:
        """
        Look up a semantically similar cached response.

        Returns the cached response string if cosine similarity >= threshold,
        otherwise None.
        """
        if not embedding_service.can_embed:
            return None

        redis = self._get_redis()
        if redis is None:
            return None

        try:
            emb = embedding_service.encode_query(query)
        except Exception as exc:
            logger.warning("Semantic cache embedding failed: %s", exc)
            return None

        query_vec = np.array(emb, dtype=np.float32)

        # Scan candidate keys from the sorted index
        candidates = redis.zrevrange(INDEX_KEY, 0, 1000, withscores=False)
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
                    "Semantic cache HIT (sim=%.3f) query=%s model=%s tier=%s",
                    best_score,
                    query[:60],
                    model,
                    tier,
                )
                return cached.decode("utf-8") if isinstance(cached, bytes) else cached

        return None

    async def set(
        self,
        query: str,
        model: str,
        tier: str,
        response: str,
    ) -> None:
        """Store a response in the semantic cache."""
        if not embedding_service.can_embed:
            return

        redis = self._get_redis()
        if redis is None:
            return

        try:
            emb = embedding_service.encode_query(query)
        except Exception as exc:
            logger.warning("Semantic cache set embedding failed: %s", exc)
            return

        key = f"{REDIS_KEY_PREFIX}:{model}:{tier}:{self._embedding_key(emb)}"
        pipe = redis.pipeline()
        pipe.hset(
            key,
            mapping={
                "embedding": json.dumps(emb),
                "response": response,
                "query": query,
            },
        )
        pipe.expire(key, SEMANTIC_CACHE_TTL)
        pipe.zadd(INDEX_KEY, {key: time.time()})
        pipe.execute()
        logger.debug(
            "Semantic cache SET query=%s model=%s tier=%s",
            query[:60],
            model,
            tier,
        )

    async def invalidate_for_collection(self, collection_id: str) -> int:
        """Invalidate all semantic cache entries linked to a collection."""
        redis = self._get_redis()
        if redis is None:
            return 0

        # Scan and delete keys matching the prefix
        pattern = f"{REDIS_KEY_PREFIX}:*"
        deleted = 0
        for key in redis.scan_iter(match=pattern, count=100):
            redis.delete(key)
            redis.zrem(INDEX_KEY, key)
            deleted += 1
        logger.info("Semantic cache invalidated %d entries for collection=%s", deleted, collection_id)
        return deleted


# Singleton instance
semantic_cache = SemanticCache()


async def invalidate_document_caches(collection_id: str | None = None) -> dict[str, Any]:
    """Invalidate all LLM and search caches after document mutation.

    Implements blueprint §6.3 cache invalidation policy:
      - Document uploaded  → invalidate search result cache + semantic cache
      - Document deleted   → invalidate exact + semantic cache

    Args:
        collection_id: Optional collection scope. If None, invalidates globally.

    Returns:
        Dict with operation outcomes (for observability / logging).
    """
    results: dict[str, Any] = {}

    # Tier 2: Semantic cache (coarse — all entries share one index)
    try:
        deleted = await semantic_cache.invalidate_for_collection(
            collection_id or "all"
        )
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
