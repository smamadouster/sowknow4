"""
Unit tests for LLMRouter (app/services/llm_router.py)
======================================================
Validates the core privacy guarantee:
  - Any confidential chunk → Ollama selected (even if 99 of 100 are public)
  - All-public chunks → non-Ollama provider selected
  - Empty chunk list → non-Ollama provider selected (safe default)
  - PII in query → Ollama selected
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.llm_router import LLMRouter, RoutingReason

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_chunk(bucket: str) -> dict:
    """Minimal chunk dict with a bucket field."""
    return {"id": "chunk-1", "text": "sample text", "bucket": bucket}


def _make_router(
    *,
    ollama_healthy: bool = True,
    has_minimax: bool = True,
    has_kimi: bool = True,
    has_openrouter: bool = True,
    has_pii_service: bool = False,
) -> LLMRouter:
    """Build an LLMRouter with injectable mock services."""

    minimax_svc = MagicMock(api_key="mk-test") if has_minimax else None
    kimi_svc = MagicMock(api_key="kimi-test") if has_kimi else None
    openrouter_svc = MagicMock() if has_openrouter else None

    ollama_svc = AsyncMock()
    ollama_svc.health_check = AsyncMock(
        return_value={"status": "healthy"} if ollama_healthy else {"status": "unhealthy", "error": "down"}
    )

    pii_svc = None
    if has_pii_service:
        pii_svc = MagicMock()
        pii_svc.detect_pii = MagicMock(return_value=False)

    return LLMRouter(
        minimax_service=minimax_svc,
        kimi_service=kimi_svc,
        openrouter_service=openrouter_svc,
        ollama_service=ollama_svc,
        pii_detection_service=pii_svc,
    )


# ---------------------------------------------------------------------------
# Confidential routing
# ---------------------------------------------------------------------------

class TestConfidentialRouting:
    """Any confidential chunk must route to Ollama — privacy guarantee."""

    @pytest.mark.asyncio
    async def test_single_confidential_chunk_routes_to_ollama(self):
        """One confidential chunk → Ollama, even with no other context."""
        router = _make_router()
        chunks = [_make_chunk("confidential")]
        decision = await router.select_provider(query="test", context_chunks=chunks)

        assert decision.provider_name == "ollama"
        assert decision.reason == RoutingReason.CONFIDENTIAL_DOCS

    @pytest.mark.asyncio
    async def test_one_confidential_among_many_public_routes_to_ollama(self):
        """99 public chunks + 1 confidential → Ollama (strict privacy rule)."""
        router = _make_router()
        chunks = [_make_chunk("public")] * 99 + [_make_chunk("confidential")]
        decision = await router.select_provider(query="test", context_chunks=chunks)

        assert decision.provider_name == "ollama", (
            "PRIVACY BREACH: confidential chunk present but Ollama not selected"
        )
        assert decision.reason == RoutingReason.CONFIDENTIAL_DOCS

    @pytest.mark.asyncio
    async def test_has_confidential_flag_overrides_chunk_inspection(self):
        """Caller-supplied has_confidential=True → Ollama without chunk scan."""
        router = _make_router()
        decision = await router.select_provider(
            query="test", context_chunks=[], has_confidential=True
        )

        assert decision.provider_name == "ollama"
        assert decision.reason == RoutingReason.CONFIDENTIAL_DOCS

    @pytest.mark.asyncio
    async def test_confidential_routing_raises_when_ollama_down(self):
        """If Ollama is down for a confidential query, raise RuntimeError (never fall back to cloud)."""
        router = _make_router(ollama_healthy=False)
        chunks = [_make_chunk("confidential")]

        with pytest.raises(RuntimeError, match="Ollama unavailable"):
            await router.select_provider(query="test", context_chunks=chunks)


# ---------------------------------------------------------------------------
# Public routing
# ---------------------------------------------------------------------------

class TestPublicRouting:
    """All-public chunks must NOT route to Ollama when cloud providers are available."""

    @pytest.mark.asyncio
    async def test_all_public_chunks_uses_cloud_provider(self):
        """All-public context → MiniMax (first in RAG chain)."""
        router = _make_router()
        chunks = [_make_chunk("public"), _make_chunk("public")]
        decision = await router.select_provider(query="test", context_chunks=chunks)

        assert decision.provider_name != "ollama", (
            "Public documents should not route to Ollama when cloud providers are available"
        )
        assert decision.provider_name == "minimax"
        assert decision.reason == RoutingReason.PUBLIC_DOCS_RAG

    @pytest.mark.asyncio
    async def test_empty_chunk_list_uses_chat_chain(self):
        """No context chunks → general chat chain (MiniMax first)."""
        router = _make_router()
        decision = await router.select_provider(query="Hello!", context_chunks=[])

        assert decision.provider_name != "ollama"
        assert decision.provider_name == "minimax"
        assert decision.reason == RoutingReason.GENERAL_CHAT

    @pytest.mark.asyncio
    async def test_no_context_no_minimax_no_kimi_falls_back_to_openrouter(self):
        """Without kimi or minimax, general chat falls back to OpenRouter."""
        router = _make_router(has_kimi=False, has_minimax=False)
        decision = await router.select_provider(query="Hello!", context_chunks=[])

        assert decision.provider_name == "openrouter"

    @pytest.mark.asyncio
    async def test_has_confidential_false_uses_cloud(self):
        """Caller-supplied has_confidential=False → cloud provider selected."""
        router = _make_router()
        decision = await router.select_provider(
            query="public question", context_chunks=[], has_confidential=False
        )

        assert decision.provider_name != "ollama"


# ---------------------------------------------------------------------------
# PII detection integration
# ---------------------------------------------------------------------------

class TestPIIRouting:
    """PII in the query text must force Ollama routing."""

    @pytest.mark.asyncio
    async def test_pii_in_query_routes_to_ollama(self):
        """Query with PII detected → Ollama (even with no document context)."""
        router = _make_router(has_pii_service=True)
        # Make PII service report PII present
        router._pii.detect_pii = MagicMock(return_value=True)

        decision = await router.select_provider(query="My SSN is 123-45-6789", context_chunks=[])

        assert decision.provider_name == "ollama"
        assert decision.reason == RoutingReason.PII_DETECTED

    @pytest.mark.asyncio
    async def test_no_pii_uses_cloud(self):
        """Query without PII → cloud provider."""
        router = _make_router(has_pii_service=True)
        router._pii.detect_pii = MagicMock(return_value=False)

        decision = await router.select_provider(
            query="What is the architecture overview?", context_chunks=[]
        )

        assert decision.provider_name != "ollama"


# ---------------------------------------------------------------------------
# detect_context_sensitivity unit tests
# ---------------------------------------------------------------------------

class TestDetectContextSensitivity:
    """Validate the synchronous sensitivity detector used by select_provider."""

    def test_confidential_bucket_is_sensitive(self):
        router = _make_router()
        is_sensitive, reason = router.detect_context_sensitivity(
            "test", [_make_chunk("confidential")]
        )
        assert is_sensitive is True
        assert "confidential" in reason

    def test_public_bucket_not_sensitive(self):
        router = _make_router()
        is_sensitive, _ = router.detect_context_sensitivity(
            "test", [_make_chunk("public")]
        )
        assert is_sensitive is False

    def test_empty_chunks_not_sensitive(self):
        router = _make_router()
        is_sensitive, _ = router.detect_context_sensitivity("hello", [])
        assert is_sensitive is False

    def test_mixed_buckets_sensitive(self):
        """Mixed public + confidential must be flagged as sensitive."""
        router = _make_router()
        chunks = [_make_chunk("public")] * 5 + [_make_chunk("confidential")]
        is_sensitive, reason = router.detect_context_sensitivity("test", chunks)
        assert is_sensitive is True
