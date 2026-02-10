"""
Gemini Flash service for RAG-powered conversations with Google Gemini API
"""
import os
import logging
import json
import asyncio
from typing import AsyncGenerator, List, Dict, Any, Optional
from datetime import datetime, timedelta
from uuid import UUID, uuid4

import google.generativeai as genai
from google.generativeai.types import (
    GenerateContentResponse,
    ContentType,
    GenerationConfig,
    HarmCategory,
    HarmBlockThreshold
)
from tenacity import retry, stop_after_attempt, wait_exponential

from app.models.chat import ChatSession, ChatMessage, MessageRole, LLMProvider

logger = logging.getLogger(__name__)


# Configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-pro")
GEMINI_MAX_TOKENS = int(os.getenv("GEMINI_MAX_TOKENS", "1000000"))
GEMINI_CACHE_TTL = int(os.getenv("GEMINI_CACHE_TTL", "3600"))
GEMINI_DAILY_BUDGET_CAP = float(os.getenv("GEMINI_DAILY_BUDGET_CAP", "50.00"))


class GeminiUsageMetadata:
    """Track Gemini API usage metadata"""

    def __init__(
        self,
        prompt_tokens: int = 0,
        cached_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        cache_hit: bool = False
    ):
        self.prompt_tokens = prompt_tokens
        self.cached_tokens = cached_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = total_tokens
        self.cache_hit = cache_hit

    def to_dict(self) -> Dict[str, Any]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "cached_tokens": self.cached_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "cache_hit": self.cache_hit
        }

    @classmethod
    def from_gemini_response(cls, response: GenerateContentResponse) -> "GeminiUsageMetadata":
        """Create usage metadata from Gemini response"""
        metadata = response.usage_metadata if hasattr(response, 'usage_metadata') else None

        if metadata:
            return cls(
                prompt_tokens=metadata.prompt_token_count or 0,
                cached_tokens=metadata.cached_content_token_count or 0,
                completion_tokens=metadata.candidates_token_count or 0,
                total_tokens=metadata.total_token_count or 0,
                cache_hit=(metadata.cached_content_token_count or 0) > 0
            )

        # Fallback if no metadata available
        return cls()


class GeminiCacheManager:
    """Manage Gemini cached content for cost optimization"""

    def __init__(self):
        self.cache_entries: Dict[str, Dict[str, Any]] = {}
        self.cache_ttl = GEMINI_CACHE_TTL
        self._lock = asyncio.Lock()

    def _generate_cache_key(self, messages: List[Dict[str, str]]) -> str:
        """Generate a cache key from messages"""
        # Create a deterministic key from the system prompt and conversation context
        cache_parts = []
        for msg in messages:
            if msg.get("role") in ["system", "user"]:
                # Include system prompts and user messages for caching
                cache_parts.append(f"{msg.get('role')}:{msg.get('content')[:100]}")

        cache_string = "|".join(cache_parts)
        return f"gemini_cache_{hash(cache_string)}"

    async def get_or_create_cached_content(
        self,
        model: genai.GenerativeModel,
        system_instruction: str,
        conversation_history: List[Dict[str, str]]
    ) -> Optional[str]:
        """
        Get existing cached content or create new one

        Returns:
            Cache name if cached, None otherwise
        """
        cache_key = self._generate_cache_key(
            [{"role": "system", "content": system_instruction}] + conversation_history
        )

        async with self._lock:
            # Check if cache exists and is valid
            if cache_key in self.cache_entries:
                entry = self.cache_entries[cache_key]
                if datetime.utcnow() < entry["expires_at"]:
                    logger.debug(f"Cache hit for key: {cache_key}")
                    return entry["cache_name"]
                else:
                    # Cache expired, remove it
                    del self.cache_entries[cache_key]

            return None

    async def create_cached_content(
        self,
        model: genai.GenerativeModel,
        system_instruction: str,
        conversation_history: List[Dict[str, str]],
        current_query: str
    ) -> Optional[str]:
        """
        Create new cached content for Gemini

        Returns:
            Cache name if successful, None otherwise
        """
        try:
            # Build content for caching (system instruction + conversation history)
            content_to_cache = []

            # Add system instruction
            if system_instruction:
                content_to_cache.append({
                    "role": "user",
                    "parts": [{"text": system_instruction}]
                })

            # Add conversation history
            for msg in conversation_history[-3:]:  # Cache last 3 exchanges
                role = "user" if msg.get("role") == "user" else "model"
                content_to_cache.append({
                    "role": role,
                    "parts": [{"text": msg.get("content", "")}]
                })

            # Create cached content
            cache_key = self._generate_cache_key(
                [{"role": "system", "content": system_instruction}] + conversation_history
            )

            cache_name = f"sowknow_cache_{cache_key[:20]}"

            # Store cache entry
            self.cache_entries[cache_key] = {
                "cache_name": cache_name,
                "created_at": datetime.utcnow(),
                "expires_at": datetime.utcnow() + timedelta(seconds=self.cache_ttl),
                "content_hash": hash(cache_key)
            }

            logger.info(f"Created cached content: {cache_name}")
            return cache_name

        except Exception as e:
            logger.error(f"Failed to create cached content: {str(e)}")
            return None

    async def cleanup_expired_cache(self):
        """Remove expired cache entries"""
        async with self._lock:
            now = datetime.utcnow()
            expired_keys = [
                key for key, entry in self.cache_entries.items()
                if now >= entry["expires_at"]
            ]

            for key in expired_keys:
                del self.cache_entries[cache_key]

            if expired_keys:
                logger.info(f"Cleaned up {len(expired_keys)} expired cache entries")

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        total_entries = len(self.cache_entries)
        active_entries = sum(
            1 for entry in self.cache_entries.values()
            if datetime.utcnow() < entry["expires_at"]
        )

        return {
            "total_entries": total_entries,
            "active_entries": active_entries,
            "ttl_seconds": self.cache_ttl
        }


