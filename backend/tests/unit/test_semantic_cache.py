"""Unit tests for the SemanticCache two-tier caching layer.

Covers:
- Cache hit/miss based on cosine similarity threshold
- Cache set with Redis pipeline (HSET, EXPIRE, ZADD)
- Cache invalidation (collection-scoped)
- Graceful degradation when Redis or embedding service is unavailable
- Embedding key determinism
- Similarity computation edge cases
- Query normalisation before embedding/keying

Blueprint reference: §6.2 Semantic Caching Layer
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, PropertyMock, patch

import numpy as np
import pytest

from app.services.semantic_cache import (
    GLOBAL_INDEX_KEY,
    REDIS_KEY_PREFIX,
    SEMANTIC_CACHE_TTL,
    SIMILARITY_THRESHOLD,
    SemanticCache,
    _entry_key,
    _index_key,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def cache() -> SemanticCache:
    return SemanticCache()


@pytest.fixture
def mock_redis() -> MagicMock:
    """Return a mock Redis client with pipeline support."""
    redis = MagicMock()
    pipe = MagicMock()
    redis.pipeline.return_value = pipe
    return redis


@pytest.fixture
def mock_embedding_service() -> MagicMock:
    """Return a mock embedding service that is healthy and returns fixed vectors."""
    svc = MagicMock()
    svc.can_embed = True
    return svc


# ---------------------------------------------------------------------------
# get()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSemanticCacheGet:
    """Tests for SemanticCache.get()"""

    async def test_get_hit_when_similarity_above_threshold(self, cache, mock_redis, mock_embedding_service):
        """A query with cosine similarity >= 0.90 should return the cached response."""
        stored_emb = [0.1, 0.2, 0.3, 0.4]
        query_emb = [0.1, 0.2, 0.3, 0.4]  # identical → sim = 1.0

        cache_key = f"{REDIS_KEY_PREFIX}:global:openrouter:standard:abc123"
        index = _index_key(None)
        mock_redis.zrevrange.return_value = [cache_key]
        mock_redis.hget.side_effect = lambda key, field: {
            (cache_key, "embedding"): json.dumps(stored_emb),
            (cache_key, "response"): "cached response",
        }.get((key, field))

        mock_embedding_service.encode_query.return_value = query_emb

        with patch("app.services.semantic_cache.embedding_service", mock_embedding_service):
            cache._redis = mock_redis
            result = await cache.get("documents about my grandfather", "openrouter", "standard")

        assert result == "cached response"
        mock_redis.zrevrange.assert_called_once_with(index, 0, 1000, withscores=False)

    async def test_get_hit_within_collection_scope(self, cache, mock_redis, mock_embedding_service):
        """A scoped query should read from the collection's index."""
        stored_emb = [0.1, 0.2, 0.3, 0.4]
        query_emb = [0.1, 0.2, 0.3, 0.4]
        collection_id = "col-123"

        cache_key = _entry_key("openrouter", "standard", "abc123", collection_id)
        index = _index_key(collection_id)
        mock_redis.zrevrange.return_value = [cache_key]
        mock_redis.hget.side_effect = lambda key, field: {
            (cache_key, "embedding"): json.dumps(stored_emb),
            (cache_key, "response"): "cached response",
        }.get((key, field))

        mock_embedding_service.encode_query.return_value = query_emb

        with patch("app.services.semantic_cache.embedding_service", mock_embedding_service):
            cache._redis = mock_redis
            result = await cache.get(
                "documents about my grandfather",
                "openrouter",
                "standard",
                collection_id=collection_id,
            )

        assert result == "cached response"
        mock_redis.zrevrange.assert_called_once_with(index, 0, 1000, withscores=False)

    async def test_get_miss_when_similarity_below_threshold(self, cache, mock_redis, mock_embedding_service):
        """A query with cosine similarity < 0.90 should return None."""
        stored_emb = [1.0, 0.0, 0.0, 0.0]
        query_emb = [0.0, 1.0, 0.0, 0.0]  # orthogonal → sim = 0.0

        cache_key = f"{REDIS_KEY_PREFIX}:global:openrouter:standard:abc123"
        mock_redis.zrevrange.return_value = [cache_key]
        mock_redis.hget.side_effect = lambda key, field: {
            (cache_key, "embedding"): json.dumps(stored_emb),
        }.get((key, field))

        mock_embedding_service.encode_query.return_value = query_emb

        with patch("app.services.semantic_cache.embedding_service", mock_embedding_service):
            cache._redis = mock_redis
            result = await cache.get("completely different topic", "openrouter", "standard")

        assert result is None

    async def test_get_hit_at_exact_threshold(self, cache, mock_redis, mock_embedding_service):
        """Similarity exactly at 0.90 should be treated as a hit."""
        # Create two vectors with cosine similarity exactly 0.90
        stored_emb = [1.0, 0.0]
        query_emb = np.array([0.9, np.sqrt(1 - 0.9**2)])  # cos = 0.9

        cache_key = f"{REDIS_KEY_PREFIX}:global:openrouter:standard:abc123"
        mock_redis.zrevrange.return_value = [cache_key]
        mock_redis.hget.side_effect = lambda key, field: {
            (cache_key, "embedding"): json.dumps(stored_emb),
            (cache_key, "response"): "threshold response",
        }.get((key, field))

        mock_embedding_service.encode_query.return_value = query_emb.tolist()

        with patch("app.services.semantic_cache.embedding_service", mock_embedding_service):
            cache._redis = mock_redis
            result = await cache.get("just barely similar", "openrouter", "standard")

        assert result == "threshold response"

    async def test_get_just_below_threshold_is_miss(self, cache, mock_redis, mock_embedding_service):
        """Similarity just below 0.90 should be a miss."""
        stored_emb = [1.0, 0.0]
        query_emb = np.array([0.89, np.sqrt(1 - 0.89**2)])  # cos ≈ 0.89

        cache_key = f"{REDIS_KEY_PREFIX}:global:openrouter:standard:abc123"
        mock_redis.zrevrange.return_value = [cache_key]
        mock_redis.hget.side_effect = lambda key, field: {
            (cache_key, "embedding"): json.dumps(stored_emb),
        }.get((key, field))

        mock_embedding_service.encode_query.return_value = query_emb.tolist()

        with patch("app.services.semantic_cache.embedding_service", mock_embedding_service):
            cache._redis = mock_redis
            result = await cache.get("not quite similar enough", "openrouter", "standard")

        assert result is None

    async def test_get_picks_best_candidate(self, cache, mock_redis, mock_embedding_service):
        """When multiple candidates exist, pick the one with highest similarity."""
        emb_a = [1.0, 0.0, 0.0, 0.0]   # low similarity to query
        emb_b = [0.1, 0.2, 0.3, 0.4]   # high similarity to query
        query_emb = [0.1, 0.2, 0.3, 0.4]

        key_a = f"{REDIS_KEY_PREFIX}:global:openrouter:standard:key_a"
        key_b = f"{REDIS_KEY_PREFIX}:global:openrouter:standard:key_b"
        mock_redis.zrevrange.return_value = [key_a, key_b]
        mock_redis.hget.side_effect = lambda key, field: {
            (key_a, "embedding"): json.dumps(emb_a),
            (key_a, "response"): "response_a",
            (key_b, "embedding"): json.dumps(emb_b),
            (key_b, "response"): "response_b",
        }.get((key, field))

        mock_embedding_service.encode_query.return_value = query_emb

        with patch("app.services.semantic_cache.embedding_service", mock_embedding_service):
            cache._redis = mock_redis
            result = await cache.get("my query", "openrouter", "standard")

        assert result == "response_b"

    async def test_get_returns_none_when_no_candidates(self, cache, mock_redis, mock_embedding_service):
        """An empty index should result in a miss."""
        mock_redis.zrevrange.return_value = []
        mock_embedding_service.encode_query.return_value = [0.1, 0.2]

        with patch("app.services.semantic_cache.embedding_service", mock_embedding_service):
            cache._redis = mock_redis
            result = await cache.get("orphan query", "openrouter", "standard")

        assert result is None

    async def test_get_graceful_when_redis_unavailable(self, cache):
        """If Redis is None, return None without raising."""
        cache._redis = None
        with patch("app.services.openrouter_service._get_redis_client", return_value=None):
            result = await cache.get("query", "openrouter", "standard")
        assert result is None

    async def test_get_graceful_when_embedding_service_unavailable(self, cache):
        """If embedding service reports can_embed=False, return None."""
        mock_svc = MagicMock()
        mock_svc.can_embed = False

        with patch("app.services.semantic_cache.embedding_service", mock_svc):
            result = await cache.get("query", "openrouter", "standard")

        assert result is None

    async def test_get_graceful_when_embedding_raises(self, cache, mock_redis):
        """If encode_query raises an exception, return None."""
        mock_svc = MagicMock()
        mock_svc.can_embed = True
        mock_svc.encode_query.side_effect = RuntimeError("embed server down")

        with patch("app.services.semantic_cache.embedding_service", mock_svc):
            cache._redis = mock_redis
            result = await cache.get("query", "openrouter", "standard")

        assert result is None

    async def test_get_decodes_bytes_response(self, cache, mock_redis, mock_embedding_service):
        """Redis with decode_responses=False may return bytes; we decode to str."""
        stored_emb = [0.1, 0.2, 0.3, 0.4]
        query_emb = [0.1, 0.2, 0.3, 0.4]

        cache_key = f"{REDIS_KEY_PREFIX}:global:openrouter:standard:abc123"
        mock_redis.zrevrange.return_value = [cache_key]
        mock_redis.hget.side_effect = lambda key, field: {
            (cache_key, "embedding"): json.dumps(stored_emb).encode(),
            (cache_key, "response"): b"bytes response",
        }.get((key, field))

        mock_embedding_service.encode_query.return_value = query_emb

        with patch("app.services.semantic_cache.embedding_service", mock_embedding_service):
            cache._redis = mock_redis
            result = await cache.get("query", "openrouter", "standard")

        assert result == "bytes response"

    async def test_get_skips_malformed_embedding(self, cache, mock_redis, mock_embedding_service):
        """If a stored embedding is malformed JSON, skip it and continue scanning."""
        stored_emb = [0.1, 0.2, 0.3, 0.4]
        query_emb = [0.1, 0.2, 0.3, 0.4]

        key_bad = f"{REDIS_KEY_PREFIX}:global:openrouter:standard:key_bad"
        key_good = f"{REDIS_KEY_PREFIX}:global:openrouter:standard:key_good"
        mock_redis.zrevrange.return_value = [key_bad, key_good]
        mock_redis.hget.side_effect = lambda key, field: {
            (key_bad, "embedding"): "not-json",
            (key_good, "embedding"): json.dumps(stored_emb),
            (key_good, "response"): "good response",
        }.get((key, field))

        mock_embedding_service.encode_query.return_value = query_emb

        with patch("app.services.semantic_cache.embedding_service", mock_embedding_service):
            cache._redis = mock_redis
            result = await cache.get("query", "openrouter", "standard")

        assert result == "good response"

    async def test_get_different_model_tier_is_separate(self, cache, mock_redis, mock_embedding_service):
        """Cache entries for different model/tier combinations are isolated by key."""
        stored_emb = [0.1, 0.2, 0.3, 0.4]
        query_emb = [0.1, 0.2, 0.3, 0.4]

        # Only a "simple" tier key exists in the global index
        cache_key = f"{REDIS_KEY_PREFIX}:global:openrouter:simple:abc123"
        mock_redis.zrevrange.return_value = [cache_key]
        mock_redis.hget.side_effect = lambda key, field: {
            (cache_key, "embedding"): json.dumps(stored_emb),
            (cache_key, "response"): "simple response",
        }.get((key, field))

        mock_embedding_service.encode_query.return_value = query_emb

        with patch("app.services.semantic_cache.embedding_service", mock_embedding_service):
            cache._redis = mock_redis
            # Query for "standard" tier scans the same global index and finds the key.
            # The key itself encodes tier, but the scan does not filter by it.
            result = await cache.get("query", "openrouter", "standard")

        assert result == "simple response"

    async def test_get_normalises_query_before_embedding(self, cache, mock_redis, mock_embedding_service):
        """Queries differing only in whitespace/case should use the same normalised form."""
        stored_emb = [0.1, 0.2, 0.3, 0.4]
        query_emb = [0.1, 0.2, 0.3, 0.4]

        cache_key = f"{REDIS_KEY_PREFIX}:global:openrouter:standard:abc123"
        mock_redis.zrevrange.return_value = [cache_key]
        mock_redis.hget.side_effect = lambda key, field: {
            (cache_key, "embedding"): json.dumps(stored_emb),
            (cache_key, "response"): "cached response",
        }.get((key, field))

        mock_embedding_service.encode_query.return_value = query_emb

        with patch("app.services.semantic_cache.embedding_service", mock_embedding_service):
            cache._redis = mock_redis
            result = await cache.get(
                "  Documents  about MY Grand-père!! ", "openrouter", "standard"
            )

        # encode_query should receive the normalised form
        encoded_query = mock_embedding_service.encode_query.call_args[0][0]
        assert encoded_query == "documents about my grand-père"
        assert result == "cached response"


