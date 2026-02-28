"""
Relationship Mapping Service for Knowledge Graph

Analyzes extracted entities and builds relationships across documents
to create a connected knowledge graph.
"""

import logging
from collections import defaultdict
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge_graph import (
    Entity,
    EntityRelationship,
    EntityType,
    RelationType,
)
from app.services.entity_extraction_service import (
    ExtractedEntity,
    ExtractedRelationship,
    entity_extraction_service,
)

logger = logging.getLogger(__name__)


class RelationshipMapper:
    """Maps relationships between entities across documents"""

    # Relationship patterns for inference
    RELATIONSHIP_PATTERNS = {
        (EntityType.PERSON, EntityType.ORGANIZATION): [
            RelationType.WORKS_AT,
            RelationType.EMPLOYEE_OF,
            RelationType.CEO_OF,
            RelationType.FOUNDED,
            RelationType.CLIENT_OF,
            RelationType.PARTNER_OF,
        ],
        (EntityType.ORGANIZATION, EntityType.LOCATION): [
            RelationType.LOCATED_IN,
            RelationType.FOUNDED,
        ],
        (EntityType.PERSON, EntityType.LOCATION): [
            RelationType.LOCATED_IN,
            RelationType.MEMBER_OF,
        ],
        (EntityType.CONCEPT, EntityType.ORGANIZATION): [
            RelationType.RELATED_TO,
            RelationType.PART_OF,
        ],
        (EntityType.EVENT, EntityType.PERSON): [
            RelationType.HAPPENED_ON,
            RelationType.MENTIONED_WITH,
        ],
        (EntityType.EVENT, EntityType.ORGANIZATION): [
            RelationType.HAPPENED_ON,
            RelationType.CREATED_ON,
        ],
    }

    def __init__(self):
        self.entity_service = entity_extraction_service

    async def infer_relationships(
        self, document_id: str, entities: list[ExtractedEntity], db: AsyncSession
    ) -> list[ExtractedRelationship]:
        """
        Infer relationships between entities in a document

        Args:
            document_id: Document ID
            entities: List of extracted entities
            db: Database session

        Returns:
            List of inferred relationships
        """
        relationships = []

        # Group entities by type
        entities_by_type = defaultdict(list)
        for entity in entities:
            entities_by_type[entity.entity_type].append(entity)

        # Apply relationship patterns
        for (
            source_type,
            target_type,
        ), relation_types in self.RELATIONSHIP_PATTERNS.items():
            sources = entities_by_type.get(source_type, [])
            targets = entities_by_type.get(target_type, [])

            for source in sources:
                for target in targets:
                    if source.name == target.name:
                        continue  # Skip self-references

                    # Infer most likely relationship based on context
                    relation = self._infer_single_relationship(source, target, relation_types)
                    if relation:
                        relationships.append(relation)

        return relationships

    def _infer_single_relationship(
        self,
        source: ExtractedEntity,
        target: ExtractedEntity,
        possible_types: list[RelationType],
    ) -> ExtractedRelationship | None:
        """Infer the most likely relationship type between two entities"""

        # Check for explicit relationship in source attributes
        if "company" in source.attributes and target.entity_type == EntityType.ORGANIZATION:
            if source.attributes.get("company") == target.name:
                return ExtractedRelationship(
                    source_name=source.name,
                    target_name=target.name,
                    relation_type=RelationType.WORKS_AT,
                    confidence=80,
                )

        # Check for role-based relationships
        if source.entity_type == EntityType.PERSON and target.entity_type == EntityType.ORGANIZATION:
            role = source.attributes.get("role", "").lower()
            if role in ["ceo", "founder", "owner"]:
                if role == "ceo":
                    return ExtractedRelationship(
                        source_name=source.name,
                        target_name=target.name,
                        relation_type=RelationType.CEO_OF,
                        confidence=85,
                    )
                elif role == "founder":
                    return ExtractedRelationship(
                        source_name=source.name,
                        target_name=target.name,
                        relation_type=RelationType.FOUNDED,
                        confidence=85,
                    )

        # Default to works_at for person-organization
        if (
            source.entity_type == EntityType.PERSON
            and target.entity_type == EntityType.ORGANIZATION
            and RelationType.WORKS_AT in possible_types
        ):
            return ExtractedRelationship(
                source_name=source.name,
                target_name=target.name,
                relation_type=RelationType.WORKS_AT,
                confidence=60,
            )

        return None

    async def find_entity_connections(self, entity_name: str, db: AsyncSession, max_depth: int = 2) -> dict[str, Any]:
        """
        Find all entities connected to a given entity

        Args:
            entity_name: Name of the entity to start from
            db: Database session
            max_depth: How many hops to explore

        Returns:
            Dictionary with connected entities and paths
        """
        # Find starting entity
        start_entity = (
            await db.execute(select(Entity).where(Entity.name.ilike(f"%{entity_name}%")))
        ).scalar_one_or_none()

        if not start_entity:
            return {"error": "Entity not found"}

        # BFS to find connected entities
        visited = {str(start_entity.id)}
        queue = [(start_entity, 0)]
        connections = []

        while queue:
            current_entity, depth = queue.pop(0)

            if depth >= max_depth:
                continue

            # Get outgoing relationships
            relationships = (
                (await db.execute(select(EntityRelationship).where(EntityRelationship.source_id == current_entity.id)))
                .scalars()
                .all()
            )

            for rel in relationships:
                if str(rel.target_id) not in visited:
                    visited.add(str(rel.target_id))

                    # Load target entity
                    target = await db.get(Entity, rel.target_id)
                    if target:
                        connections.append(
                            {
                                "from": current_entity.name,
                                "to": target.name,
                                "type": rel.relation_type.value,
                                "depth": depth + 1,
                                "confidence": rel.confidence_score,
                            }
                        )
                        queue.append((target, depth + 1))

                # Also get incoming relationships
                incoming = (
                    (
                        await db.execute(
                            select(EntityRelationship).where(EntityRelationship.target_id == current_entity.id)
                        )
                    )
                    .scalars()
                    .all()
                )

                for rel in incoming:
                    if str(rel.source_id) not in visited:
                        visited.add(str(rel.source_id))

                        source = await db.get(Entity, rel.source_id)
                        if source:
                            connections.append(
                                {
                                    "from": source.name,
                                    "to": current_entity.name,
                                    "type": rel.relation_type.value,
                                    "depth": depth + 1,
                                    "confidence": rel.confidence_score,
                                    "reverse": True,
                                }
                            )
                            queue.append((source, depth + 1))

        return {
            "start_entity": start_entity.name,
            "entity_type": start_entity.entity_type.value,
            "connections": connections,
            "total_connections": len(connections),
        }

    async def build_entity_clusters(self, db: AsyncSession, min_cluster_size: int = 2) -> list[dict[str, Any]]:
        """
        Find clusters of highly connected entities

        Useful for identifying groups (e.g., all people from the same company)

        Args:
            db: Database session
            min_cluster_size: Minimum entities to form a cluster

        Returns:
            List of entity clusters
        """
        # Get all entities with relationships
        entities_with_rels = (await db.execute(select(Entity).where(Entity.relationship_count > 0))).scalars().all()

        # Build adjacency list
        graph = defaultdict(set)
        for entity in entities_with_rels:
            # Get all related entities
            outgoing = (
                (await db.execute(select(EntityRelationship).where(EntityRelationship.source_id == entity.id)))
                .scalars()
                .all()
            )

            for rel in outgoing:
                graph[entity.name].add(rel.target_id)

            # Also add incoming
            incoming = (
                (await db.execute(select(EntityRelationship).where(EntityRelationship.target_id == entity.id)))
                .scalars()
                .all()
            )

            for rel in incoming:
                graph[entity.name].add(rel.source_id)

        # Find connected components
        visited = set()
        clusters = []

        for entity in entities_with_rels:
            if entity.name not in visited:
                # BFS to find component
                component = []
                queue = [entity.name]
                visited.add(entity.name)

                while queue:
                    current = queue.pop(0)
                    component.append(current)

                    # Get neighbors
                    for neighbor_id in graph.get(current, []):
                        neighbor = await db.get(Entity, neighbor_id)
                        if neighbor and neighbor.name not in visited:
                            visited.add(neighbor.name)
                            queue.append(neighbor.name)

                if len(component) >= min_cluster_size:
                    clusters.append({"entities": component, "size": len(component)})

        # Sort by size
        clusters.sort(key=lambda x: x["size"], reverse=True)

        return clusters[:20]


