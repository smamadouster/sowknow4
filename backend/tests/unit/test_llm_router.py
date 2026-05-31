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
    has_together: bool = False,
    has_pii_service: bool = False,
) -> LLMRouter:
    """Build an LLMRouter with injectable mock services."""

    minimax_svc = MagicMock(api_key="mk-test") if has_minimax else None
    kimi_svc = MagicMock(api_key="kimi-test") if has_kimi else None
    openrouter_svc = MagicMock() if has_openrouter else None
    together_svc = MagicMock(api_key="together-test") if has_together else None

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
        together_service=together_svc,
        pii_detection_service=pii_svc,
    )


# ---------------------------------------------------------------------------
# Confidential routing
# ---------------------------------------------------------------------------

class TestConfidentialRouting:
    """Confidential chunks route to OpenRouter with metadata-only stripping (§5.2)."""

    @pytest.mark.asyncio
    async def test_single_confidential_chunk_routes_to_openrouter(self):
        """One confidential chunk → OpenRouter (metadata-only stripping)."""
        router = _make_router()
        chunks = [_make_chunk("confidential")]
        decision = await router.select_provider(query="test", context_chunks=chunks)

        assert decision.provider_name == "openrouter"
        assert decision.reason == RoutingReason.CONFIDENTIAL_DOCS
        assert decision.metadata.get("strip_metadata") is True

    @pytest.mark.asyncio
    async def test_one_confidential_among_many_public_routes_to_openrouter(self):
        """99 public chunks + 1 confidential → OpenRouter (metadata-only stripping)."""
        router = _make_router()
        chunks = [_make_chunk("public")] * 99 + [_make_chunk("confidential")]
        decision = await router.select_provider(query="test", context_chunks=chunks)

        assert decision.provider_name == "openrouter"
        assert decision.reason == RoutingReason.CONFIDENTIAL_DOCS

    @pytest.mark.asyncio
    async def test_has_confidential_flag_overrides_chunk_inspection(self):
        """Caller-supplied has_confidential=True → OpenRouter without chunk scan."""
        router = _make_router()
        decision = await router.select_provider(
            query="test", context_chunks=[], has_confidential=True
        )

        assert decision.provider_name == "openrouter"
        assert decision.reason == RoutingReason.CONFIDENTIAL_DOCS

    @pytest.mark.asyncio
    async def test_confidential_routing_always_openrouter_even_if_ollama_healthy(self):
        """Ollama is removed from active chain — confidential always uses OpenRouter."""
        router = _make_router(ollama_healthy=True)
        chunks = [_make_chunk("confidential")]

        decision = await router.select_provider(query="test", context_chunks=chunks)
        assert decision.provider_name == "openrouter"


# ---------------------------------------------------------------------------
# Public routing
# ---------------------------------------------------------------------------

class TestPublicRouting:
    """All-public chunks must NOT route to Ollama when cloud providers are available."""

    @pytest.mark.asyncio
    async def test_all_public_chunks_uses_cloud_provider(self):
        """All-public context → OpenRouter (first in RAG chain)."""
        router = _make_router()
        chunks = [_make_chunk("public"), _make_chunk("public")]
        decision = await router.select_provider(query="test", context_chunks=chunks)

        assert decision.provider_name != "ollama", (
            "Public documents should not route to Ollama when cloud providers are available"
        )
        assert decision.provider_name == "openrouter"
        assert decision.reason == RoutingReason.PUBLIC_DOCS_RAG

    @pytest.mark.asyncio
    async def test_empty_chunk_list_uses_chat_chain(self):
        """No context chunks → general chat chain (OpenRouter first)."""
        router = _make_router()
        decision = await router.select_provider(query="Hello!", context_chunks=[])

        assert decision.provider_name != "ollama"
        assert decision.provider_name == "openrouter"
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
    """PII in the query text routes to OpenRouter with metadata-only stripping (§5.2)."""

    @pytest.mark.asyncio
    async def test_pii_in_query_routes_to_openrouter(self):
        """Query with PII detected → OpenRouter (metadata-only stripping)."""
        router = _make_router(has_pii_service=True)
        # Make PII service report PII present
        router._pii.detect_pii = MagicMock(return_value=True)

        decision = await router.select_provider(query="My SSN is 123-45-6789", context_chunks=[])

        assert decision.provider_name == "openrouter"
        assert decision.reason == RoutingReason.PII_DETECTED

    @pytest.mark.asyncio
    async def test_no_pii_uses_cloud(self):
        """Query without PII → cloud provider."""
        router = _make_router(has_pii_service=True)
        router._pii.detect_pii = MagicMock(return_value=False)

        decision = await router.select_provider(
            query="What is the architecture overview?", context_chunks=[]
        )

        assert decision.provider_name == "openrouter"


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


# ---------------------------------------------------------------------------
# Smart Collections & Reports routing (§5.2 quality-critical fallback)
# ---------------------------------------------------------------------------

