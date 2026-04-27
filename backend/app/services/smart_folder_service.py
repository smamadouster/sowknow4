"""
Smart Folder Service for AI-generated content from documents

PRD Alignment (SOWKNOW v1.2, §3.5):
- Smart Folders generate articles/content FROM documents (never hallucinated)
- Smart Collections gather documents (separate feature at /collections)
- This module detects "gather" queries and routes them to collection-style
  document assembly instead of article generation.

Anti-cheating guarantees:
1. If documents don't contain sufficient info → explicit "insufficient" message
2. LLM is FORBIDDEN from using training data to fill gaps
3. System prompt is tight (~50 tokens) not verbose (~500 tokens)
4. Relevance gate: weak matches are discarded before reaching the LLM
"""

import logging
import re
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
from app.services.minimax_service import minimax_service
from app.services.openrouter_service import openrouter_service
from app.services.search_service import search_service

logger = logging.getLogger(__name__)

# Keywords that indicate the user wants to GATHER documents rather than
# generate an article.  These are stripped from the query before search.
_GATHER_KEYWORDS = {
    # French
    "rassembler", "rassemble", "tous les documents", "tous les docs",
    "documents concernant", "docs concernant", "trouver", "rechercher",
    "liste des", "lister", "donne-moi", "montre-moi", "affiche",
    "documents sur", "docs sur", "documents à propos", "docs à propos",
    "fichiers concernant", "fichiers sur",
    # English
    "gather", "gather all", "find all", "find documents", "find docs",
    "list all", "list documents", "show me", "give me", "display",
    "documents about", "docs about", "documents regarding",
    "files about", "files regarding", "search for", "look for",
    "all documents", "all docs", "documents on", "docs on",
    "retrieve", "fetch", "pull up", "bring up",
}

# Meta-words to remove when extracting the real subject from a gather query
_META_WORDS_RE = re.compile(
    r"\b("
    r"rassembler|rassemble|tous les|tous|les documents|les docs|documents|docs"
    r"|concernant|concernés|concernant|sur|à propos de|à propos|au sujet de"
    r"|trouver|rechercher|liste|lister|donne-moi|montre-moi|affiche"
    r"|fichiers|fichier|gather|gather all|find all|find|show me|give me"
    r"|display|retrieve|fetch|pull up|bring up|list all|list|search for"
    r"|look for|all|about|regarding|concerning|on|related to|pertaining to"
    r")\b",
    re.IGNORECASE,
)

# Minimum score (from hybrid_search) for a document to be considered relevant
_MIN_RELEVANCE_SCORE = 0.25


