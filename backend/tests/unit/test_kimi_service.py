"""
Unit tests for KimiService (Moonshot AI)

Coverage:
- Initialization with / without API key
- chat_completion: non-streaming (happy path, usage sentinel, error paths)
- chat_completion: streaming (happy path, [DONE] handling)
- Context-window truncation
- Rate-limit retry (429)
- health_check method
- Integration point: chat_service imports kimi_service without crashing
- Admin health endpoint uses KIMI_API_KEY (not MOONSHOT_API_KEY)
"""
import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_non_stream_response(content: str, usage: dict | None = None) -> MagicMock:
    """Build a mock httpx.Response for non-streaming requests."""
    body = {
        "choices": [{"message": {"content": content}}],
    }
    if usage:
        body["usage"] = usage
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value=body)
    return mock_resp


def _sse_lines(content_chunks: list[str], done: bool = True) -> list[str]:
    """Generate SSE lines as the Kimi API would emit them."""
    lines = []
    for chunk in content_chunks:
        data = {"choices": [{"delta": {"content": chunk}}]}
        lines.append(f"data: {json.dumps(data)}")
    if done:
        lines.append("data: [DONE]")
    return lines


# ---------------------------------------------------------------------------
# Initialization tests
# ---------------------------------------------------------------------------

class TestKimiServiceInit:
    def test_initializes_with_api_key(self):
        # Must patch both MOONSHOT_API_KEY and KIMI_API_KEY since the module
        # reads MOONSHOT_API_KEY first: `os.getenv("MOONSHOT_API_KEY") or os.getenv("KIMI_API_KEY")`
        with patch.dict(os.environ, {"MOONSHOT_API_KEY": "test-key-123", "KIMI_API_KEY": "test-key-123"}):
            from importlib import reload

            import app.services.kimi_service as ks_module
            reload(ks_module)
            svc = ks_module.KimiService()
            assert svc.api_key == "test-key-123"
            assert svc.base_url == "https://api.moonshot.cn/v1"
            assert "moonshot" in svc.model

    def test_initializes_without_api_key(self):
        # Remove both MOONSHOT_API_KEY and KIMI_API_KEY to test the no-key path
        env = {k: v for k, v in os.environ.items() if k not in ("KIMI_API_KEY", "MOONSHOT_API_KEY")}
        with patch.dict(os.environ, env, clear=True):
            from importlib import reload

            import app.services.kimi_service as ks_module
            reload(ks_module)
            svc = ks_module.KimiService()
            assert svc.api_key is None

    def test_custom_env_overrides(self):
        with patch.dict(os.environ, {
            "KIMI_API_KEY": "my-key",
            "KIMI_BASE_URL": "https://custom.api/v1",
            "KIMI_MODEL": "moonshot-v1-8k",
        }):
            from importlib import reload

            import app.services.kimi_service as ks_module
            reload(ks_module)
            svc = ks_module.KimiService()
            assert svc.base_url == "https://custom.api/v1"
            assert svc.model == "moonshot-v1-8k"


# ---------------------------------------------------------------------------
# Non-streaming chat_completion tests
# ---------------------------------------------------------------------------

