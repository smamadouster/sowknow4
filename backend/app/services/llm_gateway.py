"""
LLM Gateway — Unified facade for all LLM providers.

This module is the SINGLE entry point for LLM consumption across Sowknow.
It wraps the existing LLMRouter with a simplified, consumer-friendly interface,
eliminating the need for direct imports of individual services
(openrouter_service, minimax_service, kimi_service, ollama_service).

Migration example (consumer code):
    OLD:
        from app.services.openrouter_service import openrouter_service
        from app.services.minimax_service import minimax_service
        async for chunk in openrouter_service.chat_completion(messages):
            ...
        # Fallback manually if openrouter fails ...

    NEW:
        from app.services.llm_gateway import llm_gateway
        async for chunk in llm_gateway.chat_completion(messages, tier="standard"):
            ...
        # Routing, fallback, and PII detection are automatic.

Benefits:
  - No provider-specific logic in consumers.
  - Centralized fallback chains.
  - Automatic PII/confidential-data routing to local Ollama.
  - Tiered model selection (simple/standard/complex).
  - Easier to add/remove providers without touching N files.
"""

import asyncio
import logging
import time
from collections.abc import AsyncGenerator
from typing import Any

from app.core.context import current_user_id, current_user_role
from app.services.llm_router import LLMRouter, TaskTier, _build_router

logger = logging.getLogger(__name__)

# Module-level concurrency caps per blueprint §2.3
# Protects expensive report generation from starving latency-sensitive chat.
_MODULE_SEMAPHORES: dict[str, asyncio.Semaphore] = {
    "chat": asyncio.Semaphore(10),
    "collections": asyncio.Semaphore(2),
    "smart_folders": asyncio.Semaphore(3),
    "knowledge_graph": asyncio.Semaphore(2),
}

# Task-aware default tier mapping (blueprint §3.3)
# When a consumer omits the *tier* arg (defaults to "standard"), we can
# infer a more appropriate tier from the *module* name.
_TASK_TIER_MAP: dict[str, str] = {
    "knowledge_graph": "simple",   # entity extraction → Gemini Flash (cheap, fast JSON)
    "chat": "standard",            # conversational RAG → Mistral Small
    "collections": "complex",      # comprehensive reports → Claude 3.5 Sonnet
    "smart_folders": "standard",   # articles / summaries → Mistral Small
}

# Per-user concurrent request tracking (blueprint §2.3 Tier A)
_USER_ACTIVE_REQUESTS: dict[str, int] = {}
_user_concurrent_lock = asyncio.Lock()


async def _acquire_user_concurrency_slot(user_id: str, role: str) -> bool:
    """Try to acquire a per-user concurrency slot. Returns True if allowed."""
    from app.services.user_quota import user_quota_manager

    quota = user_quota_manager.get_quota(role)
    max_concurrent = quota.get("concurrent", 1)

    async with _user_concurrent_lock:
        current = _USER_ACTIVE_REQUESTS.get(user_id, 0)
        if current >= max_concurrent:
            logger.warning(
                "Concurrent request limit exceeded for user=%s role=%s "
                "(%d / %d active)",
                user_id, role, current, max_concurrent,
            )
            return False
        _USER_ACTIVE_REQUESTS[user_id] = current + 1
        return True


async def _release_user_concurrency_slot(user_id: str) -> None:
    """Release a per-user concurrency slot."""
    async with _user_concurrent_lock:
        current = _USER_ACTIVE_REQUESTS.get(user_id, 0)
        if current > 0:
            _USER_ACTIVE_REQUESTS[user_id] = current - 1
        if _USER_ACTIVE_REQUESTS[user_id] == 0:
            del _USER_ACTIVE_REQUESTS[user_id]


