"""
Together.ai service for LLM access — Llama 3.1 70B (quality-critical fallback)

Together.ai provides OpenAI-compatible API access to open-weight models.
Primary use: tertiary fallback for Smart Collections & Reports when
OpenRouter (Claude Sonnet / Mistral Small) fails or JSON parsing fails.

Model: meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo
- Price-competitive
- Good JSON adherence for structured report generation
- Reliable fallback for complex reasoning tasks
"""

import json
import logging
import os
from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Any

import httpx

from app.services.base_llm_service import BaseLLMService
from app.services.llm_http_client import LLMHTTPClient

logger = logging.getLogger(__name__)

# Configuration
TOGETHER_API_KEY = os.getenv("TOGETHER_API_KEY")
TOGETHER_BASE_URL = os.getenv("TOGETHER_BASE_URL", "https://api.together.xyz/v1")
TOGETHER_MODEL = os.getenv("TOGETHER_MODEL", "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo")

# Context window limits (in tokens)
TOGETHER_CONTEXT_WINDOW = 128_000
MAX_INPUT_TOKENS = 120_000


class TogetherService(BaseLLMService):
    """Service for interacting with Together.ai API (OpenAI-compatible)."""

    def __init__(self):
        self.api_key = TOGETHER_API_KEY
        self.base_url = TOGETHER_BASE_URL
        self.model = TOGETHER_MODEL

        if self.api_key:
            logger.info("Together service initialized with model: %s", self.model)
        else:
            logger.warning("TOGETHER_API_KEY not configured")

    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count via shared utility (§7.4)."""
        from app.services.token_utils import estimate_tokens

        return estimate_tokens(text)

    def _truncate_messages(
        self, messages: list[dict[str, str]], max_tokens: int = MAX_INPUT_TOKENS
    ) -> list[dict[str, str]]:
        """Truncate messages to fit within context window."""
        total_tokens = 0
        truncated_messages = []

        for msg in messages:
            content = msg.get("content", "")
            msg_tokens = self._estimate_tokens(content)

            if total_tokens + msg_tokens > max_tokens:
                available = max_tokens - total_tokens
                if available > 100:
                    truncated_content = content[: available * 4]
                    truncated_messages.append(
                        {
                            "role": msg.get("role", "user"),
                            "content": truncated_content + "... [truncated]",
                        }
                    )
                break

            truncated_messages.append(msg)
            total_tokens += msg_tokens

        return truncated_messages

    def _get_headers(self) -> dict[str, str]:
        """Get headers for Together.ai API requests."""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def chat_completion(
        self,
        messages: list[dict[str, str]],
        stream: bool = False,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> AsyncGenerator[str, None]:
        """
        Generate chat completion using Together.ai (OpenAI-compatible API).

        Args:
            messages: List of message dicts with role and content.
            stream: Whether to stream the response.
            temperature: Sampling temperature (0.0 to 1.0).
            max_tokens: Maximum tokens to generate.
            **kwargs: Forward-compatible extra arguments (ignored).

        Yields:
            Response text chunks if streaming, full content if not.
        """
        if not self.api_key:
            logger.error("TOGETHER_API_KEY not configured")
            yield "Error: Together.ai API key not configured"
            return

        # Enforce context window limit
        truncated_messages = self._truncate_messages(messages)

        # Check if truncation occurred
        original_tokens = sum(
            self._estimate_tokens(m.get("content", "")) for m in messages
        )
        truncated_tokens = sum(
            self._estimate_tokens(m.get("content", "")) for m in truncated_messages
        )

        if original_tokens > truncated_tokens:
            logger.warning(
                "Together input truncated from ~%s to ~%s tokens to fit context window",
                original_tokens,
                truncated_tokens,
            )

        payload = {
            "model": self.model,
            "messages": truncated_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }

        client = LLMHTTPClient.get_client()

        try:
            if stream:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    headers=self._get_headers(),
                    json=payload,
                ) as response:
                    response.raise_for_status()

                    async for line in response.aiter_lines():
                        if line.strip():
                            if line.startswith("data: "):
                                data_str = line[6:]  # Remove "data: " prefix
                                if data_str == "[DONE]":
                                    break
                                try:
                                    data = json.loads(data_str)
                                    if "choices" in data and len(data["choices"]) > 0:
                                        delta = data["choices"][0].get("delta", {})
                                        content = delta.get("content", "")
                                        if content:
                                            yield content
                                except json.JSONDecodeError:
                                    continue
            else:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=self._get_headers(),
                    json=payload,
                )
                response.raise_for_status()
                result = response.json()

                if "choices" in result and len(result["choices"]) > 0:
                    content = result["choices"][0].get("message", {}).get("content", "")
                    usage = result.get("usage", {})

                    if content:
                        yield content

                    # Return usage as last chunk
                    if usage:
                        yield f"\n__USAGE__: {json.dumps(usage)}"
                else:
                    logger.error("Unexpected Together.ai response: %s", result)
                    yield "Error: Unexpected response from Together.ai API"

        except httpx.HTTPStatusError as e:
            error_body = ""
            try:
                error_body = e.response.text
            except (AttributeError, KeyError):
                pass

            if e.response.status_code == 429:
                logger.warning("Together.ai rate limit hit (429)")

            logger.error("Together.ai API error: %s - %s", e, error_body)
            yield f"Error: API error - {e.response.status_code if e.response else 'unknown'}"
        except httpx.HTTPError as e:
            logger.error("Together.ai connection error: %s", str(e))
            yield f"Error: {str(e)}"

    async def health_check(self) -> dict[str, Any]:
        """
        Check Together.ai service health.

        Returns:
            Health status dictionary.
        """
        health_status = {
            "service": "together",
            "status": "healthy",
            "model": self.model,
            "api_configured": bool(self.api_key),
            "timestamp": datetime.utcnow().isoformat(),
        }

        if not self.api_key:
            health_status["status"] = "unhealthy"
            health_status["error"] = "API key not configured"
            return health_status

        # Test API connectivity with a simple request
        try:
            test_messages = [{"role": "user", "content": "test"}]
            response_text = ""
            async for chunk in self.chat_completion(
                test_messages, stream=False, max_tokens=10
            ):
                if not chunk.startswith("Error:") and not chunk.startswith("__USAGE__"):
                    response_text += chunk

            if response_text:
                health_status["status"] = "healthy"
                health_status["api_reachable"] = True
            else:
                health_status["status"] = "degraded"
                health_status["error"] = "API returned empty response"

        except Exception as e:
            health_status["status"] = "unhealthy"
            health_status["error"] = str(e)
            health_status["api_reachable"] = False

        return health_status

    async def get_usage_stats(self) -> dict[str, Any]:
        """
        Get usage statistics for the service.

        Returns:
            Usage statistics dictionary.
        """
        return {
            "service": "together",
            "model": self.model,
            "config": {
                "base_url": self.base_url,
            },
            "timestamp": datetime.utcnow().isoformat(),
        }


# Global Together.ai service instance
together_service = TogetherService()