class SmartFolderService:
    """Service for generating AI content from document collections"""

    FALLBACK_MODEL = "qwen/qwen3-235b-a22b:free"

    def __init__(self):
        self.minimax_service = minimax_service
        self.openrouter_service = openrouter_service
        self.search_service = search_service

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

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
        Generate a Smart Folder.

        Behaviour (PRD §3.5):
        - "gather" intent  → assemble documents, return concise summary
        - "generate" intent→ write article STRICTLY from document excerpts
        - No relevant docs → honest "No relevant documents" (no hallucination)
        """
        intent = self._classify_intent(topic)

        if intent == "gather":
            return await self._handle_gather_intent(
                topic=topic,
                include_confidential=include_confidential
                and (user.role in [UserRole.ADMIN, UserRole.SUPERUSER] or user.can_access_confidential),
                user=user,
                db=db,
            )

        return await self._handle_generate_intent(
            topic=topic,
            style=style,
            length=length,
            include_confidential=include_confidential
            and (user.role in [UserRole.ADMIN, UserRole.SUPERUSER] or user.can_access_confidential),
            user=user,
            db=db,
        )

    # ------------------------------------------------------------------
    # Intent detection
    # ------------------------------------------------------------------

    def _classify_intent(self, topic: str) -> str:
        """Detect whether the user wants to gather docs or generate content."""
        lowered = topic.lower()
        for kw in _GATHER_KEYWORDS:
            if kw in lowered:
                return "gather"
        return "generate"

    def _extract_subject(self, topic: str) -> str:
        """Strip meta-words from a gather query, leaving the real subject."""
        # Remove punctuation, then meta-words
        cleaned = re.sub(r"[\"'«»]", "", topic)
        cleaned = _META_WORDS_RE.sub(" ", cleaned)
        # Collapse multiple spaces
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned or topic  # fallback if stripping removed everything

    # ------------------------------------------------------------------
    # GATHER branch  (collection-style assembly)
    # ------------------------------------------------------------------

    async def _handle_gather_intent(
        self,
        topic: str,
        include_confidential: bool,
        user: User,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """Gather documents matching the subject, create a collection, return summary."""
        subject = self._extract_subject(topic)
        logger.info(f"SmartFolder gather intent: raw='{topic}' subject='{subject}'")

        documents = await self._search_documents_for_topic(
            topic=subject,
            include_confidential=include_confidential,
            user=user,
            db=db,
        )

        if not documents:
            return {
                "collection_id": str(uuid.uuid4()),
                "topic": topic,
                "generated_content": (
                    f"Aucun document pertinent trouvé pour : {subject}\n\n"
                    f"(Recherche lancée à partir de votre demande : \"{topic}\")"
                ),
                "sources_used": [],
                "word_count": 0,
                "llm_used": "none",
            }

        # Build a concise summary of what was found (not a long article)
        doc_list_text = "\n".join(
            f"- {doc.filename} ({doc.created_at.strftime('%Y-%m-%d')})"
            for doc in documents[:10]
        )

        summary_prompt = (
            f"Résume en 2 phrases ce qui relie ces documents au sujet \"{subject}\". "
            f"Sois factuel. N'invente rien.\n\nDocuments trouvés:\n{doc_list_text}"
        )

        summary = await self._generate_constrained_summary(summary_prompt)

        collection = Collection(
            user_id=user.id,
            name=f"Documents : {subject[:50]}",
            description=f"Documents rassemblés pour : {topic}",
            collection_type=CollectionType.FOLDER,
            visibility=CollectionVisibility.PRIVATE,
            query=topic,
            parsed_intent={"intent": "gather", "subject": subject, "raw": topic},
            ai_summary=summary,
            ai_keywords=[subject],
            ai_entities=[],
            filter_criteria={"subject": subject},
            document_count=len(documents),
            last_refreshed_at=datetime.utcnow().isoformat(),
        )

        db.add(collection)
        await db.flush()

        for idx, doc in enumerate(documents):
            item = CollectionItem(
                collection_id=collection.id,
                document_id=doc.id,
                relevance_score=100 - (idx * 5),
                order_index=idx,
                added_by="ai",
                added_reason=f"Gathered for: {topic}",
            )
            db.add(item)

        await db.commit()
        await db.refresh(collection)

        return {
            "collection_id": str(collection.id),
            "topic": topic,
            "generated_content": summary,
            "sources_used": [
                {
                    "id": str(doc.id),
                    "filename": doc.filename,
                    "bucket": doc.bucket.value if doc.bucket else "public",
                    "created_at": doc.created_at.isoformat(),
                }
                for doc in documents[:10]
            ],
            "word_count": len(summary.split()),
            "llm_used": "minimax",
        }

    # ------------------------------------------------------------------
    # GENERATE branch  (article from documents)
    # ------------------------------------------------------------------

    async def _handle_generate_intent(
        self,
        topic: str,
        style: str,
        length: str,
        include_confidential: bool,
        user: User,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """Generate an article STRICTLY from document excerpts."""
        documents = await self._search_documents_for_topic(
            topic=topic,
            include_confidential=include_confidential,
            user=user,
            db=db,
        )

        if not documents:
            return {
                "collection_id": str(uuid.uuid4()),
                "topic": topic,
                "generated_content": f"No relevant documents found for topic: {topic}",
                "sources_used": [],
                "word_count": 0,
                "llm_used": "none",
            }

        document_context = await self._build_document_context(documents, db)
        await db.commit()

        generated = await self._generate_with_minimax(
            topic=topic,
            document_context=document_context,
            style=style,
            length=length,
        )
        llm_used = "minimax"

        if not generated:
            logger.warning("MiniMax generation returned empty, falling back to OpenRouter")
            generated = await self._generate_with_openrouter_fallback(
                topic=topic,
                document_context=document_context,
                style=style,
                length=length,
            )
            llm_used = "openrouter"

        collection = Collection(
            user_id=user.id,
            name=f"Smart Folder: {topic[:50]}",
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
        await db.flush()

        for idx, doc in enumerate(documents):
            item = CollectionItem(
                collection_id=collection.id,
                document_id=doc.id,
                relevance_score=100 - (idx * 5),
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
                    "bucket": doc.bucket.value if doc.bucket else "public",
                    "created_at": doc.created_at.isoformat(),
                }
                for doc in documents[:10]
            ],
            "word_count": len(generated.split()),
            "llm_used": llm_used,
        }

    # ------------------------------------------------------------------
    # Search & context
    # ------------------------------------------------------------------

    async def _search_documents_for_topic(
        self, topic: str, include_confidential: bool, user: User, db: AsyncSession
    ) -> list[Document]:
        """Search for documents relevant to the topic with score filtering."""
        search_result = await self.search_service.hybrid_search(
            query=topic, limit=50, offset=0, db=db, user=user
        )

        # Filter by minimum relevance score to avoid garbage matches
        scored_doc_ids = []
        for r in search_result["results"]:
            score = getattr(r, "final_score", None) or getattr(r, "semantic_score", 0)
            if score and score >= _MIN_RELEVANCE_SCORE:
                scored_doc_ids.append(str(r.document_id))

        # Deduplicate while preserving order
        seen = set()
        doc_ids = []
        for d_id in scored_doc_ids:
            if d_id not in seen:
                seen.add(d_id)
                doc_ids.append(d_id)

        if not doc_ids:
            return []

        stmt = select(Document).where(
            and_(Document.id.in_(doc_ids), Document.status == DocumentStatus.INDEXED)
        )

        if not include_confidential:
            stmt = stmt.where(Document.bucket == DocumentBucket.PUBLIC)

        return (await db.execute(stmt)).scalars().all()[:20]

    async def _build_document_context(self, documents: list[Document], db: AsyncSession) -> list[dict[str, Any]]:
        """Build context from documents for content generation"""
        context = []
        for doc in documents[:10]:
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

    # ------------------------------------------------------------------
    # LLM helpers  (tight prompts, no hallucination)
    # ------------------------------------------------------------------

    async def _generate_constrained_summary(self, prompt: str) -> str:
        """Generate a short, factual summary.  Fallback on error."""
        messages = [
            {
                "role": "system",
                "content": (
                    "Tu es un assistant factuel. Tu résumes ce qui est fourni. "
                    "Tu n'inventes JAMAIS d'informations. Tu ne cites que ce qui est explicite dans les documents."
                ),
            },
            {"role": "user", "content": prompt},
        ]
        try:
            async for chunk in self.minimax_service.chat_completion(
                messages=messages, stream=False, temperature=0.3, max_tokens=300
            ):
                if chunk and not chunk.startswith("Error:"):
                    return chunk.strip()
        except Exception as e:
            logger.warning(f"Constrained summary failed: {e}")
        return "Documents trouvés. Aucun résumé généré."

    async def _generate_with_minimax(
        self,
        topic: str,
        document_context: list[dict[str, Any]],
        style: str,
        length: str,
    ) -> str:
        """Generate content using MiniMax with tight anti-hallucination constraints."""

        context_text = "\n\n".join(
            [
                f"Document: {doc['filename']}\n"
                + "\n".join([f"[Page {c['page']}]: {c['text'][:300]}..." for c in doc["chunks"]])
                for doc in document_context
            ]
        )

        length_guide = {
            "short": "2-3 paragraphs",
            "medium": "4-6 paragraphs",
            "long": "7-10 paragraphs",
        }.get(length, "4-6 paragraphs")

        style_guide = {
            "informative": "Educational, informative tone. Explain concepts clearly.",
            "creative": "Creative and engaging. Use vivid language.",
            "professional": "Formal, professional business tone.",
            "casual": "Friendly, conversational tone.",
        }.get(style, "Informative, clear tone.")

        # TIGHT system prompt — ~60 tokens, no verbose identity block
        system_prompt = (
            "You are a document-based content writer. "
            "You ONLY use the provided Document Context. "
            "If the context is insufficient, you MUST say: "
            "'The available documents do not contain enough information about this topic.' "
            "You MUST NOT use your training data to fill gaps. "
            "You MUST NOT hallucinate facts, quotes, or citations."
        )

        user_prompt = f"""Write a {length_guide} article about: "{topic}"

