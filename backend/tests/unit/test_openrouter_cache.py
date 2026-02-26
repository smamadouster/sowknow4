"""
Unit tests for OpenRouter context caching functionality.

Tests cover:
- Cache key generation (SHA256)
- Cache hit scenarios
- Cache miss scenarios
- Cache metrics integration
- Streaming bypass
- Redis failure graceful degradation
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from app.services.openrouter_service import (
    OpenRouterService,
    CACHE_KEY_PREFIX,
    CACHE_TTL_SECONDS,
    COLLECTION_CACHE_KEYS_PREFIX,
)


class TestCacheKeyGeneration:
    """Tests for cache key generation logic."""

    def test_generate_cache_key_deterministic(self):
        """Cache key should be deterministic for same input."""
        service = OpenRouterService()
        messages = [
            {"role": "user", "content": "Hello, world!"},
            {"role": "assistant", "content": "Hi there!"},
        ]

        key1 = service._generate_cache_key("test-model", messages)
        key2 = service._generate_cache_key("test-model", messages)

        assert key1 == key2
        assert key1.startswith(CACHE_KEY_PREFIX)

    def test_generate_cache_key_includes_model(self):
        """Cache key should differ for different models."""
        service = OpenRouterService()
        messages = [{"role": "user", "content": "Hello"}]

        key1 = service._generate_cache_key("model-a", messages)
        key2 = service._generate_cache_key("model-b", messages)

        assert key1 != key2

    def test_generate_cache_key_includes_content(self):
        """Cache key should differ for different message content."""
        service = OpenRouterService()

        messages1 = [{"role": "user", "content": "Hello"}]
        messages2 = [{"role": "user", "content": "Goodbye"}]

        key1 = service._generate_cache_key("test-model", messages1)
        key2 = service._generate_cache_key("test-model", messages2)

        assert key1 != key2

    def test_generate_cache_key_order_independent(self):
        """Cache key should be same regardless of message order."""
        service = OpenRouterService()

        messages_a = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi!"},
        ]
        messages_b = [
            {"role": "assistant", "content": "Hi!"},
            {"role": "user", "content": "Hello"},
        ]

        key1 = service._generate_cache_key("test-model", messages_a)
        key2 = service._generate_cache_key("test-model", messages_b)

        assert key1 == key2, "Cache key should be order-independent"

    def test_generate_cache_key_sha256_format(self):
        """Cache key should use SHA256 hash format (64 hex chars)."""
        service = OpenRouterService()
        messages = [{"role": "user", "content": "Test"}]

        key = service._generate_cache_key("test-model", messages)
        hash_part = key.replace(CACHE_KEY_PREFIX, "")

        assert len(hash_part) == 64, "SHA256 hash should be 64 hex characters"
        assert all(c in "0123456789abcdef" for c in hash_part)

    def test_generate_cache_key_empty_messages(self):
        """Cache key should work with empty messages."""
        service = OpenRouterService()
        messages = []

        key = service._generate_cache_key("test-model", messages)

        assert key.startswith(CACHE_KEY_PREFIX)
        assert len(key) > len(CACHE_KEY_PREFIX)


class TestCacheHitScenario:
    """Tests for cache hit behavior."""

    @pytest.mark.asyncio
    async def test_cache_hit_returns_cached_response(self):
        """Cache hit should return cached response without API call."""
        with patch(
            "app.services.openrouter_service._get_redis_client"
        ) as mock_redis_get:
            mock_redis = MagicMock()
            mock_redis.get.return_value = "Cached response content"
            mock_redis_get.return_value = mock_redis

            service = OpenRouterService()
            service._cache_enabled = True
            service.api_key = "test-key"

            messages = [{"role": "user", "content": "Test query"}]
            result_chunks = []
            async for chunk in service.chat_completion(
                messages, stream=False, user_id="test-user"
            ):
                result_chunks.append(chunk)

            result = "".join(result_chunks)
            assert result == "Cached response content"
            mock_redis.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_cache_hit_records_metrics(self):
        """Cache hit should record metrics in cache_monitor."""
        with patch(
            "app.services.openrouter_service._get_redis_client"
        ) as mock_redis_get:
            with patch("app.services.cache_monitor.cache_monitor") as mock_monitor:
                mock_redis = MagicMock()
                mock_redis.get.return_value = "Cached response"
                mock_redis_get.return_value = mock_redis

                service = OpenRouterService()
                service._cache_enabled = True
                service.api_key = "test-key"

                messages = [{"role": "user", "content": "Test"}]
                result_chunks = []
                async for chunk in service.chat_completion(
                    messages, stream=False, user_id="test-user"
                ):
                    result_chunks.append(chunk)

                mock_monitor.record_cache_hit.assert_called_once()
                call_kwargs = mock_monitor.record_cache_hit.call_args[1]
                assert call_kwargs["user_id"] == "test-user"
                assert call_kwargs["tokens_saved"] > 0

    @pytest.mark.asyncio
    async def test_cache_hit_does_not_set_cache(self):
        """Cache hit should not attempt to set cache again."""
        with patch(
            "app.services.openrouter_service._get_redis_client"
        ) as mock_redis_get:
            mock_redis = MagicMock()
            mock_redis.get.return_value = "Cached"
            mock_redis_get.return_value = mock_redis

            service = OpenRouterService()
            service._cache_enabled = True
            service.api_key = "test-key"

            messages = [{"role": "user", "content": "Test"}]
            async for _ in service.chat_completion(messages, stream=False):
                pass

            mock_redis.setex.assert_not_called()


class TestCacheMissScenario:
    """Tests for cache miss behavior."""

    @pytest.mark.asyncio
    async def test_cache_miss_calls_api(self):
        """Cache miss should proceed to API call."""
        with patch(
            "app.services.openrouter_service._get_redis_client"
        ) as mock_redis_get:
            with patch("httpx.AsyncClient") as mock_client:
                mock_redis = MagicMock()
                mock_redis.get.return_value = None
                mock_redis_get.return_value = mock_redis

                mock_response = MagicMock()
                mock_response.json.return_value = {
                    "choices": [{"message": {"content": "API response"}}],
                    "usage": {"total_tokens": 100},
                }
                mock_response.raise_for_status = MagicMock()

                mock_cm = AsyncMock()
                mock_cm.__aenter__.return_value.post = AsyncMock(
                    return_value=mock_response
                )
                mock_cm.__aenter__.return_value.__aexit__ = MagicMock()
                mock_client.return_value = mock_cm

                service = OpenRouterService()
                service._cache_enabled = True
                service.api_key = "test-key"

                messages = [{"role": "user", "content": "Test"}]
                result_chunks = []
                async for chunk in service.chat_completion(messages, stream=False):
                    if "__USAGE__" not in chunk:
                        result_chunks.append(chunk)

                result = "".join(result_chunks)
                assert result == "API response"

    @pytest.mark.asyncio
    async def test_cache_miss_caches_response(self):
        """Cache miss should cache the API response."""
        with patch(
            "app.services.openrouter_service._get_redis_client"
        ) as mock_redis_get:
            with patch("httpx.AsyncClient") as mock_client:
                mock_redis = MagicMock()
                mock_redis.get.return_value = None
                mock_redis_get.return_value = mock_redis

                mock_response = MagicMock()
                mock_response.json.return_value = {
                    "choices": [{"message": {"content": "API response"}}],
                }
                mock_response.raise_for_status = MagicMock()

                mock_cm = AsyncMock()
                mock_cm.__aenter__.return_value.post = AsyncMock(
                    return_value=mock_response
                )
                mock_client.return_value = mock_cm

                service = OpenRouterService()
                service._cache_enabled = True
                service.api_key = "test-key"

                messages = [{"role": "user", "content": "Test"}]
                async for _ in service.chat_completion(messages, stream=False):
                    pass

                mock_redis.setex.assert_called_once()
                call_args = mock_redis.setex.call_args
                assert call_args[0][1] == CACHE_TTL_SECONDS
                assert call_args[0][2] == "API response"

    @pytest.mark.asyncio
    async def test_cache_miss_records_metrics(self):
        """Cache miss should record metrics in cache_monitor."""
        with patch(
            "app.services.openrouter_service._get_redis_client"
        ) as mock_redis_get:
            with patch("app.services.cache_monitor.cache_monitor") as mock_monitor:
                with patch("httpx.AsyncClient") as mock_client:
                    mock_redis = MagicMock()
                    mock_redis.get.return_value = None
                    mock_redis_get.return_value = mock_redis

                    mock_response = MagicMock()
                    mock_response.json.return_value = {
                        "choices": [{"message": {"content": "Response"}}],
                    }
                    mock_response.raise_for_status = MagicMock()

                    mock_cm = AsyncMock()
                    mock_cm.__aenter__.return_value.post = AsyncMock(
                        return_value=mock_response
                    )
                    mock_client.return_value = mock_cm

                    service = OpenRouterService()
                    service._cache_enabled = True
                    service.api_key = "test-key"

                    messages = [{"role": "user", "content": "Test"}]
                    async for _ in service.chat_completion(
                        messages, stream=False, user_id="test-user"
                    ):
                        pass

                    mock_monitor.record_cache_miss.assert_called_once()
                    call_kwargs = mock_monitor.record_cache_miss.call_args[1]
                    assert call_kwargs["user_id"] == "test-user"


class TestStreamingBypassCache:
    """Tests that streaming requests bypass caching."""

    @pytest.mark.asyncio
    async def test_streaming_does_not_check_cache(self):
        """Streaming requests should not check cache."""
        mock_redis = MagicMock()

        async def mock_aiter_lines():
            yield ""
            return

        class MockAsyncStreamContext:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            async def aiter_lines(self):
                yield ""

            def raise_for_status(self):
                pass

        class MockAsyncClientContext:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            def stream(self, *args, **kwargs):
                return MockAsyncStreamContext()

        with patch(
            "app.services.openrouter_service._get_redis_client"
        ) as mock_redis_get:
            with patch("httpx.AsyncClient") as mock_client:
                mock_redis_get.return_value = mock_redis
                mock_client.return_value = MockAsyncClientContext()

                service = OpenRouterService()
                service._cache_enabled = True
                service.api_key = "test-key"

                messages = [{"role": "user", "content": "Test"}]
                async for _ in service.chat_completion(messages, stream=True):
                    pass

                mock_redis.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_streaming_does_not_set_cache(self):
        """Streaming requests should not set cache."""
        mock_redis = MagicMock()

        class MockAsyncStreamContext:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            async def aiter_lines(self):
                yield ""

            def raise_for_status(self):
                pass

        class MockAsyncClientContext:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            def stream(self, *args, **kwargs):
                return MockAsyncStreamContext()

        with patch(
            "app.services.openrouter_service._get_redis_client"
        ) as mock_redis_get:
            with patch("httpx.AsyncClient") as mock_client:
                mock_redis_get.return_value = mock_redis
                mock_client.return_value = MockAsyncClientContext()

                service = OpenRouterService()
                service._cache_enabled = True
                service.api_key = "test-key"

                messages = [{"role": "user", "content": "Test"}]
                async for _ in service.chat_completion(messages, stream=True):
                    pass

                mock_redis.setex.assert_not_called()


class TestRedisFailureGracefulDegradation:
    """Tests for graceful handling of Redis failures."""

    @pytest.mark.asyncio
    async def test_redis_unavailable_disables_cache(self):
        """Service should disable cache when Redis is unavailable."""
        with patch(
            "app.services.openrouter_service._get_redis_client"
        ) as mock_redis_get:
            mock_redis_get.return_value = None

            service = OpenRouterService()
            service.api_key = "test-key"
            service._cache_enabled = False

            with patch("httpx.AsyncClient") as mock_client:
                mock_response = MagicMock()
                mock_response.json.return_value = {
                    "choices": [{"message": {"content": "Response"}}],
                }
                mock_response.raise_for_status = MagicMock()

                mock_cm = AsyncMock()
                mock_cm.__aenter__.return_value.post = AsyncMock(
                    return_value=mock_response
                )
                mock_client.return_value = mock_cm

                messages = [{"role": "user", "content": "Test"}]
                result_chunks = []
                async for chunk in service.chat_completion(messages, stream=False):
                    if not chunk.startswith("__USAGE__"):
                        result_chunks.append(chunk)

                result = "".join(result_chunks)
                assert result == "Response"

    @pytest.mark.asyncio
    async def test_redis_read_error_proceeds_with_api_call(self):
        """Redis read errors should not break the service."""
        with patch(
            "app.services.openrouter_service._get_redis_client"
        ) as mock_redis_get:
            with patch("httpx.AsyncClient") as mock_client:
                mock_redis = MagicMock()
                mock_redis.get.side_effect = Exception("Redis connection error")
                mock_redis_get.return_value = mock_redis

                mock_response = MagicMock()
                mock_response.json.return_value = {
                    "choices": [{"message": {"content": "API response"}}],
                }
                mock_response.raise_for_status = MagicMock()

                mock_cm = AsyncMock()
                mock_cm.__aenter__.return_value.post = AsyncMock(
                    return_value=mock_response
                )
                mock_client.return_value = mock_cm

                service = OpenRouterService()
                service._cache_enabled = True
                service.api_key = "test-key"

                messages = [{"role": "user", "content": "Test"}]
                result_chunks = []
                async for chunk in service.chat_completion(messages, stream=False):
                    if not chunk.startswith("__USAGE__"):
                        result_chunks.append(chunk)

                result = "".join(result_chunks)
                assert result == "API response"

    @pytest.mark.asyncio
    async def test_redis_write_error_does_not_break_response(self):
        """Redis write errors should not break the response."""
        with patch(
            "app.services.openrouter_service._get_redis_client"
        ) as mock_redis_get:
            with patch("httpx.AsyncClient") as mock_client:
                mock_redis = MagicMock()
                mock_redis.get.return_value = None
                mock_redis.setex.side_effect = Exception("Redis write error")
                mock_redis_get.return_value = mock_redis

                mock_response = MagicMock()
                mock_response.json.return_value = {
                    "choices": [{"message": {"content": "API response"}}],
                }
                mock_response.raise_for_status = MagicMock()

                mock_cm = AsyncMock()
                mock_cm.__aenter__.return_value.post = AsyncMock(
                    return_value=mock_response
                )
                mock_client.return_value = mock_cm

                service = OpenRouterService()
                service._cache_enabled = True
                service.api_key = "test-key"

                messages = [{"role": "user", "content": "Test"}]
                result_chunks = []
                async for chunk in service.chat_completion(messages, stream=False):
                    if not chunk.startswith("__USAGE__"):
                        result_chunks.append(chunk)

                result = "".join(result_chunks)
                assert result == "API response"


class TestCustomCacheKey:
    """Tests for custom cache key support."""

    @pytest.mark.asyncio
    async def test_custom_cache_key_used(self):
        """Custom cache key should be used instead of generated one."""
        custom_key = "sowknow:custom:my-key-123"

        with patch(
            "app.services.openrouter_service._get_redis_client"
        ) as mock_redis_get:
            mock_redis = MagicMock()
            mock_redis.get.return_value = "Cached"
            mock_redis_get.return_value = mock_redis

            service = OpenRouterService()
            service._cache_enabled = True
            service.api_key = "test-key"

            messages = [{"role": "user", "content": "Test"}]
            async for _ in service.chat_completion(
                messages, stream=False, cache_key=custom_key
            ):
                pass

            mock_redis.get.assert_called_once_with(custom_key)

    @pytest.mark.asyncio
    async def test_custom_cache_key_stored_on_miss(self):
        """Custom cache key should be used for storage on cache miss."""
        custom_key = "sowknow:custom:my-key-456"

        with patch(
            "app.services.openrouter_service._get_redis_client"
        ) as mock_redis_get:
            with patch("httpx.AsyncClient") as mock_client:
                mock_redis = MagicMock()
                mock_redis.get.return_value = None
                mock_redis_get.return_value = mock_redis

                mock_response = MagicMock()
                mock_response.json.return_value = {
                    "choices": [{"message": {"content": "Response"}}],
                }
                mock_response.raise_for_status = MagicMock()

                mock_cm = AsyncMock()
                mock_cm.__aenter__.return_value.post = AsyncMock(
                    return_value=mock_response
                )
                mock_client.return_value = mock_cm

                service = OpenRouterService()
                service._cache_enabled = True
                service.api_key = "test-key"

                messages = [{"role": "user", "content": "Test"}]
                async for _ in service.chat_completion(
                    messages, stream=False, cache_key=custom_key
                ):
                    pass

                mock_redis.setex.assert_called_once()
                call_args = mock_redis.setex.call_args
                assert call_args[0][0] == custom_key


class TestCacheTTL:
    """Tests for cache TTL configuration."""

    def test_cache_ttl_is_one_hour(self):
        """Cache TTL should be 3600 seconds (1 hour)."""
        assert CACHE_TTL_SECONDS == 3600

    def test_cache_key_prefix_is_correct(self):
        """Cache key prefix should be correct."""
        assert CACHE_KEY_PREFIX == "sowknow:openrouter:cache:"

    def test_collection_cache_keys_prefix_is_correct(self):
        """Collection tracking key prefix should be correct."""
        assert COLLECTION_CACHE_KEYS_PREFIX == "sowknow:openrouter:collection_keys:"


class TestConfidentialBypass:
    """Tests ensuring confidential/PII queries are NEVER cached (privacy guarantee)."""

    @pytest.mark.asyncio
    async def test_confidential_query_does_not_read_cache(self):
        """is_confidential=True must skip Redis GET entirely."""
        with patch(
            "app.services.openrouter_service._get_redis_client"
        ) as mock_redis_get:
            with patch("httpx.AsyncClient") as mock_client:
                mock_redis = MagicMock()
                mock_redis.get.return_value = "Should not be returned"
                mock_redis_get.return_value = mock_redis

                mock_response = MagicMock()
                mock_response.json.return_value = {
                    "choices": [{"message": {"content": "Live response"}}],
                }
                mock_response.raise_for_status = MagicMock()

                mock_cm = AsyncMock()
                mock_cm.__aenter__.return_value.post = AsyncMock(
                    return_value=mock_response
                )
                mock_client.return_value = mock_cm

                service = OpenRouterService()
                service._cache_enabled = True
                service.api_key = "test-key"

                messages = [{"role": "user", "content": "Confidential query"}]
                result_chunks = []
                async for chunk in service.chat_completion(
                    messages, stream=False, is_confidential=True
                ):
                    if not chunk.startswith("__USAGE__"):
                        result_chunks.append(chunk)

                # Cache must never be read for confidential queries
                mock_redis.get.assert_not_called()
                # Must still return the live API response
                assert "".join(result_chunks) == "Live response"

    @pytest.mark.asyncio
    async def test_confidential_query_does_not_write_cache(self):
        """is_confidential=True must skip Redis SETEX (response not stored)."""
        with patch(
            "app.services.openrouter_service._get_redis_client"
        ) as mock_redis_get:
            with patch("httpx.AsyncClient") as mock_client:
                mock_redis = MagicMock()
                mock_redis.get.return_value = None
                mock_redis_get.return_value = mock_redis

                mock_response = MagicMock()
                mock_response.json.return_value = {
                    "choices": [{"message": {"content": "Confidential answer"}}],
                }
                mock_response.raise_for_status = MagicMock()

                mock_cm = AsyncMock()
                mock_cm.__aenter__.return_value.post = AsyncMock(
                    return_value=mock_response
                )
                mock_client.return_value = mock_cm

                service = OpenRouterService()
                service._cache_enabled = True
                service.api_key = "test-key"

                messages = [{"role": "user", "content": "Medical records query"}]
                async for _ in service.chat_completion(
                    messages, stream=False, is_confidential=True
                ):
                    pass

                # Response must NOT be written to cache
                mock_redis.setex.assert_not_called()

    @pytest.mark.asyncio
    async def test_confidential_query_does_not_record_cache_metrics(self):
        """is_confidential=True must not record cache hit/miss metrics."""
        with patch(
            "app.services.openrouter_service._get_redis_client"
        ) as mock_redis_get:
            with patch("app.services.cache_monitor.cache_monitor") as mock_monitor:
                with patch("httpx.AsyncClient") as mock_client:
                    mock_redis = MagicMock()
                    mock_redis_get.return_value = mock_redis

                    mock_response = MagicMock()
                    mock_response.json.return_value = {
                        "choices": [{"message": {"content": "Confidential"}}],
                    }
                    mock_response.raise_for_status = MagicMock()

                    mock_cm = AsyncMock()
                    mock_cm.__aenter__.return_value.post = AsyncMock(
                        return_value=mock_response
                    )
                    mock_client.return_value = mock_cm

                    service = OpenRouterService()
                    service._cache_enabled = True
                    service.api_key = "test-key"

                    messages = [{"role": "user", "content": "Private data"}]
                    async for _ in service.chat_completion(
                        messages, stream=False, is_confidential=True
                    ):
                        pass

                    # No cache metrics should be recorded for confidential queries
                    mock_monitor.record_cache_hit.assert_not_called()
                    mock_monitor.record_cache_miss.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_confidential_query_uses_cache_normally(self):
        """is_confidential=False (default) must still use cache normally."""
        with patch(
            "app.services.openrouter_service._get_redis_client"
        ) as mock_redis_get:
            mock_redis = MagicMock()
            mock_redis.get.return_value = "Cached public response"
            mock_redis_get.return_value = mock_redis

            service = OpenRouterService()
            service._cache_enabled = True
            service.api_key = "test-key"

            messages = [{"role": "user", "content": "Public query"}]
            result_chunks = []
            async for chunk in service.chat_completion(
                messages, stream=False, is_confidential=False
            ):
                result_chunks.append(chunk)

            mock_redis.get.assert_called_once()
            assert "".join(result_chunks) == "Cached public response"


class TestCacheInvalidation:
    """Tests for collection-based cache invalidation."""

    def test_invalidate_collection_cache_deletes_tracked_keys(self):
        """invalidate_collection_cache() should delete all keys in collection set."""
        collection_id = "col-abc-123"
        tracking_key = f"{COLLECTION_CACHE_KEYS_PREFIX}{collection_id}"
        cached_keys = {
            f"{CACHE_KEY_PREFIX}aabbccdd1",
            f"{CACHE_KEY_PREFIX}aabbccdd2",
        }

        with patch(
            "app.services.openrouter_service._get_redis_client"
        ) as mock_redis_get:
            mock_redis = MagicMock()
            mock_redis.smembers.return_value = cached_keys
            mock_redis_get.return_value = mock_redis

            service = OpenRouterService()
            service._cache_enabled = True

            count = service.invalidate_collection_cache(collection_id)

            assert count == 2
            mock_redis.smembers.assert_called_once_with(tracking_key)
            # delete() should be called with all cache keys + the tracking key itself
            call_args = mock_redis.delete.call_args[0]
            assert tracking_key in call_args
            for k in cached_keys:
                assert k in call_args

    def test_invalidate_collection_cache_returns_zero_when_no_keys(self):
        """invalidate_collection_cache() should return 0 when no keys tracked."""
        with patch(
            "app.services.openrouter_service._get_redis_client"
        ) as mock_redis_get:
            mock_redis = MagicMock()
            mock_redis.smembers.return_value = set()
            mock_redis_get.return_value = mock_redis

            service = OpenRouterService()
            service._cache_enabled = True

            count = service.invalidate_collection_cache("col-empty")

            assert count == 0
            mock_redis.delete.assert_not_called()

    def test_invalidate_collection_cache_returns_zero_when_cache_disabled(self):
        """invalidate_collection_cache() should be a no-op when cache is disabled."""
        service = OpenRouterService()
        service._cache_enabled = False

        count = service.invalidate_collection_cache("col-disabled")

        assert count == 0

    def test_invalidate_collection_cache_handles_redis_error(self):
        """invalidate_collection_cache() should handle Redis errors gracefully."""
        with patch(
            "app.services.openrouter_service._get_redis_client"
        ) as mock_redis_get:
            mock_redis = MagicMock()
            mock_redis.smembers.side_effect = Exception("Redis connection lost")
            mock_redis_get.return_value = mock_redis

            service = OpenRouterService()
            service._cache_enabled = True

            # Should not raise, should return 0
            count = service.invalidate_collection_cache("col-error")

            assert count == 0

    @pytest.mark.asyncio
    async def test_collection_id_tracks_cache_key_on_miss(self):
        """collection_id parameter should track the cache key in Redis SET on cache miss."""
        collection_id = "col-xyz-789"

        with patch(
            "app.services.openrouter_service._get_redis_client"
        ) as mock_redis_get:
            with patch("httpx.AsyncClient") as mock_client:
                mock_redis = MagicMock()
                mock_redis.get.return_value = None
                mock_redis_get.return_value = mock_redis

                mock_response = MagicMock()
                mock_response.json.return_value = {
                    "choices": [{"message": {"content": "Collection response"}}],
                }
                mock_response.raise_for_status = MagicMock()

                mock_cm = AsyncMock()
                mock_cm.__aenter__.return_value.post = AsyncMock(
                    return_value=mock_response
                )
                mock_client.return_value = mock_cm

                service = OpenRouterService()
                service._cache_enabled = True
                service.api_key = "test-key"

                messages = [{"role": "user", "content": "Collection query"}]
                async for _ in service.chat_completion(
                    messages, stream=False, collection_id=collection_id
                ):
                    pass

                # sadd should be called with the tracking key and the cache key
                tracking_key = f"{COLLECTION_CACHE_KEYS_PREFIX}{collection_id}"
                mock_redis.sadd.assert_called_once()
                sadd_args = mock_redis.sadd.call_args[0]
                assert sadd_args[0] == tracking_key
                # The second arg is the cache key (starts with CACHE_KEY_PREFIX)
                assert sadd_args[1].startswith(CACHE_KEY_PREFIX)
                # TTL must be set on the tracking set
                mock_redis.expire.assert_called_once_with(tracking_key, CACHE_TTL_SECONDS)

    @pytest.mark.asyncio
    async def test_no_collection_id_does_not_track_key(self):
        """Without collection_id, sadd should not be called."""
        with patch(
            "app.services.openrouter_service._get_redis_client"
        ) as mock_redis_get:
            with patch("httpx.AsyncClient") as mock_client:
                mock_redis = MagicMock()
                mock_redis.get.return_value = None
                mock_redis_get.return_value = mock_redis

                mock_response = MagicMock()
                mock_response.json.return_value = {
                    "choices": [{"message": {"content": "Response"}}],
                }
                mock_response.raise_for_status = MagicMock()

                mock_cm = AsyncMock()
                mock_cm.__aenter__.return_value.post = AsyncMock(
                    return_value=mock_response
                )
                mock_client.return_value = mock_cm

                service = OpenRouterService()
                service._cache_enabled = True
                service.api_key = "test-key"

                messages = [{"role": "user", "content": "Query without collection"}]
                async for _ in service.chat_completion(messages, stream=False):
                    pass

                mock_redis.sadd.assert_not_called()
