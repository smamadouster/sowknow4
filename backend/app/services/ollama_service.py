"""
Ollama Service for local LLM processing

Handles communication with Ollama for confidential document processing.
This ensures PII and confidential data never leaves the local infrastructure.
"""
import os
import logging
from typing import AsyncGenerator, List, Dict, Any, Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


# Configuration
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "mistral:7b-instruct")


class OllamaService:
    """Service for interacting with Ollama (local LLM)"""

    def __init__(self):
        self.base_url = OLLAMA_BASE_URL
        self.model = OLLAMA_MODEL

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=2, max=5)
    )
    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        stream: bool = False,
        temperature: float = 0.7,
        num_predict: int = 4096
    ) -> AsyncGenerator[str, None]:
        """
        Generate chat completion using Ollama

        Args:
            messages: List of message dicts with role and content
            stream: Whether to stream the response
            temperature: Sampling temperature
            num_predict: Maximum tokens to generate

        Yields:
            Response text chunks if streaming
        """
        # Convert messages format for Ollama
        ollama_messages = []
        for msg in messages:
            role_map = {"user": "user", "assistant": "assistant", "system": "system"}
            ollama_messages.append({
                "role": role_map.get(msg.get("role", "user"), "user"),
                "content": msg.get("content", "")
            })

        payload = {
            "model": self.model,
            "messages": ollama_messages,
            "stream": stream,
            "options": {
                "temperature": temperature,
                "num_predict": num_predict
            }
        }

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                if stream:
                    async with client.stream(
                        "POST",
                        f"{self.base_url}/api/chat",
                        json=payload
                    ) as response:
                        response.raise_for_status()

                        async for line in response.aiter_lines():
                            if line.strip():
                                try:
                                    import json
                                    data = json.loads(line)
                                    if "message" in data:
                                        content = data["message"].get("content", "")
                                        if content:
                                            yield content
                                    elif "done" in data and data["done"]:
                                        break
                                except json.JSONDecodeError:
                                    continue
                else:
                    response = await client.post(
                        f"{self.base_url}/api/chat",
                        json=payload
                    )
                    response.raise_for_status()
                    result = response.json()

                    content = result.get("message", {}).get("content", "")
                    yield content

        except httpx.HTTPError as e:
            logger.error(f"Ollama error: {str(e)}")
            yield f"Error: Could not connect to Ollama service"

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=2, max=5)
    )
    async def generate(
        self,
        prompt: str,
        system: str = "You are a helpful assistant.",
        temperature: float = 0.7,
        num_predict: int = 4096
    ) -> str:
        """
        Generate text using Ollama (non-streaming)

        Args:
            prompt: The prompt to send
            system: System prompt
            temperature: Sampling temperature
            num_predict: Maximum tokens to generate

        Returns:
            Generated text
        """
        payload = {
            "model": self.model,
            "prompt": prompt,
            "system": system,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": num_predict
            }
        }

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"{self.base_url}/api/generate",
                    json=payload
                )
                response.raise_for_status()
                result = response.json()

                return result.get("response", "")

        except httpx.HTTPError as e:
            logger.error(f"Ollama generation error: {str(e)}")
            raise

    async def health_check(self) -> Dict[str, Any]:
        """
        Check Ollama service health

        Returns:
            Health check result dict
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                response.raise_for_status()
                result = response.json()

                return {
                    "service": "ollama",
                    "status": "healthy",
                    "model": self.model,
                    "available_models": [m.get("name") for m in result.get("models", [])]
                }
        except Exception as e:
            return {
                "service": "ollama",
                "status": "unhealthy",
                "error": str(e)
            }


# Global Ollama service instance
ollama_service = OllamaService()
