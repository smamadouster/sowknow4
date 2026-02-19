"""
Entity Extraction Service for Knowledge Graph

Uses Gemini Flash to extract entities (people, organizations, locations, concepts)
from documents and build a knowledge graph for graph-augmented retrieval.
"""
import logging
import json
from typing import List, Dict, Any, Optional, Set
from datetime import datetime, date
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func
from collections import defaultdict

from app.models.knowledge_graph import (
    Entity,
    EntityRelationship,
    EntityMention,
    TimelineEvent,
    EntityType,
    RelationType
)
from app.models.document import Document, DocumentChunk, DocumentStatus, DocumentBucket
from app.models.user import User
from app.services.gemini_service import gemini_service

logger = logging.getLogger(__name__)


class ExtractedEntity:
    """Container for extracted entity data"""

    def __init__(
        self,
        name: str,
        entity_type: EntityType,
        canonical_id: Optional[str] = None,
        aliases: List[str] = None,
        attributes: Dict[str, Any] = None,
        confidence: int = 50
    ):
        self.name = name
        self.entity_type = entity_type
        self.canonical_id = canonical_id
        self.aliases = aliases or []
        self.attributes = attributes or {}
        self.confidence = confidence


class ExtractedRelationship:
    """Container for extracted relationship data"""

    def __init__(
        self,
        source_name: str,
        target_name: str,
        relation_type: RelationType,
        confidence: int = 50,
        attributes: Dict[str, Any] = None
    ):
        self.source_name = source_name
        self.target_name = target_name
        self.relation_type = relation_type
        self.confidence = confidence
        self.attributes = attributes or {}


