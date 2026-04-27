"""
Collection Chat Service for follow-up Q&A

Manages chat sessions scoped to specific collections with Mistral Small 2603
(via OpenRouter) for public and confidential documents.
"""

import json
import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditAction, AuditLog
from app.models.chat import ChatMessage, ChatSession, LLMProvider, MessageRole
from app.models.collection import Collection, CollectionChatSession
from app.models.user import User
from app.services.agent_identity import build_service_prompt
from app.services.context_block_service import get_cached_context_block
from app.services.openrouter_service import openrouter_service

logger = logging.getLogger(__name__)


async def create_audit_log(
    db: AsyncSession,
    user_id: uuid.UUID,
    action: AuditAction,
    resource_type: str,
    resource_id: str | None = None,
    details: dict | None = None,
) -> None:
    """Helper function to create audit log entries for confidential access"""
    try:
        audit_entry = AuditLog(
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=json.dumps(details) if details else None,
        )
        db.add(audit_entry)
        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.error(f"Audit logging failed: {str(e)}")


class CollectionChatService:
    """Service for collection-scoped chat with context caching"""

    def __init__(self):
        self.openrouter_service = openrouter_service

    async def get_or_create_chat_session(
        self,
        collection_id: uuid.UUID,
        user: User,
        db: AsyncSession,
        session_name: str | None = None,
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
        collection = (await db.execute(select(Collection).where(Collection.id == collection_id))).scalar_one_or_none()

        if not collection:
            raise ValueError(f"Collection {collection_id} not found")

        # Check for existing session
        if collection.chat_session_id:
            session = (
                await db.execute(select(ChatSession).where(ChatSession.id == collection.chat_session_id))
            ).scalar_one_or_none()
            if session:
                return session, False

        # Create new session
        session = ChatSession(
            user_id=user.id,
            title=session_name or f"Chat about {collection.name}",
            model_preference=LLMProvider.OPENROUTER,
            document_scope=[],  # Will be populated with collection documents
        )

        db.add(session)
        await db.flush()

        # Link to collection
        collection.chat_session_id = session.id

        # Also create collection chat session record for stats
        collection_chat = CollectionChatSession(
            collection_id=collection_id,
            user_id=user.id,
            session_name=session_name,
            llm_used="openrouter",
        )
        db.add(collection_chat)

        await db.commit()
        await db.refresh(session)

        logger.info(f"Created chat session {session.id} for collection {collection_id}")
        return session, True

    async def chat_with_collection(
        self,
        collection_id: uuid.UUID,
        message: str,
        user: User,
        db: AsyncSession,
        session_name: str | None = None,
    ) -> dict[str, Any]:
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
            collection_id=collection_id, user=user, db=db, session_name=session_name
        )

        # Get collection documents for context
        collection = (await db.execute(select(Collection).where(Collection.id == collection_id))).scalar_one_or_none()

        if not collection:
            raise ValueError(f"Collection {collection_id} not found")

        # Get collection items (documents with relevance)
        from app.models.collection import CollectionItem

        collection_items = (
            (
                await db.execute(
                    select(CollectionItem)
                    .where(CollectionItem.collection_id == collection_id)
                    .order_by(CollectionItem.relevance_score.desc())
                    .limit(20)
                )
            )
            .scalars()
            .all()
        )

        # Gather document context
        document_context = await self._build_document_context(collection_items, db)

        # Check for confidential documents
        has_confidential = any(
            item.document.bucket.value == "confidential" for item in collection_items if item.document
        )

        # AUDIT LOG: Log confidential document access in collection chat
        if has_confidential:
            confidential_docs = [
                {"id": str(item.document.id), "filename": item.document.filename}
                for item in collection_items
                if item.document and item.document.bucket.value == "confidential"
            ]
            await create_audit_log(
                db=db,
                user_id=user.id,
                action=AuditAction.CONFIDENTIAL_ACCESSED,
                resource_type="collection_chat",
                resource_id=str(collection_id),
                details={
                    "collection_name": collection.name,
                    "confidential_document_count": len(confidential_docs),
                    "confidential_documents": confidential_docs,
                    "action": "chat_with_collection",
                },
            )
            logger.info(
                f"CONFIDENTIAL_ACCESSED: User {user.email} accessed confidential documents in collection chat {collection_id}"
            )

        # Store user message
        user_msg = ChatMessage(
            session_id=session.id,
            role=MessageRole.USER,
            content=message,
            llm_used=LLMProvider.OPENROUTER,
        )
        db.add(user_msg)
        await db.flush()

        # Commit before the long-running LLM call to avoid holding a DB
        # connection idle-in-transaction while waiting for OpenRouter.
        await db.commit()

        # Generate response
        response_data = await self._chat_with_openrouter(
            message=message,
            collection=collection,
            document_context=document_context,
            session=session,
            db=db,
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
            total_tokens=response_data.get("total_tokens"),
        )
        db.add(assistant_msg)

        # Update session
        session.title = session.title  # Triggers updated_at

        # Update collection chat stats
        result = await db.execute(
            select(CollectionChatSession).where(CollectionChatSession.collection_id == collection_id)
        )
        collection_chat = result.scalar_one_or_none()
        if collection_chat:
            collection_chat.message_count += 1
            collection_chat.llm_used = response_data["llm_used"]
            collection_chat.total_tokens_used += response_data.get("total_tokens", 0)

        await db.commit()

        return {
            "session_id": str(session.id),
            "collection_id": str(collection_id),
            "response": response_data["response"],
            "sources": response_data.get("sources", []),
            "llm_used": response_data["llm_used"],
            "cache_hit": response_data.get("cache_hit", False),
        }

    async def _build_document_context(self, collection_items: list[Any], db: AsyncSession) -> list[dict[str, Any]]:
        """Build document context from collection items"""
        context = []

        for item in collection_items[:10]:  # Top 10 documents
            if not item.document:
                continue

            # Get document chunks for better context
            from app.models.document import DocumentChunk

            chunks = (
                (await db.execute(select(DocumentChunk).where(DocumentChunk.document_id == item.document_id).limit(3)))
                .scalars()
                .all()
            )  # Top 3 chunks per document

            doc_info = {
                "id": str(item.document.id),
                "filename": item.document.filename,
                "created_at": item.document.created_at.isoformat(),
                "relevance": item.relevance_score,
                "chunks": [{"text": chunk.chunk_text[:500], "page": chunk.page_number} for chunk in chunks],
            }
            context.append(doc_info)

        return context

    async def _chat_with_openrouter(
        self,
        message: str,
        collection: Collection,
        document_context: list[dict[str, Any]],
        session: ChatSession,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """Chat with OpenRouter (mistral-small-2603) for public collections"""

        # Build system prompt with collection context
        collection_task = f"""You are answering questions about a document collection called "{collection.name}".

Collection Summary: {collection.ai_summary or "No summary available"}
Query: {collection.query}

You have access to {len(document_context)} documents in this collection. Use this context to answer questions.

When answering:
1. Reference specific documents by filename when relevant
2. Quote relevant passages from the documents
3. If the information isn't in the documents, say so
4. Be concise but thorough"""

        system_prompt = build_service_prompt(
            service_name="SOWKNOW Collection Chat Service",
            mission="Provide collection-scoped conversational AI with context isolated to the selected document collection",
            constraints=(
                "- You MUST restrict answers to documents within the active collection\n"
                "- You MUST cite which collection documents support each claim\n"
                "- You MUST handle confidential collection queries with appropriate privacy safeguards\n"
                "- You MUST NOT reference documents outside the active collection"
            ),
            task_prompt=collection_task,
        )

        # Build document context text
        context_parts = []
        for doc in document_context:
            chunk_text = chr(10).join([f"Page {c['page']}: {c['text'][:200]}..." for c in doc["chunks"]])
            context_parts.append(f"Document: {doc['filename']}\n{chunk_text}")
        context_text = "\n\n".join(context_parts)

        # Get conversation history
        history = (
            (
                await db.execute(
                    select(ChatMessage)
                    .where(ChatMessage.session_id == session.id)
                    .order_by(ChatMessage.created_at)
                    .limit(10)
                )
            )
            .scalars()
            .all()
        )

        messages = [
            {"role": "system", "content": system_prompt},
        ]

        # Add history
        for msg in history[-6:]:  # Last 6 messages for context
            role = "user" if msg.role == MessageRole.USER else "assistant"
            messages.append({"role": role, "content": msg.content})

        # Add current message with document context
        messages.append(
            {
                "role": "user",
                "content": f"Documents context:\n{context_text}\n\nUser question: {message}",
            }
        )

        # Prepend working memory context block
        try:
            context_block = await get_cached_context_block(db)
            if context_block and messages and messages[0]["role"] == "system":
                messages[0]["content"] = context_block + "\n\n" + messages[0]["content"]
        except Exception:
            pass

        # Generate response with OpenRouter (mistral-small-2603) for public collections
        response_parts = []

        async for chunk in self.openrouter_service.chat_completion(
            messages=messages, stream=False, temperature=0.7, max_tokens=2048
        ):
            if chunk and not chunk.startswith("Error:"):
                response_parts.append(chunk)

        response_text = "".join(response_parts).strip()

        # Extract sources from document context
        sources = [
            {
                "document_id": doc["id"],
                "filename": doc["filename"],
                "relevance": doc["relevance"],
            }
            for doc in document_context[:5]
        ]

        return {
            "response": response_text,
            "sources": sources,
            "llm_used": "openrouter",
        }


# Global collection chat service instance
collection_chat_service = CollectionChatService()
