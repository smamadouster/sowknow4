"""
Centralized LLM routing service.

Single source of truth for provider selection based on document confidentiality,
PII detection, task complexity tier, and service availability.

All chat services should route through this module instead of embedding routing logic inline.

Routing strategy
----------------
* Confidential docs or PII detected → OpenRouter (metadata-only stripping)
* Public docs (RAG)                 → OpenRouter tiered
* General chat (no docs)            → OpenRouter tiered

Tiered model routing (OpenRouter)
---------------------------------
* simple:    google/gemini-2.0-flash-001  (classification, tagging, intent)
* standard:  mistralai/mistral-small-2409  (chat, synthesis, articles)
* complex:   anthropic/claude-3.5-sonnet  (reasoning, reports, verification)
"""

import logging
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class RoutingReason(StrEnum):
    CONFIDENTIAL_DOCS = "confidential_docs"
    PII_DETECTED = "pii_detected"
    PUBLIC_DOCS_RAG = "public_docs_rag"
    GENERAL_CHAT = "general_chat"
    FINAL_FALLBACK = "final_fallback"


class LLMProvider(StrEnum):
    """Canonical provider identifiers — single source of truth."""

    MINIMAX = "minimax"
    KIMI = "kimi"
    OPENROUTER = "openrouter"
    OLLAMA = "ollama"
    TOGETHER = "together"


class TaskTier(StrEnum):
    """Complexity tier for task-aware model selection."""

    SIMPLE = "simple"       # Classification, tagging, intent parsing
    STANDARD = "standard"   # Chat, synthesis, articles, summaries
    COMPLEX = "complex"     # Reasoning, coding, verification, reports


class FallbackTrigger(StrEnum):
    """Reasons that trigger a fallback to the next provider or tier."""

    HTTP_429 = "rate_limit"
    HTTP_5XX = "server_error"
    TTFT_EXCEEDED = "ttft_exceeded"
    COST_ANOMALY = "cost_anomaly"
    CIRCUIT_OPEN = "circuit_open"
    JSON_PARSE_FAIL = "json_parse_fail"
    EMPTY_RESPONSE = "empty_response"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class RoutingDecision:
    """Result of the LLM routing decision."""

    provider_name: str  # e.g. "minimax", "openrouter", "ollama"
    reason: RoutingReason
    service: Any  # The actual service instance
    metadata: dict[str, Any] = field(default_factory=dict)
    tier: TaskTier = TaskTier.STANDARD


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


