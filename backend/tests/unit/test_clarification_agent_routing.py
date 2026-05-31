"""
Unit tests for ClarificationAgent confidential-document routing fix.

Verifies that the agent passes has_confidential to the unified LLM gateway
so routing is handled centrally — exactly like ResearcherAgent, AnswerAgent,
VerificationAgent.
"""
from unittest.mock import AsyncMock, MagicMock, patch

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
    agent.llm = MagicMock(name="llm")
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
# clarify() — has_confidential routing via LLM gateway
# ---------------------------------------------------------------------------

class TestClarifyUsesConfidentialRouting:
    @pytest.mark.asyncio
    async def test_use_ollama_kwarg_passes_has_confidential_true(self):
        """Legacy use_ollama=True must pass has_confidential=True to the gateway."""
        agent = _make_agent()

        async def _fake_completion(*args, **kwargs):
            yield '{"is_clear": true, "confidence": 0.9, "questions": [], "assumptions": [], "reasoning": "ok"}'

        agent.llm.chat_completion = _fake_completion

        request = ClarificationRequest(query="how old is grandpa?")
        result = await agent.clarify(request, use_ollama=True)

        assert result is not None
        assert result.is_clear is True

    @pytest.mark.asyncio
    async def test_confidential_sources_passes_has_confidential_true(self):
        """Confidential sources must pass has_confidential=True to the gateway."""
        agent = _make_agent()
        captured = []

        async def _capture(*args, **kwargs):
            captured.append(kwargs.get("has_confidential"))
            yield '{"is_clear": true, "confidence": 0.8, "questions": [], "assumptions": [], "reasoning": "ok"}'

        agent.llm.chat_completion = _capture

        request = ClarificationRequest(
            query="find secret docs", sources=[_confidential_source()]
        )
        await agent.clarify(request)

        assert captured == [True]

    @pytest.mark.asyncio
    async def test_public_sources_passes_has_confidential_false(self):
        """Public sources must pass has_confidential=False to the gateway."""
        agent = _make_agent()
        captured = []

        async def _capture(*args, **kwargs):
            captured.append(kwargs.get("has_confidential"))
            yield '{"is_clear": true, "confidence": 0.8, "questions": [], "assumptions": [], "reasoning": "ok"}'

        agent.llm.chat_completion = _capture

        request = ClarificationRequest(
            query="find family photos", sources=[_public_source()]
        )
        await agent.clarify(request)

        assert captured == [False]


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
