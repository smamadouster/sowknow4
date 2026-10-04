"""
LLM Service Test Fixtures

Provides reusable pytest fixtures and mock factories for all LLM services:
- OpenRouter (via the SAKANAL gateway, with Redis cache)
- Ollama (local, confidential docs)

The legacy direct-provider clients were removed (single-door doctrine:
all cloud LLM traffic transits the SAKANAL gateway).

Usage in tests:
    from tests.fixtures.llm_services import (
        mock_ollama_service, mock_openrouter_service,
        llm_response_factory, streaming_response_factory
    )

Or use the pytest fixtures directly (requires conftest to import them):
    def test_something(mock_openrouter_service):
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
# OpenRouter Service mock (via SAKANAL gateway, with Redis cache)
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
    service.model = "deepseek/deepseek-v4-pro"

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
def mock_ollama_service():
    """pytest fixture: mock OllamaService with healthy default."""
    return make_mock_ollama_service()


@pytest.fixture
def mock_openrouter_service():
    """pytest fixture: mock OpenRouterService with healthy default."""
    return make_mock_openrouter_service()


@pytest.fixture
def mock_all_llm_services(mock_ollama_service, mock_openrouter_service):
    """pytest fixture: all LLM services mocked, returned as a dict."""
    return {
        "ollama": mock_ollama_service,
        "openrouter": mock_openrouter_service,
    }


# ---------------------------------------------------------------------------
# Context manager patches for patching module-level service singletons
# ---------------------------------------------------------------------------

def patch_ollama_service(response_content: str = "Ollama test response.", **kwargs):
    """Context manager to patch the module-level ollama_service singleton."""
    mock = make_mock_ollama_service(response_content=response_content, **kwargs)
    return patch("app.services.ollama_service.ollama_service", mock)


def patch_openrouter_service(response_content: str = "OpenRouter test response.", **kwargs):
    """Context manager to patch the module-level openrouter_service singleton."""
    mock = make_mock_openrouter_service(response_content=response_content, **kwargs)
    return patch("app.services.openrouter_service.openrouter_service", mock)
