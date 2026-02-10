"""
Collection Chat Service for follow-up Q&A with context caching

Manages chat sessions scoped to specific collections with Gemini Flash
context caching for cost optimization on recurring queries.
"""
import logging
import uuid
from typing import List, Dict, Any, Optional, AsyncGenerator
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.models.collection import Collection, CollectionChatSession
from app.models.chat import ChatSession, ChatMessage, MessageRole, LLMProvider
from app.models.user import User
from app.models.document import Document
from app.services.gemini_service import gemini_service
from app.services.ollama_service import ollama_service

logger = logging.getLogger(__name__)


class CollectionChatService:
    """Service for collection-scoped chat with context caching"""

    def __init__(self):
        self.gemini_service = gemini_service
        self.ollama_service = ollama_service

    async def get_or_create_chat_session(
        self,
        collection_id: uuid.UUID,
        user: User,
        db: Session,
        session_name: Optional[str] = None
    ) -> tuple[ChatSession, bool]:
        """
        Get existing chat session for collection or create new one

        Args:
            collection_id: Collection to chat about
            user: Current user
            db: Database session
            session_name: Optional name for the session

        Returns:
            Tuple of (ChatSession, created)
        """
        # Get collection
        collection = db.query(Collection).filter(
            Collection.id == collection_id
        ).first()

        if not collection:
            raise ValueError(f"Collection {collection_id} not found")

        # Check for existing session
        if collection.chat_session_id:
            session = db.query(ChatSession).filter(
                ChatSession.id == collection.chat_session_id
            ).first()
            if session:
                return session, False

        # Create new session
        session = ChatSession(
            user_id=user.id,
            title=session_name or f"Chat about {collection.name}",
            model_preference=LLMProvider.GEMINI,
            document_scope=[]  # Will be populated with collection documents
        )

        db.add(session)
        db.flush()

        # Link to collection
        collection.chat_session_id = session.id

        # Also create collection chat session record for stats
        collection_chat = CollectionChatSession(
            collection_id=collection_id,
            user_id=user.id,
            session_name=session_name,
            llm_used="gemini"
        )
        db.add(collection_chat)

        db.commit()
        db.refresh(session)

        logger.info(f"Created chat session {session.id} for collection {collection_id}")
        return session, True

    async def chat_with_collection(
        self,
        collection_id: uuid.UUID,
        message: str,
        user: User,
        db: Session,
        session_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Send message to collection-scoped chat

        Args:
            collection_id: Collection to chat about
            message: User message
            user: Current user
            db: Database session
            session_name: Optional name for new session

        Returns:
            Response with answer, sources, and metadata
        """
        # Get or create chat session
        session, created = await self.get_or_create_chat_session(
            collection_id=collection_id,
            user=user,
            db=db,
            session_name=session_name
        )

        # Get collection documents for context
        collection = db.query(Collection).filter(
            Collection.id == collection_id
        ).first()

        if not collection:
            raise ValueError(f"Collection {collection_id} not found")

        # Get collection items (documents with relevance)
        from app.models.collection import CollectionItem
        collection_items = db.query(CollectionItem).filter(
            CollectionItem.collection_id == collection_id
        ).order_by(CollectionItem.relevance_score.desc()).limit(20).all()

        # Gather document context
        document_context = await self._build_document_context(
            collection_items, db
        )

        # Check for confidential documents
        has_confidential = any(
            item.document.bucket.value == "confidential"
            for item in collection_items
            if item.document
        )

        # Store user message
        user_msg = ChatMessage(
            session_id=session.id,
            role=MessageRole.USER,
            content=message,
            llm_used=LLMProvider.OLLAMA if has_confidential else LLMProvider.GEMINI
        )
        db.add(user_msg)
        db.flush()

        # Generate response
        if has_confidential:
            response_data = await self._chat_with_ollama(
                message=message,
                collection=collection,
                document_context=document_context,
                session=session,
                db=db
            )
        else:
            response_data = await self._chat_with_gemini(
                message=message,
                collection=collection,
                document_context=document_context,
                session=session,
                db=db
            )

        # Store assistant message
        assistant_msg = ChatMessage(
            session_id=session.id,
            role=MessageRole.ASSISTANT,
            content=response_data["response"],
            llm_used=response_data["llm_used"],
            sources=response_data.get("sources"),
            prompt_tokens=response_data.get("prompt_tokens"),
            completion_tokens=response_data.get("completion_tokens"),
            total_tokens=response_data.get("total_tokens")
        )
        db.add(assistant_msg)

        # Update session
        session.title = session.title  # Triggers updated_at

        # Update collection chat stats
        collection_chat = db.query(CollectionChatSession).filter(
            CollectionChatSession.collection_id == collection_id
        ).first()
        if collection_chat:
            collection_chat.message_count += 1
            collection_chat.llm_used = response_data["llm_used"]
            collection_chat.total_tokens_used += response_data.get("total_tokens", 0)

        db.commit()

        return {
            "session_id": str(session.id),
            "collection_id": str(collection_id),
            "response": response_data["response"],
            "sources": response_data.get("sources", []),
            "llm_used": response_data["llm_used"],
            "cache_hit": response_data.get("cache_hit", False)
        }

    async def _build_document_context(
        self,
        collection_items: List[Any],
        db: Session
    ) -> List[Dict[str, Any]]:
        """Build document context from collection items"""
        context = []

        for item in collection_items[:10]:  # Top 10 documents
            if not item.document:
                continue

            # Get document chunks for better context
            from app.models.document import DocumentChunk
            chunks = db.query(DocumentChunk).filter(
                DocumentChunk.document_id == item.document_id
            ).limit(3).all()  # Top 3 chunks per document

            doc_info = {
                "id": str(item.document.id),
                "filename": item.document.filename,
                "bucket": item.document.bucket.value,
                "created_at": item.document.created_at.isoformat(),
                "relevance": item.relevance_score,
                "chunks": [
                    {
                        "text": chunk.chunk_text[:500],
                        "page": chunk.page_number
                    }
                    for chunk in chunks
                ]
            }
            context.append(doc_info)

        return context

    async def _chat_with_gemini(
        self,
        message: str,
        collection: Collection,
        document_context: List[Dict[str, Any]],
        session: ChatSession,
        db: Session
    ) -> Dict[str, Any]:
        """Chat with Gemini Flash with context caching"""

        # Build system prompt with collection context
        system_prompt = f"""You are SOWKNOW, a helpful assistant for a document collection called "{collection.name}".

Collection Summary: {collection.ai_summary or "No summary available"}
Query: {collection.query}

You have access to {len(document_context)} documents in this collection. Use this context to answer questions.

When answering:
1. Reference specific documents by filename when relevant
2. Quote relevant passages from the documents
3. If the information isn't in the documents, say so
4. Be concise but thorough"""

        # Build document context text
        context_text = "\n\n".join([
            f"Document: {doc['filename']}\n{chr(10).join([f"Page {c['page']}: {c['text'][:200]}..." for c in doc['chunks']])}"
            for doc in document_context
        ])

        # Get conversation history
        history = db.query(ChatMessage).filter(
            ChatMessage.session_id == session.id
        ).order_by(ChatMessage.created_at).limit(10).all()

        messages = [
            {"role": "system", "content": system_prompt},
        ]

        # Add history
        for msg in history[-6:]:  # Last 6 messages for context
            role = "user" if msg.role == MessageRole.USER else "assistant"
            messages.append({"role": role, "content": msg.content})

        # Add current message with document context
        messages.append({
            "role": "user",
            "content": f"Documents context:\n{context_text}\n\nUser question: {message}"
        })

        # Generate response with caching
        response_parts = []
        cache_hit = False
        usage_metadata = {}

        async for chunk in self.gemini_service.chat_completion(
            messages=messages,
            stream=False,
            temperature=0.7,
            max_tokens=2048,
            cache_key=f"collection_{collection.id}"  # Cache per collection
        ):
            if chunk and not chunk.startswith("Error:"):
                if chunk.startswith("__USAGE__"):
                    import json
                    try:
                        usage_json = chunk.replace("__USAGE__: ", "")
                        usage_metadata = json.loads(usage_json)
                        cache_hit = usage_metadata.get("cache_hit", False)
                    except:
                        pass
                else:
                    response_parts.append(chunk)

        response_text = "".join(response_parts).strip()

        # Extract sources from document context
        sources = [
            {
                "document_id": doc["id"],
                "filename": doc["filename"],
                "relevance": doc["relevance"]
            }
            for doc in document_context[:5]
        ]

        return {
            "response": response_text,
            "sources": sources,
            "llm_used": "gemini",
            "cache_hit": cache_hit,
            "prompt_tokens": usage_metadata.get("prompt_tokens"),
            "completion_tokens": usage_metadata.get("completion_tokens"),
            "total_tokens": usage_metadata.get("total_tokens")
        }

    async def _chat_with_ollama(
        self,
        message: str,
        collection: Collection,
        document_context: List[Dict[str, Any]],
        session: ChatSession,
        db: Session
    ) -> Dict[str, Any]:
        """Chat with Ollama for confidential collections"""

        # Build prompt
        context_text = "\n\n".join([
            f"- {doc['filename']}"
            for doc in document_context
        ])

        prompt = f"""Collection: {collection.name}
Summary: {collection.ai_summary or 'No summary'}

Available documents:
{context_text}

User question: {message}

Answer based on the available documents. If you don't have enough information, say so."""

        try:
            # Get response from Ollama
            response_text = await self.ollama_service.generate(
                prompt=prompt,
                system="You are SOWKNOW, a helpful document assistant.",
                temperature=0.7
            )

            sources = [
                {
                    "document_id": doc["id"],
                    "filename": doc["filename"]
                }
                for doc in document_context[:5]
            ]

            return {
                "response": response_text,
                "sources": sources,
                "llm_used": "ollama",
                "cache_hit": False
            }

        except Exception as e:
            logger.error(f"Ollama error: {e}")
            return {
                "response": "I'm sorry, I couldn't process your question. The local LLM may be unavailable.",
                "sources": [],
                "llm_used": "ollama",
                "cache_hit": False
            }


# Global collection chat service instance
collection_chat_service = CollectionChatService()