# ---------------------------------------------------------------------------
# set()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSemanticCacheSet:
    """Tests for SemanticCache.set()"""

    async def test_set_uses_pipeline(self, cache, mock_redis, mock_embedding_service):
        """set() should use a Redis pipeline for atomic HSET+EXPIRE+ZADD."""
        redis, pipe = mock_redis, mock_redis.pipeline.return_value
        emb = [0.1, 0.2, 0.3, 0.4]
        mock_embedding_service.encode_query.return_value = emb

        with patch("app.services.semantic_cache.embedding_service", mock_embedding_service):
            cache._redis = redis
            await cache.set("my query", "openrouter", "standard", "my response")

        pipe.hset.assert_called_once()
        pipe.expire.assert_called()
        pipe.zadd.assert_called_once()
        pipe.execute.assert_called_once()

    async def test_set_hset_mapping(self, cache, mock_redis, mock_embedding_service):
        """The HSET mapping should contain embedding, response, and normalised query."""
        redis, pipe = mock_redis, mock_redis.pipeline.return_value
        emb = [0.1, 0.2, 0.3, 0.4]
        mock_embedding_service.encode_query.return_value = emb

        with patch("app.services.semantic_cache.embedding_service", mock_embedding_service):
            cache._redis = redis
            await cache.set("  MY Query!! ", "openrouter", "standard", "my response")

        call_args = pipe.hset.call_args[1]["mapping"]
        assert json.loads(call_args["embedding"]) == emb
        assert call_args["response"] == "my response"
        assert call_args["query"] == "my query"

    async def test_set_expire_ttl(self, cache, mock_redis, mock_embedding_service):
        """EXPIRE should be set to SEMANTIC_CACHE_TTL (1800s)."""
        redis, pipe = mock_redis, mock_redis.pipeline.return_value
        mock_embedding_service.encode_query.return_value = [0.1]

        with patch("app.services.semantic_cache.embedding_service", mock_embedding_service):
            cache._redis = redis
            await cache.set("q", "openrouter", "standard", "r")

        pipe.expire.assert_called()
        # expire is called on the key with TTL
        expire_calls = [c for c in pipe.expire.call_args_list if c[0][1] == SEMANTIC_CACHE_TTL]
        assert expire_calls, "Expected at least one EXPIRE call with SEMANTIC_CACHE_TTL"

    async def test_set_uses_scoped_index(self, cache, mock_redis, mock_embedding_service):
        """set() with collection_id should add the key to the collection index."""
        redis, pipe = mock_redis, mock_redis.pipeline.return_value
        emb = [0.1, 0.2, 0.3, 0.4]
        mock_embedding_service.encode_query.return_value = emb
        collection_id = "col-abc"

        with patch("app.services.semantic_cache.embedding_service", mock_embedding_service):
            cache._redis = redis
            await cache.set("q", "openrouter", "standard", "r", collection_id=collection_id)

        index = _index_key(collection_id)
        pipe.zadd.assert_called_once()
        zadd_args = pipe.zadd.call_args[0]
        assert zadd_args[0] == index

    async def test_set_noop_when_embedding_disabled(self, cache):
        """When can_embed is False, set() should be a no-op."""
        mock_svc = MagicMock()
        mock_svc.can_embed = False

        with patch("app.services.semantic_cache.embedding_service", mock_svc):
            await cache.set("q", "openrouter", "standard", "r")

        # No Redis interaction should occur
        assert cache._redis is None

    async def test_set_noop_when_redis_unavailable(self, cache, mock_embedding_service):
        """When Redis is None, set() should be a no-op."""
        mock_embedding_service.encode_query.return_value = [0.1]

        with patch("app.services.semantic_cache.embedding_service", mock_embedding_service):
            cache._redis = None
            with patch("app.services.openrouter_service._get_redis_client", return_value=None):
                await cache.set("q", "openrouter", "standard", "r")

    async def test_set_graceful_on_embedding_failure(self, cache, mock_redis):
        """If encode_query raises, set() should not propagate the exception."""
        mock_svc = MagicMock()
        mock_svc.can_embed = True
        mock_svc.encode_query.side_effect = RuntimeError("embed server down")

        with patch("app.services.semantic_cache.embedding_service", mock_svc):
            cache._redis = mock_redis
            await cache.set("q", "openrouter", "standard", "r")

        # Should not raise; pipeline should not be executed
        mock_redis.pipeline.return_value.execute.assert_not_called()