class RelationshipService:
    """Service for managing entity relationships"""

    def __init__(self):
        self.mapper = RelationshipMapper()

    async def update_entity_connections(self, db: AsyncSession, entity_name: str) -> dict[str, Any]:
        """
        Update and refresh entity connections

        Args:
            db: Database session
            entity_name: Name of entity to update

        Returns:
            Updated connection graph
        """
        connections = await self.mapper.find_entity_connections(entity_name=entity_name, db=db, max_depth=2)

        return connections

    async def get_entity_neighbors(
        self, entity_id: str, db: AsyncSession, relation_type: RelationType | None = None
    ) -> list[dict[str, Any]]:
        """
        Get direct neighbors of an entity

        Args:
            entity_id: Entity ID
            db: Database session
            relation_type: Optional filter by relationship type

        Returns:
            List of neighboring entities
        """
        stmt = select(EntityRelationship).where(
            or_(
                EntityRelationship.source_id == entity_id,
                EntityRelationship.target_id == entity_id,
            )
        )

        if relation_type:
            stmt = stmt.where(EntityRelationship.relation_type == relation_type)

        relationships = (await db.execute(stmt)).scalars().all()

        neighbors = []
        for rel in relationships:
            is_source = rel.source_id == entity_id
            other_id = rel.target_id if is_source else rel.source_id

            entity = await db.get(Entity, other_id)
            if entity:
                neighbors.append(
                    {
                        "entity_id": str(entity.id),
                        "name": entity.name,
                        "type": entity.entity_type.value,
                        "relation_type": rel.relation_type.value,
                        "direction": "outgoing" if is_source else "incoming",
                        "confidence": rel.confidence_score,
                    }
                )

        return neighbors

    async def get_shortest_path(
        self, source_entity_name: str, target_entity_name: str, db: AsyncSession
    ) -> list[dict[str, Any]] | None:
        """
        Find shortest path between two entities

        Args:
            source_entity_name: Starting entity name
            target_entity_name: Target entity name
            db: Database session

        Returns:
            List of entities in the path, or None if no path exists
        """
        # Find entities
        source = (
            await db.execute(select(Entity).where(Entity.name.ilike(f"%{source_entity_name}%")))
        ).scalar_one_or_none()

        target = (
            await db.execute(select(Entity).where(Entity.name.ilike(f"%{target_entity_name}%")))
        ).scalar_one_or_none()

        if not source or not target:
            return None

        # BFS to find shortest path
        from collections import deque

        queue = deque([(source.id, [])])
        visited = {str(source.id)}
        parent = {}  # For path reconstruction

        while queue:
            current_id, path = queue.popleft()

            if current_id == target.id:
                # Reconstruct path
                full_path = path + [target.name]
                return [{"entity": name, "step": i} for i, name in enumerate(full_path)]

            # Get neighbors
            relationships = (
                (await db.execute(select(EntityRelationship).where(EntityRelationship.source_id == current_id)))
                .scalars()
                .all()
            )

            for rel in relationships:
                target_id = str(rel.target_id)
                if target_id not in visited:
                    visited.add(target_id)
                    parent[target_id] = (current_id, path)
                    queue.append((rel.target_id, path + [rel.relation_type.value]))

        return None


# Global relationship service instance
relationship_service = RelationshipService()
