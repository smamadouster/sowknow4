"""
LLM Service Test Fixtures

Provides reusable pytest fixtures and mock factories for all LLM services:
- OpenRouter (Kimi K2.5 via OpenRouter, with Redis cache)
- MiniMax (direct API, M2.5)
- Kimi (direct Moonshot AI API)
- Ollama (local, confidential docs)

Usage in tests:
    from tests.fixtures.llm_services import (
        mock_kimi_service, mock_minimax_service,
        mock_ollama_service, mock_openrouter_service,
        llm_response_factory, streaming_response_factory
    )

Or use the pytest fixtures directly (requires conftest to import them):
    def test_something(mock_kimi_service):
        ...
"""
from collections.abc import AsyncGenerator
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Response factory helpers
# ---------------------------------------------------------------------------

def llm_response_factory(content: str = "This is a test response.") -> str:
    """Create a plain text LLM response string."""
    return content


async def streaming_response_factory(
    chunks: list[str] = None,
) -> AsyncGenerator[str, None]:
    """Async generator that yields response chunks (simulates streaming)."""
    if chunks is None:
        chunks = ["This ", "is ", "a ", "test ", "response."]
    for chunk in chunks:
        yield chunk


def health_ok_factory(service_name: str = "llm") -> dict[str, Any]:
    """Return a healthy status dict like the real services return."""
    return {"status": "healthy", "service": service_name, "model": "test-model"}


def health_error_factory(service_name: str = "llm", error: str = "Connection refused") -> dict[str, Any]:
    """Return an unhealthy status dict."""
    return {"status": "unhealthy", "service": service_name, "error": error}


# ---------------------------------------------------------------------------
# Kimi Service mock (Moonshot AI direct)
# ---------------------------------------------------------------------------

def make_mock_kimi_service(
    response_content: str = "Kimi test response.",
    health_status: str = "healthy",
    raise_on_call: Exception | None = None,
) -> MagicMock:
    """
    Create a mock KimiService instance.

    The mock mimics the real KimiService interface:
    - chat_completion(messages, stream=False, ...) -> AsyncGenerator[str] or str
    - health_check() -> Dict
    """
    service = MagicMock()
    service.api_key = "test-kimi-key"
    service.base_url = "https://api.moonshot.cn/v1"
    service.model = "moonshot-v1-128k"

    if raise_on_call:
        service.chat_completion = AsyncMock(side_effect=raise_on_call)
    else:
        async def _kimi_chat_completion(messages, stream=False, **kwargs):
            if stream:
                async def _stream():
                    for word in response_content.split():
                        yield word + " "
                return _stream()
            return response_content

        service.chat_completion = _kimi_chat_completion

    if health_status == "healthy":
        service.health_check = AsyncMock(return_value=health_ok_factory("kimi"))
    else:
        service.health_check = AsyncMock(
            return_value=health_error_factory("kimi", "API key not configured")
        )

    return service


# ---------------------------------------------------------------------------
# MiniMax Service mock (direct API)
# ---------------------------------------------------------------------------

def make_mock_minimax_service(
    response_content: str = "MiniMax test response.",
    health_status: str = "healthy",
    raise_on_call: Exception | None = None,
) -> MagicMock:
    """
    Create a mock MiniMaxService instance.

    Interface:
    - chat_completion(messages, stream=False, ...) -> str
    - chat_completion_non_stream(messages, ...) -> str
    """
    service = MagicMock()
    service.api_key = "test-minimax-key"
    service.base_url = "https://api.minimax.chat"
    service.model = "MiniMax-M2.5"

    if raise_on_call:
        service.chat_completion = AsyncMock(side_effect=raise_on_call)
        service.chat_completion_non_stream = AsyncMock(side_effect=raise_on_call)
    else:
        async def _minimax_chat_completion(messages, stream=False, **kwargs):
            if stream:
                async def _stream():
                    for word in response_content.split():
                        yield word + " "
                return _stream()
            return response_content

        service.chat_completion = _minimax_chat_completion
        service.chat_completion_non_stream = AsyncMock(return_value=response_content)

    if health_status == "healthy":
        service.health_check = AsyncMock(return_value=health_ok_factory("minimax"))
    else:
        service.health_check = AsyncMock(
            return_value=health_error_factory("minimax", "API key not configured")
        )

    return service


# ---------------------------------------------------------------------------
# Ollama Service mock (local, confidential)
# ---------------------------------------------------------------------------

