"""
Kimi 2.5 Service for Chatbot, Telegram, and Search Agentic

Uses Moonshot AI API for conversational AI features.
"""
import logging
import os
import httpx
import time
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class SimpleCache:
    """Simple in-memory cache for Kimi responses"""
    def __init__(self, ttl: int = 3600, max_size: int = 100):
        self.cache: Dict[str, tuple[Dict[str, Any], float]] = {}
        self.ttl = ttl
        self.max_size = max_size

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        if key in self.cache:
            data, timestamp = self.cache[key]
            if time.time() - timestamp < self.ttl:
                return data
            else:
                del self.cache[key]
        return None

    def set(self, key: str, value: Dict[str, Any]):
        if len(self.cache) >= self.max_size:
            # Remove oldest entry
            oldest_key = min(self.cache.keys(), key=lambda k: self.cache[k][1])
            del self.cache[oldest_key]
        self.cache[key] = (value, time.time())


class KimiService:
    """
    Kimi 2.5 API client for Moonshot AI

    Used for:
    - Chatbot conversations
    - Telegram bot
    - Search agentic workflows
    """

    def __init__(self):
        self.api_key = os.getenv("KIMI_API_KEY", "")
        self.base_url = "https://api.moonshot.cn/v1"
        self.model = os.getenv("KIMI_MODEL", "moonshot-v1-8k")
        self.timeout = 30.0
        self.max_retries = 3

        # Simple cache for context
        self.cache = SimpleCache(ttl=3600, max_size=100)

        if not self.api_key:
            logger.warning("KIMI_API_KEY not configured - Kimi service will be unavailable")

    async def health_check(self) -> Dict[str, Any]:
        """Check if Kimi API is accessible"""
        if not self.api_key:
            return {
                "service": "kimi",
                "status": "unhealthy",
                "model": self.model,
                "api_configured": False,
                "api_reachable": False,
                "error": "KIMI_API_KEY not configured"
            }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": self.model,
                        "messages": [{"role": "user", "content": "ping"}],
                        "max_tokens": 5
                    }
                )

                if response.status_code == 200:
                    return {
                        "service": "kimi",
                        "status": "healthy",
                        "model": self.model,
                        "api_configured": True,
                        "api_reachable": True
                    }
                else:
                    return {
                        "service": "kimi",
                        "status": "unhealthy",
                        "model": self.model,
                        "api_configured": True,
                        "api_reachable": False,
                        "error": f"HTTP {response.status_code}"
                    }

        except Exception as e:
            return {
                "service": "kimi",
                "status": "unhealthy",
                "model": self.model,
                "api_configured": True,
                "api_reachable": False,
                "error": str(e)
            }

    async def chat_completion_dict(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 2000,
        stream: bool = False,
        use_cache: bool = True
    ) -> Dict[str, Any]:
        """
        Generate chat completion using Kimi 2.5

        Args:
            messages: List of message dicts with 'role' and 'content'
            temperature: Sampling temperature (0-1)
            max_tokens: Maximum tokens to generate
            stream: Whether to stream responses
            use_cache: Whether to use context caching

        Returns:
            Response dict with content, metadata
        """
        if not self.api_key:
            raise ValueError("KIMI_API_KEY not configured")

        # Check cache for identical recent requests
        cache_key = self._generate_cache_key(messages, temperature, max_tokens)
        if use_cache:
            cached = self.cache.get(cache_key)
            if cached:
                logger.info(f"Cache hit for Kimi request")
                return cached

        # Prepare request
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream
        }

        # Execute with retries
        for attempt in range(self.max_retries):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(
                        f"{self.base_url}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json"
                        },
                        json=payload
                    )

                    response.raise_for_status()
                    data = response.json()

                    # Extract response
                    content = data["choices"][0]["message"]["content"]
                    result = {
                        "content": content,
                        "model": self.model,
                        "provider": "kimi",
                        "usage": data.get("usage", {}),
                        "finish_reason": data["choices"][0].get("finish_reason"),
                        "cached": False
                    }

                    # Cache the result
                    if use_cache:
                        self.cache.set(cache_key, result)

                    return result

            except httpx.HTTPStatusError as e:
                logger.warning(f"Kimi API error (attempt {attempt + 1}): {e.response.status_code}")
                if e.response.status_code == 401:
                    raise ValueError("Invalid Kimi API key")
                elif e.response.status_code == 429:
                    await self._handle_rate_limit()
                elif attempt == self.max_retries - 1:
                    raise

            except Exception as e:
                logger.error(f"Kimi API error: {e}")
                if attempt == self.max_retries - 1:
                    raise

        raise Exception("Max retries exceeded for Kimi API")

    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        stream: bool = False,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        cache_key: Optional[str] = None
    ):
        """
        Async generator for chat completion (compatible with Gemini/Ollama interface)

        Yields response text chunks. For non-streaming, yields the full response.
        """
        result = await self.chat_completion_dict(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=stream,
            use_cache=True
        )

        # Yield usage info first (for compatibility)
        if result.get("usage"):
            usage = result["usage"]
            yield f"__USAGE__|prompt_tokens={usage.get('prompt_tokens', 0)}|completion_tokens={usage.get('completion_tokens', 0)}"

        # Yield content
        yield result["content"]

    def _generate_cache_key(self, messages: List[Dict], temperature: float, max_tokens: int) -> str:
        """Generate cache key from request parameters"""
        import hashlib
        key_parts = [
            str(msg.get("role", "")) + msg.get("content", "")[:100]
            for msg in messages[-5:]  # Last 5 messages
        ]
        key_parts.append(str(temperature))
        key_parts.append(str(max_tokens))
        key_string = "|".join(key_parts)
        return hashlib.md5(key_string.encode()).hexdigest()

    async def _handle_rate_limit(self):
        """Handle rate limiting with exponential backoff"""
        import asyncio
        await asyncio.sleep(2 ** self.max_retries)  # Exponential backoff

    async def count_tokens(self, text: str) -> int:
        """
        Estimate token count for text

        Kimi (Moonshot) uses similar tokenization to GPT - approximately
        1 token per 3-4 characters for English, more for Chinese.
        """
        # Simple heuristic: ~1.3 tokens per 3 characters
        # Accurate estimation would require tiktoken or similar
        return len(text) // 3

    async def truncate_to_token_limit(self, text: str, max_tokens: int = 8000) -> str:
        """Truncate text to fit within token limit"""
        estimated_tokens = await self.count_tokens(text)
        if estimated_tokens <= max_tokens:
            return text

        # Truncate with buffer
        ratio = (max_tokens * 0.9) / estimated_tokens
        return text[:int(len(text) * ratio)]


# Global service instance
kimi_service = KimiService()
