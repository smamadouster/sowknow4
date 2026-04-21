"""
OpenRouter service for LLM access — Mistral Small 2603 fallback
OpenRouter provides OpenAI-compatible API access to multiple LLMs.
Used as the fallback when MiniMax M2.7 direct API is unavailable.

CONTEXT CACHING:
- Redis-backed cache for repeated queries to reduce API costs
- Cache key = SHA256(model + sorted messages content)
- TTL = 1 hour for public document responses
- Metrics tracked via cache_monitor service
- Ollama (confidential) responses are NEVER cached - handled by caller
"""

import hashlib
import json
import logging
import os
from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Configuration
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "mistralai/mistral-small-2603")
OPENROUTER_SITE_URL = os.getenv("OPENROUTER_SITE_URL", "https://sowknow.gollamtech.com")
OPENROUTER_SITE_NAME = os.getenv("OPENROUTER_SITE_NAME", "SOWKNOW")

# Redis configuration for context caching
from app.core.redis_url import safe_redis_url

REDIS_URL = safe_redis_url()
CACHE_TTL_SECONDS = 3600  # 1 hour TTL for cached responses
CACHE_KEY_PREFIX = "sowknow:openrouter:cache:"

# Context window limits (in tokens)
MISTRAL_CONTEXT_WINDOW = 32000  # Mistral Small 2603 supports 32K
MAX_INPUT_TOKENS = 28000  # Leave buffer for response

# Collection cache key tracking (for invalidation)
COLLECTION_CACHE_KEYS_PREFIX = "sowknow:openrouter:collection_keys:"

# Redis client (lazy initialization)
_redis_client = None


def _get_redis_client():
    """Get or create Redis client for caching."""
    global _redis_client
    if _redis_client is None:
        try:
            import redis

            _redis_client = redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=5, socket_connect_timeout=5)
            _redis_client.ping()
            logger.info("OpenRouter cache: Redis connection established")
        except Exception as e:
            logger.warning(f"OpenRouter cache: Redis unavailable, caching disabled: {e}")
            _redis_client = None
    return _redis_client