def make_mock_ollama_service(
    response_content: str = "Ollama test response.",
    health_status: str = "healthy",
    raise_on_call: Exception | None = None,
) -> MagicMock:
    """
    Create a mock OllamaService instance.

    Interface:
    - chat_completion(messages, stream=False, ...) -> AsyncGenerator[str] or str
    - generate(prompt, stream=False, ...) -> str
    - health_check() -> Dict
    """
    service = MagicMock()
    service.base_url = "http://ollama:11434"
    service.model = "mistral:7b-instruct"

    if raise_on_call:
        service.chat_completion = AsyncMock(side_effect=raise_on_call)
        service.generate = AsyncMock(side_effect=raise_on_call)
    else:
        async def _ollama_chat_completion(messages, stream=False, **kwargs):
            if stream:
                async def _stream():
                    for word in response_content.split():
                        yield word + " "
                return _stream()
            return response_content

        async def _ollama_generate(prompt, stream=False, **kwargs):
            if stream:
                async def _stream():
                    for word in response_content.split():
                        yield word + " "
                return _stream()
            return response_content

        service.chat_completion = _ollama_chat_completion
        service.generate = _ollama_generate

    if health_status == "healthy":
        service.health_check = AsyncMock(
            return_value={
                "status": "healthy",
                "service": "ollama",
                "model": service.model,
                "models_available": [service.model],
            }
        )
    else:
        service.health_check = AsyncMock(
            return_value=health_error_factory("ollama", "Ollama not running")
        )

    return service


# ---------------------------------------------------------------------------
# OpenRouter Service mock (Kimi K2.5 fallback, with Redis cache)
# ---------------------------------------------------------------------------

def make_mock_openrouter_service(
    response_content: str = "OpenRouter test response.",
    health_status: str = "healthy",
    cache_hit: bool = False,
    raise_on_call: Exception | None = None,
) -> MagicMock:
    """
    Create a mock OpenRouterService instance.

    Interface:
    - chat_completion(messages, stream=False, ...) -> AsyncGenerator[str] or str
    - check_cache(messages) -> Optional[str]
    - health_check() -> Dict
    - invalidate_collection_cache(collection_id) -> int
    """
    service = MagicMock()
    service.api_key = "test-openrouter-key"
    service.base_url = "https://openrouter.ai/api/v1"
    service.model = "moonshotai/kimi-k2.5"

    # Cache simulation
    service.check_cache = MagicMock(
        return_value=response_content if cache_hit else None
    )
    service.invalidate_collection_cache = MagicMock(return_value=0)

    if raise_on_call:
        service.chat_completion = AsyncMock(side_effect=raise_on_call)
    else:
        async def _openrouter_chat_completion(messages, stream=False, **kwargs):
            if stream:
                async def _stream():
                    for word in response_content.split():
                        yield word + " "
                return _stream()
            return response_content

        service.chat_completion = _openrouter_chat_completion

    if health_status == "healthy":
        service.health_check = AsyncMock(return_value=health_ok_factory("openrouter"))
    else:
        service.health_check = AsyncMock(
            return_value=health_error_factory("openrouter", "API key not configured")
        )

    service.get_usage_stats = AsyncMock(
        return_value={"requests": 0, "cache_hits": 0, "cache_misses": 0}
    )
    service.list_models = AsyncMock(return_value=[])

    return service


# ---------------------------------------------------------------------------
# pytest fixtures (importable into conftest.py or test modules)
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_kimi_service():
    """pytest fixture: mock KimiService with healthy default."""
    return make_mock_kimi_service()


@pytest.fixture
def mock_minimax_service():
    """pytest fixture: mock MiniMaxService with healthy default."""
    return make_mock_minimax_service()


@pytest.fixture
def mock_ollama_service():
    """pytest fixture: mock OllamaService with healthy default."""
    return make_mock_ollama_service()


@pytest.fixture
def mock_openrouter_service():
    """pytest fixture: mock OpenRouterService with healthy default."""
    return make_mock_openrouter_service()


@pytest.fixture
def mock_all_llm_services(mock_kimi_service, mock_minimax_service,
                           mock_ollama_service, mock_openrouter_service):
    """pytest fixture: all LLM services mocked, returned as a dict."""
    return {
        "kimi": mock_kimi_service,
        "minimax": mock_minimax_service,
        "ollama": mock_ollama_service,
        "openrouter": mock_openrouter_service,
    }


# ---------------------------------------------------------------------------
# Context manager patches for patching module-level service singletons
# ---------------------------------------------------------------------------

def patch_kimi_service(response_content: str = "Kimi test response.", **kwargs):
    """
    Context manager / decorator to patch the module-level kimi_service singleton.

    Usage:
        with patch_kimi_service("Hello from Kimi"):
            result = await chat_service.chat(...)
    """
    mock = make_mock_kimi_service(response_content=response_content, **kwargs)
    return patch("app.services.kimi_service.kimi_service", mock)


def patch_minimax_service(response_content: str = "MiniMax test response.", **kwargs):
    """Context manager to patch the module-level minimax_service singleton."""
    mock = make_mock_minimax_service(response_content=response_content, **kwargs)
    return patch("app.services.minimax_service.minimax_service", mock)


def patch_ollama_service(response_content: str = "Ollama test response.", **kwargs):
    """Context manager to patch the module-level ollama_service singleton."""
    mock = make_mock_ollama_service(response_content=response_content, **kwargs)
    return patch("app.services.ollama_service.ollama_service", mock)


def patch_openrouter_service(response_content: str = "OpenRouter test response.", **kwargs):
    """Context manager to patch the module-level openrouter_service singleton."""
    mock = make_mock_openrouter_service(response_content=response_content, **kwargs)
    return patch("app.services.openrouter_service.openrouter_service", mock)
