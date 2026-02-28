"""
Unit tests for ClarificationAgent confidential-document routing fix.

Verifies that the agent automatically selects Ollama for confidential
sources — exactly like ResearcherAgent, AnswerAgent, VerificationAgent —
without requiring the caller to pass an explicit `use_ollama=True`.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.agents.clarification_agent import (
    ClarificationAgent,
    ClarificationRequest,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_agent():
    agent = ClarificationAgent.__new__(ClarificationAgent)
    agent.ollama_service = MagicMock(name="ollama_service")
    agent.minimax_service = MagicMock(name="minimax_service")
    return agent


def _public_source():
    return {"document_id": "abc", "document_bucket": "public"}


def _confidential_source():
    return {"document_id": "xyz", "document_bucket": "confidential"}


# ---------------------------------------------------------------------------
# _has_confidential_documents
# ---------------------------------------------------------------------------

class TestHasConfidentialDocuments:
    def test_empty_sources_returns_false(self):
        agent = _make_agent()
        assert agent._has_confidential_documents([]) is False

    def test_none_sources_returns_false(self):
        agent = _make_agent()
        assert agent._has_confidential_documents(None) is False

    def test_only_public_returns_false(self):
        agent = _make_agent()
        assert agent._has_confidential_documents([_public_source()]) is False

    def test_confidential_returns_true(self):
        agent = _make_agent()
        assert agent._has_confidential_documents([_confidential_source()]) is True

    def test_mixed_sources_returns_true(self):
        agent = _make_agent()
        assert agent._has_confidential_documents(
            [_public_source(), _confidential_source()]
        ) is True


# ---------------------------------------------------------------------------
# _get_llm_service — routing decisions
# ---------------------------------------------------------------------------

class TestGetLLMService:
    def test_public_sources_returns_minimax(self):
        agent = _make_agent()
        request = ClarificationRequest(
            query="q", sources=[_public_source()]
        )
        assert agent._get_llm_service(request) is agent.minimax_service

    def test_confidential_sources_returns_ollama(self):
        agent = _make_agent()
        request = ClarificationRequest(
            query="q", sources=[_confidential_source()]
        )
        assert agent._get_llm_service(request) is agent.ollama_service

    def test_no_sources_returns_minimax(self):
        agent = _make_agent()
        request = ClarificationRequest(query="q")
        assert agent._get_llm_service(request) is agent.minimax_service

    def test_has_confidential_flag_true_returns_ollama(self):
        agent = _make_agent()
        request = ClarificationRequest(query="q", has_confidential=True)
        assert agent._get_llm_service(request) is agent.ollama_service

    def test_has_confidential_flag_false_returns_minimax(self):
        agent = _make_agent()
        request = ClarificationRequest(query="q", has_confidential=False)
        assert agent._get_llm_service(request) is agent.minimax_service

    def test_mixed_sources_routes_to_ollama(self):
        """Any confidential source in the list overrides to Ollama."""
        agent = _make_agent()
        request = ClarificationRequest(
            query="q",
            sources=[_public_source(), _confidential_source()],
        )
        assert agent._get_llm_service(request) is agent.ollama_service


# ---------------------------------------------------------------------------
# clarify() — backward-compat use_ollama kwarg
# ---------------------------------------------------------------------------

class TestClarifyUsesOllamaKwarg:
    @pytest.mark.asyncio
    async def test_use_ollama_kwarg_forces_ollama(self):
        """Legacy use_ollama=True must still route to Ollama."""
        agent = _make_agent()

        async def _fake_completion(messages, stream, temperature, max_tokens):
            yield '{"is_clear": true, "confidence": 0.9, "questions": [], "assumptions": [], "reasoning": "ok"}'

        agent.ollama_service.chat_completion = _fake_completion
        agent.minimax_service.chat_completion = AsyncMock()

        request = ClarificationRequest(query="how old is grandpa?")
        result = await agent.clarify(request, use_ollama=True)

        # Ollama was called (minimax was not)
        agent.minimax_service.chat_completion.assert_not_called()
        assert result is not None
        assert result.is_clear is True

    @pytest.mark.asyncio
    async def test_no_kwarg_public_uses_minimax(self):
        """Default (no kwarg, public sources) must use MiniMax."""
        agent = _make_agent()

        async def _fake_completion(messages, stream, temperature, max_tokens):
            yield '{"is_clear": true, "confidence": 0.8, "questions": [], "assumptions": [], "reasoning": "ok"}'

        agent.minimax_service.chat_completion = _fake_completion
        agent.ollama_service.chat_completion = AsyncMock()

        request = ClarificationRequest(
            query="find family photos", sources=[_public_source()]
        )
        result = await agent.clarify(request)

        agent.ollama_service.chat_completion.assert_not_called()
        assert result is not None


# ---------------------------------------------------------------------------
# ClarificationRequest dataclass
# ---------------------------------------------------------------------------

class TestClarificationRequestDefaults:
    def test_has_confidential_defaults_to_false(self):
        req = ClarificationRequest(query="test")
        assert req.has_confidential is False

    def test_sources_defaults_to_none(self):
        req = ClarificationRequest(query="test")
        assert req.sources is None

    def test_can_set_sources_and_flag(self):
        req = ClarificationRequest(
            query="test",
            sources=[_confidential_source()],
            has_confidential=True,
        )
        assert req.has_confidential is True
        assert len(req.sources) == 1
