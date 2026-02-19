"""
OpenRouter service for LLM access (MiniMax, etc.)
OpenRouter provides OpenAI-compatible API access to multiple LLMs
"""
import os
import logging
import json
import asyncio
from typing import AsyncGenerator, List, Dict, Any, Optional
from datetime import datetime

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

# Configuration
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "minimax/minimax-01")
OPENROUTER_SITE_URL = os.getenv("OPENROUTER_SITE_URL", "https://sowknow.gollamtech.com")
OPENROUTER_SITE_NAME = os.getenv("OPENROUTER_SITE_NAME", "SOWKNOW")

# Context window limits (in tokens)
MINIMAX_CONTEXT_WINDOW = 128000  # MiniMax 2.5 supports 128K
MAX_INPUT_TOKENS = 120000  # Leave buffer for response


class OpenRouterService:
    """Service for interacting with OpenRouter API (OpenAI-compatible)"""

    def __init__(self):
        self.api_key = OPENROUTER_API_KEY
        self.base_url = OPENROUTER_BASE_URL
        self.model = OPENROUTER_MODEL
        self.site_url = OPENROUTER_SITE_URL
        self.site_name = OPENROUTER_SITE_NAME

        if self.api_key:
            logger.info(f"OpenRouter service initialized with model: {self.model}")
        else:
            logger.warning("OPENROUTER_API_KEY not configured")

    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count using simple character-based approximation"""
        if not text:
            return 0
        return len(text) // 4

    def _truncate_messages(self, messages: List[Dict[str, str]], max_tokens: int = MAX_INPUT_TOKENS) -> List[Dict[str, str]]:
        """Truncate messages to fit within context window"""
        total_tokens = 0
        truncated_messages = []
        
        for msg in messages:
            content = msg.get("content", "")
            msg_tokens = self._estimate_tokens(content)
            
            if total_tokens + msg_tokens > max_tokens:
                available = max_tokens - total_tokens
                if available > 100:
                    truncated_content = content[:available * 4]
                    truncated_messages.append({
                        "role": msg.get("role", "user"),
                        "content": truncated_content + "... [truncated]"
                    })
                break
            
            truncated_messages.append(msg)
            total_tokens += msg_tokens
        
        return truncated_messages

    def _get_headers(self) -> Dict[str, str]:
        """Get headers for OpenRouter API requests"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if self.site_url:
            headers["HTTP-Referer"] = self.site_url
        if self.site_name:
            headers["X-Title"] = self.site_name
        return headers

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        stream: bool = False,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        cache_key: Optional[str] = None
    ) -> AsyncGenerator[str, None]:
        """
        Generate chat completion using OpenRouter (OpenAI-compatible API)

        Args:
            messages: List of message dicts with role and content
            stream: Whether to stream the response
            temperature: Sampling temperature (0.0 to 1.0)
            max_tokens: Maximum tokens to generate
            cache_key: Optional key for caching (not used in OpenRouter)

        Yields:
            Response text chunks if streaming, full content if not
        """
        if not self.api_key:
            logger.error("OPENROUTER_API_KEY not configured")
            yield "Error: OpenRouter API key not configured"
            return

        # Enforce context window limit
        truncated_messages = self._truncate_messages(messages)
        
        # Check if truncation occurred
        original_tokens = sum(self._estimate_tokens(m.get("content", "")) for m in messages)
        truncated_tokens = sum(self._estimate_tokens(m.get("content", "")) for m in truncated_messages)
        
        if original_tokens > truncated_tokens:
            logger.warning(f"Input truncated from ~{original_tokens} to ~{truncated_tokens} tokens to fit context window")

        payload = {
            "model": self.model,
            "messages": truncated_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream
        }

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                if stream:
                    async with client.stream(
                        "POST",
                        f"{self.base_url}/chat/completions",
                        headers=self._get_headers(),
                        json=payload
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
                        json=payload
                    )
                    response.raise_for_status()
                    result = response.json()

                    if "choices" in result and len(result["choices"]) > 0:
                        content = result["choices"][0].get("message", {}).get("content", "")
                        usage = result.get("usage", {})

                        yield content

                        # Return usage as last chunk
                        if usage:
                            yield f"\n__USAGE__: {json.dumps(usage)}"
                    else:
                        logger.error(f"Unexpected OpenRouter response: {result}")
                        yield "Error: Unexpected response from OpenRouter API"

        except httpx.HTTPStatusError as e:
            error_body = ""
            try:
                error_body = e.response.text
            except:
                pass
            
            # Handle rate limit (429) errors with specific retry trigger
            if e.response.status_code == 429:
                logger.warning(f"OpenRouter rate limit hit (429), will retry with backoff")
                # Re-raise to trigger tenacity retry with exponential backoff
                raise
            
            logger.error(f"OpenRouter API error: {e} - {error_body}")
            yield f"Error: API error - {e.response.status_code if e.response else 'unknown'}"
        except httpx.HTTPError as e:
            logger.error(f"OpenRouter connection error: {str(e)}")
            yield f"Error: {str(e)}"

    async def health_check(self) -> Dict[str, Any]:
        """
        Check OpenRouter service health

        Returns:
            Health status dictionary
        """
        health_status = {
            "service": "openrouter",
            "status": "healthy",
            "model": self.model,
            "api_configured": bool(self.api_key),
            "timestamp": datetime.utcnow().isoformat()
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
                test_messages,
                stream=False,
                max_tokens=10
            ):
                if not chunk.startswith("__USAGE__"):
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

    async def get_usage_stats(self) -> Dict[str, Any]:
        """
        Get usage statistics for the service

        Returns:
            Usage statistics dictionary
        """
        return {
            "service": "openrouter",
            "model": self.model,
            "config": {
                "base_url": self.base_url,
            },
            "timestamp": datetime.utcnow().isoformat()
        }

    async def list_models(self) -> List[Dict[str, Any]]:
        """
        List available models from OpenRouter

        Returns:
            List of model dictionaries
        """
        if not self.api_key:
            return []

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{self.base_url}/models",
                    headers=self._get_headers()
                )
                response.raise_for_status()
                result = response.json()
                return result.get("data", [])
        except Exception as e:
            logger.error(f"Error listing models: {str(e)}")
            return []


# Global OpenRouter service instance
openrouter_service = OpenRouterService()
