"""
Unit tests for the DeepSeek/Qwen tiered model config and model-level failover
in openrouter_service (2026-08-05 DeepSeek migration).

Covers:
- Tier model selection (deepseek flash/pro)
- Per-tier fallback model resolution (qwen/qwen3.8-max)
- Failover to the tier fallback model on 400/404/429/5xx, exactly once
- No failover recursion (second failure surfaces the error string)
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.openrouter_service import (
    OPENROUTER_TIER_FALLBACK_MODELS,
    OPENROUTER_TIER_MODELS,
    OpenRouterService,
)


class TestTierModelConfig:
    """Tests for tier model selection and fallback resolution."""

    def test_default_tier_models_are_deepseek(self):
        """Default tiers must be DeepSeek V4 Flash (simple/standard) + V4 Pro (complex)."""
        assert OPENROUTER_TIER_MODELS["simple"] == "deepseek/deepseek-v4-flash-0731"
        assert OPENROUTER_TIER_MODELS["standard"] == "deepseek/deepseek-v4-flash-0731"
        assert OPENROUTER_TIER_MODELS["complex"] == "deepseek/deepseek-v4-pro"

    def test_default_fallback_is_qwen(self):
        """Default per-tier fallback must be qwen/qwen3.8-max."""
        for tier in ("simple", "standard", "complex"):
            assert OPENROUTER_TIER_FALLBACK_MODELS[tier] == "qwen/qwen3.8-max"

    def test_select_model_for_tier(self):
        service = OpenRouterService()
        assert service.select_model_for_tier("simple") == OPENROUTER_TIER_MODELS["simple"]
        assert service.select_model_for_tier("standard") == OPENROUTER_TIER_MODELS["standard"]
        assert service.select_model_for_tier("complex") == OPENROUTER_TIER_MODELS["complex"]
        # Unknown tier falls back to the primary model
        assert service.select_model_for_tier("bogus") == service.model

    def test_fallback_model_for_resolves_per_tier(self):
        service = OpenRouterService()
        assert service._fallback_model_for("standard") == "qwen/qwen3.8-max"
        assert service._fallback_model_for("complex") == "qwen/qwen3.8-max"

    def test_fallback_model_for_returns_none_when_same(self):
        """When fallback equals the tier model, no failover should occur."""
        service = OpenRouterService()
        # Simulate a misconfigured fallback identical to the primary.
        with patch.object(service, "_tier_fallback_models", {"standard": "deepseek/deepseek-v4-flash-0731"}):
            assert service._fallback_model_for("standard") is None


class TestModelLevelFailover:
    """Tests that the tier fallback model is used once on HTTP failures."""

    def _make_raising_service(self, status_code: int):
        import httpx
        from unittest.mock import patch as _patch

        mock_resp = MagicMock()
        mock_resp.status_code = status_code
        mock_resp.text = "boom"

        def _raise_for_status():
            raise httpx.HTTPStatusError(f"{status_code} Error", request=MagicMock(), response=mock_resp)

        mock_resp.raise_for_status.side_effect = _raise_for_status

        mock_client = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_resp)

        # OPENROUTER_API_KEY is read at import time as a module constant.
        key_patcher = _patch("app.services.openrouter_service.OPENROUTER_API_KEY", "test-key")
        key_patcher.start()
        try:
            service = OpenRouterService()
        finally:
            key_patcher.stop()
        return service, mock_client

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "status_code,expects_raise",
        [(400, False), (404, False), (429, True), (500, False), (503, False)],
    )
    async def test_fails_over_to_fallback_model_once(self, status_code, expects_raise):
        """A 400/404/429/5xx must retry the tier fallback model exactly once.

        400/404/5xx surface the error string; a 429 that also fails on the
        fallback model propagates so the router can run its own tier fallback.
        """
        import httpx

        service, mock_client = self._make_raising_service(status_code)
        with patch(
            "app.services.llm_http_client.LLMHTTPClient.get_client",
            return_value=mock_client,
        ):
            chunks = []
            if expects_raise:
                with pytest.raises(httpx.HTTPStatusError):
                    async for chunk in service.chat_completion(
                        [{"role": "user", "content": "test"}],
                        stream=False,
                        max_tokens=10,
                    ):
                        chunks.append(chunk)
            else:
                async for chunk in service.chat_completion(
                    [{"role": "user", "content": "test"}],
                    stream=False,
                    max_tokens=10,
                ):
                    chunks.append(chunk)
                assert "Error: API error" in "".join(chunks)

            # Primary + fallback attempt = 2 POSTs to OpenRouter.
            assert mock_client.post.call_count == 2

    @pytest.mark.asyncio
    async def test_no_failover_when_disabled(self):
        """With _allow_model_failover=False the fallback model is never tried."""
        service, mock_client = self._make_raising_service(503)
        with patch(
            "app.services.llm_http_client.LLMHTTPClient.get_client",
            return_value=mock_client,
        ):
            chunks = []
            async for chunk in service.chat_completion(
                [{"role": "user", "content": "test"}],
                stream=False,
                max_tokens=10,
                _allow_model_failover=False,
            ):
                chunks.append(chunk)

            assert mock_client.post.call_count == 1
            assert "Error: API error" in "".join(chunks)
