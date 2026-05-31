"""
Shared async HTTP client for all LLM providers with connection pooling.

Replaces per-request httpx.AsyncClient instantiation across OpenRouter,
MiniMax, Kimi, and Ollama services. Eliminates TCP handshake overhead
and prevents connection pool exhaustion under load.
"""

import logging

import httpx
from typing import Optional

logger = logging.getLogger(__name__)


class LLMHTTPClient:
    """Shared async HTTP client for all LLM providers with connection pooling."""

    _instance: Optional[httpx.AsyncClient] = None
    _limits = httpx.Limits(
        max_keepalive_connections=20,
        max_connections=50,
        keepalive_expiry=30.0,
    )
    _timeout = httpx.Timeout(connect=5.0, read=60.0, write=10.0, pool=5.0)

    @classmethod
    def get_client(cls) -> httpx.AsyncClient:
        if cls._instance is None or cls._instance.is_closed:
            if cls._instance is not None and cls._instance.is_closed:
                logger.warning(
                    "LLMHTTPClient: recreating AsyncClient because previous instance was closed"
                )
            cls._instance = httpx.AsyncClient(
                limits=cls._limits,
                timeout=cls._timeout,
                http2=False,
            )
            logger.info(
                "LLMHTTPClient: created new AsyncClient (keepalive=%s, max_connections=%s)",
                cls._limits.max_keepalive_connections,
                cls._limits.max_connections,
            )
        return cls._instance

    @classmethod
    async def close(cls) -> None:
        if cls._instance is not None and not cls._instance.is_closed:
            await cls._instance.aclose()
            cls._instance = None