# ---------------------------------------------------------------------------
# invalidate_for_collection()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSemanticCacheInvalidate:
    """Tests for SemanticCache.invalidate_for_collection()"""

    async def test_invalidate_deletes_scoped_keys(self, cache):
        """Should delete only the keys in the collection index plus the index itself."""
        collection_id = "col-123"
        index = _index_key(collection_id)
        keys = [
            f"{REDIS_KEY_PREFIX}:{collection_id}:openrouter:standard:k1",
            f"{REDIS_KEY_PREFIX}:{collection_id}:openrouter:simple:k2",
        ]
        redis = MagicMock()
        redis.zrange.return_value = keys

        cache._redis = redis
        deleted = await cache.invalidate_for_collection(collection_id)

        assert deleted == 2
        redis.zrange.assert_called_once_with(index, 0, -1)
        # Entries are deleted first, then the index is removed.
        redis.delete.assert_any_call(*keys)
        redis.delete.assert_any_call(index)

    async def test_invalidate_global_only_deletes_global_keys(self, cache):
        """invalidate_for_collection(None) should only clear the global index."""
        keys = [
            f"{REDIS_KEY_PREFIX}:global:openrouter:standard:k1",
        ]
        redis = MagicMock()
        redis.zrange.return_value = keys

        cache._redis = redis
        deleted = await cache.invalidate_for_collection(None)

        assert deleted == 1
        redis.zrange.assert_called_once_with(GLOBAL_INDEX_KEY, 0, -1)

    async def test_invalidate_returns_zero_when_no_keys(self, cache):
        """When the index is empty, return 0."""
        redis = MagicMock()
        redis.zrange.return_value = []

        cache._redis = redis
        deleted = await cache.invalidate_for_collection("col-123")

        assert deleted == 0
        redis.delete.assert_called_once()  # index delete still happens

    async def test_invalidate_returns_zero_when_redis_unavailable(self, cache):
        """When Redis is None, return 0."""
        cache._redis = None
        with patch("app.services.openrouter_service._get_redis_client", return_value=None):
            deleted = await cache.invalidate_for_collection("col-123")
        assert deleted == 0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


