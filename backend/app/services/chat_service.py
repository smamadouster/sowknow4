"""
Chat service for RAG-powered conversations

LLM Routing Strategy:
- Confidential Docs: Ollama (privacy — never leaves the server)
- All public (RAG + general): MiniMax M2.7 (direct API) -> mistral-small-2603 (OpenRouter) -> Ollama
"""

import asyncio
import json
import logging
import os
import time as _time
from collections.abc import AsyncGenerator
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import select
from tenacity import retry, stop_after_attempt, wait_exponential

from app.models.chat import ChatMessage, ChatSession, LLMProvider, MessageRole
from app.models.user import User
from app.services.deferred_query_service import deferred_query_service
from app.services.llm_router import llm_router
from app.services.pii_detection_service import pii_detection_service
from app.services.prometheus_metrics import (
    llm_request_duration,
    llm_request_total,
    llm_retry_total,
)
from app.services.agent_identity import build_service_prompt
from app.services.context_block_service import get_cached_context_block
from app.services.search_service import search_service

# Import all LLM services
try:
    from app.services.kimi_service import kimi_service
except ImportError:
    kimi_service = None
    logging.warning("Kimi service not available")

try:
    from app.services.openrouter_service import openrouter_service
except ImportError:
    openrouter_service = None
    logging.warning("OpenRouter service not available")

try:
    from app.services.minimax_service import minimax_service
except ImportError:
    minimax_service = None
    logging.warning("MiniMax service not available")

logger = logging.getLogger(__name__)


# Configuration
OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")

# Model configurations
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "mistral:7b-instruct")


