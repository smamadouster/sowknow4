"""
Unit tests for P1-D3: Cache hit indicator in streaming SSE pipeline.

Verifies:
1. OpenRouterService.check_cache() returns cached content when Redis has it
2. generate_chat_response_stream emits cache_hit=True in llm_info event when
   the cache contains the response
3. generate_chat_response_stream emits cache_hit=False for Kimi / Ollama paths
4. The data payloads include the `type` field so the frontend can dispatch
"""

import json
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# OpenRouterService.check_cache()
# ---------------------------------------------------------------------------

class TestOpenRouterCheckCache:
    """Unit tests for the new check_cache() method."""

    def _make_service(self, redis_value=None, cache_enabled=True):
        """Return a partially-mocked OpenRouterService instance."""
        from app.services.openrouter_service import OpenRouterService

        svc = OpenRouterService.__new__(OpenRouterService)
        svc.model = "minimax/minimax-01"
        svc._cache_enabled = cache_enabled
        svc.api_key = "test-key"
        svc.base_url = "https://openrouter.ai/api/v1"
        svc.site_url = ""
        svc.site_name = ""

        redis_mock = MagicMock()
        redis_mock.get = MagicMock(return_value=redis_value)

        with patch("app.services.openrouter_service._get_redis_client", return_value=redis_mock):
            svc._redis_mock = redis_mock  # keep a reference for assertion
        return svc, redis_mock

    def test_returns_cached_string_when_hit(self):
        from app.services.openrouter_service import OpenRouterService
        svc = OpenRouterService.__new__(OpenRouterService)
        svc.model = "minimax/minimax-01"
        svc._cache_enabled = True

        redis_mock = MagicMock()
        redis_mock.get = MagicMock(return_value="cached answer")

        messages = [{"role": "user", "content": "What is 2+2?"}]

        with patch("app.services.openrouter_service._get_redis_client", return_value=redis_mock):
            result = svc.check_cache(messages)

        assert result == "cached answer"

    def test_returns_none_on_cache_miss(self):
        from app.services.openrouter_service import OpenRouterService
        svc = OpenRouterService.__new__(OpenRouterService)
        svc.model = "minimax/minimax-01"
        svc._cache_enabled = True

        redis_mock = MagicMock()
        redis_mock.get = MagicMock(return_value=None)

        messages = [{"role": "user", "content": "Unknown query"}]

        with patch("app.services.openrouter_service._get_redis_client", return_value=redis_mock):
            result = svc.check_cache(messages)

        assert result is None

    def test_returns_none_when_cache_disabled(self):
        from app.services.openrouter_service import OpenRouterService
        svc = OpenRouterService.__new__(OpenRouterService)
        svc.model = "minimax/minimax-01"
        svc._cache_enabled = False

        messages = [{"role": "user", "content": "test"}]
        result = svc.check_cache(messages)
        assert result is None

    def test_returns_none_when_redis_unavailable(self):
        from app.services.openrouter_service import OpenRouterService
        svc = OpenRouterService.__new__(OpenRouterService)
        svc.model = "minimax/minimax-01"
        svc._cache_enabled = True

        messages = [{"role": "user", "content": "test"}]
        with patch("app.services.openrouter_service._get_redis_client", return_value=None):
            result = svc.check_cache(messages)
        assert result is None

    def test_returns_none_on_redis_exception(self):
        from app.services.openrouter_service import OpenRouterService
        svc = OpenRouterService.__new__(OpenRouterService)
        svc.model = "minimax/minimax-01"
        svc._cache_enabled = True

        redis_mock = MagicMock()
        redis_mock.get = MagicMock(side_effect=Exception("Redis timeout"))

        messages = [{"role": "user", "content": "test"}]
        with patch("app.services.openrouter_service._get_redis_client", return_value=redis_mock):
            result = svc.check_cache(messages)
        assert result is None


# ---------------------------------------------------------------------------
# Helper to drain an async generator into a list of parsed SSE data events
# ---------------------------------------------------------------------------

async def _collect_sse_events(gen: AsyncGenerator) -> list[dict]:
    """Collect all `data:` lines from an SSE generator and parse their JSON."""
    events = []
    async for line in gen:
        if line.startswith("data: "):
            payload = line[6:].strip()
            if payload:
                try:
                    events.append(json.loads(payload))
                except json.JSONDecodeError:
                    pass
    return events


