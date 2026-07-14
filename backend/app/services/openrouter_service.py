"""
OpenRouter service for LLM access — Mistral Small primary
OpenRouter provides OpenAI-compatible API access to multiple LLMs.
Primary model: mistralai/mistral-small-2409 (best FR/EN balance for family narrative).
Tiered stack: simple=google/gemini-2.0-flash-001, standard=mistralai/mistral-small-2409,
complex=anthropic/claude-3.5-sonnet.

CONTEXT CACHING:
- Redis-backed cache for repeated queries to reduce API costs
- Cache key = SHA256(model + sorted messages content)
- TTL = 1 hour for public document responses
- Metrics tracked via cache_monitor service
- Confidential responses are NEVER cached - handled by caller
"""

import asyncio
import hashlib
import json
import logging
import os
from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
    RetryCallState,
)

logger = logging.getLogger(__name__)

# Configuration
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "mistralai/mistral-small-2409")

# Tiered model configuration for cost/quality optimization
OPENROUTER_TIER_MODELS = {
    "complex": os.getenv("OPENROUTER_TIER_COMPLEX", "anthropic/claude-3.5-sonnet"),
    "standard": os.getenv("OPENROUTER_TIER_STANDARD", "mistralai/mistral-small-2409"),
    "simple": os.getenv("OPENROUTER_TIER_SIMPLE", "google/gemini-2.0-flash-001"),
}
OPENROUTER_TIER_BUDGET_PCT = {
    "complex": 0.5,  # 50% of daily budget reserved for complex tasks
    "standard": 0.35,  # 35% for standard tasks
    "simple": 0.15,  # 15% for simple tasks (free tier)
}
OPENROUTER_SITE_URL = os.getenv("OPENROUTER_SITE_URL", "https://sowknow.gollamtech.com")
OPENROUTER_SITE_NAME = os.getenv("OPENROUTER_SITE_NAME", "SOWKNOW")

# OpenRouter native response caching (beta) — https://openrouter.ai/docs/features/cache
OPENROUTER_RESPONSE_CACHE_ENABLED = os.getenv(
    "OPENROUTER_RESPONSE_CACHE_ENABLED", "false"
).lower() in ("true", "1", "yes")
OPENROUTER_RESPONSE_CACHE_TTL = int(os.getenv("OPENROUTER_RESPONSE_CACHE_TTL", "300"))

# Redis configuration for context caching
from app.core.redis_url import safe_redis_url

REDIS_URL = safe_redis_url()
CACHE_TTL_SECONDS = 3600  # 1 hour TTL for cached responses
CACHE_KEY_PREFIX = "sowknow:openrouter:cache:"

# Context window limits (in tokens)
DEEPSEEK_CONTEXT_WINDOW = 1_000_000  # DeepSeek V4 Pro supports 1M tokens
MAX_INPUT_TOKENS = 128_000  # Conservative limit to manage cost/latency

# Collection cache key tracking (for invalidation)
COLLECTION_CACHE_KEYS_PREFIX = "sowknow:openrouter:collection_keys:"

# Redis client (lazy initialization)
_redis_client = None


def close_redis_client() -> None:
    """Close the module-level Redis client singleton (lifespan shutdown)."""
    global _redis_client
    if _redis_client is not None:
        try:
            _redis_client.close()
        except Exception:
            pass
        _redis_client = None


