"""
Synthesis Pipeline Service for Knowledge Graph

Uses Map-Reduce pattern with MiniMax (public documents) or Ollama
(confidential documents) to synthesize information from multiple documents,
creating comprehensive insights and summaries.
"""

import logging
from collections import defaultdict
from collections.abc import Callable
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentBucket, DocumentChunk
from app.models.knowledge_graph import Entity, TimelineEvent
from app.services.agent_identity import build_service_prompt
from app.services.context_block_service import get_cached_context_block
from app.services.minimax_service import minimax_service

logger = logging.getLogger(__name__)


class SynthesisRequest:
    """Request parameters for synthesis"""

    def __init__(
        self,
        topic: str,
        document_ids: list[str],
        synthesis_type: str = "comprehensive",
        style: str = "informative",
        language: str = "en",
        max_length: int = 2000,
        include_timeline: bool = True,
        include_entities: bool = True,
        include_sources: bool = True,
    ):
        self.topic = topic
        self.document_ids = document_ids
        self.synthesis_type = synthesis_type  # comprehensive, brief, analytical, timeline
        self.style = style  # informative, professional, creative, casual
        self.language = language
        self.max_length = max_length
        self.include_timeline = include_timeline
        self.include_entities = include_entities
        self.include_sources = include_sources


class SynthesisResult:
    """Result of synthesis operation"""

    def __init__(
        self,
        topic: str,
        synthesis: str,
        key_points: list[str],
        sources: list[dict[str, Any]],
        entities: list[dict[str, Any]],
        timeline: list[dict[str, Any]] | None = None,
        confidence: float = 0.8,
    ):
        self.topic = topic
        self.synthesis = synthesis
        self.key_points = key_points
        self.sources = sources
        self.entities = entities
        self.timeline = timeline
        self.confidence = confidence
        self.generated_at = datetime.now()