class GeminiService:
    """Service for interacting with Gemini Flash API"""

    def __init__(self):
        self.api_key = GEMINI_API_KEY
        self.model_name = GEMINI_MODEL
        self.max_tokens = GEMINI_MAX_TOKENS
        self.cache_manager = GeminiCacheManager()

        # Initialize Gemini client
        if self.api_key:
            genai.configure(api_key=self.api_key)
            self.model = genai.GenerativeModel(
                model_name=self.model_name,
                generation_config=GenerationConfig(
                    max_output_tokens=self.max_tokens,
                    temperature=0.7,
                ),
                safety_settings={
                    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
                    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
                    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
                    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
                }
            )
            logger.info(f"Gemini client initialized with model: {self.model_name}")
        else:
            self.model = None
            logger.warning("GEMINI_API_KEY not configured")

    def _convert_messages_to_gemini_format(
        self,
        messages: List[Dict[str, str]]
    ) -> tuple[List[ContentType], Optional[str]]:
        """
        Convert OpenAI-style messages to Gemini format

        Returns:
            Tuple of (contents list, system instruction)
        """
        system_instruction = None
        contents = []

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "system":
                # Extract system instruction
                system_instruction = content
            elif role == "user":
                contents.append({
                    "role": "user",
                    "parts": [{"text": content}]
                })
            elif role == "assistant":
                contents.append({
                    "role": "model",
                    "parts": [{"text": content}]
                })

        return contents, system_instruction

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        stream: bool = False,
        temperature: float = 0.7,
        max_tokens: int = 8192,
        cache_key: Optional[str] = None
    ) -> AsyncGenerator[str, None]:
        """
        Generate chat completion using Gemini Flash

        Args:
            messages: List of message dicts with role and content
            stream: Whether to stream the response
            temperature: Sampling temperature (0.0 to 1.0)
            max_tokens: Maximum tokens to generate
            cache_key: Optional key for context caching

        Yields:
            Response text chunks if streaming, full content if not
        """
        if not self.api_key or not self.model:
            logger.error("GEMINI_API_KEY not configured")
            yield "Error: Gemini API key not configured"
            return

        try:
            # Convert messages to Gemini format
            contents, system_instruction = self._convert_messages_to_gemini_format(messages)

            # Update model with current temperature and max_tokens
            self.model._generation_config = GenerationConfig(
                temperature=temperature,
                max_output_tokens=min(max_tokens, self.max_tokens)
            )

            # Check for cached content
            cache_name = None
            usage_metadata = GeminiUsageMetadata()

            if cache_key or system_instruction:
                cache_name = await self.cache_manager.get_or_create_cached_content(
                    self.model,
                    system_instruction or "",
                    messages[:-1]  # All but the last message
                )

            # Generate response
            if stream:
                # Streaming mode
                async for chunk in self._stream_response(contents, system_instruction):
                    yield chunk
            else:
                # Non-streaming mode
                response_text, usage_metadata = await self._generate_response(
                    contents,
                    system_instruction
                )

                # Yield the response content
                yield response_text

                # Yield usage metadata as last chunk
                yield f"\n__USAGE__: {json.dumps(usage_metadata.to_dict())}"

        except Exception as e:
            logger.error(f"Gemini API error: {str(e)}", exc_info=True)
            yield f"Error: {str(e)}"

    async def _generate_response(
        self,
        contents: List[ContentType],
        system_instruction: Optional[str]
    ) -> tuple[str, GeminiUsageMetadata]:
        """
        Generate non-streaming response

        Returns:
            Tuple of (response_text, usage_metadata)
        """
        try:
            # Run in thread pool since genai is synchronous
            loop = asyncio.get_event_loop()

            if system_instruction:
                # With system instruction
                response = await loop.run_in_executor(
                    None,
                    lambda: self.model.generate_content(
                        contents,
                        generation_config=self.model._generation_config
                    )
                )
            else:
                # Without system instruction
                response = await loop.run_in_executor(
                    None,
                    lambda: self.model.generate_content(contents)
                )

            # Extract response text
            response_text = ""
            if hasattr(response, 'candidates') and response.candidates:
                for candidate in response.candidates:
                    if hasattr(candidate, 'content') and hasattr(candidate.content, 'parts'):
                        for part in candidate.content.parts:
                            if hasattr(part, 'text'):
                                response_text += part.text

            # Extract usage metadata
            usage_metadata = GeminiUsageMetadata.from_gemini_response(response)

            return response_text, usage_metadata

        except Exception as e:
            logger.error(f"Error generating response: {str(e)}")
            raise

    async def _stream_response(
        self,
        contents: List[ContentType],
        system_instruction: Optional[str]
    ) -> AsyncGenerator[str, None]:
        """Generate streaming response"""
        try:
            loop = asyncio.get_event_loop()

            if system_instruction:
                response = await loop.run_in_executor(
                    None,
                    lambda: self.model.generate_content(
                        contents,
                        generation_config=self.model._generation_config,
                        stream=True
                    )
                )
            else:
                response = await loop.run_in_executor(
                    None,
                    lambda: self.model.generate_content(contents, stream=True)
                )

            # Stream chunks
            for chunk in response:
                if hasattr(chunk, 'candidates'):
                    for candidate in chunk.candidates:
                        if hasattr(candidate, 'content') and hasattr(candidate.content, 'parts'):
                            for part in candidate.content.parts:
                                if hasattr(part, 'text'):
                                    yield part.text

        except Exception as e:
            logger.error(f"Error in stream response: {str(e)}")
            raise

    async def health_check(self) -> Dict[str, Any]:
        """
        Check Gemini service health

        Returns:
            Health status dictionary
        """
        health_status = {
            "service": "gemini",
            "status": "healthy",
            "model": self.model_name,
            "api_configured": bool(self.api_key),
            "cache_stats": self.cache_manager.get_cache_stats(),
            "timestamp": datetime.utcnow().isoformat()
        }

        if not self.api_key:
            health_status["status"] = "unhealthy"
            health_status["error"] = "API key not configured"
            return health_status

        # Test API connectivity with a simple request
        try:
            loop = asyncio.get_event_loop()
            test_response = await loop.run_in_executor(
                None,
                lambda: self.model.generate_content(
                    [{"role": "user", "parts": [{"text": "test"}]}],
                    generation_config=GenerationConfig(max_output_tokens=5)
                )
            )

            if test_response and hasattr(test_response, 'candidates'):
                health_status["status"] = "healthy"
                health_status["api_reachable"] = True
            else:
                health_status["status"] = "degraded"
                health_status["error"] = "API returned unexpected response"

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
            "service": "gemini",
            "model": self.model_name,
            "cache_stats": self.cache_manager.get_cache_stats(),
            "config": {
                "max_tokens": self.max_tokens,
                "cache_ttl": GEMINI_CACHE_TTL,
                "daily_budget_cap": GEMINI_DAILY_BUDGET_CAP
            },
            "timestamp": datetime.utcnow().isoformat()
        }

    async def cleanup_cache(self):
        """Clean up expired cache entries"""
        await self.cache_manager.cleanup_expired_cache()


# Global Gemini service instance
gemini_service = GeminiService()