class EntityExtractionService:
    """Service for extracting entities and building knowledge graph"""

    def __init__(self):
        self.gemini_service = gemini_service
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

    async def extract_entities_from_document(
        self,
        document: Document,
        chunks: List[DocumentChunk],
        db: Session
    ) -> Dict[str, Any]:
        """
        Extract entities from a document using Gemini Flash or Ollama

        Args:
            document: Document to extract from
            chunks: Document chunks (text content)
            db: Database session

        Returns:
            Dictionary with extraction results
        """
        try:
            # Determine LLM routing based on document bucket
            use_ollama = document.bucket == DocumentBucket.CONFIDENTIAL
            
            # Prepare text for analysis
            document_text = self._prepare_document_text(chunks)

            # Extract entities using appropriate LLM
            extracted = await self._extract_with_llm(
                filename=str(document.filename),
                text=document_text,
                metadata={
                    "created_at": document.created_at.isoformat(),
                    "mime_type": document.mime_type
                },
                use_ollama=use_ollama
            )

            if not extracted:
                return {"entities": [], "relationships": [], "events": []}

            # Store entities
            entity_map = {}  # name -> Entity
            for entity_data in extracted.get("entities", []):
                entity = await self._get_or_create_entity(
                    entity_data=entity_data,
                    db=db
                )
                if entity:
                    entity_map[entity.name] = entity

                    # Create mention record
                    mention = EntityMention(
                        entity_id=entity.id,
                        document_id=document.id,
                        context_text=entity_data.get("context", "")[:500],
                        confidence_score=entity_data.get("confidence", 50)
                    )
                    db.add(mention)

            # Store relationships
            for rel_data in extracted.get("relationships", []):
                await self._create_relationship(
                    rel_data=rel_data,
                    entity_map=entity_map,
                    document_id=document.id,
                    db=db
                )

            # Extract timeline events
            events = extracted.get("events", [])
            for event_data in events:
                await self._create_timeline_event(
                    event_data=event_data,
                    document_id=document.id,
                    db=db
                )

            db.commit()

            logger.info(f"Extracted {len(extracted.get('entities', []))} entities from {document.filename}")
            return extracted

        except Exception as e:
            logger.error(f"Entity extraction error for {document.filename}: {e}")
            return {"entities": [], "relationships": [], "events": []}

    def _prepare_document_text(self, chunks: List[DocumentChunk]) -> str:
        """Prepare document text for entity extraction"""
        # Combine chunks with page references
        text_parts = []
        for chunk in chunks[:20]:  # Limit to 20 chunks for token efficiency
            page_ref = f"[Page {chunk.page_number}] " if chunk.page_number else ""
            text_parts.append(f"{page_ref}{chunk.chunk_text[:500]}")

        return "\n\n".join(text_parts)

    async def _extract_with_llm(
        self,
        filename: str,
        text: str,
        metadata: Dict[str, Any],
        use_ollama: bool = False
    ) -> Optional[Dict[str, Any]]:
        """Extract entities using Gemini Flash or Ollama based on document confidentiality"""

        system_prompt = """You are an expert entity extractor for SOWKNOW, a knowledge management system. Extract structured information from documents.

Extract the following types of entities:
1. **People** (person): Names of individuals
2. **Organizations** (organization): Companies, institutions, agencies
3. **Locations** (location): Cities, countries, addresses
4. **Concepts** (concept): Topics, themes, ideas, technologies
5. **Events** (event): Dated events, milestones

For each entity, also extract relationships between them (e.g., "person WORKS_AT organization").

IMPORTANT RULES:
- Only extract entities explicitly mentioned in the text
- Assign confidence scores (70-100 for clear mentions, 50-70 for inferred)
- Include context snippets for entities
- Extract dates for timeline events
- Respond ONLY with valid JSON

Response format:
```json
{
  "entities": [
    {
      "name": "Entity Name",
      "type": "person|organization|location|concept|event",
      "confidence": 85,
      "context": "surrounding text...",
      "attributes": {"role": "CEO", "industry": "Technology"}
    }
  ],
  "relationships": [
    {
      "source": "Person Name",
      "target": "Company Name",
      "type": "works_at|ceo_of|founded|located_in|related_to",
      "confidence": 80,
      "context": "text evidence..."
    }
  ],
  "events": [
    {
      "title": "Event Title",
      "date": "YYYY-MM-DD",
      "precision": "exact|approximate",
      "type": "milestone|appointment|founding",
      "description": "Event description",
      "importance": 75
    }
  ]
}
```"""

        user_prompt = f"""Extract entities and relationships from this document:

Filename: {filename}
Date: {metadata.get('created_at', 'Unknown')}
Type: {metadata.get('mime_type', 'Unknown')}

Document Text:
{text[:3000]}

Extract all entities, relationships, and dated events now:"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        try:
            response_parts = []
            
            # Route to appropriate LLM based on document confidentiality
            if use_ollama:
                llm_service = self._get_ollama_service()
                async for chunk in llm_service.chat_completion(
                    messages=messages,
                    stream=False,
                    temperature=0.3,
                    num_predict=2048
                ):
                    if chunk and not chunk.startswith("Error:") and not chunk.startswith("__USAGE__"):
                        response_parts.append(chunk)
            else:
                llm_service = self._get_openrouter_service()
                async for chunk in llm_service.chat_completion(
                    messages=messages,
                    stream=False,
                    temperature=0.3,
                    max_tokens=2048
                ):
                    if chunk and not chunk.startswith("Error:") and not chunk.startswith("__USAGE__"):
                        response_parts.append(chunk)

            response_text = "".join(response_parts).strip()

            # Extract JSON
            json_text = self._extract_json(response_text)
            if json_text:
                return json.loads(json_text)

        except Exception as e:
            logger.error(f"Entity extraction error: {e}")

        return None

    def _extract_json(self, text: str) -> Optional[str]:
        """Extract JSON from Gemini response"""
        text = text.strip()

        # Remove markdown code blocks
        if "```json" in text:
            start = text.find("```json") + 7
            end = text.rfind("```")
            if end > start:
                text = text[start:end].strip()
        elif "```" in text:
            start = text.find("```") + 3
            end = text.rfind("```")
            if end > start:
                text = text[start:end].strip()

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

        return None

    async def _get_or_create_entity(
        self,
        entity_data: Dict[str, Any],
        db: Session
    ) -> Optional[Entity]:
        """Get existing entity or create new one"""
        entity_type = EntityType(entity_data.get("type", "other"))
        name = entity_data.get("name", "")

        if not name:
            return None

        # Check for existing entity (same name and type)
        entity = db.query(Entity).filter(
            and_(
                Entity.name == name,
                Entity.entity_type == entity_type
            )
        ).first()

        if not entity:
            # Create new entity
            entity = Entity(
                name=name,
                entity_type=entity_type,
                canonical_id=entity_data.get("canonical_id"),
                aliases=entity_data.get("aliases", []),
                attributes=entity_data.get("attributes", {}),
                confidence_score=entity_data.get("confidence", 50),
                first_seen_at=date.today(),
                last_seen_at=date.today()
            )
            db.add(entity)
            db.flush()

        # Update document count
        entity.document_count += 1
        entity.last_seen_at = date.today()

        return entity

    async def _create_relationship(
        self,
        rel_data: Dict[str, Any],
        entity_map: Dict[str, Entity],
        document_id: str,
        db: Session
    ):
        """Create relationship between entities"""
        source_name = rel_data.get("source", "")
        target_name = rel_data.get("target", "")
        relation_type = RelationType(rel_data.get("type", "related_to"))

        # Find entities
        source_entity = None
        target_entity = None

        # Try exact match first
        for entity in entity_map.values():
            if entity.name == source_name:
                source_entity = entity
            if entity.name == target_name:
                target_entity = entity

        if not source_entity or not target_entity:
            return

        # Check for existing relationship
        existing = db.query(EntityRelationship).filter(
            and_(
                EntityRelationship.source_id == source_entity.id,
                EntityRelationship.target_id == target_entity.id,
                EntityRelationship.relation_type == relation_type
            )
        ).first()

        if existing:
            existing.document_count += 1
            existing.last_seen_at = date.today()
        else:
            # Create new relationship
            relationship = EntityRelationship(
                source_id=source_entity.id,
                target_id=target_entity.id,
                relation_type=relation_type,
                confidence_score=rel_data.get("confidence", 50),
                attributes=rel_data.get("attributes", {}),
                document_count=1,
                first_seen_at=date.today(),
                last_seen_at=date.today()
            )
            db.add(relationship)

        # Update relationship counts
        source_entity.relationship_count += 1
        target_entity.relationship_count += 1

    async def _create_timeline_event(
        self,
        event_data: Dict[str, Any],
        document_id: str,
        db: Session
    ):
        """Create timeline event from extracted data"""
        try:
            event_date_str = event_data.get("date")
            if not event_date_str:
                return

            # Parse date
            try:
                event_date = datetime.strptime(event_date_str, "%Y-%m-%d").date()
            except:
                return

            event = TimelineEvent(
                title=event_data.get("title", "Untitled Event"),
                description=event_data.get("description", ""),
                event_date=event_date,
                event_date_precision=event_data.get("precision", "exact"),
                entity_ids=event_data.get("entity_ids", []),
                document_id=document_id,
                event_type=event_data.get("type", "milestone"),
                importance=event_data.get("importance", 50)
            )
            db.add(event)

        except Exception as e:
            logger.error(f"Error creating timeline event: {e}")

    async def get_entity_graph(
        self,
        db: Session,
        entity_type: Optional[EntityType] = None,
        limit: int = 100
    ) -> Dict[str, Any]:
        """
        Get knowledge graph data for visualization

        Args:
            db: Database session
            entity_type: Optional entity type filter
            limit: Maximum number of entities

        Returns:
            Graph data with nodes and edges
        """
        query = db.query(Entity)

        if entity_type:
            query = query.filter(Entity.entity_type == entity_type)

        entities = query.order_by(Entity.document_count.desc()).limit(limit).all()

        # Build nodes
        nodes = []
        for entity in entities:
            nodes.append({
                "id": str(entity.id),
                "name": entity.name,
                "type": entity.entity_type.value,
                "size": entity.document_count,
                "color": self._get_color_for_type(entity.entity_type)
            })

        # Get relationships
        entity_ids = [e.id for e in entities]
        relationships = db.query(EntityRelationship).filter(
            and_(
                EntityRelationship.source_id.in_(entity_ids),
                EntityRelationship.target_id.in_(entity_ids)
            )
        ).all()

        # Build edges
        edges = []
        for rel in relationships:
            edges.append({
                "source": str(rel.source_id),
                "target": str(rel.target_id),
                "label": rel.relation_type.value,
                "weight": rel.document_count
            })

        return {
            "nodes": nodes,
            "edges": edges,
            "entity_count": len(nodes),
            "relationship_count": len(edges)
        }

    def _get_color_for_type(self, entity_type: EntityType) -> str:
        """Get visualization color for entity type"""
        colors = {
            EntityType.PERSON: "#3B82F6",      # Blue
            EntityType.ORGANIZATION: "#10B981", # Green
            EntityType.LOCATION: "#F59E0B",     # Orange
            EntityType.CONCEPT: "#8B5CF6",      # Purple
            EntityType.EVENT: "#EF4444",        # Red
            EntityType.PRODUCT: "#EC4899",      # Pink
            EntityType.PROJECT: "#6366F1",      # Indigo
            EntityType.DATE: "#6B7280",         # Gray
            EntityType.OTHER: "#9CA3AF"         # Light gray
        }
        return colors.get(entity_type, "#9CA3AF")


# Global entity extraction service instance
entity_extraction_service = EntityExtractionService()
