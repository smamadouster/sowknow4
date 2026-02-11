"""
Collection service for Smart Collections feature

Manages creation, retrieval, and updates of Smart Collections, including
intent parsing, document gathering, and AI summary generation.
"""
import logging
import uuid
from typing import List, Optional, Dict, Any
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc

from app.models.collection import (
    Collection,
    CollectionItem,
    CollectionChatSession,
    CollectionVisibility,
    CollectionType
)
from app.models.document import Document, DocumentBucket, DocumentStatus
from app.models.user import User, UserRole
from app.models.chat import ChatSession, LLMProvider
from app.schemas.collection import (
    CollectionCreate,
    CollectionUpdate
)
from app.services.intent_parser import intent_parser_service, ParsedIntent as ParsedIntentModel
from app.services.search_service import search_service
from app.services.gemini_service import gemini_service
from app.services.ollama_service import ollama_service

logger = logging.getLogger(__name__)


class CollectionService:
    """Service for managing Smart Collections"""

    def __init__(self):
        self.intent_parser = intent_parser_service
        self.search_service = search_service
        self.gemini_service = gemini_service
        self.ollama_service = ollama_service

    def _get_user_visibility_filter(self, user: User) -> List[CollectionVisibility]:
        """Get allowed collection visibility levels for user"""
        if user.role == UserRole.ADMIN or user.role == UserRole.SUPERUSER:
            return [
                CollectionVisibility.PRIVATE,
                CollectionVisibility.SHARED,
                CollectionVisibility.PUBLIC
            ]
        else:
            return [CollectionVisibility.PUBLIC]

    async def create_collection(
        self,
        collection_data: CollectionCreate,
        user: User,
        db: Session
    ) -> Collection:
        """
        Create a new Smart Collection from natural language query

        Args:
            collection_data: Collection creation data with query
            user: Current user
            db: Database session

        Returns:
            Created Collection object
        """
        # Parse intent from natural language query
        parsed_intent = await self.intent_parser.parse_intent(
            query=collection_data.query,
            user_language="en"  # TODO: Get from user profile
        )

        # Gather documents based on parsed intent
        documents = await self._gather_documents_for_intent(
            intent=parsed_intent,
            user=user,
            db=db
        )

        # Generate AI summary if documents found
        ai_summary = None
        ai_keywords = parsed_intent.keywords
        ai_entities = parsed_intent.entities

        if documents:
            ai_summary = await self._generate_collection_summary(
                collection_name=parsed_intent.collection_name or collection_data.name,
                query=collection_data.query,
                documents=documents[:10],  # Summarize top 10
                parsed_intent=parsed_intent
            )

        # Create collection
        collection = Collection(
            user_id=user.id,
            name=collection_data.name,
            description=collection_data.description,
            collection_type=collection_data.collection_type,
            visibility=collection_data.visibility,
            query=collection_data.query,
            parsed_intent=parsed_intent.to_dict(),
            ai_summary=ai_summary,
            ai_keywords=ai_keywords,
            ai_entities=ai_entities,
            filter_criteria=parsed_intent.to_search_filter(),
            document_count=len(documents),
            last_refreshed_at=datetime.utcnow().isoformat(),
            is_pinned=False,
            is_favorite=False
        )

        db.add(collection)
        db.flush()  # Get the ID before adding items

        # Add collection items
        for idx, doc in enumerate(documents):
            # Calculate relevance score based on keyword matches
            relevance = self._calculate_relevance(doc, parsed_intent)

            item = CollectionItem(
                collection_id=collection.id,
                document_id=doc.id,
                relevance_score=relevance,
                order_index=idx,
                added_by="ai",
                added_reason=f"Matched query: {collection_data.query}"
            )
            db.add(item)

        db.commit()
        db.refresh(collection)

        logger.info(f"Created collection '{collection.name}' with {len(documents)} documents for user {user.email}")
        return collection

    async def preview_collection(
        self,
        query: str,
        user: User,
        db: Session
    ) -> Dict[str, Any]:
        """
        Preview a collection without saving it

        Args:
            query: Natural language query
            user: Current user
            db: Database session

        Returns:
            Preview data with intent and documents
        """
        # Parse intent
        parsed_intent = await self.intent_parser.parse_intent(query=query)

        # Gather documents
        documents = await self._gather_documents_for_intent(
            intent=parsed_intent,
            user=user,
            db=db
        )

        # Generate quick summary
        ai_summary = None
        if documents:
            ai_summary = await self._generate_collection_summary(
                collection_name=parsed_intent.collection_name or "Preview",
                query=query,
                documents=documents[:5],
                parsed_intent=parsed_intent
            )

        return {
            "intent": parsed_intent,
            "documents": [
                {
                    "id": str(doc.id),
                    "filename": doc.filename,
                    "bucket": doc.bucket.value,
                    "created_at": doc.created_at.isoformat()
                }
                for doc in documents[:20]
            ],
            "estimated_count": len(documents),
            "ai_summary": ai_summary,
            "suggested_name": parsed_intent.collection_name or query[:50]
        }

    async def refresh_collection(
        self,
        collection_id: uuid.UUID,
        user: User,
        db: Session,
        update_summary: bool = True
    ) -> Collection:
        """
        Refresh collection documents based on original query

        Args:
            collection_id: Collection to refresh
            user: Current user
            db: Database session
            update_summary: Whether to regenerate AI summary

        Returns:
            Updated Collection
        """
        collection = db.query(Collection).filter(
            and_(
                Collection.id == collection_id,
                Collection.user_id == user.id
            )
        ).first()

        if not collection:
            raise ValueError(f"Collection {collection_id} not found")

        # Re-parse intent from stored query
        parsed_intent = await self.intent_parser.parse_intent(query=collection.query)

        # Gather documents
        documents = await self._gather_documents_for_intent(
            intent=parsed_intent,
            user=user,
            db=db
        )

        # Remove existing items
        db.query(CollectionItem).filter(
            CollectionItem.collection_id == collection_id
        ).delete()

        # Add new items
        for idx, doc in enumerate(documents):
            relevance = self._calculate_relevance(doc, parsed_intent)

            item = CollectionItem(
                collection_id=collection.id,
                document_id=doc.id,
                relevance_score=relevance,
                order_index=idx,
                added_by="ai",
                added_reason="Refreshed collection"
            )
            db.add(item)

        # Update summary if requested
        if update_summary and documents:
            collection.ai_summary = await self._generate_collection_summary(
                collection_name=collection.name,
                query=collection.query,
                documents=documents[:10],
                parsed_intent=parsed_intent
            )

        # Update metadata
        collection.document_count = len(documents)
        collection.last_refreshed_at = datetime.utcnow().isoformat()
        collection.parsed_intent = parsed_intent.to_dict()
        collection.filter_criteria = parsed_intent.to_search_filter()

        db.commit()
        db.refresh(collection)

        logger.info(f"Refreshed collection '{collection.name}' with {len(documents)} documents")
        return collection

    async def _gather_documents_for_intent(
        self,
        intent: ParsedIntentModel,
        user: User,
        db: Session
    ) -> List[Document]:
        """
        Gather documents based on parsed intent

        Args:
            intent: Parsed intent from natural language
            user: Current user
            db: Database session

        Returns:
            List of matching documents
        """
        # Build base query
        query = db.query(Document).filter(
            Document.status == DocumentStatus.INDEXED
        )

        # Apply bucket filter based on user role
        if user.role not in [UserRole.ADMIN, UserRole.SUPERUSER]:
            query = query.filter(Document.bucket == DocumentBucket.PUBLIC)

        # Apply document type filter
        if intent.document_types and "all" not in intent.document_types:
            # Map document types to MIME types
            mime_type_map = {
                "pdf": ["application/pdf"],
                "image": ["image/jpeg", "image/png", "image/gif", "image/webp"],
                "docx": ["application/vnd.openxmlformats-officedocument.wordprocessingml.document"],
                "txt": ["text/plain"],
                "md": ["text/markdown"],
                "json": ["application/json"],
                "spreadsheet": ["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"],
                "presentation": ["application/vnd.openxmlformats-officedocument.presentationml.presentation"]
            }

            mime_types = []
            for doc_type in intent.document_types:
                if doc_type in mime_type_map:
                    mime_types.extend(mime_type_map[doc_type])

            if mime_types:
                query = query.filter(Document.mime_type.in_(mime_types))

        # Apply date range filter
        if intent.date_range:
            resolved_range = intent._resolve_date_range()
            if resolved_range:
                start_date = datetime.fromisoformat(resolved_range["start"])
                end_date = datetime.fromisoformat(resolved_range["end"])
                query = query.filter(
                    and_(
                        Document.created_at >= start_date,
                        Document.created_at < end_date
                    )
                )

        # Get documents by semantic search if we have keywords
        if intent.keywords:
            # Use hybrid search for better results
            search_query = " ".join(intent.keywords)
            search_result = await self.search_service.hybrid_search(
                query=search_query,
                limit=100,
                offset=0,
                db=db,
                user=user
            )

            # Extract unique document IDs from search results
            doc_ids = list(set(r.document_id for r in search_result["results"]))

            if doc_ids:
                query = query.filter(Document.id.in_(doc_ids))

        # Execute query with limit
        documents = query.limit(100).all()

        return documents

    def _calculate_relevance(
        self,
        document: Document,
        intent: ParsedIntentModel
    ) -> int:
        """Calculate relevance score for document"""
        score = 50  # Base score

        # Boost for keyword matches in filename
        filename_lower = document.filename.lower()
        for keyword in intent.keywords:
            if keyword.lower() in filename_lower:
                score += 10

        # Cap at 100
        return min(score, 100)

    async def _generate_collection_summary(
        self,
        collection_name: str,
        query: str,
        documents: List[Document],
        parsed_intent: ParsedIntentModel
    ) -> str:
        """
        Generate AI summary for collection with privacy-preserving LLM routing

        Args:
            collection_name: Name of the collection
            query: Original query
            documents: List of documents in collection
            parsed_intent: Parsed intent object

        Returns:
            Generated summary text

        SECURITY: Routes to Ollama for confidential documents, Gemini for public only
        """
        # Check for confidential documents - PRIVACY FIRST
        has_confidential = any(
            doc.bucket == DocumentBucket.CONFIDENTIAL
            for doc in documents
        )

        # Build document list for AI (filenames only for privacy)
        doc_list = "\n".join([
            f"- {doc.filename} (created: {doc.created_at.strftime('%Y-%m-%d')})"
            for doc in documents
        ])

        entities_str = ', '.join([e['name'] for e in parsed_intent.entities]) if parsed_intent.entities else 'None'

        try:
            if has_confidential:
                # Use Ollama for confidential collections - keeps data local
                logger.info(f"Collection summary using Ollama (confidential documents detected) for: {collection_name}")

                prompt = f"""Generate a brief summary (2-3 sentences) for a document collection called "{collection_name}".

Query: "{query}"

Documents in collection:
{doc_list}

Entities found: {entities_str}

Generate a concise summary describing what this collection contains and its key themes."""

                response = await self.ollama_service.generate(
                    prompt=prompt,
                    system="You are a helpful assistant that summarizes document collections concisely.",
                    temperature=0.5
                )
                return response.strip()
            else:
                # Use Gemini Flash for public collections - cost optimized with caching
                logger.info(f"Collection summary using Gemini (public documents only) for: {collection_name}")

                prompt = f"""Generate a brief summary (2-3 sentences) for a document collection called "{collection_name}".

Query: "{query}"

Documents in collection:
{doc_list}

Entities found: {entities_str}

Generate a concise summary describing what this collection contains and its key themes."""

                messages = [
                    {"role": "system", "content": "You are a helpful assistant that summarizes document collections concisely."},
                    {"role": "user", "content": prompt}
                ]

                response_parts = []
                async for chunk in self.gemini_service.chat_completion(
                    messages=messages,
                    stream=False,
                    temperature=0.5,
                    max_tokens=500
                ):
                    if chunk and not chunk.startswith("Error:") and not chunk.startswith("__USAGE__"):
                        response_parts.append(chunk)

                return "".join(response_parts).strip()

        except Exception as e:
            logger.error(f"Failed to generate collection summary: {e}")
            return f"Collection of {len(documents)} documents related to: {query}"

    def get_collection_stats(
        self,
        user: User,
        db: Session
    ) -> Dict[str, Any]:
        """Get statistics about user's collections"""
        visibility_filter = self._get_user_visibility_filter(user)

        collections = db.query(Collection).filter(
            or_(
                Collection.user_id == user.id,
                Collection.visibility.in_(visibility_filter)
            )
        ).all()

        total_docs = sum(c.document_count for c in collections)
        avg_docs = total_docs / len(collections) if collections else 0

        # Count by type
        by_type = {}
        for c in collections:
            by_type[c.collection_type.value] = by_type.get(c.collection_type.value, 0) + 1

        # Recent activity (last 5 updated)
        recent = sorted(collections, key=lambda x: x.updated_at, reverse=True)[:5]

        return {
            "total_collections": len(collections),
            "pinned_collections": sum(1 for c in collections if c.is_pinned),
            "favorite_collections": sum(1 for c in collections if c.is_favorite),
            "total_documents_in_collections": total_docs,
            "average_documents_per_collection": round(avg_docs, 1),
            "collections_by_type": by_type,
            "recent_activity": [
                {
                    "id": str(c.id),
                    "name": c.name,
                    "updated_at": c.updated_at.isoformat()
                }
                for c in recent
            ]
        }


# Global collection service instance
collection_service = CollectionService()