class TestSmartCollectionsRouting:
    """Report / smart-collection tasks get Together.ai in their fallback chain."""

    @pytest.mark.asyncio
    async def test_report_task_routes_to_openrouter_with_together_in_chain(self):
        router = _make_router(has_together=True)
        decision = await router.select_provider(
            query="Generate report", context_chunks=[], task_type="report"
        )
        assert decision.provider_name == "openrouter"
        assert "together" in decision.metadata.get("chain", [])
        assert decision.metadata.get("task_type") == "report"

    @pytest.mark.asyncio
    async def test_smart_collection_task_routes_to_openrouter_with_together_in_chain(self):
        router = _make_router(has_together=True)
        decision = await router.select_provider(
            query="Smart folder", context_chunks=[], task_type="smart_collection"
        )
        assert decision.provider_name == "openrouter"
        assert "together" in decision.metadata.get("chain", [])
        assert decision.metadata.get("task_type") == "smart_collection"

    @pytest.mark.asyncio
    async def test_report_task_falls_back_together_when_openrouter_missing(self):
        router = _make_router(has_openrouter=False, has_together=True)
        decision = await router.select_provider(
            query="Generate report", context_chunks=[], task_type="report"
        )
        assert decision.provider_name == "together"

    @pytest.mark.asyncio
    async def test_chat_task_does_not_include_together_in_chain(self):
        router = _make_router(has_together=True)
        decision = await router.select_provider(
            query="Hello", context_chunks=[], task_type="chat"
        )
        assert decision.provider_name == "openrouter"
        assert "together" not in decision.metadata.get("chain", [])


class TestGenerateReportCompletion:
    """§5.2 Report generation fallback chain: complex → standard → together → bullets."""

    @pytest.mark.asyncio
    async def test_primary_openrouter_complex_succeeds(self):
        router = _make_router(has_openrouter=True)

        async def _mock_chat(*args, **kwargs):
            yield "report text"

        router._openrouter.chat_completion = _mock_chat

        chunks = []
        async for chunk in router.generate_report_completion(
            messages=[{"role": "user", "content": "test"}]
        ):
            chunks.append(chunk)
        assert "".join(chunks) == "report text"

    @pytest.mark.asyncio
    async def test_secondary_openrouter_standard_on_complex_failure(self):
        router = _make_router(has_openrouter=True)
        call_count = 0

        async def _mock_chat(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            tier = kwargs.get("tier", "complex")
            if tier == "complex":
                raise RuntimeError("complex failed")
            yield "standard report"

        router._openrouter.chat_completion = _mock_chat

        chunks = []
        async for chunk in router.generate_report_completion(
            messages=[{"role": "user", "content": "test"}]
        ):
            chunks.append(chunk)
        assert "".join(chunks) == "standard report"
        assert call_count == 2  # complex attempted, then standard

    @pytest.mark.asyncio
    async def test_tertiary_together_on_openrouter_failure(self):
        router = _make_router(has_openrouter=True, has_together=True)

        async def _mock_or(*args, **kwargs):
            raise RuntimeError("openrouter failed")

        async def _mock_together(*args, **kwargs):
            yield "together report"

        router._openrouter.chat_completion = _mock_or
        router._together.chat_completion = _mock_together

        chunks = []
        async for chunk in router.generate_report_completion(
            messages=[{"role": "user", "content": "test"}]
        ):
            chunks.append(chunk)
        assert "".join(chunks) == "together report"

    @pytest.mark.asyncio
    async def test_ultimate_bullet_summary_when_all_providers_fail(self):
        router = _make_router(has_openrouter=True, has_together=True)

        async def _mock_fail(*args, **kwargs):
            raise RuntimeError("always fails")

        router._openrouter.chat_completion = _mock_fail
        router._together.chat_completion = _mock_fail

        context_chunks = [
            {"document_name": "Doc A", "chunk_text": "First sentence. More text."},
            {"document_name": "Doc B", "chunk_text": "Another sentence here."},
        ]
        chunks = []
        async for chunk in router.generate_report_completion(
            messages=[{"role": "user", "content": "test"}],
            context_chunks=context_chunks,
        ):
            chunks.append(chunk)
        result = "".join(chunks)
        assert "Doc A" in result
        assert "Doc B" in result
        assert "First sentence" in result


class TestBulletSummaryFallback:
    """Graceful degradation to bullet-point summary without LLM synthesis."""

    def test_generate_bullet_summary_with_context_chunks(self):
        router = _make_router()
        context = [
            {"document_name": "Doc A", "chunk_text": "First sentence. More text."},
            {"document_name": "Doc B", "chunk_text": "Another sentence here."},
        ]
        summary = router._generate_bullet_summary(context)
        assert summary is not None
        assert "Doc A" in summary
        assert "Doc B" in summary
        assert "First sentence" in summary

    def test_generate_bullet_summary_deduplicates_similar_chunks(self):
        router = _make_router()
        context = [
            {"document_name": "Doc A", "chunk_text": "Same text."},
            {"document_name": "Doc A", "chunk_text": "Same text."},
        ]
        summary = router._generate_bullet_summary(context)
        # Should only appear once due to deduplication
        assert summary is not None
        assert summary.count("Doc A") == 1

    def test_generate_bullet_summary_empty_context_returns_none(self):
        router = _make_router()
        assert router._generate_bullet_summary([]) is None
        assert router._generate_bullet_summary(None) is None


# ---------------------------------------------------------------------------
# Async helpers
# ---------------------------------------------------------------------------

async def async_gen(items):
    """Helper: async generator yielding items."""
    for item in items:
        yield item


async def async_gen_raise(exc):
    """Helper: async generator that immediately raises."""
    raise exc
    yield ""  # pragma: no cover
