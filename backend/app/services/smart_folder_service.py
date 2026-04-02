"""
Smart Folder Service for AI-generated content from documents

Uses MiniMax M2.7 directly for all documents to
generate articles, reports, and synthesized content from gathered documents
based on user-provided topics.
"""

import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.collection import (
    Collection,
    CollectionItem,
    CollectionType,
    CollectionVisibility,
)
from app.models.document import Document, DocumentBucket, DocumentStatus
from app.models.user import User, UserRole
from app.services.agent_identity import build_service_prompt
from app.services.minimax_service import minimax_service
from app.services.search_service import search_service

logger = logging.getLogger(__name__)


class SmartFolderService:
    """Service for generating AI content from document collections"""

    def __init__(self):
        self.minimax_service = minimax_service
        self.search_service = search_service

    async def generate_smart_folder(
        self,
        topic: str,
        style: str = "informative",
        length: str = "medium",
        include_confidential: bool = False,
        user: User = None,
        db: AsyncSession = None,
    ) -> dict[str, Any]:
        """
        Generate a Smart Folder with AI-generated content

        Args:
            topic: Topic to generate content about
            style: Writing style (informative, creative, professional, casual)
            length: Content length (short, medium, long)
            include_confidential: Whether to include confidential documents (admin only)
            user: Current user
            db: Database session

        Returns:
            Dictionary with generated content, sources, and metadata
        """
        # Search for relevant documents
        documents = await self._search_documents_for_topic(
            topic=topic,
            include_confidential=include_confidential
            and (user.role in [UserRole.ADMIN, UserRole.SUPERUSER] or user.can_access_confidential),
            user=user,
            db=db,
        )

        if not documents:
            return {
                "collection_id": str(uuid.uuid4()),
                "generated_content": f"No relevant documents found for topic: {topic}",
                "sources_used": [],
                "word_count": 0,
                "llm_used": "none",
            }

        # Gather document context
        document_context = await self._build_document_context(documents, db)

        # Generate content using MiniMax for all documents
        generated = await self._generate_with_minimax(
            topic=topic,
            document_context=document_context,
            style=style,
            length=length,
        )
        llm_used = "minimax"

        # Create collection for the smart folder
        collection_name = f"Smart Folder: {topic[:50]}"

        collection = Collection(
            user_id=user.id,
            name=collection_name,
            description=f"AI-generated content about: {topic}",
            collection_type=CollectionType.FOLDER,
            visibility=CollectionVisibility.PRIVATE,
            query=topic,
            parsed_intent={"topic": topic, "style": style, "length": length},
            ai_summary=generated[:500] + "..." if len(generated) > 500 else generated,
            ai_keywords=[topic],
            ai_entities=[],
            filter_criteria={"topic": topic},
            document_count=len(documents),
            last_refreshed_at=datetime.utcnow().isoformat(),
        )

        db.add(collection)
        db.flush()

        # Add documents to collection
        for idx, doc in enumerate(documents):
            item = CollectionItem(
                collection_id=collection.id,
                document_id=doc.id,
                relevance_score=100 - (idx * 5),  # Decreasing relevance
                order_index=idx,
                added_by="ai",
                added_reason=f"Smart Folder generation for: {topic}",
            )
            db.add(item)

        await db.commit()
        await db.refresh(collection)

        return {
            "collection_id": str(collection.id),
            "topic": topic,
            "generated_content": generated,
            "sources_used": [
                {
                    "id": str(doc.id),
                    "filename": doc.filename,
                    "created_at": doc.created_at.isoformat(),
                }
                for doc in documents[:10]
            ],
            "word_count": len(generated.split()),
            "llm_used": llm_used,
        }

    async def _search_documents_for_topic(
        self, topic: str, include_confidential: bool, user: User, db: AsyncSession
    ) -> list[Document]:
        """Search for documents relevant to the topic"""
        # Use hybrid search
        search_result = await self.search_service.hybrid_search(query=topic, limit=50, offset=0, db=db, user=user)

        # Extract unique document IDs
        doc_ids = list({r.document_id for r in search_result["results"]})

        if not doc_ids:
            return []

        # Fetch documents
        stmt = select(Document).where(and_(Document.id.in_(doc_ids), Document.status == DocumentStatus.INDEXED))

        # Apply confidential filter
        if not include_confidential:
            stmt = stmt.where(Document.bucket == DocumentBucket.PUBLIC)

        return (await db.execute(stmt)).scalars().all()[:20]  # Top 20 documents

    async def _build_document_context(self, documents: list[Document], db: AsyncSession) -> list[dict[str, Any]]:
        """Build context from documents for content generation"""
        context = []

        for doc in documents[:10]:  # Top 10 documents
            from app.models.document import DocumentChunk

            chunks = (
                (
                    await db.execute(
                        select(DocumentChunk)
                        .where(DocumentChunk.document_id == doc.id)
                        .order_by(DocumentChunk.chunk_index)
                        .limit(5)
                    )
                )
                .scalars()
                .all()
            )

            doc_info = {
                "filename": doc.filename,
                "created_at": doc.created_at.isoformat(),
                "chunks": [{"text": chunk.chunk_text, "page": chunk.page_number} for chunk in chunks],
            }
            context.append(doc_info)

        return context

    async def _generate_with_minimax(
        self,
        topic: str,
        document_context: list[dict[str, Any]],
        style: str,
        length: str,
    ) -> str:
        """Generate content using MiniMax"""

        # Build context text
        context_text = "\n\n".join(
            [
                f"Document: {doc['filename']}\n"
                + "\n".join([f"[Page {c['page']}]: {c['text'][:300]}..." for c in doc["chunks"]])
                for doc in document_context
            ]
        )

        # Determine length constraint
        length_guide = {
            "short": "2-3 paragraphs",
            "medium": "4-6 paragraphs",
            "long": "7-10 paragraphs",
        }.get(length, "4-6 paragraphs")

        # Determine style guide
        style_guide = {
            "informative": "Write in an educational, informative tone. Explain concepts clearly.",
            "creative": "Write with creativity and engagement. Use vivid language and storytelling.",
            "professional": "Write in a formal, professional tone suitable for business contexts.",
            "casual": "Write in a friendly, conversational tone.",
        }.get(style, "Write in an informative, clear tone.")

        task_prompt = f"""Create a {length_guide} article about the topic: "{topic}"

{style_guide}

IMPORTANT GUIDELINES:
- Base your content on the provided document context
- Cite specific documents by filename when referencing information
- If the documents don't contain sufficient information, acknowledge limitations
- Organize content with clear headings and structure
- Be thorough but concise

Document Context:
{context_text}

Generate the article now:"""

        system_prompt = build_service_prompt(
            service_name="SOWKNOW Smart Folder Service",
            mission="Automatically categorize documents into smart folders using intent parsing and content analysis",
            constraints=(
                "- You MUST respect document bucket isolation\n"
                "- You MUST classify documents based on content, not just filename\n"
                "- You MUST log categorization decisions for audit\n"
                "- You MUST NOT expose confidential document metadata in public folder structures"
            ),
            task_prompt=task_prompt,
        )

        messages = [
            {
                "role": "system",
                "content": system_prompt,
            },
            {"role": "user", "content": f'Create a {length_guide} article about: "{topic}"'},
        ]

        response_parts = []
        # Use MiniMax for public documents
        async for chunk in self.minimax_service.chat_completion(
            messages=messages, stream=False, temperature=0.7, max_tokens=4096
        ):
            if chunk and not chunk.startswith("Error:"):
                response_parts.append(chunk)

        return "".join(response_parts).strip()


# Global smart folder service instance
smart_folder_service = SmartFolderService()