class LLMGateway:
    """
    Simplified facade over LLMRouter.

    Exposes a single async method ``chat_completion`` that handles provider
    selection, tiered routing, and failover automatically.
    """

    def __init__(self, router: LLMRouter | None = None) -> None:
        self._router = router or _build_router()

    # ── Instrumentation helper ──

    async def _timed_generate(
        self,
        gen: AsyncGenerator[str, None],
        *,
        tier: str,
        stream: bool,
    ) -> AsyncGenerator[str, None]:
        """Wrap a generator to record latency/TTFT for rollback monitoring."""
        start = time.perf_counter()
        first_chunk_time: float | None = None
        error_prefix = False
        try:
            async for chunk in gen:
                if first_chunk_time is None:
                    first_chunk_time = time.perf_counter()
                if chunk and chunk.startswith("Error:"):
                    error_prefix = True
                yield chunk
        finally:
            await gen.aclose()
            end = time.perf_counter()
            latency_ms = (end - start) * 1000
            try:
                from app.services.rollback_monitor import rollback_monitor

                rollback_monitor.record_latency(tier, latency_ms)
                if stream and first_chunk_time is not None:
                    ttft_ms = (first_chunk_time - start) * 1000
                    rollback_monitor.record_ttft(tier, ttft_ms)
                if error_prefix:
                    # Record as a pseudo-parse failure — caller services track real JSON failures
                    rollback_monitor.record_json_parse(tier, success=False)
            except Exception as exc:
                logger.debug("RollbackMonitor recording failed: %s", exc)

    # ── Core chat completion ──

    async def chat_completion(
        self,
        messages: list[dict[str, str]],
        *,
        query: str = "",
        context_chunks: list[dict[str, Any]] | None = None,
        stream: bool = False,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tier: str = "standard",
        has_confidential: bool | None = None,
        user_id: str | None = None,
        user_role: str | None = None,
        module: str | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[str, None]:
        """
        Generate a chat completion via the best available provider.

        Args:
            messages: OpenAI-format message list.
            query: The raw user query (used for PII/sensitivity detection).
            context_chunks: Retrieved RAG chunks, if any.
            stream: Whether to stream tokens.
            temperature: Sampling temperature (0–1).
            max_tokens: Max generation length.
            tier: "simple" | "standard" | "complex" — auto-selects model quality.
            has_confidential: Override confidentiality flag (None = auto-detect).
            user_id: Optional user identifier for quota tracking.
            user_role: Optional user role (admin, superuser, user) for quota limits.
            module: Optional module name for concurrency caps
                (chat, collections, smart_folders, knowledge_graph).
            **kwargs: Provider-specific overrides (rarely needed).

        Yields:
            Text chunks (streaming) or single chunk (non-streaming).
        """
        # ── Task-aware tier selection (blueprint §3.3) ──
        # If the caller left tier at the default "standard" and provided a
        # module name, pick a more appropriate default.
        effective_tier = tier
        if tier == "standard" and module and module in _TASK_TIER_MAP:
            effective_tier = _TASK_TIER_MAP[module]
            logger.debug("Task-aware tier override: module=%s → tier=%s", module, effective_tier)

        tier_enum = TaskTier(effective_tier)

        # ── Resolve user identity from explicit args or request context ──
        resolved_user_id = user_id or current_user_id.get()
        resolved_user_role = user_role or current_user_role.get()

        # ── Module-level concurrency cap (blueprint §2.3) ──
        sem = _MODULE_SEMAPHORES.get(module) if module else None
        # Admin has total priority — bypass concurrency caps
        if resolved_user_role == "admin":
            sem = None

        # ── Per-user quota + cost budget checks (blueprint §2.3) ──
        if resolved_user_id and resolved_user_role:
            from app.services.user_quota import user_quota_manager, QuotaExceededError
            from app.services.monitoring import (
                get_per_user_cost_budget,
                BudgetExceededError,
            )

            # Rough token estimation for quota pre-check
            estimated = sum(len(m.get("content", "")) for m in messages) // 3
            estimated += max_tokens

            # 1. Token quota
            try:
                user_quota_manager.check_and_consume(
                    resolved_user_id, resolved_user_role, estimated
                )
            except QuotaExceededError as exc:
                logger.warning("Quota exceeded for user=%s: %s", resolved_user_id, exc)
                yield f"[QUOTA_EXCEEDED] {exc}"
                return

            # 2. Cost budget (dollar-based, Redis-backed)
            try:
                budget = get_per_user_cost_budget()
                # Pessimistic cost estimate: assume all tokens are output-priced
                svc = self._router._openrouter
                tier_model = (
                    svc.select_model_for_tier(tier)
                    if svc
                    else "mistralai/mistral-small-2409"
                )
                from app.services.monitoring import CostTracker

                pricing = CostTracker.OPENROUTER_PRICING.get(
                    tier_model,
                    CostTracker.OPENROUTER_PRICING.get("mistralai/mistral-small-2409"),
                )
                estimated_cost = (estimated / 1000) * pricing.get("output", 0.003)
                budget.check_and_consume(
                    resolved_user_id, resolved_user_role, estimated_cost
                )
            except BudgetExceededError as exc:
                logger.warning(
                    "Cost budget exceeded for user=%s: %s", resolved_user_id, exc
                )
                yield f"[QUOTA_EXCEEDED] {exc}"
                return

        logger.info(
            "LLMGateway: tier=%s stream=%s module=%s user=%s confidential_override=%s",
            tier,
            stream,
            module,
            resolved_user_id,
            has_confidential,
        )

        # ── Per-user concurrency cap (blueprint §2.3 Tier A) ──
        if resolved_user_id and resolved_user_role:
            if not await _acquire_user_concurrency_slot(
                resolved_user_id, resolved_user_role
            ):
                yield (
                    "[QUOTA_EXCEEDED] Too many concurrent requests. "
                    "Please wait for existing requests to complete."
                )
                return

        # ── Hard prompt ceiling (blueprint §7.4) ──
        from app.services.token_utils import enforce_prompt_ceiling

        capped_messages = enforce_prompt_ceiling(messages, tier=effective_tier)
        if len(capped_messages) < len(messages):
            dropped = len(messages) - len(capped_messages)
            logger.warning(
                "LLMGateway: prompt ceiling dropped %d messages (tier=%s)",
                dropped,
                effective_tier,
            )

        async def _do_generate() -> AsyncGenerator[str, None]:
            """Inner generator — actual LLM call + semantic cache."""
            # ── Semantic cache (non-streaming only) ──
            if not stream and query:
                from app.services.semantic_cache import semantic_cache

                cached = await semantic_cache.get(query, model="openrouter", tier=tier)
                if cached is not None:
                    logger.info("LLMGateway semantic cache hit for query=%s", query[:60])
                    yield cached
                    return

            # ── Generate and optionally buffer for caching ──
            if stream:
                # Streaming: pass through directly (no semantic cache)
                router_gen = self._router.generate_completion(
                    messages=capped_messages,
                    query=query,
                    context_chunks=context_chunks,
                    has_confidential=has_confidential,
                    stream=True,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    tier=tier_enum,
                )
                timed_gen = self._timed_generate(router_gen, tier=tier, stream=True)
                try:
                    if sem is not None:
                        async with sem:
                            async for chunk in timed_gen:
                                yield chunk
                    else:
                        async for chunk in timed_gen:
                            yield chunk
                finally:
                    await timed_gen.aclose()
            else:
                # Non-streaming: buffer response for semantic cache
                parts: list[str] = []
                router_gen = self._router.generate_completion(
                    messages=capped_messages,
                    query=query,
                    context_chunks=context_chunks,
                    has_confidential=has_confidential,
                    stream=False,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    tier=tier_enum,
                )
                timed_gen = self._timed_generate(router_gen, tier=tier, stream=False)
                try:
                    if sem is not None:
                        async with sem:
                            async for chunk in timed_gen:
                                parts.append(chunk)
                                yield chunk
                    else:
                        async for chunk in timed_gen:
                            parts.append(chunk)
                            yield chunk
                finally:
                    await timed_gen.aclose()

                # Store in semantic cache after generation completes
                if query and parts:
                    from app.services.semantic_cache import semantic_cache

                    full_response = "".join(parts)
                    if full_response:
                        await semantic_cache.set(
                            query, model="openrouter", tier=tier, response=full_response
                        )

        do_gen = _do_generate()
        try:
            async for chunk in do_gen:
                yield chunk
        finally:
            await do_gen.aclose()
            if resolved_user_id:
                await _release_user_concurrency_slot(resolved_user_id)

    # ── Provider-specific passthroughs ──
    #
    # The following methods expose capabilities that exist on specific
    # providers (mostly OpenRouter).  They are kept here so consumers
    # don't need to import provider modules directly.
    # If the underlying provider is unavailable the call is a no-op or
    # raises a clear RuntimeError.

    @property
    def model(self) -> str:
        """Return the model name of the primary provider (OpenRouter)."""
        svc = self._router._openrouter
        if svc is not None:
            return getattr(svc, "model", "unknown")
        return "unknown"

    def check_cache(self, messages: list[dict[str, str]]) -> str | None:
        """Check Redis cache for a cached non-streaming response (OpenRouter)."""
        svc = self._router._openrouter
        if svc is not None and hasattr(svc, "check_cache"):
            return svc.check_cache(messages)
        return None

    def invalidate_collection_cache(self, collection_id: str) -> int:
        """Invalidate all cached responses for a collection (OpenRouter)."""
        svc = self._router._openrouter
        if svc is not None and hasattr(svc, "invalidate_collection_cache"):
            return svc.invalidate_collection_cache(str(collection_id))
        return 0

    async def get_usage_stats(self) -> dict[str, Any]:
        """Return usage statistics from the primary provider (OpenRouter)."""
        svc = self._router._openrouter
        if svc is not None and hasattr(svc, "get_usage_stats"):
            return await svc.get_usage_stats()
        return {"service": "openrouter", "status": "unavailable"}

    async def chat_completion_non_stream(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 2048,
        **kwargs: Any,
    ) -> str:
        """
        Synchronous-style non-streaming completion.

        Used by legacy consumers that expect a single string response.
        Delegates to MiniMax when available, otherwise OpenRouter.
        """
        # Prefer MiniMax for non-streaming calls (legacy behaviour)
        svc = self._router._minimax or self._router._openrouter
        if svc is None:
            raise RuntimeError("No LLM provider available for non-streaming completion")

        if hasattr(svc, "chat_completion_non_stream"):
            return await svc.chat_completion_non_stream(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )

        # Fallback: collect streamed chunks into a single string
        parts: list[str] = []
        async for chunk in svc.chat_completion(
            messages=messages,
            stream=False,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        ):
            if (
                chunk
                and not chunk.startswith("Error:")
                and not chunk.startswith("__USAGE__")
            ):
                parts.append(chunk)
        return "".join(parts)

    # ── Report generation (quality-critical multi-tier fallback) ──

    async def generate_report_completion(
        self,
        messages: list[dict[str, Any]],
        *,
        query: str = "",
        context_chunks: list[dict[str, Any]] | None = None,
        stream: bool = False,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        tier: str = "complex",
    ) -> AsyncGenerator[str, None]:
        """
        §5.2 Smart Collections & Reports: quality-critical multi-tier fallback.

        Delegates to LLMRouter.generate_report_completion which implements:
            1. OpenRouter complex (Claude 3.5 Sonnet)
            2. OpenRouter standard (Mistral Small)
            3. Together.ai Llama 3.1 70B
            4. Graceful degradation to bullet-point summary
        """
        from app.services.llm_router import TaskTier

        tier_enum = TaskTier(tier)

        async for chunk in self._router.generate_report_completion(
            messages=messages,
            query=query,
            context_chunks=context_chunks,
            stream=stream,
            temperature=temperature,
            max_tokens=max_tokens,
            tier=tier_enum,
        ):
            yield chunk

    # ── Health ──

    async def health_check(self) -> dict[str, Any]:
        """Return health status of all configured providers."""
        return await self._router.health_check()


# Singleton instance — import this in consumers.
llm_gateway = LLMGateway()
