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

import logging
from collections.abc import AsyncGenerator
from typing import Any

from app.services.llm_router import LLMRouter, TaskTier, _build_router

logger = logging.getLogger(__name__)


class LLMGateway:
    """
    Simplified facade over LLMRouter.

    Exposes a single async method ``chat_completion`` that handles provider
    selection, tiered routing, and failover automatically.
    """

    def __init__(self, router: LLMRouter | None = None) -> None:
        self._router = router or _build_router()

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
            **kwargs: Provider-specific overrides (rarely needed).

        Yields:
            Text chunks (streaming) or single chunk (non-streaming).
        """
        tier_enum = TaskTier(tier)

        logger.info(
            "LLMGateway: tier=%s stream=%s confidential_override=%s",
            tier,
            stream,
            has_confidential,
        )

        async for chunk in self._router.generate_completion(
            messages=messages,
            query=query,
            context_chunks=context_chunks,
            has_confidential=has_confidential,
            stream=stream,
            temperature=temperature,
            max_tokens=max_tokens,
            tier=tier_enum,
        ):
            yield chunk

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
                messages=messages, temperature=temperature, max_tokens=max_tokens, **kwargs
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
            if chunk and not chunk.startswith("Error:") and not chunk.startswith("__USAGE__"):
                parts.append(chunk)
        return "".join(parts)

    # ── Health ──

    async def health_check(self) -> dict[str, Any]:
        """Return health status of all configured providers."""
        return await self._router.health_check()


# Singleton instance — import this in consumers.
llm_gateway = LLMGateway()