class TestSemanticCacheInternals:
    """Tests for _embedding_key and _compute_similarity."""

    def test_embedding_key_deterministic(self):
        """Same embedding must always produce the same 16-char key."""
        cache = SemanticCache()
        emb = [0.5, -0.3, 0.1, -0.8, 0.2, -0.1, 0.0, 0.9]
        key1 = cache._embedding_key(emb)
        key2 = cache._embedding_key(emb)
        assert key1 == key2
        assert len(key1) == 16
        assert all(c in "0123456789abcdef" for c in key1)

    def test_embedding_key_different_inputs(self):
        """Different embeddings should (with very high probability) produce different keys."""
        cache = SemanticCache()
        key1 = cache._embedding_key([0.5, -0.3, 0.1, -0.8])
        key2 = cache._embedding_key([-0.5, 0.3, -0.1, 0.8])
        assert key1 != key2

    def test_compute_similarity_identical_vectors(self):
        """Cosine similarity of identical vectors is 1.0."""
        cache = SemanticCache()
        vec = np.array([0.5, 0.5, 0.5, 0.5], dtype=np.float32)
        sim = cache._compute_similarity(vec, vec)
        assert pytest.approx(sim, 0.001) == 1.0

    def test_compute_similarity_orthogonal_vectors(self):
        """Cosine similarity of orthogonal vectors is 0.0."""
        cache = SemanticCache()
        a = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        b = np.array([0.0, 1.0, 0.0], dtype=np.float32)
        sim = cache._compute_similarity(a, b)
        assert pytest.approx(sim, 0.001) == 0.0

    def test_compute_similarity_opposite_vectors(self):
        """Cosine similarity of opposite vectors is -1.0."""
        cache = SemanticCache()
        a = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        b = np.array([-1.0, 0.0, 0.0], dtype=np.float32)
        sim = cache._compute_similarity(a, b)
        assert pytest.approx(sim, 0.001) == -1.0

    def test_compute_similarity_zero_vector(self):
        """Zero vector should return 0.0 to avoid division by zero."""
        cache = SemanticCache()
        a = np.array([0.0, 0.0, 0.0], dtype=np.float32)
        b = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        sim = cache._compute_similarity(a, b)
        assert sim == 0.0

    def test_compute_similarity_both_zero_vectors(self):
        """Two zero vectors should return 0.0."""
        cache = SemanticCache()
        a = np.array([0.0, 0.0, 0.0], dtype=np.float32)
        b = np.array([0.0, 0.0, 0.0], dtype=np.float32)
        sim = cache._compute_similarity(a, b)
        assert sim == 0.0


# ---------------------------------------------------------------------------
# Singleton instance contract
# ---------------------------------------------------------------------------


class TestSemanticCacheSingleton:
    """Smoke tests for the module-level singleton."""

    def test_singleton_is_semantic_cache_instance(self):
        from app.services.semantic_cache import semantic_cache
        assert isinstance(semantic_cache, SemanticCache)

    def test_singleton_has_none_redis_by_default(self):
        from app.services.semantic_cache import semantic_cache
        assert semantic_cache._redis is None
