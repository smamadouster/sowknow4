"""
Kimi service for general chat (Moonshot AI)

LLM Routing Role:
- General chat (no document context): Kimi 2.5 (moonshot-v1-8k/32k/128k)
- Chatbot, Telegram bot, search agentic flows
- Falls back to MiniMax if unavailable (handled by caller in chat_service.py)

API: Moonshot AI OpenAI-compatible endpoint
Auth: KIMI_API_KEY environment variable
"""

import os
import logging
import json
from typing import AsyncGenerator, List, Dict, Any, Optional
from datetime import datetime

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

# Configuration — Moonshot AI OpenAI-compatible endpoint
KIMI_API_KEY = os.getenv("KIMI_API_KEY")
KIMI_BASE_URL = os.getenv("KIMI_BASE_URL", "https://api.moonshot.cn/v1")
# moonshot-v1-128k is the flagship 128K context model (like "kimi-latest")
KIMI_MODEL = os.getenv("KIMI_MODEL", "moonshot-v1-128k")

# Context window limits (in tokens)
KIMI_CONTEXT_WINDOW = 128000  # moonshot-v1-128k supports 128K tokens
MAX_INPUT_TOKENS = 120000  # Leave headroom for response


class KimiService:
    """Service for interacting with the Kimi API (Moonshot AI).

    Uses the OpenAI-compatible /v1/chat/completions endpoint.
    Intended for general-purpose chat, Telegram bot, and search-agentic flows
    where no confidential documents are involved.
    """

    def __init__(self):
        self.api_key = KIMI_API_KEY
        self.base_url = KIMI_BASE_URL.rstrip("/")
        self.model = KIMI_MODEL

        if self.api_key:
            logger.info(f"Kimi service initialized with model: {self.model}")
        else:
            logger.warning("KIMI_API_KEY not configured — Kimi service unavailable")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _estimate_tokens(self, text: str) -> int:
        """Rough token estimate: 4 chars ≈ 1 token."""
        if not text:
            return 0
        return len(text) // 4

    def _truncate_messages(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int = MAX_INPUT_TOKENS,
    ) -> List[Dict[str, str]]:
        """Truncate message list to stay within the context window."""
        total_tokens = 0
        truncated: List[Dict[str, str]] = []

        for msg in messages:
            content = msg.get("content", "")
            msg_tokens = self._estimate_tokens(content)

            if total_tokens + msg_tokens > max_tokens:
                available = max_tokens - total_tokens
                if available > 100:
                    truncated.append(
                        {
                            "role": msg.get("role", "user"),
                            "content": content[: available * 4] + "... [truncated]",
                        }
                    )
                break

            truncated.append(msg)
            total_tokens += msg_tokens

        return truncated

    def _get_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------
    # Primary interface
    # ------------------------------------------------------------------

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        stream: bool = False,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        cache_key: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """Generate a chat completion via the Kimi (Moonshot AI) API.

        Matches the calling convention used by OpenRouterService and
        MiniMaxService so chat_service.py can treat all providers uniformly.

        Args:
            messages: OpenAI-style message list (role + content dicts).
            stream: Whether to stream the response token-by-token.
            temperature: Sampling temperature (0.0–1.0).
            max_tokens: Maximum tokens to generate.
            cache_key: Unused; accepted for interface compatibility.
            user_id: Unused; accepted for interface compatibility.

        Yields:
            Response text chunks.  A ``__USAGE__`` sentinel is yielded last
            for non-streaming calls to carry token-usage data.
        """
        if not self.api_key:
            logger.error("KIMI_API_KEY not configured")
            yield "Error: Kimi API key not configured"
            return

        truncated_messages = self._truncate_messages(messages)

        # Log truncation if it occurred
        original_count = sum(
            self._estimate_tokens(m.get("content", "")) for m in messages
        )
        truncated_count = sum(
            self._estimate_tokens(m.get("content", "")) for m in truncated_messages
        )
        if original_count > truncated_count:
            logger.warning(
                f"Kimi: input truncated from ~{original_count} to "
                f"~{truncated_count} tokens"
            )

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
                        f"{self.base_url}/chat/completions",
                        headers=self._get_headers(),
                        json=payload,
                    ) as response:
                        response.raise_for_status()
                        async for line in response.aiter_lines():
                            if not line.strip():
                                continue
                            if line.startswith("data: "):
                                data_str = line[6:]
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
                        content = (
                            result["choices"][0].get("message", {}).get("content", "")
                        )
                        usage = result.get("usage", {})

                        yield content

                        # Emit usage sentinel to match OpenRouter pattern
                        if usage:
                            yield f"\n__USAGE__: {json.dumps(usage)}"
                    else:
                        logger.error(f"Unexpected Kimi response: {result}")
                        yield "Error: Unexpected response from Kimi API"

        except httpx.HTTPStatusError as e:
            error_body = ""
            try:
                error_body = e.response.text
            except Exception:
                pass

            if e.response.status_code == 429:
                logger.warning("Kimi rate limit hit (429), will retry with backoff")
                raise  # Let tenacity retry

            logger.error(f"Kimi API error {e.response.status_code}: {error_body}")
            yield f"Error: Kimi API returned {e.response.status_code}"

        except httpx.HTTPError as e:
            logger.error(f"Kimi connection error: {str(e)}")
            yield f"Error: {str(e)}"

    # ------------------------------------------------------------------
    # Utility methods
    # ------------------------------------------------------------------

    async def health_check(self) -> Dict[str, Any]:
        """Check Kimi service reachability.

        Returns a status dict compatible with the admin health endpoint.
        """
        status: Dict[str, Any] = {
            "service": "kimi",
            "status": "healthy",
            "model": self.model,
            "api_configured": bool(self.api_key),
            "timestamp": datetime.utcnow().isoformat(),
        }

        if not self.api_key:
            status["status"] = "unhealthy"
            status["error"] = "KIMI_API_KEY not configured"
            return status

        try:
            test_messages = [{"role": "user", "content": "ping"}]
            response_text = ""
            async for chunk in self.chat_completion(
                test_messages, stream=False, max_tokens=5
            ):
                if not chunk.startswith("__USAGE__"):
                    response_text += chunk

            if response_text and not response_text.startswith("Error:"):
                status["api_reachable"] = True
            else:
                status["status"] = "degraded"
                status["error"] = "API returned empty or error response"
                status["api_reachable"] = False

        except Exception as e:
            status["status"] = "unhealthy"
            status["error"] = str(e)
            status["api_reachable"] = False

        return status

    async def get_usage_stats(self) -> Dict[str, Any]:
        """Return service configuration metadata."""
        return {
            "service": "kimi",
            "model": self.model,
            "config": {
                "base_url": self.base_url,
                "context_window": KIMI_CONTEXT_WINDOW,
            },
            "timestamp": datetime.utcnow().isoformat(),
        }


# Global singleton — imported by chat_service.py
kimi_service = KimiService()