class OpenRouterService:
    """Service for interacting with OpenRouter API (OpenAI-compatible)

    FEATURES:
    - Redis-backed context caching for cost optimization
    - Automatic cache key generation from model + messages
    - Integration with cache_monitor for metrics tracking
    """

    def __init__(self):
        self.api_key = OPENROUTER_API_KEY
        self.base_url = OPENROUTER_BASE_URL
        self.model = OPENROUTER_MODEL
        self.site_url = OPENROUTER_SITE_URL
        self.site_name = OPENROUTER_SITE_NAME
        self._cache_enabled = False

        if self.api_key:
            logger.info(f"OpenRouter service initialized with model: {self.model}")
        else:
            logger.warning("OPENROUTER_API_KEY not configured")

        # Check if caching is available
        try:
            redis_client = _get_redis_client()
            if redis_client:
                self._cache_enabled = True
                logger.info("OpenRouter context caching enabled")
        except Exception:
            logger.info("OpenRouter context caching disabled (Redis unavailable)")

    def _generate_cache_key(self, model: str, messages: list[dict[str, str]]) -> str:
        """Generate a deterministic cache key from model and messages.

        Cache key = SHA256(model + sorted messages content)
        This ensures identical requests get the same cache key regardless of
        message order while maintaining content-based uniqueness.

        Args:
            model: The model identifier
            messages: List of message dicts with role and content

        Returns:
            SHA256 hash string prefixed with cache namespace
        """
        # Sort messages by role+content for deterministic ordering
        sorted_messages = sorted(messages, key=lambda m: f"{m.get('role', '')}:{m.get('content', '')}")

        # Create a canonical string representation
        cache_content = f"{model}:{json.dumps(sorted_messages, sort_keys=True)}"

        # Generate SHA256 hash
        cache_hash = hashlib.sha256(cache_content.encode("utf-8")).hexdigest()

        return f"{CACHE_KEY_PREFIX}{cache_hash}"

    def check_cache(self, messages: list[dict[str, str]]) -> str | None:
        """Check Redis cache for a previously computed non-streaming response.

        Used by the streaming pipeline to detect cache hits before issuing an
        LLM call, so the `cache_hit` SSE flag can be set accurately.

        Returns:
            Cached response string if found, else None.
        """
        if not self._cache_enabled:
            return None
        cache_key = self._generate_cache_key(self.model, messages)
        redis_client = _get_redis_client()
        if not redis_client:
            return None
        try:
            cached = redis_client.get(cache_key)
            return str(cached) if cached else None
        except Exception as e:
            logger.debug(f"Cache check error: {e}")
            return None

    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count using simple character-based approximation"""
        if not text:
            return 0
        return len(text) // 4

    def _truncate_messages(
        self, messages: list[dict[str, str]], max_tokens: int = MAX_INPUT_TOKENS
    ) -> list[dict[str, str]]:
        """Truncate messages to fit within context window"""
        total_tokens = 0
        truncated_messages = []

        for msg in messages:
            content = msg.get("content", "")
            msg_tokens = self._estimate_tokens(content)

            if total_tokens + msg_tokens > max_tokens:
                available = max_tokens - total_tokens
                if available > 100:
                    truncated_content = content[: available * 4]
                    truncated_messages.append(
                        {
                            "role": msg.get("role", "user"),
                            "content": truncated_content + "... [truncated]",
                        }
                    )
                break

            truncated_messages.append(msg)
            total_tokens += msg_tokens

        return truncated_messages

    def _get_headers(self) -> dict[str, str]:
        """Get headers for OpenRouter API requests"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if self.site_url:
            headers["HTTP-Referer"] = self.site_url
        if self.site_name:
            headers["X-Title"] = self.site_name
        return headers

    async def chat_completion(
        self,
        messages: list[dict[str, str]],
        stream: bool = False,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        cache_key: str | None = None,
        user_id: str | None = None,
        is_confidential: bool = False,
        collection_id: str | None = None,
    ) -> AsyncGenerator[str, None]:
        """
        Generate chat completion using OpenRouter (OpenAI-compatible API)

        CONTEXT CACHING:
        - Non-streaming requests are cached in Redis for 1 hour
        - Cache key = SHA256(model + sorted messages) if not provided
        - Streaming requests bypass cache (not useful for streaming)
        - Confidential/PII queries are NEVER cached (is_confidential=True)
        - Cache metrics tracked via cache_monitor service
        - Collection-scoped keys tracked for bulk invalidation

        Args:
            messages: List of message dicts with role and content
            stream: Whether to stream the response (bypasses cache if True)
            temperature: Sampling temperature (0.0 to 1.0)
            max_tokens: Maximum tokens to generate
            cache_key: Optional pre-computed cache key (auto-generated if None)
            user_id: Optional user ID for cache metrics tracking
            is_confidential: When True, skip all caching (privacy guarantee)
            collection_id: Optional collection ID for cache invalidation tracking

        Yields:
            Response text chunks if streaming, full content if not
        """
        from app.services.cache_monitor import cache_monitor

        if not self.api_key:
            logger.error("OPENROUTER_API_KEY not configured")
            yield "Error: OpenRouter API key not configured"
            return

        # Enforce context window limit
        truncated_messages = self._truncate_messages(messages)

        # Check if truncation occurred
        original_tokens = sum(self._estimate_tokens(m.get("content", "")) for m in messages)
        truncated_tokens = sum(self._estimate_tokens(m.get("content", "")) for m in truncated_messages)

        if original_tokens > truncated_tokens:
            logger.warning(
                f"Input truncated from ~{original_tokens} to ~{truncated_tokens} tokens to fit context window"
            )

        # Generate cache key if not provided and caching is enabled
        # PRIVACY: confidential/PII queries are NEVER cached
        effective_cache_key = None
        if self._cache_enabled and not stream and not is_confidential:
            effective_cache_key = cache_key or self._generate_cache_key(self.model, truncated_messages)

            # Check cache for non-streaming requests
            redis_client = _get_redis_client()
            if redis_client and effective_cache_key:
                try:
                    cached_response = redis_client.get(effective_cache_key)
                    if cached_response and isinstance(cached_response, str):
                        logger.info(f"OpenRouter cache HIT: key={effective_cache_key[:50]}...")
                        # Record cache hit metrics
                        try:
                            tokens_saved = self._estimate_tokens(cached_response)
                            cache_monitor.record_cache_hit(
                                cache_key=effective_cache_key,
                                tokens_saved=tokens_saved,
                                user_id=user_id,
                            )
                        except Exception as metric_error:
                            logger.warning(f"Failed to record cache hit metric: {metric_error}")

                        yield str(cached_response)
                        return
                except Exception as e:
                    logger.warning(f"Cache read error, proceeding with API call: {e}")

            # Record cache miss (we're about to make an API call)
            logger.debug(f"OpenRouter cache MISS: key={effective_cache_key[:50] if effective_cache_key else 'N/A'}...")
            try:
                cache_monitor.record_cache_miss(
                    cache_key=effective_cache_key or "no_key",
                    user_id=user_id,
                )
            except Exception as metric_error:
                logger.warning(f"Failed to record cache miss metric: {metric_error}")

        payload = {
            "model": self.model,
            "messages": truncated_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                if stream:
                    async with client.stream(
                        "POST",
                        f"{self.base_url}/chat/completions",
                        headers=self._get_headers(),
                        json=payload,
                    ) as response:
                        response.raise_for_status()

                        async for line in response.aiter_lines():
                            if line.strip():
                                if line.startswith("data: "):
                                    data_str = line[6:]  # Remove "data: " prefix
                                    if data_str == "[DONE]":
                                        break
                                    try:
                                        data = json.loads(data_str)
                                        if "choices" in data and len(data["choices"]) > 0:
                                            delta = data["choices"][0].get("delta", {})
                                            content = delta.get("content", "")
                                            if content:
                                                yield content
                                    except json.JSONDecodeError:
                                        continue
                else:
                    response = await client.post(
                        f"{self.base_url}/chat/completions",
                        headers=self._get_headers(),
                        json=payload,
                    )
                    response.raise_for_status()
                    result = response.json()

                    if "choices" in result and len(result["choices"]) > 0:
                        content = result["choices"][0].get("message", {}).get("content", "")
                        usage = result.get("usage", {})

                        # Cache the response for future requests
                        # PRIVACY: is_confidential check is already handled above —
                        # effective_cache_key is None when is_confidential=True
                        if self._cache_enabled and effective_cache_key and content:
                            redis_client = _get_redis_client()
                            if redis_client:
                                try:
                                    redis_client.setex(
                                        effective_cache_key,
                                        CACHE_TTL_SECONDS,
                                        content,
                                    )
                                    logger.info(
                                        f"OpenRouter cached response: key={effective_cache_key[:50]}..., ttl={CACHE_TTL_SECONDS}s"
                                    )
                                    # Track key under collection for bulk invalidation
                                    if collection_id:
                                        tracking_key = f"{COLLECTION_CACHE_KEYS_PREFIX}{collection_id}"
                                        redis_client.sadd(tracking_key, effective_cache_key)
                                        redis_client.expire(tracking_key, CACHE_TTL_SECONDS)
                                except Exception as cache_error:
                                    logger.warning(f"Failed to cache response: {cache_error}")

                        yield content

                        # Return usage as last chunk
                        if usage:
                            yield f"\n__USAGE__: {json.dumps(usage)}"
                    else:
                        logger.error(f"Unexpected OpenRouter response: {result}")
                        yield "Error: Unexpected response from OpenRouter API"

        except httpx.HTTPStatusError as e:
            error_body = ""
            try:
                error_body = e.response.text
            except (AttributeError, KeyError):
                pass

            # Handle rate limit (429) errors with specific retry trigger
            if e.response.status_code == 429:
                logger.warning("OpenRouter rate limit hit (429), will retry with backoff")
                # Re-raise to trigger tenacity retry with exponential backoff
                raise

            logger.error(f"OpenRouter API error: {e} - {error_body}")
            yield f"Error: API error - {e.response.status_code if e.response else 'unknown'}"
        except httpx.HTTPError as e:
            logger.error(f"OpenRouter connection error: {str(e)}")
            yield f"Error: {str(e)}"

    def invalidate_collection_cache(self, collection_id: str) -> int:
        """Invalidate all cached responses associated with a collection.

        Call this when a document in the collection is updated or deleted so
        stale responses are not served from cache.

        Redis key schema:
          Tracking set : sowknow:openrouter:collection_keys:{collection_id}
          Cache entries: sowknow:openrouter:cache:{sha256_hash}

        Args:
            collection_id: UUID string of the collection to invalidate

        Returns:
            Number of cache entries invalidated (0 if none or Redis unavailable)
        """
        if not self._cache_enabled:
            return 0
        redis_client = _get_redis_client()
        if not redis_client:
            return 0

        tracking_key = f"{COLLECTION_CACHE_KEYS_PREFIX}{collection_id}"
        try:
            cache_keys = redis_client.smembers(tracking_key)
            if not cache_keys:
                logger.debug(f"Cache invalidation: no keys tracked for collection {collection_id}")
                return 0

            keys_to_delete = list(cache_keys) + [tracking_key]
            redis_client.delete(*keys_to_delete)
            count = len(cache_keys)
            logger.info(f"Cache invalidation: removed {count} entries for collection {collection_id}")
            return count
        except Exception as e:
            logger.warning(f"Cache invalidation error for collection {collection_id}: {e}")
            return 0

    async def health_check(self) -> dict[str, Any]:
        """
        Check OpenRouter service health

        Returns:
            Health status dictionary
        """
        health_status = {
            "service": "openrouter",
            "status": "healthy",
            "model": self.model,
            "api_configured": bool(self.api_key),
            "timestamp": datetime.utcnow().isoformat(),
        }

        if not self.api_key:
            health_status["status"] = "unhealthy"
            health_status["error"] = "API key not configured"
            return health_status

        # Test API connectivity with a simple request
        try:
            test_messages = [{"role": "user", "content": "test"}]
            response_text = ""
            async for chunk in self.chat_completion(test_messages, stream=False, max_tokens=10):
                if not chunk.startswith("__USAGE__"):
                    response_text += chunk

            if response_text:
                health_status["status"] = "healthy"
                health_status["api_reachable"] = True
            else:
                health_status["status"] = "degraded"
                health_status["error"] = "API returned empty response"

        except Exception as e:
            health_status["status"] = "unhealthy"
            health_status["error"] = str(e)
            health_status["api_reachable"] = False

        return health_status

    async def get_usage_stats(self) -> dict[str, Any]:
        """
        Get usage statistics for the service

        Returns:
            Usage statistics dictionary
        """
        return {
            "service": "openrouter",
            "model": self.model,
            "config": {
                "base_url": self.base_url,
            },
            "timestamp": datetime.utcnow().isoformat(),
        }

    async def list_models(self) -> list[dict[str, Any]]:
        """
        List available models from OpenRouter

        Returns:
            List of model dictionaries
        """
        if not self.api_key:
            return []

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(f"{self.base_url}/models", headers=self._get_headers())
                response.raise_for_status()
                result = response.json()
                return result.get("data", [])
        except Exception as e:
            logger.error(f"Error listing models: {str(e)}")
            return []


# Global OpenRouter service instance
openrouter_service = OpenRouterService()