class LLMRouter:
    """
    Stateful routing helper.  Call :meth:`select_provider` to get a
    :class:`RoutingDecision`, then use ``decision.service`` to call
    ``chat_completion``.

    Services are injected at construction time so that tests can pass in mocks.
    """

    # Fallback chains per routing scenario (§5.2 updated).
    # Ollama and Together.ai are removed from the active chain.
    # MiniMax is optional; all traffic routes through OpenRouter with tier fallback.
    # Each chain is an ordered list of provider names tried left-to-right.
    fallback_chains: dict[str, list[str]] = {
        "confidential": ["openrouter"],
        "public_docs": ["openrouter"],
        "general_chat": ["openrouter"],
        # §5.2 Smart Collections & Reports: quality-critical tier fallback
        # Primary: OpenRouter complex (Claude Sonnet)
        # Secondary: OpenRouter standard (Mistral Small) — tier fallback
        # Ultimate: Graceful degradation to bullet-point summary
        "smart_collections": ["openrouter"],
        "reports": ["openrouter"],
    }

    def __init__(
        self,
        *,
        minimax_service: Any = None,
        kimi_service: Any = None,
        openrouter_service: Any = None,
        ollama_service: Any = None,
        together_service: Any = None,
        pii_detection_service: Any = None,
    ) -> None:
        self._minimax = minimax_service
        self._kimi = kimi_service
        self._openrouter = openrouter_service
        self._ollama = ollama_service
        self._together = together_service
        self._pii = pii_detection_service

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def generate_completion(
        self,
        messages: list[dict[str, Any]],
        query: str = "",
        context_chunks: list[dict[str, Any]] | None = None,
        *,
        has_confidential: bool | None = None,
        stream: bool = False,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tier: TaskTier = TaskTier.STANDARD,
    ) -> AsyncGenerator[str, None]:
        """
        High-level entry point: route the query and call the selected provider.

        Tries the primary provider; if it fails, iterates through the fallback
        chain until one succeeds.  If all providers fail, yields a graceful
        error message so the caller can continue without crashing.

        Args:
            tier: Task complexity tier (simple/standard/complex) for model selection.

        Yields:
            Text chunks from the provider.
        """
        # Build the ordered list of providers to try.
        providers_to_try: list[tuple[str, Any]] = []

        # Determine sensitivity
        if has_confidential is None:
            is_sensitive, sensitivity_reason = self.detect_context_sensitivity(query, context_chunks or [])
        else:
            is_sensitive = has_confidential
            sensitivity_reason = "confidential_docs" if has_confidential else "public_content"

        # §5.2: All traffic routes through OpenRouter.
        # Ollama and Together.ai are intentionally removed from the active fallback chain.
        # Confidential data relies on metadata-only stripping (PRD §1.3).
        if self._openrouter is not None:
            providers_to_try.append(("openrouter", self._openrouter))
        if self._minimax is not None and getattr(self._minimax, "api_key", None):
            providers_to_try.append(("minimax", self._minimax))

        last_error = ""
        for name, service in providers_to_try:
            if service is None:
                continue
            adapter = LLMServiceAdapter(service, name)
            built_messages = adapter.build_messages(messages)

            # Primary attempt with requested tier
            gen = adapter.call_service(
                built_messages,
                stream=stream,
                temperature=temperature,
                max_tokens=max_tokens,
                tier=tier.value,
            )
            try:
                async for chunk in gen:
                    yield chunk
                return  # Success — stop trying other providers
            except (Exception) as exc:
                last_error = str(exc)
                logger.warning("LLM provider %s (tier=%s) failed: %s", name, tier.value, last_error)

                # §5.2: Tier fallback within OpenRouter.
                # If standard/complex fails with 429/timeout, try simple tier (Gemini Flash).
                if name == "openrouter" and tier in (TaskTier.STANDARD, TaskTier.COMPLEX):
                    fallback_gen = adapter.call_service(
                        built_messages,
                        stream=stream,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        tier="simple",
                    )
                    try:
                        async for chunk in fallback_gen:
                            yield chunk
                        logger.info("OpenRouter tier fallback succeeded: %s → simple", tier.value)
                        return
                    except Exception as exc2:
                        last_error = str(exc2)
                        logger.warning(
                            "OpenRouter simple tier fallback also failed: %s", exc2
                        )
                continue

        logger.error("All LLM providers failed. Last error: %s", last_error)
        # Graceful degradation: if we have context chunks, generate a bullet summary
        bullet_summary = self._generate_bullet_summary(context_chunks)
        if bullet_summary:
            yield bullet_summary
        else:
            yield "[LLM indisponible — la réponse synthétique n'a pas pu être générée. Veuillez consulter les documents listés ci-dessus.]"

    def detect_context_sensitivity(
        self,
        query: str,
        context_chunks: list[dict[str, Any]] | None = None,
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

    def _generate_bullet_summary(
        self, context_chunks: list[dict[str, Any]] | None
    ) -> str | None:
        """
        §5.2 Ultimate fallback: generate a bullet-point summary from retrieved
        documents without any LLM synthesis.

        Used when all LLM providers fail for Smart Collections & Reports.
        """
        if not context_chunks:
            return None

        lines: list[str] = [
            "**Résumé automatique des documents (synthèse non générée par IA)**\n",
        ]
        seen: set[str] = set()
        for chunk in context_chunks[:15]:
            doc_name = chunk.get("document_name") or chunk.get("filename") or chunk.get("title", "Document")
            text = chunk.get("chunk_text") or chunk.get("text", "")
            if not text:
                continue
            key = f"{doc_name}:{text[:80]}"
            if key in seen:
                continue
            seen.add(key)
            # Truncate to first sentence or 200 chars
            snippet = text[:200].split(".")[0] + "." if "." in text[:200] else text[:200]
            lines.append(f"- **{doc_name}** : {snippet}")

        if len(lines) == 1:
            return None
        lines.append(
            "\n_La synthèse détaillée n'a pas pu être générée. "
            "Veuillez consulter les documents ci-dessus pour plus de détails._"
        )
        return "\n".join(lines)

    async def generate_report_completion(
        self,
        messages: list[dict[str, Any]],
        query: str = "",
        context_chunks: list[dict[str, Any]] | None = None,
        *,
        stream: bool = False,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        tier: TaskTier = TaskTier.COMPLEX,
    ) -> AsyncGenerator[str, None]:
        """
        §5.2 Smart Collections & Reports: quality-critical tier fallback.

        Chain:
            1. OpenRouter complex (Claude 3.5 Sonnet)
            2. OpenRouter standard (Mistral Small) — on 429/timeout/JSON failure
            3. Graceful degradation — bullet-point summary of retrieved documents

        Yields:
            Text chunks from the provider, or bullet summary if all fail.
        """
        built_messages = [{"role": str(m.get("role", "user")), "content": str(m.get("content", ""))} for m in messages]

        # 1. Primary: OpenRouter complex
        if self._openrouter is not None:
            adapter = LLMServiceAdapter(self._openrouter, "openrouter")
            primary_gen = adapter.call_service(
                built_messages,
                stream=stream,
                temperature=temperature,
                max_tokens=max_tokens,
                tier="complex",
            )
            try:
                async for chunk in primary_gen:
                    yield chunk
                return
            except Exception as exc:
                logger.warning("Report primary failed (OpenRouter complex): %s", exc)
                await primary_gen.aclose()

                # 2. Secondary: OpenRouter standard (tier fallback)
                secondary_gen = adapter.call_service(
                    built_messages,
                    stream=stream,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    tier="standard",
                )
                try:
                    async for chunk in secondary_gen:
                        yield chunk
                    logger.info("Report secondary succeeded: OpenRouter complex → standard")
                    return
                except Exception as exc2:
                    logger.warning("Report secondary failed (OpenRouter standard): %s", exc2)

        # 3. Ultimate: Graceful degradation to bullet-point summary
        logger.error("All report LLM providers failed. Emitting bullet summary.")
        bullet_summary = self._generate_bullet_summary(context_chunks)
        if bullet_summary:
            yield bullet_summary
        else:
            yield "[LLM indisponible — le rapport n'a pas pu être généré. Veuillez consulter les documents listés ci-dessus.]"

    async def select_provider(
        self,
        query: str,
        context_chunks: list[dict[str, Any]] | None = None,
        *,
        has_confidential: bool | None = None,
        task_type: str = "chat",
    ) -> RoutingDecision:
        """
        Choose the appropriate LLM provider.

        ``has_confidential`` may be supplied directly (already computed by the
        caller) to skip the PII / bucket scan.  If omitted, sensitivity is
        detected from *query* and *context_chunks*.

        ``task_type`` hints at the consumer: "chat", "report", "smart_collection".
        For quality-critical tasks, OpenRouter tier fallback is used.

        Confidential queries route to OpenRouter with metadata-only stripping.
        """
        context_chunks = context_chunks or []

        # Determine sensitivity
        if has_confidential is None:
            is_sensitive, sensitivity_reason = self.detect_context_sensitivity(query, context_chunks)
        else:
            is_sensitive = has_confidential
            sensitivity_reason = "confidential_docs" if has_confidential else "public_content"

        # §5.2: All traffic routes through OpenRouter.
        # Ollama is removed from the active fallback chain (CPU too slow).
        # Confidential data relies on metadata-only stripping (PRD §1.3).
        if is_sensitive:
            reason = (
                RoutingReason.CONFIDENTIAL_DOCS if "confidential" in sensitivity_reason else RoutingReason.PII_DETECTED
            )
            logger.info("LLM routing → openrouter (%s, metadata-only stripping)", reason.value)
            if self._openrouter is not None:
                return RoutingDecision(
                    provider_name="openrouter",
                    reason=reason,
                    service=self._openrouter,
                    metadata={"chain": ["openrouter"], "sensitive": True, "strip_metadata": True},
                )
            raise RuntimeError("No LLM provider available for sensitive query.")

        # --- Public path ---
        has_context = bool(context_chunks)

        if has_context:
            reason = RoutingReason.PUBLIC_DOCS_RAG
        else:
            reason = RoutingReason.GENERAL_CHAT

        # §5.2: Quality-critical tasks use OpenRouter tier fallback only.
        if task_type in ("report", "smart_collection"):
            chain = ["openrouter"]
            logger.info("LLM routing → openrouter (%s, quality-critical chain=%s)", reason.value, chain)
            if self._openrouter is not None:
                return RoutingDecision(
                    provider_name="openrouter",
                    reason=reason,
                    service=self._openrouter,
                    metadata={"chain": chain, "task_type": task_type, "tier": TaskTier.COMPLEX},
                    tier=TaskTier.COMPLEX,
                )
            raise RuntimeError("No LLM provider available for quality-critical task.")

        if self._openrouter is not None:
            logger.info("LLM routing → openrouter (%s)", reason.value)
            return RoutingDecision(
                provider_name="openrouter",
                reason=reason,
                service=self._openrouter,
                metadata={"chain": ["openrouter"]},
            )

        raise RuntimeError("No LLM provider available.")

    def get_provider_for_direct_call(
        self,
        preferred: LLMProvider = LLMProvider.OPENROUTER,
        tier: TaskTier = TaskTier.STANDARD,
    ) -> tuple[Any, str]:
        """Get a provider service for direct (non-routed) calls.

        Used by services that bypass the router but still want tiered model selection.

        Returns:
            (service_instance, provider_name)
        """
        if preferred == LLMProvider.OPENROUTER and self._openrouter is not None:
            return self._openrouter, "openrouter"
        if preferred == LLMProvider.MINIMAX and self._minimax is not None:
            return self._minimax, "minimax"
        # Fallback to any available
        for svc, name in [
            (self._openrouter, "openrouter"),
            (self._minimax, "minimax"),
        ]:
            if svc is not None:
                return svc, name
        raise RuntimeError("No LLM provider available for direct call.")


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

    def build_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, str]]:
        """
        Normalise the message list to OpenAI format (role + content dicts).

        Strips unknown keys so every provider receives a clean payload.
        """
        return [{"role": str(m.get("role", "user")), "content": str(m.get("content", ""))} for m in messages]

    async def call_service(
        self,
        messages: list[dict[str, str]],
        *,
        stream: bool = False,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tier: str = "standard",
    ) -> AsyncGenerator[str, None]:
        """
        Dispatch to the underlying service's ``chat_completion``, translating
        parameter names as needed.
        """
        kwargs = {"stream": stream, "temperature": temperature, "max_tokens": max_tokens}
        # Pass tier to OpenRouter for model selection; other providers ignore it
        if self._provider == "openrouter":
            kwargs["tier"] = tier
        gen = self._service.chat_completion(messages, **kwargs)
        try:
            async for chunk in gen:
                yield chunk
        finally:
            await gen.aclose()


