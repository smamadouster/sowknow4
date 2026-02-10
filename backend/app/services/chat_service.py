"""
Chat service for RAG-powered conversations with Kimi 2.5, Gemini Flash, and Ollama

LLM Routing Strategy:
- Chatbot/Telegram (general chat without docs): Kimi 2.5
- Smart Features (RAG with public docs): Gemini Flash
- Confidential Docs (RAG with confidential docs): Ollama
"""
import os
import logging
import json
import asyncio
from typing import AsyncGenerator, List, Dict, Any, Optional
from uuid import UUID

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.models.chat import ChatSession, ChatMessage, MessageRole, LLMProvider
from app.models.user import User
from app.models.document import Document, DocumentBucket
from app.services.search_service import search_service
from app.services.pii_detection_service import pii_detection_service

# Import all LLM services
try:
    from app.services.kimi_service import kimi_service
except ImportError:
    kimi_service = None
    logger.warning("Kimi service not available")

logger = logging.getLogger(__name__)


# Configuration
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")

# Model configurations
GEMINI_MODEL = "gemini-pro"
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "mistral:7b-instruct")


class GeminiService:
    """Service for interacting with Gemini Flash (Google AI API)"""

    def __init__(self):
        self.api_key = GEMINI_API_KEY
        self.base_url = GEMINI_API_URL
        self.model = GEMINI_MODEL

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
        Generate chat completion using Gemini Flash

        Args:
            messages: List of message dicts with role and content
            stream: Whether to stream the response
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            cache_key: Optional cache key for prompt caching

        Yields:
            Response text chunks if streaming
        """
        if not self.api_key:
            logger.error("GEMINI_API_KEY not configured")
            yield "Error: Gemini API key not configured"
            return

        # Convert messages to Gemini format
        gemini_messages = []
        system_prompt = None

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "system":
                system_prompt = content
            else:
                gemini_role = "user" if role == "user" else "model"
                gemini_messages.append({
                    "role": gemini_role,
                    "parts": [{"text": content}]
                })

        # Build request payload
        payload = {
            "contents": gemini_messages,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            }
        }

        # Add system instruction if present
        if system_prompt:
            payload["systemInstruction"] = {
                "parts": [{"text": system_prompt}]
            }

        # Add caching if cache_key provided
        if cache_key:
            payload["contents"][0]["role"] = "user"
            payload["contents"][0]["parts"] = [{
                "text": f"[CACHE_KEY: {cache_key}]\n" + gemini_messages[0]["parts"][0]["text"]
            }]

        try:
            url = f"{self.base_url}?key={self.api_key}"

            async with httpx.AsyncClient(timeout=60.0) as client:
                if stream:
                    async with client.stream(
                        "POST",
                        url,
                        json=payload
                    ) as response:
                        response.raise_for_status()

                        async for line in response.aiter_lines():
                            if line.strip():
                                try:
                                    data = json.loads(line)
                                    if "candidates" in data:
                                        candidate = data["candidates"][0]
                                        if "content" in candidate:
                                            content = candidate["content"]["parts"][0].get("text", "")
                                            if content:
                                                yield content
                                except json.JSONDecodeError:
                                    continue
                else:
                    response = await client.post(
                        url,
                        json=payload
                    )
                    response.raise_for_status()
                    result = response.json()

                    if "candidates" in result and len(result["candidates"]) > 0:
                        content = result["candidates"][0]["content"]["parts"][0].get("text", "")
                        usage_metadata = result.get("usageMetadata", {})

                        yield content
                        # Return usage as last chunk
                        if usage_metadata:
                            yield f"\n__USAGE__: {json.dumps(usage_metadata)}"
                    else:
                        logger.error(f"Unexpected Gemini response: {result}")
                        yield "Error: Unexpected response from Gemini API"

        except httpx.HTTPError as e:
            logger.error(f"Gemini API error: {str(e)}")
            yield f"Error: {str(e)}"


class OllamaService:
    """Service for interacting with Ollama (local LLM)"""

    def __init__(self):
        self.base_url = OLLAMA_URL
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


class ChatService:
    """Service for managing chat sessions with RAG"""

    def __init__(self):
        self.gemini_service = GeminiService()
        self.ollama_service = OllamaService()
        self.kimi_service = kimi_service  # For chatbot/telegram/general chat
        self.max_context_messages = 10

    async def get_conversation_history(
        self,
        session_id: UUID,
        db
    ) -> List[Dict[str, str]]:
        """Get conversation history for context"""
        messages = db.query(ChatMessage).filter(
            ChatMessage.session_id == session_id
        ).order_by(
            ChatMessage.created_at.asc()
        ).limit(self.max_context_messages).all()

        history = []
        for msg in messages:
            role = "user" if msg.role == MessageRole.USER else "assistant"
            history.append({
                "role": role,
                "content": msg.content
            })

        return history

    async def retrieve_relevant_chunks(
        self,
        query: str,
        session_id: UUID,
        db,
        current_user: User
    ) -> tuple[List[Dict], bool]:
        """
        Retrieve relevant document chunks for RAG

        Returns:
            Tuple of (source_documents, has_confidential)
        """
        # Check for PII in query for privacy protection
        has_pii = pii_detection_service.detect_pii(query)
        if has_pii:
            pii_summary = pii_detection_service.get_pii_summary(query)
            logger.warning(f"PII detected in chat query by user {current_user.email}: {pii_summary['detected_types']}")

        # Get session to check document scope
        session = db.query(ChatSession).filter(
            ChatSession.id == session_id
        ).first()

        # Perform search
        search_result = await search_service.hybrid_search(
            query=query,
            limit=10,
            offset=0,
            db=db,
            user=current_user
        )

        # Filter by document scope if specified
        if session and session.document_scope:
            scope_set = set(str(doc_id) for doc_id in session.document_scope)
            search_result["results"] = [
                r for r in search_result["results"]
                if str(r.document_id) in scope_set
            ]

        # Check for confidential documents OR PII in query
        has_confidential = any(
            r.document_bucket == "confidential" for r in search_result["results"]
        ) or has_pii

        # Format as source documents
        sources = []
        for r in search_result["results"][:5]:  # Top 5 results
            # Redact PII from chunk text if PII detected
            chunk_text = r.chunk_text
            if has_pii:
                chunk_text, _ = pii_detection_service.redact_pii(chunk_text)

            sources.append({
                "document_id": r.document_id,
                "document_name": r.document_name,
                "chunk_id": r.chunk_id,
                "chunk_text": chunk_text,
                "relevance_score": r.final_score
            })

        return sources, has_confidential

    def build_rag_context(
        self,
        query: str,
        sources: List[Dict],
        conversation_history: List[Dict[str, str]]
    ) -> List[Dict[str, str]]:
        """
        Build RAG context with system prompt and retrieved documents

        Args:
            query: User query
            sources: Retrieved source documents
            conversation_history: Previous conversation

        Returns:
            Messages list for LLM
        """
        # Build context from sources
        context_parts = []
        for i, source in enumerate(sources):
            context_parts.append(
                f"[Document {i+1}] {source['document_name']}\n"
                f"{source['chunk_text']}\n"
            )

        context_text = "\n".join(context_parts)

        # System prompt
        system_prompt = """You are SOWKNOW, a helpful AI assistant for a multi-generational legacy knowledge system.