Style: {style_guide}

Rules:
1. ONLY use information from the Document Context below.
2. Cite specific documents by filename when referencing information.
3. If the documents lack sufficient information, state that explicitly.
4. Do NOT invent facts, quotes, or statistics.

Document Context:
{context_text}

Write the article now:"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        response_parts = []
        async for chunk in self.minimax_service.chat_completion(
            messages=messages, stream=False, temperature=0.5, max_tokens=4096
        ):
            if chunk and not chunk.startswith("Error:"):
                response_parts.append(chunk)

        return "".join(response_parts).strip()

    async def _generate_with_openrouter_fallback(
        self,
        topic: str,
        document_context: list[dict[str, Any]],
        style: str,
        length: str,
    ) -> str:
        """Fallback: generate content using OpenRouter with Qwen free model."""

        context_text = "\n\n".join(
            [
                f"Document: {doc['filename']}\n"
                + "\n".join([f"[Page {c['page']}]: {c['text'][:300]}..." for c in doc["chunks"]])
                for doc in document_context
            ]
        )

        length_guide = {
            "short": "2-3 paragraphs",
            "medium": "4-6 paragraphs",
            "long": "7-10 paragraphs",
        }.get(length, "4-6 paragraphs")

        style_guide = {
            "informative": "Educational, informative tone. Explain concepts clearly.",
            "creative": "Creative and engaging. Use vivid language.",
            "professional": "Formal, professional business tone.",
            "casual": "Friendly, conversational tone.",
        }.get(style, "Informative, clear tone.")

        system_prompt = (
            "You are a document-based content writer. "
            "You ONLY use the provided Document Context. "
            "If the context is insufficient, you MUST say: "
            "'The available documents do not contain enough information about this topic.' "
            "You MUST NOT use your training data to fill gaps. "
            "You MUST NOT hallucinate facts, quotes, or citations."
        )

        user_prompt = f"""Write a {length_guide} article about: "{topic}"

Style: {style_guide}

Rules:
1. ONLY use information from the Document Context below.
2. Cite specific documents by filename when referencing information.
3. If the documents lack sufficient information, state that explicitly.
4. Do NOT invent facts, quotes, or statistics.

Document Context:
{context_text}

Write the article now:"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            import httpx

            payload = {
                "model": self.FALLBACK_MODEL,
                "messages": messages,
                "temperature": 0.5,
                "max_tokens": 4096,
                "stream": False,
            }

            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"{self.openrouter_service.base_url}/chat/completions",
                    json=payload,
                    headers=self.openrouter_service._get_headers(),
                )
                response.raise_for_status()
                data = response.json()

                if "choices" in data and len(data["choices"]) > 0:
                    return data["choices"][0].get("message", {}).get("content", "")

            return ""
        except Exception as e:
            logger.error(f"OpenRouter fallback generation error: {e}")
            return "Unable to generate content. Both MiniMax and OpenRouter failed."


# Global smart folder service instance
smart_folder_service = SmartFolderService()
