"""
Progressive Revelation Service for Knowledge Graph

Provides information in layers based on user context, role, and
interaction history. Enables family context generation and personalized
information disclosure.
"""
import logging
from typing import List, Dict, Any, Optional, Set
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from collections import defaultdict

from app.models.user import User
from app.models.knowledge_graph import Entity, EntityRelationship, TimelineEvent
from app.models.document import DocumentBucket
from app.services.gemini_service import gemini_service

logger = logging.getLogger(__name__)


class RevelationLayer:
    """Layers of information disclosure"""

    SURFACE = "surface"       # Basic, non-sensitive information
    CONTEXT = "context"       # Additional context and connections
    DETAILED = "detailed"     # In-depth information
    COMPREHENSIVE = "comprehensive"  # Everything including inferences


class FamilyContext:
    """Context about family relationships and history"""

    def __init__(
        self,
        family_members: List[Dict[str, Any]],
        relationships: List[Dict[str, Any]],
        key_events: List[Dict[str, Any]],
        family_narrative: str
    ):
        self.family_members = family_members
        self.relationships = relationships
        self.key_events = key_events
        self.family_narrative = family_narrative


class ProgressiveRevelationService:
    """Service for progressive information disclosure"""

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

    async def reveal_entity_info(
        self,
        entity_id: str,
        user: User,
        layer: str = RevelationLayer.SURFACE,
        db: Session = None
    ) -> Dict[str, Any]:
        """
        Reveal entity information at the appropriate layer

        Args:
            entity_id: Entity to reveal
            user: Current user
            layer: Revelation depth
            db: Database session

        Returns:
            Layered entity information
        """
        if not db:
            return {"error": "Database session required"}

        entity = db.query(Entity).get(entity_id)
        if not entity:
            return {"error": "Entity not found"}

        base_info = {
            "id": str(entity.id),
            "name": entity.name,
            "type": entity.entity_type.value
        }

        # Layer 1: Surface - Basic information only
        if layer == RevelationLayer.SURFACE:
            return {
                **base_info,
                "layer": "surface",
                "description": f"{entity.entity_type.value} found in documents",
                "document_count": entity.document_count
            }

        # Layer 2: Context - Add aliases and basic connections
        if layer == RevelationLayer.CONTEXT:
            return {
                **base_info,
                "layer": "context",
                "aliases": entity.aliases or [],
                "document_count": entity.document_count,
                "relationship_count": entity.relationship_count,
                "first_seen": entity.first_seen_at.isoformat() if entity.first_seen_at else None,
                "last_seen": entity.last_seen_at.isoformat() if entity.last_seen_at else None
            }

        # Layer 3: Detailed - Add attributes and relationship details
        if layer == RevelationLayer.DETAILED:
            # Get relationships
            relationships = db.query(EntityRelationship).filter(
                db.or_(
                    EntityRelationship.source_id == entity_id,
                    EntityRelationship.target_id == entity_id
                )
            ).limit(20).all()

            rel_info = []
            for rel in relationships:
                other_id = rel.target_id if rel.source_id == entity_id else rel.source_id
                other = db.query(Entity).get(other_id)
                if other:
                    rel_info.append({
                        "with": other.name,
                        "type": rel.relation_type.value,
                        "direction": "outgoing" if rel.source_id == entity_id else "incoming"
                    })

            return {
                **base_info,
                "layer": "detailed",
                "aliases": entity.aliases or [],
                "attributes": entity.attributes or {},
                "confidence": entity.confidence_score,
                "document_count": entity.document_count,
                "relationships": rel_info
            }

        # Layer 4: Comprehensive - Everything including inferences
        if layer == RevelationLayer.COMPREHENSIVE:
            # All detailed info plus timeline and mentions
            from app.models.knowledge_graph import EntityMention

            mentions = db.query(EntityMention).filter(
                EntityMention.entity_id == entity_id
            ).limit(10).all()

            mention_info = []
            for m in mentions:
                mention_info.append({
                    "context": m.context_text[:200] if m.context_text else None,
                    "page_number": m.page_number,
                    "confidence": m.confidence_score
                })

            # Get timeline events
            timeline_events = db.query(TimelineEvent).filter(
                TimelineEvent.entity_ids.contains([entity_id])
            ).order_by(TimelineEvent.event_date).limit(10).all()

            timeline_info = []
            for te in timeline_events:
                timeline_info.append({
                    "title": te.title,
                    "date": te.event_date.isoformat() if te.event_date else None,
                    "type": te.event_type
                })

            return {
                **base_info,
                "layer": "comprehensive",
                "aliases": entity.aliases or [],
                "attributes": entity.attributes or {},
                "confidence": entity.confidence_score,
                "document_count": entity.document_count,
                "relationship_count": entity.relationship_count,
                "first_seen": entity.first_seen_at.isoformat() if entity.first_seen_at else None,
                "last_seen": entity.last_seen_at.isoformat() if entity.last_seen_at else None,
                "mentions": mention_info,
                "timeline": timeline_info
            }

        return base_info

    async def generate_family_context(
        self,
        focus_person: str,
        db: Session,
        depth: int = 2,
        include_timeline: bool = True,
        bucket: DocumentBucket = DocumentBucket.PUBLIC
    ) -> FamilyContext:
        """
        Generate family context and narrative

        Args:
            focus_person: Name of the person to focus on
            db: Database session
            depth: How many relationship levels to explore
            include_timeline: Whether to include family timeline
            bucket: Document bucket for routing decisions

        Returns:
            FamilyContext with members, relationships, events, and narrative
        """
        try:
            # Find the focus person
            person = db.query(Entity).filter(
                db.and_(
                    Entity.name.ilike(f"%{focus_person}%"),
                    Entity.entity_type == "person"
                )
            ).first()

            if not person:
                return FamilyContext(
                    family_members=[],
                    relationships=[],
                    key_events=[],
                    family_narrative=f"Could not find information about {focus_person}"
                )

            # Find family members through relationships
            family_ids = {str(person.id)}
            family_members = [{
                "id": str(person.id),
                "name": person.name,
                "role": "focus",
                "attributes": person.attributes or {}
            }]

            # Expand to find family members
            queue = [(str(person.id), 0)]
            visited = {str(person.id)}

            family_rels = [
                "family", "parent_of", "child_of", "spouse_of",
                "sibling_of", "related_to", "member_of"
            ]

            while queue:
                current_id, current_depth = queue.pop(0)

                if current_depth >= depth:
                    continue

                # Get relationships
                relationships = db.query(EntityRelationship).filter(
                    db.or_(
                        EntityRelationship.source_id == current_id,
                        EntityRelationship.target_id == current_id
                    )
                ).all()

                for rel in relationships:
                    # Check if this is a family-type relationship
                    is_family = (
                        rel.relation_type.value in family_rels or
                        any(fr in rel.relation_type.value for fr in family_rels)
                    )

                    if is_family:
                        other_id = str(rel.target_id if rel.source_id == current_id else rel.source_id)

                        if other_id not in visited:
                            visited.add(other_id)
                            other = db.query(Entity).get(other_id)

                            if other and other.entity_type.value == "person":
                                family_ids.add(other_id)
                                family_members.append({
                                    "id": other_id,
                                    "name": other.name,
                                    "role": rel.relation_type.value,
                                    "attributes": other.attributes or {}
                                })
                                queue.append((other_id, current_depth + 1))

            # Get relationships between family members
            relationships = []
            for member_id in family_ids:
                rels = db.query(EntityRelationship).filter(
                    db.or_(
                        EntityRelationship.source_id == member_id,
                        EntityRelationship.target_id == member_id
                    )
                ).all()

                for rel in rels:
                    other_id = str(rel.target_id if rel.source_id == member_id else rel.source_id)

                    if other_id in family_ids:
                        from_member = db.query(Entity).get(member_id)
                        to_member = db.query(Entity).get(other_id)

                        if from_member and to_member:
                            relationships.append({
                                "from": from_member.name,
                                "to": to_member.name,
                                "type": rel.relation_type.value,
                                "confidence": rel.confidence_score
                            })

            # Get key family events
            key_events = []
            if include_timeline:
                timeline_events = db.query(TimelineEvent).filter(
                    db.and_(
                        TimelineEvent.entity_ids.overlap(list(family_ids)),
                        TimelineEvent.event_date.isnot(None)
                    )
                ).order_by(TimelineEvent.event_date).limit(20).all()

                for te in timeline_events:
                    # Get participating entities
                    participants = []
                    for eid in te.entity_ids or []:
                        if eid in family_ids:
                            entity = db.query(Entity).get(eid)
                            if entity:
                                participants.append(entity.name)

                    key_events.append({
                        "title": te.title,
                        "date": te.event_date.isoformat() if te.event_date else None,
                        "type": te.event_type,
                        "participants": participants,
                        "description": te.description
                    })

            # Generate narrative
            narrative = await self._generate_family_narrative(
                focus_person,
                family_members,
                relationships,
                key_events,
                bucket
            )

            return FamilyContext(
                family_members=family_members,
                relationships=relationships,
                key_events=key_events,
                family_narrative=narrative
            )

        except Exception as e:
            logger.error(f"Family context generation error: {e}")
            return FamilyContext(
                family_members=[],
                relationships=[],
                key_events=[],
                family_narrative=f"Error generating family context: {str(e)}"
            )

    async def _generate_family_narrative(
        self,
        focus_person: str,
        members: List[Dict[str, Any]],
        relationships: List[Dict[str, Any]],
        events: List[Dict[str, Any]],
        bucket: DocumentBucket = DocumentBucket.PUBLIC
    ) -> str:
        """Generate a narrative description of the family context"""
        
        # Determine LLM routing based on bucket
        use_ollama = bucket == DocumentBucket.CONFIDENTIAL
        
        system_prompt = """You are SOWKNOW's family historian. Create a warm, engaging narrative
that describes family relationships, connections, and key events based on the provided information.

Your narrative should:
1. Be respectful and factual
2. Focus on relationships and connections
3. Highlight important family events
4. Be suitable for family archival purposes
5. Write in a narrative, storytelling style"""

        # Build context
        context_parts = [f"Family context for {focus_person}.\n"]

        if members:
            context_parts.append(f"\nFamily Members ({len(members)}):")
            for member in members[:10]:
                role = member.get("role", "relative")
                context_parts.append(f"- {member['name']} ({role})")

        if relationships:
            context_parts.append(f"\nRelationships ({len(relationships)}):")
            for rel in relationships[:10]:
                context_parts.append(f"- {rel['from']} → {rel['to']} ({rel['type']})")

        if events:
            context_parts.append(f"\nKey Family Events ({len(events)}):")
            for event in events[:10]:
                date_str = event.get("date", "Unknown date")
                participants = ", ".join(event.get("participants", []))
                context_parts.append(f"- {date_str}: {event['title']}")
                if participants:
                    context_parts.append(f"  Participants: {participants}")

        context_text = "\n".join(context_parts)

        user_prompt = f"""{context_text}

Please write a family narrative that weaves together these relationships and events:"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        try:
            # Get appropriate LLM service based on bucket
            llm_service = self._get_ollama_service() if use_ollama else self._get_openrouter_service()
            
            response = []
            async for chunk in llm_service.chat_completion(
                messages=messages,
                stream=False,
                temperature=0.8,
                max_tokens=2048
            ):
                if chunk and not chunk.startswith("Error:") and not chunk.startswith("__USAGE__"):
                    response.append(chunk)

            return "".join(response).strip()

        except Exception as e:
            logger.error(f"Narrative generation error: {e}")
            return f"Family of {focus_person} with {len(members)} members and {len(events)} key events."

    async def suggest_revelation_layer(
        self,
        user: User,
        entity_id: str,
        interaction_history: List[Dict[str, Any]],
        db: Session
    ) -> str:
        """
        Suggest appropriate revelation layer based on user and context

        Args:
            user: Current user
            entity_id: Entity being accessed
            interaction_history: User's past interactions
            db: Database session

        Returns:
            Recommended revelation layer
        """
        # Check user role
        if user.role == "admin":
            return RevelationLayer.COMPREHENSIVE
        elif user.role == "super_user":
            return RevelationLayer.DETAILED
        else:
            # Regular users get progressive disclosure
            # Check interaction history
            entity_interactions = [
                i for i in interaction_history
                if i.get("entity_id") == entity_id
            ]

            if len(entity_interactions) > 5:
                return RevelationLayer.DETAILED
            elif len(entity_interactions) > 2:
                return RevelationLayer.CONTEXT
            else:
                return RevelationLayer.SURFACE

    async def get_progressive_search_results(
        self,
        query: str,
        user: User,
        results: List[Dict[str, Any]],
        db: Session
    ) -> Dict[str, Any]:
        """
        Return search results with progressive revelation based on user role

        Args:
            query: Search query
            user: Current user
            results: Raw search results
            db: Database session

        Returns:
            Layered search results
        """
        # Determine layer based on user role
        if user.role == "admin":
            layer = RevelationLayer.COMPREHENSIVE
        elif user.role == "super_user":
            layer = RevelationLayer.DETAILED
        else:
            layer = RevelationLayer.CONTEXT

        # Apply progressive filtering
        filtered_results = []

        for result in results:
            filtered_result = {
                "document_id": result.get("document_id"),
                "filename": result.get("filename"),
                "score": result.get("score"),
                "layer": layer
            }

            # Add content based on layer
            if layer == RevelationLayer.SURFACE:
                filtered_result["snippet"] = result.get("content", "")[:100] + "..."
            elif layer == RevelationLayer.CONTEXT:
                filtered_result["snippet"] = result.get("content", "")[:300] + "..."
            elif layer == RevelationLayer.DETAILED:
                filtered_result["snippet"] = result.get("content", "")[:800] + "..."
                filtered_result["metadata"] = result.get("metadata", {})
            else:  # COMPREHENSIVE
                filtered_result["content"] = result.get("content")
                filtered_result["metadata"] = result.get("metadata", {})
                filtered_result["entities"] = result.get("entities", [])

            filtered_results.append(filtered_result)

        return {
            "query": query,
            "layer": layer,
            "result_count": len(filtered_results),
            "results": filtered_results
        }


# Global progressive revelation service instance
progressive_revelation_service = ProgressiveRevelationService()