Your role is to help users find information from their personal document vault and provide thoughtful, accurate responses.

Guidelines:
- Answer questions based on the provided context from documents
- If the context doesn't contain enough information, say so clearly
- Cite specific documents when providing information
- Be conversational and helpful
- Respect privacy and confidentiality
- Provide information in the same language as the user's query (French or English)

Context from documents:
{context}

Remember: You're helping users access their own knowledge. Be accurate but also conversational."""

        # Build messages
        messages = [
            {
                "role": "system",
                "content": system_prompt.format(context=context_text)
            }
        ]

        # Add conversation history
        for msg in conversation_history:
            messages.append({
                "role": msg["role"],
                "content": msg["content"]
            })

        # Add current query
        messages.append({
            "role": "user",
            "content": query
        })

        return messages

    async def generate_chat_response(
        self,
        session_id: UUID,
        user_message: str,
        db,
        current_user: User
    ) -> Dict[str, Any]:
        """Generate chat response (non-streaming)"""
        # Retrieve relevant chunks
        sources, has_confidential = await self.retrieve_relevant_chunks(
            query=user_message,
            session_id=session_id,
            db=db,
            current_user=current_user
        )

        # Get conversation history
        history = await self.get_conversation_history(session_id, db)

        # Build RAG context
        messages = self.build_rag_context(user_message, sources, history)

        # Select LLM based on use case and confidentiality
        # Priority:
        # 1. Confidential docs -> Ollama (privacy)
        # 2. RAG with public docs -> Gemini Flash (smart features)
        # 3. General chat (no docs) -> Kimi 2.5 (chatbot/telegram)

        if has_confidential:
            # Confidential: always use Ollama
            llm_service = self.ollama_service
            llm_provider = LLMProvider.OLLAMA
            routing_reason = "confidential_docs"
        elif sources and len(sources) > 0:
            # RAG mode with public docs: use Gemini Flash
            llm_service = self.gemini_service
            llm_provider = LLMProvider.GEMINI
            routing_reason = "rag_public_docs"
        else:
            # General chat mode: use Kimi 2.5 for chatbot/telegram
            if self.kimi_service:
                llm_service = self.kimi_service
                llm_provider = LLMProvider.KIMI
                routing_reason = "general_chat"
            else:
                # Fallback to Gemini if Kimi not available
                llm_service = self.gemini_service
                llm_provider = LLMProvider.GEMINI
                routing_reason = "general_chat_fallback"

        logger.info(f"LLM routing: {llm_provider.value} (reason: {routing_reason})")

        # Generate response
        response_text = ""
        async for chunk in llm_service.chat_completion(messages, stream=False):
            if chunk.startswith("__USAGE__"):
                continue
            response_text += chunk

        # Format sources for response
        formatted_sources = []
        for source in sources:
            formatted_sources.append({
                "document_id": source["document_id"],
                "document_name": source["document_name"],
                "chunk_id": source["chunk_id"],
                "chunk_text": source["chunk_text"][:200],
                "relevance_score": source["relevance_score"]
            })

        return {
            "content": response_text,
            "llm_used": llm_provider,
            "sources": formatted_sources,
            "has_confidential": has_confidential
        }

    async def generate_chat_response_stream(
        self,
        session_id: UUID,
        user_message: str,
        db,
        current_user: User
    ) -> AsyncGenerator[str, None]:
        """Generate streaming chat response"""
        # Retrieve relevant chunks
        sources, has_confidential = await self.retrieve_relevant_chunks(
            query=user_message,
            session_id=session_id,
            db=db,
            current_user=current_user
        )

        # Get conversation history
        history = await self.get_conversation_history(session_id, db)

        # Build RAG context
        messages = self.build_rag_context(user_message, sources, history)

        # Select LLM based on use case and confidentiality
        # Priority:
        # 1. Confidential docs -> Ollama (privacy)
        # 2. RAG with public docs -> Gemini Flash (smart features)
        # 3. General chat (no docs) -> Kimi 2.5 (chatbot/telegram)

        if has_confidential:
            # Confidential: always use Ollama
            llm_service = self.ollama_service
            llm_provider = LLMProvider.OLLAMA
            routing_reason = "confidential_docs"
        elif sources and len(sources) > 0:
            # RAG mode with public docs: use Gemini Flash
            llm_service = self.gemini_service
            llm_provider = LLMProvider.GEMINI
            routing_reason = "rag_public_docs"
        else:
            # General chat mode: use Kimi 2.5 for chatbot/telegram
            if self.kimi_service:
                llm_service = self.kimi_service
                llm_provider = LLMProvider.KIMI
                routing_reason = "general_chat"
            else:
                # Fallback to Gemini if Kimi not available
                llm_service = self.gemini_service
                llm_provider = LLMProvider.GEMINI
                routing_reason = "general_chat_fallback"

        logger.info(f"LLM routing: {llm_provider.value} (reason: {routing_reason})")

        # Send initial event with LLM info
        yield f"event: llm_info\ndata: {json.dumps({'llm_used': llm_provider.value, 'has_confidential': has_confidential})}\n\n"

        # Stream response
        async for chunk in llm_service.chat_completion(messages, stream=True):
            yield f"event: message\ndata: {json.dumps({'content': chunk})}\n\n"

        # Send sources
        formatted_sources = []
        for source in sources:
            formatted_sources.append({
                "document_id": source["document_id"],
                "document_name": source["document_name"],
                "chunk_id": source["chunk_id"],
                "relevance_score": source["relevance_score"]
            })

        yield f"event: sources\ndata: {json.dumps({'sources': formatted_sources})}\n\n"
        yield "event: done\ndata: {}\n\n"


# Global chat service instance
chat_service = ChatService()