def _get_redis_client():
    """Get or create Redis client for caching."""
    global _redis_client
    if _redis_client is None:
        try:
            import redis

            _redis_client = redis.from_url(
                REDIS_URL,
                decode_responses=True,
                socket_timeout=5,
                socket_connect_timeout=5,
            )
            _redis_client.ping()
            logger.info("OpenRouter cache: Redis connection established")
        except Exception as e:
            logger.warning(
                f"OpenRouter cache: Redis unavailable, caching disabled: {e}"
            )
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
        self._tier_models = OPENROUTER_TIER_MODELS
        self._tier_budget_pct = OPENROUTER_TIER_BUDGET_PCT
        self._or_cache_enabled = OPENROUTER_RESPONSE_CACHE_ENABLED
        self._or_cache_ttl = OPENROUTER_RESPONSE_CACHE_TTL

        if self.api_key:
            logger.info(
                f"OpenRouter service initialized with primary model: {self.model}"
            )
            logger.info(
                f"OpenRouter tier config: complex={self._tier_models['complex']}, "
                f"standard={self._tier_models['standard']}, simple={self._tier_models['simple']}"
            )
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

    def _generate_cache_key(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        tier: str = "standard",
        collection_id: str | None = None,
    ) -> str:
        """Generate a deterministic cache key scoped by model, tier, collection and messages.

        Including ``collection_id`` prevents identical messages in different
        collections from colliding; including ``tier`` prevents different model
        quality tiers from sharing a cached response.

        Args:
            model: The model identifier.
            messages: List of message dicts with role and content.
            tier: Task tier used for model selection.
            collection_id: Optional collection/workspace scope.

        Returns:
            SHA256 hash string prefixed with cache namespace.
        """
        scope = collection_id or "global"
        cache_content = (
            f"{model}:{tier}:{scope}:"
            f"{json.dumps(messages, separators=(',', ':'), ensure_ascii=False)}"
        )
        cache_hash = hashlib.sha256(cache_content.encode("utf-8")).hexdigest()
        return f"{CACHE_KEY_PREFIX}{cache_hash}"

    def check_cache(
        self,
        messages: list[dict[str, str]],
        *,
        tier: str = "standard",
        collection_id: str | None = None,
    ) -> str | None:
        """Check Redis cache for a previously computed non-streaming response.

        Used by the streaming pipeline to detect cache hits before issuing an
        LLM call, so the `cache_hit` SSE flag can be set accurately.

        Returns:
            Cached response string if found, else None.
        """
        if not self._cache_enabled:
            return None
        cache_key = self._generate_cache_key(
            self.model, messages, tier=tier, collection_id=collection_id
        )
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
        """Estimate token count via shared utility (§7.4)."""
        from app.services.token_utils import estimate_tokens

        return estimate_tokens(text)

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

    def _get_headers(
        self, cache_enabled: bool | None = None, cache_ttl: int | None = None
    ) -> dict[str, str]:
        """Get headers for OpenRouter API requests"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if self.site_url:
            headers["HTTP-Referer"] = self.site_url
        if self.site_name:
            headers["X-Title"] = self.site_name

        use_cache = (
            cache_enabled if cache_enabled is not None else self._or_cache_enabled
        )
        use_ttl = cache_ttl if cache_ttl is not None else self._or_cache_ttl
        if use_cache:
            headers["X-OpenRouter-Cache"] = "true"
            if use_ttl:
                headers["X-OpenRouter-Cache-TTL"] = str(use_ttl)
        return headers

    def select_model_for_tier(self, tier: str = "standard") -> str:
        """Select the appropriate model for a task tier.

        Tiers:
            - "simple":   Cheap/free models for classification, tagging, intent
            - "standard": Balanced models for chat, synthesis, articles
            - "complex":  Frontier models for reasoning, coding, verification

        Returns:
            Model identifier string for the given tier.
        """
        model = self._tier_models.get(tier, self.model)
        logger.debug(f"OpenRouter tier routing: {tier} -> {model}")
        return model

    def _check_cost_ceiling(
        self,
        estimated_input_tokens: int,
        estimated_output_tokens: int,
        tier: str = "standard",
        user_id: str | None = None,
        user_role: str | None = None,
    ) -> bool:
        """Check if a call would exceed the cost ceiling.

        Returns True if the call is allowed, False if it would exceed budget.
        """
        try:
            from app.services.monitoring import get_cost_ceiling

            ceiling = get_cost_ceiling()
            return ceiling.check_call_allowed(
                service="openrouter",
                model=self.select_model_for_tier(tier),
                estimated_input_tokens=estimated_input_tokens,
                estimated_output_tokens=estimated_output_tokens,
                tier=tier,
                user_id=user_id,
                user_role=user_role,
            )
        except Exception as e:
            logger.warning(f"Cost ceiling check failed, allowing call: {e}")
            return True

    def _check_cost_anomaly(
        self,
        estimated_input_tokens: int,
        estimated_output_tokens: int,
        tier: str = "standard",
    ) -> str:
        """§5.2 Cost-anomaly fallback — downgrade tier if per-query cost spikes.

        Returns the tier to use (may be downgraded to 'simple').
        """
        COST_ANOMALY_THRESHOLD_USD = float(
            os.getenv("OPENROUTER_COST_ANOMALY_THRESHOLD", "0.05")
        )
        if tier not in ("standard", "complex"):
            return tier

        # Look up actual pricing from CostTracker for accurate estimation
        try:
            from app.services.monitoring import CostTracker

            model = self.select_model_for_tier(tier)
            rates = CostTracker.OPENROUTER_PRICING.get(
                model, {"input": 0.0002, "output": 0.0006}
            )
            est_cost = (
                (estimated_input_tokens / 1000) * rates["input"]
                + (estimated_output_tokens / 1000) * rates["output"]
            )
            if est_cost > COST_ANOMALY_THRESHOLD_USD:
                logger.warning(
                    "Cost anomaly detected: $%.4f > $%.2f, downgrading tier %s → simple",
                    est_cost,
                    COST_ANOMALY_THRESHOLD_USD,
                    tier,
                )
                return "simple"
        except Exception as exc:
            logger.debug("Cost anomaly check failed, keeping tier=%s: %s", tier, exc)
        return tier

    def _before_sleep_on_retry(self, retry_state: RetryCallState) -> None:
        """Callback invoked before each tenacity retry.

        Records 429s for adaptive backoff and warns on free-tier fallbacks.
        """
        exc = retry_state.outcome.exception() if retry_state.outcome else None
        if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429:
            from app.services.openrouter_throttle import openrouter_throttle

            openrouter_throttle.record_429(self.model)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_random_exponential(multiplier=1, min=1, max=15),
        retry=retry_if_exception_type(
            (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException)
        ),
        reraise=True,
        before_sleep=_before_sleep_on_retry,
    )
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
        tier: str = "standard",
        use_openrouter_cache: bool | None = None,
        openrouter_cache_ttl: int | None = None,
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
        original_tokens = sum(
            self._estimate_tokens(m.get("content", "")) for m in messages
        )
        truncated_tokens = sum(
            self._estimate_tokens(m.get("content", "")) for m in truncated_messages
        )

        if original_tokens > truncated_tokens:
            logger.warning(
                f"Input truncated from ~{original_tokens} to ~{truncated_tokens} tokens to fit context window"
            )

        # OpenRouter native response caching (beta)
        or_cache_enabled = (
            use_openrouter_cache
            if use_openrouter_cache is not None
            else OPENROUTER_RESPONSE_CACHE_ENABLED
        )
        or_cache_ttl = (
            openrouter_cache_ttl
            if openrouter_cache_ttl is not None
            else OPENROUTER_RESPONSE_CACHE_TTL
        )
        # PRIVACY: never use provider-side caching for confidential queries
        if is_confidential:
            or_cache_enabled = False

        # Generate cache key if not provided and caching is enabled
        # PRIVACY: confidential/PII queries are NEVER cached
        effective_cache_key = None
        if self._cache_enabled and not stream and not is_confidential:
            model = self.select_model_for_tier(tier)
            effective_cache_key = cache_key or self._generate_cache_key(
                model, truncated_messages, tier=tier, collection_id=collection_id
            )

            # Check cache for non-streaming requests
            redis_client = _get_redis_client()
            if redis_client and effective_cache_key:
                try:
                    cached_response = await asyncio.to_thread(
                        redis_client.get, effective_cache_key
                    )
                    if cached_response and isinstance(cached_response, str):
                        logger.info(
                            f"OpenRouter cache HIT: key={effective_cache_key[:50]}..."
                        )
                        # Record cache hit metrics
                        try:
                            tokens_saved = self._estimate_tokens(cached_response)
                            cache_monitor.record_cache_hit(
                                cache_key=effective_cache_key,
                                tokens_saved=tokens_saved,
                                user_id=user_id,
                            )
                            from app.services.prometheus_metrics import get_metrics

                            get_metrics().counter("sowknow_cache_hits_total").inc(
                                labels={"cache_type": "openrouter_exact"}
                            )
                        except Exception as metric_error:
                            logger.warning(
                                f"Failed to record cache hit metric: {metric_error}"
                            )

                        yield str(cached_response)
                        return
                except Exception as e:
                    logger.warning(f"Cache read error, proceeding with API call: {e}")

            # Record cache miss (we're about to make an API call)
            logger.debug(
                f"OpenRouter cache MISS: key={effective_cache_key[:50] if effective_cache_key else 'N/A'}..."
            )
            try:
                cache_monitor.record_cache_miss(
                    cache_key=effective_cache_key or "no_key",
                    user_id=user_id,
                )
                from app.services.prometheus_metrics import get_metrics

                get_metrics().counter("sowknow_cache_misses_total").inc(
                    labels={"cache_type": "openrouter_exact"}
                )
            except Exception as metric_error:
                logger.warning(f"Failed to record cache miss metric: {metric_error}")

        # --- Cost ceiling pre-flight check ---
        est_input = sum(
            self._estimate_tokens(m.get("content", "")) for m in truncated_messages
        )
        est_output = max_tokens
        if not self._check_cost_ceiling(est_input, est_output, tier=tier):
            logger.error(
                f"OpenRouter call BLOCKED by cost ceiling (tier={tier}, est_input={est_input}, est_output={est_output})"
            )
            yield "Error: LLM cost ceiling reached. Please try again later or contact support."
            return

        # §5.2: Cost-anomaly fallback — downgrade tier if query cost spikes
        effective_tier = self._check_cost_anomaly(est_input, est_output, tier)
        if effective_tier != tier:
            tier = effective_tier

        model = self.select_model_for_tier(tier)

        # --- Provider-aware dynamic throttling (blueprint §2.3 Tier C) ---
        from app.services.openrouter_throttle import openrouter_throttle

        if not openrouter_throttle.check_allowed(model):
            logger.warning(
                "OpenRouter call BLOCKED by throttle (tier=%s, model=%s)",
                tier,
                model,
            )
            yield "Error: Rate limit reached. Please try again in a moment."
            return

        payload = {
            "model": model,
            "messages": truncated_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }

        from app.services.llm_http_client import LLMHTTPClient

        try:
            client = LLMHTTPClient.get_client()
            if stream:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    headers=self._get_headers(
                        cache_enabled=or_cache_enabled, cache_ttl=or_cache_ttl
                    ),
                    json=payload,
                ) as response:
                    response.raise_for_status()
                    # Log OpenRouter native cache status
                    cache_status = getattr(response, "headers", {}).get(
                        "X-OpenRouter-Cache-Status"
                    )
                    if cache_status:
                        logger.info(
                            f"OpenRouter native cache {cache_status}: "
                            f"tier={tier}, model={model}, stream=True"
                        )

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
                    # Record successful streaming request for throttle accounting
                    openrouter_throttle.record_request(model)
            else:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=self._get_headers(
                        cache_enabled=or_cache_enabled, cache_ttl=or_cache_ttl
                    ),
                    json=payload,
                )
                response.raise_for_status()
                # Log OpenRouter native cache status
                cache_status = getattr(response, "headers", {}).get(
                    "X-OpenRouter-Cache-Status"
                )
                if cache_status:
                    logger.info(
                        f"OpenRouter native cache {cache_status}: "
                        f"tier={tier}, model={model}, stream=False"
                    )
                    if cache_status == "HIT":
                        cache_age = getattr(response, "headers", {}).get(
                            "X-OpenRouter-Cache-Age"
                        )
                        cache_ttl_remaining = getattr(response, "headers", {}).get(
                            "X-OpenRouter-Cache-TTL"
                        )
                        logger.debug(
                            f"OpenRouter cache age={cache_age}s, "
                            f"ttl_remaining={cache_ttl_remaining}s"
                        )
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
                                await asyncio.to_thread(
                                    redis_client.setex,
                                    effective_cache_key,
                                    CACHE_TTL_SECONDS,
                                    content,
                                )
                                logger.info(
                                    f"OpenRouter cached response: key={effective_cache_key[:50]}..., ttl={CACHE_TTL_SECONDS}s"
                                )
                                # Track key under collection for bulk invalidation
                                if collection_id:
                                    tracking_key = (
                                        f"{COLLECTION_CACHE_KEYS_PREFIX}{collection_id}"
                                    )
                                    await asyncio.to_thread(
                                        redis_client.sadd,
                                        tracking_key,
                                        effective_cache_key,
                                    )
                                    await asyncio.to_thread(
                                        redis_client.expire,
                                        tracking_key,
                                        CACHE_TTL_SECONDS,
                                    )
                            except Exception as cache_error:
                                logger.warning(
                                    f"Failed to cache response: {cache_error}"
                                )

                    # Record successful non-streaming request for throttle accounting
                    openrouter_throttle.record_request(model)

                    # Record actual cost for budget tracking
                    try:
                        from app.services.monitoring import get_cost_tracker

                        tracker = get_cost_tracker()
                        tracker.record_api_call(
                            service="openrouter",
                            operation="chat",
                            model=model,
                            input_tokens=(
                                usage.get("prompt_tokens", 0) if usage else est_input
                            ),
                            output_tokens=(
                                usage.get("completion_tokens", 0) if usage else 0
                            ),
                        )
                    except Exception as cost_err:
                        logger.debug(f"Cost tracking failed: {cost_err}")

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
                logger.warning(
                    "OpenRouter rate limit hit (429), will retry with backoff"
                )
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
                logger.debug(
                    f"Cache invalidation: no keys tracked for collection {collection_id}"
                )
                return 0

            keys_to_delete = list(cache_keys) + [tracking_key]
            redis_client.delete(*keys_to_delete)
            count = len(cache_keys)
            logger.info(
                f"Cache invalidation: removed {count} entries for collection {collection_id}"
            )
            return count
        except Exception as e:
            logger.warning(
                f"Cache invalidation error for collection {collection_id}: {e}"
            )
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
            "tier_models": self._tier_models,
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
            async for chunk in self.chat_completion(
                test_messages, stream=False, max_tokens=10
            ):
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
            client = LLMHTTPClient.get_client()
            response = await client.get(
                f"{self.base_url}/models", headers=self._get_headers()
            )
            response.raise_for_status()
            result = response.json()
            return result.get("data", [])
        except Exception as e:
            logger.error(f"Error listing models: {str(e)}")
            return []


# Global OpenRouter service instance
openrouter_service = OpenRouterService()