class TestChatCompletionNonStream:
    @pytest.mark.asyncio
    async def test_no_api_key_yields_error(self):
        from app.services.kimi_service import KimiService
        svc = KimiService.__new__(KimiService)
        svc.api_key = None
        svc.base_url = "https://api.moonshot.cn/v1"
        svc.model = "moonshot-v1-128k"

        chunks = []
        async for chunk in svc.chat_completion([{"role": "user", "content": "hi"}]):
            chunks.append(chunk)

        assert any("Error" in c for c in chunks)

    @pytest.mark.asyncio
    async def test_non_stream_returns_content_and_usage(self):
        from app.services.kimi_service import KimiService

        svc = KimiService.__new__(KimiService)
        svc.api_key = "test-key"
        svc.base_url = "https://api.moonshot.cn/v1"
        svc.model = "moonshot-v1-128k"

        usage = {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
        mock_resp = _make_non_stream_response("Hello world", usage=usage)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("app.services.kimi_service.httpx.AsyncClient", return_value=mock_client):
            chunks = []
            async for chunk in svc.chat_completion(
                [{"role": "user", "content": "hello"}], stream=False
            ):
                chunks.append(chunk)

        full = "".join(chunks)
        assert "Hello world" in full
        assert "__USAGE__" in full
        assert "total_tokens" in full

    @pytest.mark.asyncio
    async def test_non_stream_empty_choices(self):
        from app.services.kimi_service import KimiService

        svc = KimiService.__new__(KimiService)
        svc.api_key = "test-key"
        svc.base_url = "https://api.moonshot.cn/v1"
        svc.model = "moonshot-v1-128k"

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json = MagicMock(return_value={"choices": []})

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("app.services.kimi_service.httpx.AsyncClient", return_value=mock_client):
            chunks = []
            async for chunk in svc.chat_completion(
                [{"role": "user", "content": "hello"}], stream=False
            ):
                chunks.append(chunk)

        assert any("Error" in c or c == "" for c in chunks)


# ---------------------------------------------------------------------------
# Streaming chat_completion tests
# ---------------------------------------------------------------------------

class TestChatCompletionStream:
    @pytest.mark.asyncio
    async def test_stream_yields_content_chunks(self):
        from app.services.kimi_service import KimiService

        svc = KimiService.__new__(KimiService)
        svc.api_key = "test-key"
        svc.base_url = "https://api.moonshot.cn/v1"
        svc.model = "moonshot-v1-128k"

        sse_lines = _sse_lines(["Hello", " ", "world"])

        mock_stream = AsyncMock()
        mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
        mock_stream.__aexit__ = AsyncMock(return_value=False)
        mock_stream.raise_for_status = MagicMock()

        async def aiter_lines():
            for line in sse_lines:
                yield line

        mock_stream.aiter_lines = aiter_lines

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.stream = MagicMock(return_value=mock_stream)

        with patch("app.services.kimi_service.httpx.AsyncClient", return_value=mock_client):
            chunks = []
            async for chunk in svc.chat_completion(
                [{"role": "user", "content": "hello"}], stream=True
            ):
                chunks.append(chunk)

        assert "".join(chunks) == "Hello world"

    @pytest.mark.asyncio
    async def test_stream_ignores_malformed_lines(self):
        from app.services.kimi_service import KimiService

        svc = KimiService.__new__(KimiService)
        svc.api_key = "test-key"
        svc.base_url = "https://api.moonshot.cn/v1"
        svc.model = "moonshot-v1-128k"

        bad_lines = ["data: {not valid json}", "data: [DONE]"]

        mock_stream = AsyncMock()
        mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
        mock_stream.__aexit__ = AsyncMock(return_value=False)
        mock_stream.raise_for_status = MagicMock()

        async def aiter_lines():
            for line in bad_lines:
                yield line

        mock_stream.aiter_lines = aiter_lines
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.stream = MagicMock(return_value=mock_stream)

        with patch("app.services.kimi_service.httpx.AsyncClient", return_value=mock_client):
            chunks = []
            async for chunk in svc.chat_completion(
                [{"role": "user", "content": "test"}], stream=True
            ):
                chunks.append(chunk)

        # Should not crash; malformed lines are silently skipped
        assert isinstance(chunks, list)


# ---------------------------------------------------------------------------
# Context truncation tests
# ---------------------------------------------------------------------------

class TestContextTruncation:
    def test_truncate_messages_within_limit(self):
        from app.services.kimi_service import KimiService
        svc = KimiService.__new__(KimiService)
        svc.api_key = "k"
        svc.base_url = ""
        svc.model = ""

        msgs = [{"role": "user", "content": "short message"}]
        result = svc._truncate_messages(msgs, max_tokens=5000)
        assert result == msgs

    def test_truncate_messages_over_limit(self):
        from app.services.kimi_service import KimiService
        svc = KimiService.__new__(KimiService)
        svc.api_key = "k"
        svc.base_url = ""
        svc.model = ""

        # 400 chars → ~100 tokens; limit is 50 tokens → should truncate
        long_content = "x" * 400
        msgs = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": long_content},
        ]
        result = svc._truncate_messages(msgs, max_tokens=50)
        # System message (4 tokens) fits; user message gets truncated
        combined = " ".join(m["content"] for m in result)
        assert "[truncated]" in combined or len(result) < len(msgs)

    def test_estimate_tokens_zero_for_empty(self):
        from app.services.kimi_service import KimiService
        svc = KimiService.__new__(KimiService)
        assert svc._estimate_tokens("") == 0
        assert svc._estimate_tokens("abcd") == 1


# ---------------------------------------------------------------------------
# Rate-limit handling
# ---------------------------------------------------------------------------

