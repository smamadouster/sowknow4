"""
Abstract base class for all LLM services.

Defines the standard interface that MiniMax, Kimi, OpenRouter, and Ollama services must implement.
Allows the LLM router to call any provider through a uniform API.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from typing import Any


class BaseLLMService(ABC):
    """Standard interface for LLM service providers."""

    @abstractmethod
    async def chat_completion(
        self,
        messages: list[dict[str, str]],
        stream: bool = False,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        **kwargs: Any,
    ) -> AsyncGenerator[str, None]:
        """
        Generate a chat completion.

        Args:
            messages: List of {"role": ..., "content": ...} dicts (OpenAI format).
            stream: Whether to stream the response token-by-token.
            temperature: Sampling temperature (0–1).
            max_tokens: Maximum tokens to generate.
            **kwargs: Provider-specific parameters (e.g. cache_key for MiniMax,
                      num_predict for Ollama). Implementations must accept and
                      ignore unknown kwargs to stay forward-compatible.

        Yields:
            Text chunks. Non-streaming implementations must still be async
            generators — yield the complete content in a single chunk.
            The sentinel string "__USAGE__..." may be yielded last for token
            accounting; callers must skip lines starting with "__USAGE__".
        """

    @abstractmethod
    async def health_check(self) -> dict[str, Any]:
        """
        Check whether the service is reachable and ready.

        Returns:
            Dict with at minimum:
                "service": str — provider name
                "status": "healthy" | "degraded" | "unhealthy"
            May include additional provider-specific fields.
        """