# ---------------------------------------------------------------------------
# generate_chat_response_stream SSE format + cache_hit flag
# ---------------------------------------------------------------------------

class TestStreamingCacheHit:
    """
    Tests for generate_chat_response_stream: verifies that:
    - Every `data:` payload contains a `type` field
    - `llm_info` event includes `cache_hit` bool
    - When OpenRouter cache has a response, cache_hit=True and no LLM call
    - For Kimi / Ollama paths, cache_hit=False
    """

    def _make_chat_service(self):
        from app.services.chat_service import ChatService
        svc = ChatService.__new__(ChatService)
        svc.kimi_service = None
        svc.minimax_service = None
        svc.openrouter_service = None
        # Use spec to prevent MagicMock auto-creating check_cache on ollama mock
        svc.ollama_service = MagicMock(spec=["chat_completion"])
        return svc

    @pytest.mark.asyncio
    async def test_llm_info_event_has_type_field(self):
        """Every SSE data payload must include a `type` field for frontend dispatch."""

        svc = self._make_chat_service()

        # Ollama path (no cache)
        async def fake_ollama_stream(messages, stream=False):
            yield "Hello"

        svc.ollama_service.chat_completion = fake_ollama_stream

        with patch.object(svc, "retrieve_relevant_chunks", new=AsyncMock(return_value=([], False))), \
             patch.object(svc, "get_conversation_history", new=AsyncMock(return_value=[])), \
             patch.object(svc, "build_rag_context", return_value=[{"role": "user", "content": "hi"}]):
            events = await _collect_sse_events(
                svc.generate_chat_response_stream(
                    session_id="s1", user_message="hi", db=MagicMock(), current_user=MagicMock()
                )
            )

        for ev in events:
            assert "type" in ev, f"Missing `type` in event: {ev}"

    @pytest.mark.asyncio
    async def test_llm_info_contains_cache_hit_false_for_ollama(self):
        """Ollama path always emits cache_hit=False."""

        svc = self._make_chat_service()

        async def fake_stream(messages, stream=False):
            yield "response"

        svc.ollama_service.chat_completion = fake_stream

        with patch.object(svc, "retrieve_relevant_chunks", new=AsyncMock(return_value=([], True))), \
             patch.object(svc, "get_conversation_history", new=AsyncMock(return_value=[])), \
             patch.object(svc, "build_rag_context", return_value=[{"role": "user", "content": "q"}]):
            events = await _collect_sse_events(
                svc.generate_chat_response_stream(
                    session_id="s1", user_message="q", db=MagicMock(), current_user=MagicMock()
                )
            )

        llm_info = next((e for e in events if e.get("type") == "llm_info"), None)
        assert llm_info is not None, "No llm_info event found"
        assert llm_info.get("cache_hit") is False

    @pytest.mark.asyncio
    async def test_cache_hit_true_when_openrouter_has_cached_response(self):
        """When OpenRouter cache has a response, cache_hit=True and LLM is not called."""

        svc = self._make_chat_service()

        # Wire up a mock OpenRouter service that says "cache hit"
        mock_openrouter = MagicMock()
        mock_openrouter.check_cache = MagicMock(return_value="The cached answer")
        llm_called = []

        async def fake_llm_stream(messages, stream=False):
            llm_called.append(True)
            yield "should not be called"

        mock_openrouter.chat_completion = fake_llm_stream
        svc.openrouter_service = mock_openrouter

        with patch.object(svc, "retrieve_relevant_chunks", new=AsyncMock(return_value=(
            [{"document_id": "d1", "document_name": "doc.pdf", "chunk_id": "c1",
              "chunk_text": "ctx", "relevance_score": 0.9, "document_bucket": "public"}], False
        ))), \
             patch.object(svc, "get_conversation_history", new=AsyncMock(return_value=[])), \
             patch.object(svc, "build_rag_context", return_value=[{"role": "user", "content": "q"}]):
            events = await _collect_sse_events(
                svc.generate_chat_response_stream(
                    session_id="s1", user_message="q", db=MagicMock(), current_user=MagicMock()
                )
            )

        # cache_hit must be True in llm_info
        llm_info = next((e for e in events if e.get("type") == "llm_info"), None)
        assert llm_info is not None, "No llm_info event"
        assert llm_info.get("cache_hit") is True

        # The LLM should NOT have been called
        assert llm_called == [], "LLM should not be invoked on a cache hit"

        # The cached content must appear in a message event
        msg_events = [e for e in events if e.get("type") == "message"]
        combined = "".join(e.get("content", "") for e in msg_events)
        assert "The cached answer" in combined

    @pytest.mark.asyncio
    async def test_cache_hit_false_when_openrouter_cache_miss(self):
        """When OpenRouter cache has no entry, cache_hit=False and LLM is called."""

        svc = self._make_chat_service()

        mock_openrouter = MagicMock()
        mock_openrouter.check_cache = MagicMock(return_value=None)  # cache miss
        llm_called = []

        async def fake_llm_stream(messages, stream=False):
            llm_called.append(True)
            yield "live response"

        mock_openrouter.chat_completion = fake_llm_stream
        svc.openrouter_service = mock_openrouter

        with patch.object(svc, "retrieve_relevant_chunks", new=AsyncMock(return_value=(
            [{"document_id": "d1", "document_name": "doc.pdf", "chunk_id": "c1",
              "chunk_text": "ctx", "relevance_score": 0.9, "document_bucket": "public"}], False
        ))), \
             patch.object(svc, "get_conversation_history", new=AsyncMock(return_value=[])), \
             patch.object(svc, "build_rag_context", return_value=[{"role": "user", "content": "q"}]):
            events = await _collect_sse_events(
                svc.generate_chat_response_stream(
                    session_id="s1", user_message="q", db=MagicMock(), current_user=MagicMock()
                )
            )

        llm_info = next((e for e in events if e.get("type") == "llm_info"), None)
        assert llm_info is not None
        assert llm_info.get("cache_hit") is False
        assert llm_called == [True], "LLM must be called on cache miss"

    @pytest.mark.asyncio
    async def test_all_events_have_type_field(self):
        """Verify every emitted data event has a `type` field (frontend contract)."""

        svc = self._make_chat_service()

        async def fake_stream(messages, stream=False):
            yield "chunk1"
            yield "chunk2"

        svc.ollama_service.chat_completion = fake_stream

        with patch.object(svc, "retrieve_relevant_chunks", new=AsyncMock(return_value=([], False))), \
             patch.object(svc, "get_conversation_history", new=AsyncMock(return_value=[])), \
             patch.object(svc, "build_rag_context", return_value=[{"role": "user", "content": "q"}]):
            events = await _collect_sse_events(
                svc.generate_chat_response_stream(
                    session_id="s1", user_message="q", db=MagicMock(), current_user=MagicMock()
                )
            )

        # Every event must have a type field
        for ev in events:
            assert "type" in ev, f"Event missing `type`: {ev}"

        # Check all expected types are present
        types = {e["type"] for e in events}
        assert "llm_info" in types
        assert "message" in types
        assert "sources" in types
        assert "done" in types

    @pytest.mark.asyncio
    async def test_kimi_path_has_no_check_cache(self):
        """OpenRouter service without check_cache must default to cache_hit=False.

        The routing chain is: confidential→Ollama, minimax→MiniMax, openrouter→OpenRouter,
        else→Ollama.  We wire a mock openrouter service whose spec omits check_cache
        (mimicking a Kimi-only deployment where the cache layer isn't present) and
        verify cache_hit=False is emitted and the LLM is still called.
        """

        svc = self._make_chat_service()

        # OpenRouter service without check_cache attribute
        mock_openrouter = MagicMock(spec=["chat_completion"])  # no check_cache
        svc.minimax_service = None
        svc.openrouter_service = mock_openrouter
        llm_called = []

        async def fake_openrouter_stream(messages, stream=False):
            llm_called.append(True)
            yield "openrouter response"

        mock_openrouter.chat_completion = fake_openrouter_stream

        with patch.object(svc, "retrieve_relevant_chunks", new=AsyncMock(return_value=([], False))), \
             patch.object(svc, "get_conversation_history", new=AsyncMock(return_value=[])), \
             patch.object(svc, "build_rag_context", return_value=[{"role": "user", "content": "q"}]):
            events = await _collect_sse_events(
                svc.generate_chat_response_stream(
                    session_id="s1", user_message="q", db=MagicMock(), current_user=MagicMock()
                )
            )

        llm_info = next((e for e in events if e.get("type") == "llm_info"), None)
        assert llm_info is not None
        assert llm_info.get("cache_hit") is False
        # LLM was still called
        assert llm_called == [True]