class SynthesisPipelineService:
    """Service for map-reduce style synthesis of multiple documents"""

    def __init__(self):
        self.minimax_service = minimax_service
        self._ollama_service = None
        self._openrouter_service = None

    def _get_ollama_service(self):
        if self._ollama_service is None:
            from app.services.ollama_service import ollama_service

            self._ollama_service = ollama_service
        return self._ollama_service

    def _get_openrouter_service(self):
        if self._openrouter_service is None:
            from app.services.openrouter_service import openrouter_service

            self._openrouter_service = openrouter_service
        return self._openrouter_service

    async def synthesize(
        self,
        request: SynthesisRequest,
        db: AsyncSession,
        on_progress: Callable[[str, float], None] | None = None,
    ) -> SynthesisResult:
        """
        Synthesize information from multiple documents using Map-Reduce

        Args:
            request: Synthesis request parameters
            db: Database session
            on_progress: Optional callback for progress updates

        Returns:
            Synthesis result with comprehensive information
        """
        # Fetch working memory context block once for all LLM calls
        _context_block: str | None = None
        try:
            _context_block = await get_cached_context_block(db)
        except Exception:
            pass

        try:
            # Step 1: Fetch and prepare documents (Map phase)
            if on_progress:
                on_progress("Fetching documents...", 0.1)

            documents = await self._fetch_documents(request.document_ids, db)
            if not documents:
                raise ValueError("No valid documents found for synthesis")

            # Step 2: Extract key information from each document (Map)
            if on_progress:
                on_progress("Extracting key information...", 0.3)

            mapped_results = await self._map_documents(
                documents, request.topic, request.synthesis_type, db, on_progress,
                context_block=_context_block,
            )

            # Step 3: Gather related entities if requested
            entities = []
            if request.include_entities:
                if on_progress:
                    on_progress("Gathering entities...", 0.5)
                entities = await self._gather_entities(documents, db)

            # Step 4: Gather timeline if requested
            timeline = []
            if request.include_timeline:
                if on_progress:
                    on_progress("Building timeline...", 0.6)
                timeline = await self._build_timeline(documents, db)

            # Step 5: Reduce - synthesize all information (Reduce phase)
            if on_progress:
                on_progress("Synthesizing information...", 0.7)

            synthesis = await self._reduce_synthesis(
                request.topic,
                mapped_results,
                entities,
                timeline,
                request.style,
                request.language,
                request.max_length,
                documents,
                context_block=_context_block,
            )

            # Step 6: Extract key points
            if on_progress:
                on_progress("Extracting key points...", 0.9)

            key_points = await self._extract_key_points(
                synthesis, request.topic, documents, context_block=_context_block,
            )

            # Step 7: Prepare source citations
            sources = self._prepare_sources(documents, mapped_results)

            if on_progress:
                on_progress("Complete!", 1.0)

            return SynthesisResult(
                topic=request.topic,
                synthesis=synthesis,
                key_points=key_points,
                sources=sources,
                entities=entities,
                timeline=timeline if request.include_timeline else None,
                confidence=self._calculate_confidence(mapped_results, len(documents)),
            )

        except Exception as e:
            logger.error(f"Synthesis pipeline error: {e}")
            raise

    async def _fetch_documents(self, document_ids: list[str], db: AsyncSession) -> list[Document]:
        """Fetch documents from database"""
        documents = []
        for doc_id in document_ids:
            doc = await db.get(Document, doc_id)
            if doc:
                documents.append(doc)
        return documents

    async def _map_documents(
        self,
        documents: list[Document],
        topic: str,
        synthesis_type: str,
        db: AsyncSession,
        on_progress: Callable[[str, float], None] | None = None,
        context_block: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Map phase: Extract key information from each document

        Returns a list of extracted information per document
        """
        results = []

        for i, doc in enumerate(documents):
            try:
                # Get document chunks for content
                chunks = (
                    (await db.execute(select(DocumentChunk).where(DocumentChunk.document_id == doc.id).limit(10)))
                    .scalars()
                    .all()
                )

                content = "\n\n".join([c.chunk_text[:500] for c in chunks])

                # Map this document
                mapped = await self._map_single_document(
                    doc, content, topic, synthesis_type, context_block=context_block,
                )
                results.append(mapped)

                if on_progress:
                    progress = 0.3 + (0.2 * (i + 1) / len(documents))
                    on_progress(f"Processing {doc.filename}...", progress)

            except Exception as e:
                logger.warning(f"Error mapping document {doc.id}: {e}")
                results.append(
                    {
                        "document_id": str(doc.id),
                        "filename": doc.filename,
                        "error": str(e),
                    }
                )

        return results

    async def _map_single_document(
        self, doc: Document, content: str, topic: str, synthesis_type: str,
        context_block: str | None = None,
    ) -> dict[str, Any]:
        """Extract key information from a single document"""
        system_prompt = build_service_prompt(
            service_name="SOWKNOW Synthesis Map Agent",
            mission="Synthesize information from multiple documents using map-reduce analysis to extract key points, timelines, and comprehensive summaries",
            constraints=(
                "- You MUST process each document independently in the map phase\n"
                "- You MUST reconcile conflicting information in the reduce phase\n"
                "- You MUST cite source documents for all synthesized claims\n"
                "- You MUST flag temporal inconsistencies across documents\n"
                "- You MUST NOT include information from confidential documents in cloud-routed synthesis"
            ),
            task_prompt=f"""Extract the most relevant information from this document related to the topic.

Topic: {topic}
Synthesis Type: {synthesis_type}

Extract:
1. Key facts directly relevant to the topic
2. Important dates and events
3. Significant people, organizations, or locations mentioned
4. Data points, statistics, or measurements
5. Quotes or direct statements that are relevant

Keep your extraction focused and concise. Return as structured JSON.""",
        )

        user_prompt = f"""Document: {doc.filename}
Date: {doc.created_at.isoformat() if doc.created_at else "Unknown"}

Content:
{content[:3000]}

Extract all relevant information about "{topic}" from this document:"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        # Prepend working memory context block
        if context_block and messages and messages[0]["role"] == "system":
            messages[0]["content"] = context_block + "\n\n" + messages[0]["content"]

        try:
            # Determine LLM routing based on document bucket
            use_ollama = doc.bucket == DocumentBucket.CONFIDENTIAL
            llm_service = self._get_ollama_service() if use_ollama else self._get_openrouter_service()

            response = []
            async for chunk in llm_service.chat_completion(
                messages=messages, stream=False, temperature=0.3, max_tokens=1024
            ):
                if chunk and not chunk.startswith("Error:") and not chunk.startswith("__USAGE__"):
                    response.append(chunk)

            response_text = "".join(response).strip()

            # Try to parse as JSON
            import json

            try:
                extracted = json.loads(self._extract_json(response_text))
            except (json.JSONDecodeError, ValueError, TypeError):
                # Fallback: treat as plain text
                extracted = {"summary": response_text, "facts": []}

            return {
                "document_id": str(doc.id),
                "filename": doc.filename,
                "bucket": doc.bucket,
                "created_at": doc.created_at.isoformat() if doc.created_at else None,
                "extracted": extracted,
                "content_length": len(content),
            }

        except Exception as e:
            logger.warning(f"Error in map for {doc.filename}: {e}")
            return {
                "document_id": str(doc.id),
                "filename": doc.filename,
                "bucket": doc.bucket,
                "error": str(e),
            }

    async def _gather_entities(self, documents: list[Document], db: AsyncSession) -> list[dict[str, Any]]:
        """Gather entities mentioned in the documents"""
        from app.models.knowledge_graph import EntityMention

        entity_counts = defaultdict(int)
        entity_details = {}

        for doc in documents:
            mentions = (
                (await db.execute(select(EntityMention).where(EntityMention.document_id == doc.id))).scalars().all()
            )

            for mention in mentions:
                entity_counts[mention.entity_id] += 1
                if mention.entity_id not in entity_details:
                    entity = await db.get(Entity, mention.entity_id)
                    if entity:
                        entity_details[mention.entity_id] = {
                            "id": str(entity.id),
                            "name": entity.name,
                            "type": entity.entity_type.value,
                            "aliases": entity.aliases,
                            "attributes": entity.attributes,
                        }

        # Sort by mention count
        sorted_entities = sorted(entity_counts.items(), key=lambda x: x[1], reverse=True)

        return [{**entity_details[entity_id], "mention_count": count} for entity_id, count in sorted_entities[:20]]

    async def _build_timeline(self, documents: list[Document], db: AsyncSession) -> list[dict[str, Any]]:
        """Build timeline from documents"""
        events_by_date = defaultdict(list)

        for doc in documents:
            events = (
                (await db.execute(select(TimelineEvent).where(TimelineEvent.document_id == doc.id))).scalars().all()
            )

            for event in events:
                events_by_date[event.event_date].append(
                    {
                        "id": str(event.id),
                        "title": event.title,
                        "description": event.description,
                        "type": event.event_type,
                        "importance": event.importance,
                        "document_id": str(doc.id),
                    }
                )

        # Sort by date
        sorted_timeline = []
        for date in sorted(events_by_date.keys()):
            sorted_timeline.append({"date": date.isoformat(), "events": events_by_date[date]})

        return sorted_timeline

    async def _reduce_synthesis(
        self,
        topic: str,
        mapped_results: list[dict[str, Any]],
        entities: list[dict[str, Any]],
        timeline: list[dict[str, Any]],
        style: str,
        language: str,
        max_length: int,
        documents: list[Document],
        context_block: str | None = None,
    ) -> str:
        """
        Reduce phase: Synthesize all mapped information into a coherent summary
        """
        # Filter successful mappings
        successful = [r for r in mapped_results if "error" not in r]

        if not successful:
            return "Unable to synthesize information from the provided documents."

        # Determine bucket-based routing - use most restrictive (confidential if any)
        use_ollama = any(r.get("bucket") == DocumentBucket.CONFIDENTIAL for r in successful)

        # Build context
        context_parts = []

        # Add extracted information from each document
        for i, result in enumerate(successful):
            context_parts.append(f"## Document {i + 1}: {result['filename']}")
            if result.get("created_at"):
                context_parts.append(f"Date: {result['created_at']}")

            extracted = result.get("extracted", {})
            if extracted.get("summary"):
                context_parts.append(f"Summary: {extracted['summary']}")

            if extracted.get("facts"):
                context_parts.append("Key Facts:")
                for fact in extracted["facts"][:5]:
                    context_parts.append(f"- {fact}")

            context_parts.append("")

        # Add entities
        if entities:
            context_parts.append("## Key Entities")
            for entity in entities[:10]:
                context_parts.append(f"- **{entity['name']}** ({entity['type']})")

            context_parts.append("")

        # Add timeline
        if timeline:
            context_parts.append("## Timeline")
            for entry in timeline[:10]:
                date = entry["date"]
                for event in entry["events"]:
                    context_parts.append(f"- {date}: {event['title']}")
            context_parts.append("")

        context_text = "\n".join(context_parts)

        # Build synthesis prompt
        style_instructions = {
            "informative": "Write in a clear, educational style that explains the topic thoroughly",
            "professional": "Write in a formal business tone with professional language",
            "creative": "Write in an engaging, narrative style that captures interest",
            "casual": "Write in a friendly, conversational tone",
        }

        system_prompt = build_service_prompt(
            service_name="SOWKNOW Synthesis Reduce Agent",
            mission="Synthesize information from multiple documents using map-reduce analysis to extract key points, timelines, and comprehensive summaries",
            constraints=(
                "- You MUST process each document independently in the map phase\n"
                "- You MUST reconcile conflicting information in the reduce phase\n"
                "- You MUST cite source documents for all synthesized claims\n"
                "- You MUST flag temporal inconsistencies across documents\n"
                "- You MUST NOT include information from confidential documents in cloud-routed synthesis"
            ),
            task_prompt=f"""Create a comprehensive synthesis about the topic.

Style: {style_instructions.get(style, style_instructions["informative"])}
Language: {language}
Maximum Length: {max_length} words

Your synthesis should:
1. Integrate information from all sources coherently
2. Highlight key themes and patterns across documents
3. Identify important relationships and connections
4. Present a balanced view incorporating all perspectives
5. Be well-structured with clear sections""",
        )

        user_prompt = f"""Topic: {topic}

Source Material:
{context_text[:8000]}

Please create a comprehensive synthesis about "{topic}" that integrates all the information above:"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        # Prepend working memory context block
        if context_block and messages and messages[0]["role"] == "system":
            messages[0]["content"] = context_block + "\n\n" + messages[0]["content"]

        try:
            # Determine LLM routing based on document bucket
            llm_service = self._get_ollama_service() if use_ollama else self._get_openrouter_service()

            response = []
            async for chunk in llm_service.chat_completion(
                messages=messages, stream=False, temperature=0.7, max_tokens=4096
            ):
                if chunk and not chunk.startswith("Error:") and not chunk.startswith("__USAGE__"):
                    response.append(chunk)

            return "".join(response).strip()

        except Exception as e:
            logger.error(f"Error in reduce synthesis: {e}")
            return f"Error synthesizing information: {str(e)}"

    async def _extract_key_points(
        self, synthesis: str, topic: str, documents: list[Document],
        context_block: str | None = None,
    ) -> list[str]:
        """Extract key points from the synthesis"""
        # Determine bucket-based routing
        use_ollama = any(doc.bucket == DocumentBucket.CONFIDENTIAL for doc in documents)

        system_prompt = build_service_prompt(
            service_name="SOWKNOW Synthesis Key Points Agent",
            mission="Synthesize information from multiple documents using map-reduce analysis to extract key points, timelines, and comprehensive summaries",
            constraints=(
                "- You MUST process each document independently in the map phase\n"
                "- You MUST reconcile conflicting information in the reduce phase\n"
                "- You MUST cite source documents for all synthesized claims\n"
                "- You MUST flag temporal inconsistencies across documents\n"
                "- You MUST NOT include information from confidential documents in cloud-routed synthesis"
            ),
            task_prompt="Extract the 3-7 most important key points from the text.\nReturn as a JSON array of strings, each being a key point.",
        )

        user_prompt = f"""Topic: {topic}

Text:
{synthesis[:3000]}

Extract the key points:"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        # Prepend working memory context block
        if context_block and messages and messages[0]["role"] == "system":
            messages[0]["content"] = context_block + "\n\n" + messages[0]["content"]

        try:
            llm_service = self._get_ollama_service() if use_ollama else self._get_openrouter_service()

            response = []
            async for chunk in llm_service.chat_completion(
                messages=messages, stream=False, temperature=0.3, max_tokens=512
            ):
                if chunk and not chunk.startswith("Error:") and not chunk.startswith("__USAGE__"):
                    response.append(chunk)

            response_text = "".join(response).strip()

            import json

            try:
                key_points = json.loads(self._extract_json(response_text))
                if isinstance(key_points, list):
                    return key_points[:7]
            except (json.JSONDecodeError, ValueError, TypeError):
                pass

            # Fallback: split by newlines
            lines = synthesis.split("\n")
            points = [line.strip("- ").strip() for line in lines if line.strip().startswith(("- ", "•", "*"))]
            return points[:7]

        except Exception as e:
            logger.warning(f"Error extracting key points: {e}")
            return []

    def _prepare_sources(self, documents: list[Document], mapped_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Prepare source citations"""
        sources = []

        for doc in documents:
            sources.append(
                {
                    "document_id": str(doc.id),
                    "filename": doc.filename,
                    "created_at": (doc.created_at.isoformat() if doc.created_at else None),
                    "mime_type": doc.mime_type,
                }
            )

        return sources

    def _calculate_confidence(self, mapped_results: list[dict[str, Any]], total_documents: int) -> float:
        """Calculate confidence score based on successful extractions"""
        successful = sum(1 for r in mapped_results if "error" not in r)
        return min(1.0, successful / max(1, total_documents))

    def _extract_json(self, text: str) -> str:
        """Extract JSON from response text"""
        text = text.strip()

        if "```json" in text:
            start = text.find("```json") + 7
            end = text.rfind("```")
            if end > start:
                return text[start:end].strip()

        if "```" in text:
            start = text.find("```") + 3
            end = text.rfind("```")
            if end > start:
                return text[start:end].strip()

        if text.startswith("{"):
            brace_count = 0
            end_pos = 0
            for i, char in enumerate(text):
                if char == "{":
                    brace_count += 1
                elif char == "}":
                    brace_count -= 1
                    if brace_count == 0:
                        end_pos = i + 1
                        break
            if end_pos > 0:
                return text[:end_pos]

        if text.startswith("["):
            bracket_count = 0
            end_pos = 0
            for i, char in enumerate(text):
                if char == "[":
                    bracket_count += 1
                elif char == "]":
                    bracket_count -= 1
                    if bracket_count == 0:
                        end_pos = i + 1
                        break
            if end_pos > 0:
                return text[:end_pos]

        return text

    async def batch_synthesize(
        self,
        requests: list[SynthesisRequest],
        db: AsyncSession,
        on_progress: Callable[[int, int, str], None] | None = None,
    ) -> list[SynthesisResult]:
        """
        Process multiple synthesis requests in batch

        Args:
            requests: List of synthesis requests
            db: Database session
            on_progress: Optional callback (index, total, status)

        Returns:
            List of synthesis results
        """
        results = []

        for i, request in enumerate(requests):
            if on_progress:
                on_progress(i, len(requests), f"Processing {request.topic}...")

            try:
                result = await self.synthesize(request, db)
                results.append(result)
            except Exception as e:
                logger.error(f"Error in batch synthesis {i}: {e}")
                # Add error result
                results.append(
                    SynthesisResult(
                        topic=request.topic,
                        synthesis=f"Error: {str(e)}",
                        key_points=[],
                        sources=[],
                        entities=[],
                        confidence=0.0,
                    )
                )

        return results


# Global synthesis service instance
synthesis_service = SynthesisPipelineService()
