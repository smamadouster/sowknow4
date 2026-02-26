"""
Centralized LLM routing service.

Single source of truth for provider selection based on document confidentiality,
PII detection, and service availability.  All chat services should route through
this module instead of embedding routing logic inline.

Routing strategy
----------------
* Confidential docs or PII detected → Ollama only (privacy guarantee)
* Public docs (RAG)                 → MiniMax M2.5 → OpenRouter (Kimi K2.5) → Ollama
* General chat (no docs)            → Kimi (direct) → MiniMax → OpenRouter → Ollama
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncGenerator, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class RoutingReason(str, Enum):
    CONFIDENTIAL_DOCS = "confidential_docs"
    PII_DETECTED = "pii_detected"
    PUBLIC_DOCS_RAG = "public_docs_rag"
    GENERAL_CHAT = "general_chat"
    FINAL_FALLBACK = "final_fallback_ollama"


class LLMProvider(str, Enum):
    """Canonical provider identifiers — single source of truth."""

    MINIMAX = "minimax"
    KIMI = "kimi"
    OPENROUTER = "openrouter"
    OLLAMA = "ollama"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class RoutingDecision:
    """Result of the LLM routing decision."""

    provider_name: str  # e.g. "minimax", "ollama"
    reason: RoutingReason
    service: Any  # The actual service instance
    metadata: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


class LLMRouter:
    """
    Stateless routing helper.  Call :meth:`select_provider` to get a
    :class:`RoutingDecision`, then use ``decision.service`` to call
    ``chat_completion``.

    Services are injected at construction time so that tests can pass in mocks.
    """

    # Fallback chains per routing scenario.
    # Each chain is an ordered list of provider names tried left-to-right.
    fallback_chains: Dict[str, List[str]] = {
        "confidential": ["ollama"],
        "public_docs": ["minimax", "openrouter", "ollama"],
        "general_chat": ["kimi", "minimax", "openrouter", "ollama"],
    }

    def __init__(
        self,
        *,
        minimax_service: Any = None,
        kimi_service: Any = None,
        openrouter_service: Any = None,
        ollama_service: Any = None,
        pii_detection_service: Any = None,
    ) -> None:
        self._minimax = minimax_service
        self._kimi = kimi_service
        self._openrouter = openrouter_service
        self._ollama = ollama_service
        self._pii = pii_detection_service

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def generate_completion(
        self,
        messages: List[Dict[str, Any]],
        query: str = "",
        context_chunks: Optional[List[Dict[str, Any]]] = None,
        *,
        has_confidential: Optional[bool] = None,
        stream: bool = False,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> AsyncGenerator[str, None]:
        """
        High-level entry point: route the query and call the selected provider.

        Selects the best provider via :meth:`select_provider`, then delegates to
        :class:`LLMServiceAdapter` for normalised ``chat_completion`` dispatch.

        Yields:
            Text chunks from the provider.
        """
        decision = await self.select_provider(
            query=query,
            context_chunks=context_chunks,
            has_confidential=has_confidential,
        )
        adapter = LLMServiceAdapter(decision.service, decision.provider_name)
        built_messages = adapter.build_messages(messages)
        async for chunk in adapter.call_service(
            built_messages,
            stream=stream,
            temperature=temperature,
            max_tokens=max_tokens,
        ):
            yield chunk

    def detect_context_sensitivity(
        self,
        query: str,
        context_chunks: Optional[List[Dict[str, Any]]] = None,
    ) -> tuple[bool, str]:
        """
        Determine whether the query or its context is sensitive.

        Returns:
            (is_sensitive, reason_string)
        """
        # PII in query text
        if self._pii is not None:
            has_pii = self._pii.detect_pii(query)
            if has_pii:
                return True, "pii_in_query"

        # Confidential document buckets in retrieved context
        if context_chunks:
            for chunk in context_chunks:
                bucket = chunk.get("document_bucket") or chunk.get("bucket", "")
                if bucket == "confidential":
                    return True, "confidential_bucket"

        return False, "public_content"

    async def select_provider(
        self,
        query: str,
        context_chunks: Optional[List[Dict[str, Any]]] = None,
        *,
        has_confidential: Optional[bool] = None,
    ) -> RoutingDecision:
        """
        Choose the appropriate LLM provider.

        ``has_confidential`` may be supplied directly (already computed by the
        caller) to skip the PII / bucket scan.  If omitted, sensitivity is
        detected from *query* and *context_chunks*.

        When confidential routing is selected and Ollama is unreachable this
        method raises :class:`RuntimeError` — the caller must handle that and
        return an appropriate user-facing error.
        """
        context_chunks = context_chunks or []

        # Determine sensitivity
        if has_confidential is None:
            is_sensitive, sensitivity_reason = self.detect_context_sensitivity(
                query, context_chunks
            )
        else:
            is_sensitive = has_confidential
            sensitivity_reason = "confidential_docs" if has_confidential else "public_content"

        # --- Confidential path: Ollama only ---
        if is_sensitive:
            if self._ollama is None:
                raise RuntimeError("Ollama service not configured.")

            health = await self._ollama.health_check()
            if health.get("status") != "healthy":
                raise RuntimeError(
                    f"Ollama unavailable for confidential query: {health.get('error', 'unknown')}"
                )

            reason = (
                RoutingReason.CONFIDENTIAL_DOCS
                if "confidential" in sensitivity_reason
                else RoutingReason.PII_DETECTED
            )
            logger.info(f"LLM routing → ollama ({reason.value})")
            return RoutingDecision(
                provider_name="ollama",
                reason=reason,
                service=self._ollama,
                metadata={"sensitivity_reason": sensitivity_reason, "ollama_health": health},
            )

        # --- Public path ---
        has_context = bool(context_chunks)

        if has_context:
            # RAG query: MiniMax → OpenRouter → Ollama
            chain = [
                ("minimax", self._minimax, lambda s: s is not None and getattr(s, "api_key", None)),
                ("openrouter", self._openrouter, lambda s: s is not None),
                ("ollama", self._ollama, lambda s: s is not None),
            ]
            reason = RoutingReason.PUBLIC_DOCS_RAG
        else:
            # General chat: Kimi → MiniMax → OpenRouter → Ollama
            chain = [
                ("kimi", self._kimi, lambda s: s is not None and getattr(s, "api_key", None)),
                ("minimax", self._minimax, lambda s: s is not None and getattr(s, "api_key", None)),
                ("openrouter", self._openrouter, lambda s: s is not None),
                ("ollama", self._ollama, lambda s: s is not None),
            ]
            reason = RoutingReason.GENERAL_CHAT

        for name, service, available in chain:
            if available(service):
                logger.info(f"LLM routing → {name} ({reason.value})")
                return RoutingDecision(
                    provider_name=name,
                    reason=reason,
                    service=service,
                    metadata={"chain": [n for n, _, _ in chain]},
                )

        raise RuntimeError("No LLM provider available.")


# ---------------------------------------------------------------------------
# Service adapter — normalises calling conventions across providers
# ---------------------------------------------------------------------------


class LLMServiceAdapter:
    """
    Adapts a provider service instance to a common calling convention.

    Different providers use slightly different parameter names
    (``max_tokens`` vs ``num_predict``, etc.).  This adapter normalises
    them so :meth:`LLMRouter.generate_completion` can treat all providers
    uniformly.
    """

    def __init__(self, service: Any, provider_name: str) -> None:
        self._service = service
        self._provider = provider_name

    def build_messages(
        self, messages: List[Dict[str, Any]]
    ) -> List[Dict[str, str]]:
        """
        Normalise the message list to OpenAI format (role + content dicts).

        Strips unknown keys so every provider receives a clean payload.
        """
        return [
            {"role": str(m.get("role", "user")), "content": str(m.get("content", ""))}
            for m in messages
        ]

    async def call_service(
        self,
        messages: List[Dict[str, str]],
        *,
        stream: bool = False,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> AsyncGenerator[str, None]:
        """
        Dispatch to the underlying service's ``chat_completion``, translating
        parameter names as needed.
        """
        if self._provider == "ollama":
            # Ollama uses num_predict instead of max_tokens
            async for chunk in self._service.chat_completion(
                messages,
                stream=stream,
                temperature=temperature,
                num_predict=max_tokens,
            ):
                yield chunk
        else:
            async for chunk in self._service.chat_completion(
                messages,
                stream=stream,
                temperature=temperature,
                max_tokens=max_tokens,
            ):
                yield chunk


# ---------------------------------------------------------------------------
# Module-level singleton (lazy imports to avoid circular dependency)
# ---------------------------------------------------------------------------


def _build_router() -> LLMRouter:
    """Instantiate the router with the project's singleton services."""
    # All imports intentionally lazy to avoid circular imports at module load.
    minimax_svc = None
    kimi_svc = None
    openrouter_svc = None
    ollama_svc = None
    pii_svc = None

    try:
        from app.services.minimax_service import minimax_service as _m

        minimax_svc = _m
    except Exception:
        logger.warning("LLMRouter: minimax_service not available")

    try:
        from app.services.kimi_service import kimi_service as _k

        kimi_svc = _k
    except Exception:
        logger.warning("LLMRouter: kimi_service not available")

    try:
        from app.services.openrouter_service import openrouter_service as _or

        openrouter_svc = _or
    except Exception:
        logger.warning("LLMRouter: openrouter_service not available")

    try:
        from app.services.ollama_service import ollama_service as _ol

        ollama_svc = _ol
    except Exception:
        logger.warning("LLMRouter: ollama_service not available")

    try:
        from app.services.pii_detection_service import pii_detection_service as _pii

        pii_svc = _pii
    except Exception:
        logger.warning("LLMRouter: pii_detection_service not available")

    return LLMRouter(
        minimax_service=minimax_svc,
        kimi_service=kimi_svc,
        openrouter_service=openrouter_svc,
        ollama_service=ollama_svc,
        pii_detection_service=pii_svc,
    )


# Singleton — built on first import.
# llm_router = LLMRouter()  — services are wired by _build_router() to avoid circular imports
llm_router: LLMRouter = _build_router()