# ---------------------------------------------------------------------------
# Module-level singleton (lazy imports to avoid circular dependency)
# ---------------------------------------------------------------------------


def _build_router() -> LLMRouter:
    """Instantiate the router with the project's singleton services."""
    # All imports intentionally lazy to avoid circular imports at module load.
    # Ollama and Together.ai are intentionally not imported: they are removed
    # from the active fallback chain and must not be instantiated in production.
    minimax_svc = None
    kimi_svc = None
    openrouter_svc = None
    pii_svc = None

    try:
        from app.services.minimax_service import minimax_service as _m

        minimax_svc = _m
    except Exception as exc:
        logger.warning("LLMRouter: minimax_service not available: %s", exc, exc_info=True)

    try:
        from app.services.kimi_service import kimi_service as _k

        kimi_svc = _k
    except Exception as exc:
        logger.warning("LLMRouter: kimi_service not available: %s", exc, exc_info=True)

    try:
        from app.services.openrouter_service import openrouter_service as _or

        openrouter_svc = _or
    except Exception as exc:
        logger.warning("LLMRouter: openrouter_service not available: %s", exc, exc_info=True)

    try:
        from app.services.pii_detection_service import pii_detection_service as _pii

        pii_svc = _pii
    except Exception as exc:
        logger.warning("LLMRouter: pii_detection_service not available: %s", exc, exc_info=True)

    return LLMRouter(
        minimax_service=minimax_svc,
        kimi_service=kimi_svc,
        openrouter_service=openrouter_svc,
        pii_detection_service=pii_svc,
    )


# Singleton — built on first import.
# llm_router = LLMRouter()  — services are wired by _build_router() to avoid circular imports
llm_router: LLMRouter = _build_router()