class OllamaService:
    """Service for interacting with Ollama (local LLM)"""

    def __init__(self):
        self.base_url = OLLAMA_URL
        self.model = OLLAMA_MODEL

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=5))
    async def chat_completion(
        self,
        messages: list[dict[str, str]],
        stream: bool = False,
        temperature: float = 0.7,
        num_predict: int = 4096,
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
            ollama_messages.append(
                {
                    "role": role_map.get(msg.get("role", "user"), "user"),
                    "content": msg.get("content", ""),
                }
            )

        payload = {
            "model": self.model,
            "messages": ollama_messages,
            "stream": stream,
            "options": {"temperature": temperature, "num_predict": num_predict},
        }

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                if stream:
                    async with client.stream("POST", f"{self.base_url}/api/chat", json=payload) as response:
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
                    response = await client.post(f"{self.base_url}/api/chat", json=payload)
                    response.raise_for_status()
                    result = response.json()

                    content = result.get("message", {}).get("content", "")
                    yield content

        except httpx.HTTPError as e:
            logger.error(f"Ollama error: {str(e)}")
            yield "Error: Could not connect to Ollama service"

    async def health_check(self) -> dict[str, Any]:
        """Return Ollama reachability status."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                response.raise_for_status()
                return {"service": "ollama", "status": "healthy"}
        except Exception as e:
            return {"service": "ollama", "status": "unhealthy", "error": str(e)}


class ChatService:
    """Service for managing chat sessions with RAG"""

    def __init__(self):
        self.openrouter_service = openrouter_service  # Fallback LLM
        self.ollama_service = OllamaService()
        self.kimi_service = kimi_service  # For chatbot/telegram/general chat
        self.minimax_service = minimax_service  # Default LLM for RAG (direct API)
        self.max_context_messages = 10

    async def get_conversation_history(self, session_id: UUID, db) -> list[dict[str, str]]:
        """Get conversation history for context"""
        messages = (
            (
                await db.execute(
                    select(ChatMessage)
                    .where(ChatMessage.session_id == session_id)
                    .order_by(ChatMessage.created_at.asc())
                    .limit(self.max_context_messages)
                )
            )
            .scalars()
            .all()
        )

        history = []
        for msg in messages:
            role = "user" if msg.role == MessageRole.USER else "assistant"
            history.append({"role": role, "content": msg.content})

        return history

    async def retrieve_relevant_chunks(
        self, query: str, session_id: UUID, db, current_user: User
    ) -> tuple[list[dict], bool]:
        """
        Retrieve relevant document chunks for RAG.

        Confidential results are stripped to metadata only — the actual chunk
        text never reaches the LLM prompt.  Public results keep full text.

        Returns:
            Tuple of (source_documents, has_confidential)
        """
        # Check for PII in query for privacy protection
        has_pii = pii_detection_service.detect_pii(query)
        if has_pii:
            pii_summary = pii_detection_service.get_pii_summary(query)
            logger.warning(f"PII detected in chat query by user {current_user.email}: {pii_summary['detected_types']}")

        # Get session to check document scope
        session = (await db.execute(select(ChatSession).where(ChatSession.id == session_id))).scalar_one_or_none()

        # Perform search
        search_result = await search_service.hybrid_search(query=query, limit=10, offset=0, db=db, user=current_user)

        # Filter by document scope if specified
        if session and session.document_scope:
            scope_set = {str(doc_id) for doc_id in session.document_scope}
            search_result["results"] = [r for r in search_result["results"] if str(r.document_id) in scope_set]

        top_results = search_result["results"][:5]

        # Check for confidential documents OR PII in query
        has_confidential = any(r.document_bucket == "confidential" for r in top_results) or has_pii

        # Batch-fetch metadata for confidential documents
        confidential_doc_ids = [
            r.document_id for r in top_results if r.document_bucket == "confidential"
        ]
        doc_metadata: dict = {}
        if confidential_doc_ids:
            from app.models.document import Document
            result = await db.execute(
                select(Document).where(Document.id.in_(confidential_doc_ids))
            )
            for doc in result.scalars().all():
                doc_metadata[str(doc.id)] = doc

        # Format as source documents
        sources = []
        for r in top_results:
            if r.document_bucket == "confidential":
                # Metadata-only: strip chunk text, include document metadata
                doc = doc_metadata.get(str(r.document_id))
                tags = [t.tag_name for t in doc.tags] if doc and doc.tags else []
                page_count = doc.page_count if doc else None
                mime_type = doc.mime_type if doc else "unknown"
                created_at = doc.created_at.strftime("%Y-%m-%d") if doc and doc.created_at else "unknown"

                metadata_summary = (
                    f"[Confidential document — content not sent to AI] "
                    f"pages: {page_count or 'N/A'} | type: {mime_type} | "
                    f"uploaded: {created_at}"
                )
                if tags:
                    metadata_summary += f" | tags: {', '.join(tags)}"

                sources.append({
                    "document_id": r.document_id,
                    "document_name": r.document_name,
                    "chunk_id": r.chunk_id,
                    "chunk_text": metadata_summary,
                    "relevance_score": r.final_score,
                    "bucket": "confidential",
                    "page_count": page_count,
                    "mime_type": mime_type,
                    "created_at": created_at,
                    "tags": tags,
                })
            else:
                # Public: full chunk text
                chunk_text = r.chunk_text
                if has_pii:
                    chunk_text, _ = pii_detection_service.redact_pii(chunk_text)

                sources.append({
                    "document_id": r.document_id,
                    "document_name": r.document_name,
                    "chunk_id": r.chunk_id,
                    "chunk_text": chunk_text,
                    "relevance_score": r.final_score,
                    "bucket": "public",
                })

        return sources, has_confidential

    def build_rag_context(
        self,
        query: str,
        sources: list[dict],
        conversation_history: list[dict[str, str]],
    ) -> list[dict[str, str]]:
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
            context_parts.append(f"[Document {i + 1}] {source['document_name']}\n{source['chunk_text']}\n")

        context_text = "\n".join(context_parts)

        # System prompt
        task_prompt = """Answer questions based on the provided context from documents.
If the context doesn't contain enough information, say so clearly.
Cite specific documents when providing information.
Be conversational and helpful.

Context from documents:
{context}

Remember: You're helping users access their own knowledge. Be accurate but also conversational."""

        system_prompt = build_service_prompt(
            service_name="SOWKNOW Chat Service",
            mission="Provide intelligent, context-aware conversational responses using RAG over the SOWKNOW vault",
            constraints=(
                "- You MUST cite source documents when referencing vault content\n"
                "- You MUST route confidential queries to Ollama\n"
                "- You MUST maintain conversation context across turns\n"
                "- You MUST NOT hallucinate information not in the retrieved documents"
            ),
            task_prompt=task_prompt,
        )

        # Build messages
        messages = [{"role": "system", "content": system_prompt.format(context=context_text)}]

        # Add conversation history
        for msg in conversation_history:
            messages.append({"role": msg["role"], "content": msg["content"]})

        # Add current query
        messages.append({"role": "user", "content": query})

        return messages

    async def generate_chat_response(
        self, session_id: UUID, user_message: str, db, current_user: User
    ) -> dict[str, Any]:
        """Generate chat response (non-streaming)"""
        # Retrieve relevant chunks using a SEPARATE db session because
        # hybrid_search uses asyncio.wait with timeouts that can cancel tasks
        # mid-query, corrupting the shared connection.
        from app.database import AsyncSessionLocal

        async with AsyncSessionLocal() as search_db:
            sources, has_confidential = await self.retrieve_relevant_chunks(
                query=user_message, session_id=session_id, db=search_db, current_user=current_user
            )

        # Get conversation history (safe to use the original db session now)
        history = await self.get_conversation_history(session_id, db)

        # Build RAG context
        messages = self.build_rag_context(user_message, sources, history)

        # Prepend working memory context block
        try:
            context_block = await get_cached_context_block(db)
            if context_block and messages and messages[0]["role"] == "system":
                messages[0]["content"] = context_block + "\n\n" + messages[0]["content"]
        except Exception:
            pass  # Context block is optional — don't break chat

        # Select LLM via centralized llm_router (single source of truth for routing).
        # Confidential docs → Ollama only (privacy guarantee).
        # Public docs/general → fallback chain per llm_router.fallback_chains.

        if has_confidential:
            ollama_health = await self.ollama_service.health_check()
            if ollama_health["status"] not in ("healthy", "degraded"):
                logger.error(f"Ollama unavailable for confidential query: {ollama_health.get('error', 'unknown')}")
                # Enqueue via DeferredQueryService so the query is retried when Ollama recovers
                deferred_id = await deferred_query_service.enqueue(
                    user_id=str(current_user.id),
                    query_text=user_message,
                    document_ids=[c.get("document_id") for c in sources if c.get("document_id")],
                )
                logger.info(f"Confidential query queued as deferred_id={deferred_id} via DeferredQueryService")
                return {
                    "content": (
                        "Votre requête implique des documents confidentiels qui nécessitent "
                        "un traitement local sécurisé. Le service IA local est temporairement "
                        "indisponible. Votre requête a été mise en file d'attente (queued) et sera "
                        "traitée automatiquement dès que le service sera disponible. / "
                        "Your query involves confidential documents requiring secure local processing. "
                        "The local AI service is temporarily unavailable. Your query has been queued "
                        "and will be processed automatically when the service recovers."
                    ),
                    "llm_used": LLMProvider.OLLAMA,
                    "sources": [],
                    "has_confidential": True,
                    "error": "ollama_unavailable",
                    "queued": True,
                    "deferred_id": deferred_id,
                }

        # Delegate provider selection to llm_router — no inline routing here
        try:
            routing_decision = await llm_router.select_provider(
                query=user_message,
                context_chunks=sources,
                has_confidential=has_confidential,
            )
            llm_service = routing_decision.service
            llm_provider = LLMProvider(routing_decision.provider_name)
            routing_reason = routing_decision.reason.value
        except RuntimeError as routing_err:
            logger.error(f"llm_router.select_provider failed, falling back to Ollama: {routing_err}")
            llm_service = self.ollama_service
            llm_provider = LLMProvider.OLLAMA
            routing_reason = "emergency_fallback"

        logger.info(f"LLM routing: {llm_provider.value} (reason: {routing_reason})")

        # Generate response (with 60s timeout to prevent hanging on slow LLM)
        response_text = ""
        _provider_name = llm_provider.value
        _model_name = getattr(llm_service, "model", "unknown")
        _start = _time.monotonic()
        try:
            async def _collect_response():
                text = ""
                async for chunk in llm_service.chat_completion(messages, stream=False):
                    if not isinstance(chunk, str) or not chunk:
                        continue
                    if chunk.startswith("__USAGE__"):
                        continue
                    text += chunk
                return text

            response_text = await asyncio.wait_for(_collect_response(), timeout=60.0)
            _elapsed = _time.monotonic() - _start
            llm_request_duration.observe(_elapsed, labels={"provider": _provider_name, "model": _model_name})
            llm_request_total.inc(labels={"provider": _provider_name, "status": "success"})
        except asyncio.TimeoutError:
            _elapsed = _time.monotonic() - _start
            llm_request_duration.observe(_elapsed, labels={"provider": _provider_name, "model": _model_name})
            llm_request_total.inc(labels={"provider": _provider_name, "status": "error"})
            logger.error("LLM call timed out after 60s (provider=%s, model=%s)", _provider_name, _model_name)
            return {
                "content": (
                    "Le service IA est temporairement lent. Veuillez réessayer dans quelques instants. / "
                    "The AI service is temporarily slow. Please try again in a moment."
                ),
                "llm_used": llm_provider,
                "sources": [],
                "has_confidential": has_confidential,
            }
        except Exception:
            _elapsed = _time.monotonic() - _start
            llm_request_duration.observe(_elapsed, labels={"provider": _provider_name, "model": _model_name})
            llm_request_total.inc(labels={"provider": _provider_name, "status": "error"})
            raise

        # Format sources for response
        formatted_sources = []
        for source in sources:
            chunk_text = source.get("chunk_text") or ""
            formatted_sources.append(
                {
                    "document_id": source.get("document_id"),
                    "document_name": source.get("document_name", "Unknown"),
                    "chunk_id": source.get("chunk_id"),
                    "chunk_text": chunk_text[:200],
                    "relevance_score": source.get("relevance_score", 0.0),
                }
            )

        return {
            "content": response_text,
            "llm_used": llm_provider,
            "sources": formatted_sources,
            "has_confidential": has_confidential,
        }

    async def generate_chat_response_stream(
        self, session_id: UUID, user_message: str, db, current_user: User
    ) -> AsyncGenerator[str, None]:
        """Generate streaming chat response"""
        # Retrieve relevant chunks
        sources, has_confidential = await self.retrieve_relevant_chunks(
            query=user_message, session_id=session_id, db=db, current_user=current_user
        )

        # Get conversation history
        history = await self.get_conversation_history(session_id, db)

        # Build RAG context
        messages = self.build_rag_context(user_message, sources, history)

        # Prepend working memory context block
        try:
            context_block = await get_cached_context_block(db)
            if context_block and messages and messages[0]["role"] == "system":
                messages[0]["content"] = context_block + "\n\n" + messages[0]["content"]
        except Exception:
            pass

        # Select LLM based on confidentiality — unified routing for all public interactions
        # 1. Confidential docs -> Ollama (privacy guarantee)
        # 2. All public (RAG + general) -> MiniMax M2.7 (direct) -> mistral-small-2603 (OpenRouter) -> Ollama

        if has_confidential:
            ollama_health = await self.ollama_service.health_check()
            if ollama_health["status"] not in ("healthy", "degraded"):
                logger.error(
                    f"Ollama unavailable for confidential stream query: {ollama_health.get('error', 'unknown')}"
                )
                # Queue via DeferredQueryService for retry when Ollama recovers
                deferred_id = await deferred_query_service.enqueue(
                    user_id=str(current_user.id),
                    query_text=user_message,
                    document_ids=[c.get("document_id") for c in sources if c.get("document_id")],
                )
                logger.info(f"Streaming confidential query queued deferred_id={deferred_id}")
                error_msg = (
                    "Votre requête implique des documents confidentiels qui nécessitent "
                    "un traitement local sécurisé. Le service IA local est temporairement "
                    "indisponible. Votre requête a été mise en file d'attente (queued). / "
                    "Your query involves confidential documents requiring secure local processing. "
                    "The local AI service is temporarily unavailable. Your query has been queued."
                )
                yield f"data: {json.dumps({'type': 'llm_info', 'llm_used': LLMProvider.OLLAMA.value, 'has_confidential': True, 'cache_hit': False, 'queued': True, 'deferred_id': deferred_id})}\n\n"
                yield f"data: {json.dumps({'type': 'message', 'content': error_msg})}\n\n"
                yield f"data: {json.dumps({'type': 'done'})}\n\n"
                return

        # Delegate provider selection to llm_router — no inline routing here
        try:
            routing_decision = await llm_router.select_provider(
                query=user_message,
                context_chunks=sources,
                has_confidential=has_confidential,
            )
            llm_service = routing_decision.service
            llm_provider = LLMProvider(routing_decision.provider_name)
            routing_reason = routing_decision.reason.value
        except RuntimeError as routing_err:
            logger.error(f"llm_router.select_provider failed (stream), falling back to Ollama: {routing_err}")
            llm_service = self.ollama_service
            llm_provider = LLMProvider.OLLAMA
            routing_reason = "emergency_fallback"

        logger.info(f"LLM routing: {llm_provider.value} (reason: {routing_reason})")

        # --- Cache pre-check (OpenRouter path only) ---
        # For the OpenRouter/MiniMax service, check whether an identical
        # non-streaming response has already been cached in Redis.  If so we
        # can serve it immediately and emit cache_hit=True so the frontend
        # can display the ⚡ indicator.
        cache_hit = False
        cached_content: str | None = None
        if hasattr(llm_service, "check_cache") and callable(llm_service.check_cache):
            cached_content = llm_service.check_cache(messages)
            if isinstance(cached_content, str) and cached_content:
                cache_hit = True
                logger.info("Stream cache HIT – serving from Redis cache")
                try:
                    from app.services.cache_monitor import cache_monitor

                    cache_monitor.record_cache_hit(
                        cache_key="stream_pre_check",
                        tokens_saved=len(cached_content) // 4,
                    )
                except Exception:
                    pass

        # Emit llm_info metadata including cache_hit flag.
        # Data payload uses `type` field so the frontend SSE reader can
        # dispatch on parsed.type without relying on the SSE `event:` name.
        yield f"data: {json.dumps({'type': 'llm_info', 'llm_used': llm_provider.value, 'has_confidential': has_confidential, 'cache_hit': cache_hit})}\n\n"

        if cache_hit and cached_content is not None:
            # Serve cached response as a single message chunk
            yield f"data: {json.dumps({'type': 'message', 'content': cached_content})}\n\n"
        else:
            # Stream live response from LLM
            _stream_provider = llm_provider.value
            _stream_model = getattr(llm_service, "model", "unknown")
            _stream_start = _time.monotonic()
            try:
                async for chunk in llm_service.chat_completion(messages, stream=True):
                    yield f"data: {json.dumps({'type': 'message', 'content': chunk})}\n\n"
                _stream_elapsed = _time.monotonic() - _stream_start
                llm_request_duration.observe(_stream_elapsed, labels={"provider": _stream_provider, "model": _stream_model})
                llm_request_total.inc(labels={"provider": _stream_provider, "status": "success"})
            except Exception:
                _stream_elapsed = _time.monotonic() - _stream_start
                llm_request_duration.observe(_stream_elapsed, labels={"provider": _stream_provider, "model": _stream_model})
                llm_request_total.inc(labels={"provider": _stream_provider, "status": "error"})
                raise

        # Send sources
        formatted_sources = []
        for source in sources:
            formatted_sources.append(
                {
                    "document_id": str(source["document_id"]),
                    "document_name": source["document_name"],
                    "chunk_id": str(source["chunk_id"]),
                    "relevance_score": source["relevance_score"],
                }
            )

        yield f"data: {json.dumps({'type': 'sources', 'sources': formatted_sources})}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"


# Global chat service instance
chat_service = ChatService()