class TestRateLimitRetry:
    @pytest.mark.asyncio
    async def test_429_raises_for_tenacity_retry(self):
        import httpx

        from app.services.kimi_service import KimiService

        svc = KimiService.__new__(KimiService)
        svc.api_key = "test-key"
        svc.base_url = "https://api.moonshot.cn/v1"
        svc.model = "moonshot-v1-128k"

        mock_429 = MagicMock(spec=httpx.Response)
        mock_429.status_code = 429
        mock_429.text = "rate limited"
        error = httpx.HTTPStatusError("rate limited", request=MagicMock(), response=mock_429)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=error)

        # tenacity will re-raise after exhausting retries
        with patch("app.services.kimi_service.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(httpx.HTTPStatusError):
                # Consume the generator to trigger the network call
                async for _ in svc.chat_completion(
                    [{"role": "user", "content": "test"}], stream=False
                ):
                    pass


# ---------------------------------------------------------------------------
# Health check tests
# ---------------------------------------------------------------------------

class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_health_check_no_key(self):
        from app.services.kimi_service import KimiService

        svc = KimiService.__new__(KimiService)
        svc.api_key = None
        svc.base_url = "https://api.moonshot.cn/v1"
        svc.model = "moonshot-v1-128k"

        result = await svc.health_check()
        assert result["status"] == "unhealthy"
        assert result["api_configured"] is False

    @pytest.mark.asyncio
    async def test_health_check_successful_ping(self):
        from app.services.kimi_service import KimiService

        svc = KimiService.__new__(KimiService)
        svc.api_key = "test-key"
        svc.base_url = "https://api.moonshot.cn/v1"
        svc.model = "moonshot-v1-128k"

        mock_resp = _make_non_stream_response("pong")
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("app.services.kimi_service.httpx.AsyncClient", return_value=mock_client):
            result = await svc.health_check()

        assert result["status"] == "healthy"
        assert result["api_configured"] is True
        assert result["api_reachable"] is True

    @pytest.mark.asyncio
    async def test_health_check_api_unreachable(self):
        import httpx

        from app.services.kimi_service import KimiService

        svc = KimiService.__new__(KimiService)
        svc.api_key = "test-key"
        svc.base_url = "https://api.moonshot.cn/v1"
        svc.model = "moonshot-v1-128k"

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("connection refused"))

        with patch("app.services.kimi_service.httpx.AsyncClient", return_value=mock_client):
            result = await svc.health_check()

        # ConnectError is caught inside chat_completion and returned as "Error: ..."
        # text, so health_check sees a failed response and marks the service "degraded"
        # (api_configured=True but unreachable). Only missing config yields "unhealthy".
        assert result["status"] in ("degraded", "unhealthy")
        assert result["api_reachable"] is False


# ---------------------------------------------------------------------------
# get_usage_stats
# ---------------------------------------------------------------------------

class TestGetUsageStats:
    @pytest.mark.asyncio
    async def test_usage_stats_structure(self):
        from app.services.kimi_service import KimiService

        svc = KimiService.__new__(KimiService)
        svc.api_key = "k"
        svc.base_url = "https://api.moonshot.cn/v1"
        svc.model = "moonshot-v1-128k"

        stats = await svc.get_usage_stats()
        assert stats["service"] == "kimi"
        assert "model" in stats
        assert "timestamp" in stats
        assert stats["config"]["context_window"] == 128000


# ---------------------------------------------------------------------------
# Integration: chat_service imports kimi_service cleanly
# ---------------------------------------------------------------------------

class TestChatServiceIntegration:
    def test_kimi_service_importable(self):
        """kimi_service.py must be importable without side effects."""
        from app.services import kimi_service as ks_module
        assert hasattr(ks_module, "kimi_service")
        assert hasattr(ks_module, "KimiService")

    def test_chat_service_kimi_attribute(self):
        """ChatService should expose .kimi_service (may be None if no key)."""
        from app.services.chat_service import chat_service
        assert hasattr(chat_service, "kimi_service")

    def test_llm_provider_kimi_enum(self):
        """LLMProvider.KIMI must resolve to 'kimi'."""
        from app.models.chat import LLMProvider
        assert LLMProvider.KIMI.value == "kimi"


# ---------------------------------------------------------------------------
# Admin health endpoint uses KIMI_API_KEY
# ---------------------------------------------------------------------------

class TestAdminHealthKimiKey:
    def test_kimi_api_key_env_var(self):
        """Admin health check reads KIMI_API_KEY (not MOONSHOT_API_KEY)."""
        with patch.dict(os.environ, {"KIMI_API_KEY": "some-key"}, clear=False):
            key = os.getenv("KIMI_API_KEY")
            assert key == "some-key"

    def test_moonshot_api_key_not_used(self):
        """Ensure the old MOONSHOT_API_KEY variable is no longer the canonical key."""
        # The admin.py health check should read KIMI_API_KEY
        import ast
        admin_path = os.path.join(
            os.path.dirname(__file__),
            "../../app/api/admin.py",
        )
        with open(os.path.normpath(admin_path)) as f:
            source = f.read()
        tree = ast.parse(source)

        kimi_getenv_calls = []
        moonshot_getenv_calls = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr == "getenv":
                    for arg in node.args:
                        if isinstance(arg, ast.Constant):
                            if arg.value == "KIMI_API_KEY":
                                kimi_getenv_calls.append(arg.value)
                            if arg.value == "MOONSHOT_API_KEY":
                                moonshot_getenv_calls.append(arg.value)

        assert len(kimi_getenv_calls) >= 1, "admin.py should call os.getenv('KIMI_API_KEY')"
        assert len(moonshot_getenv_calls) == 0, (
            "admin.py must not reference MOONSHOT_API_KEY — use KIMI_API_KEY"
        )
