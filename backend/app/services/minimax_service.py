"""
MiniMax service for direct API access (no OpenRouter markup)
"""

import json
import logging
import os
from collections.abc import AsyncGenerator

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.services.base_llm_service import BaseLLMService

logger = logging.getLogger(__name__)

# Configuration
MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY")
MINIMAX_BASE_URL = os.getenv("MINIMAX_BASE_URL", "https://api.minimax.chat")
MINIMAX_MODEL = os.getenv("MINIMAX_MODEL", "MiniMax-M2.5")

# Context window limits (in tokens)
MINIMAX_CONTEXT_WINDOW = 128000
MAX_INPUT_TOKENS = 120000


class MiniMaxService(BaseLLMService):
    """Service for interacting with MiniMax API directly"""

    def __init__(self):
        self.api_key = MINIMAX_API_KEY
        self.base_url = MINIMAX_BASE_URL
        self.model = MINIMAX_MODEL

        if self.api_key:
            logger.info(f"MiniMax service initialized with model: {self.model}")
        else:
            logger.warning("MINIMAX_API_KEY not configured")

    def _estimate_tokens(self, text: str) -> int:
        if not text:
            return 0
        return len(text) // 4

    def _truncate_messages(
        self, messages: list[dict[str, str]], max_tokens: int = MAX_INPUT_TOKENS
    ) -> list[dict[str, str]]:
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
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def chat_completion(
        self,
        messages: list[dict[str, str]],
        stream: bool = False,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        cache_key: str | None = None,
    ) -> AsyncGenerator[str, None]:
        """
        Generate chat completion using MiniMax API directly
        """
        if not self.api_key:
            yield "Error: MINIMAX_API_KEY not configured"
            return

        truncated_messages = self._truncate_messages(messages)

        payload = {
            "model": self.model,
            "messages": truncated_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                if stream:
                    async with client.stream(
                        "POST",
                        f"{self.base_url}/v1/text/chatcompletion_v2",
                        json=payload,
                        headers=self._get_headers(),
                    ) as response:
                        response.raise_for_status()
                        async for line in response.aiter_lines():
                            if line.strip():
                                try:
                                    data = json.loads(line)
                                    if "choices" in data and len(data["choices"]) > 0:
                                        delta = data["choices"][0].get("delta", {})
                                        content = delta.get("content", "")
                                        if content:
                                            yield content
                                except json.JSONDecodeError:
                                    continue
                else:
                    response = await client.post(
                        f"{self.base_url}/v1/text/chatcompletion_v2",
                        json=payload,
                        headers=self._get_headers(),
                    )
                    response.raise_for_status()
                    data = response.json()

                    if "choices" in data and len(data["choices"]) > 0:
                        content = data["choices"][0].get("message", {}).get("content", "")
                        yield content

        except httpx.HTTPStatusError as e:
            logger.error(f"MiniMax API error: {e.response.status_code} - {e.response.text}")
            yield f"Error: MiniMax API returned {e.response.status_code}"
        except Exception as e:
            logger.error(f"MiniMax service error: {str(e)}")
            yield f"Error: {str(e)}"

    async def chat_completion_non_stream(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> str:
        """Non-streaming version"""
        result = ""
        async for chunk in self.chat_completion(messages, stream=False, temperature=temperature, max_tokens=max_tokens):
            result += chunk
        return result

    async def health_check(self) -> dict:
        """Check whether MiniMax API is reachable."""
        if not self.api_key:
            return {"service": "minimax", "status": "unhealthy", "reason": "MINIMAX_API_KEY not configured"}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.base_url}/v1/text/chatcompletion_v2",
                    headers=self._get_headers(),
                )
                if response.status_code in (200, 400, 405):
                    return {"service": "minimax", "status": "healthy", "model": self.model}
                return {"service": "minimax", "status": "degraded", "http_status": response.status_code}
        except Exception as e:
            return {"service": "minimax", "status": "unhealthy", "reason": str(e)}


# Global instance
minimax_service = MiniMaxService()
