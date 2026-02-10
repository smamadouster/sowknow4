"""
Graph-RAG Service for Knowledge Graph Augmented Retrieval

Enhances search results by incorporating entity relationships and
context from the knowledge graph. Uses graph structure to improve
relevance and discover related information.
"""
import logging
from typing import List, Dict, Any, Optional, Set, Tuple
from collections import defaultdict
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func

from app.models.knowledge_graph import (
    Entity,
    EntityRelationship,
    EntityMention,
    EntityType,
    RelationType
)
from app.models.document import Document, DocumentChunk
from app.services.gemini_service import gemini_service

logger = logging.getLogger(__name__)


class GraphRAGService:
    """Service for graph-augmented retrieval and generation"""

    def __init__(self):
        self.gemini_service = gemini_service

    async def enhance_search_with_graph(
        self,
        query: str,
        initial_results: List[Dict[str, Any]],
        db: Session,
        top_k_entities: int = 10,
        expansion_depth: int = 2
    ) -> Dict[str, Any]:
        """
        Enhance search results using knowledge graph

        Args:
            query: Original search query
            initial_results: Initial semantic search results
            db: Database session
            top_k_entities: Number of top entities to consider
            expansion_depth: How many hops to expand in the graph

        Returns:
            Enhanced search results with graph context
        """
        try:
            # Extract entities from query
            query_entities = await self._extract_query_entities(query, db)

            # Find relevant entities from search results
            result_entities = await self._find_entities_in_results(
                initial_results,
                db,
                limit=top_k_entities
            )

            # Combine query and result entities
            all_relevant_entities = list(set(query_entities + result_entities))

            if not all_relevant_entities:
                return {
                    "query": query,
                    "results": initial_results,
                    "graph_context": None,
                    "related_entities": [],
                    "explanation": "No relevant entities found in knowledge graph"
                }

            # Expand to find related entities
            expanded_entities = await self._expand_entities(
                all_relevant_entities,
                db,
                max_depth=expansion_depth
            )

            # Build graph context
            graph_context = await self._build_graph_context(
                all_relevant_entities,
                expanded_entities,
                db
            )

            # Rank and augment results
            enhanced_results = await self._rank_results_with_graph(
                initial_results,
                all_relevant_entities,
                expanded_entities,
                db
            )

            return {
                "query": query,
                "results": enhanced_results,
                "graph_context": graph_context,
                "related_entities": expanded_entities[:20],
                "entity_count": len(all_relevant_entities),
                "explanation": f"Enhanced with {len(all_relevant_entities)} entities and {len(expanded_entities)} related concepts"
            }

        except Exception as e:
            logger.error(f"Graph-RAG enhancement error: {e}")
            return {
                "query": query,
                "results": initial_results,
                "graph_context": None,
                "error": str(e)
            }

    async def _extract_query_entities(
        self,
        query: str,
        db: Session
    ) -> List[str]:
        """Extract entity names from the query"""
        # Simple extraction: find entities mentioned in query
        entities = []

        # Get all entities and check if their names appear in query
        all_entities = db.query(Entity).filter(
            Entity.document_count > 0
        ).limit(100).all()

        query_lower = query.lower()
        for entity in all_entities:
            if entity.name.lower() in query_lower:
                entities.append(entity.id)

        return entities

    async def _find_entities_in_results(
        self,
        results: List[Dict[str, Any]],
        db: Session,
        limit: int = 10
    ) -> List[str]:
        """Find entities mentioned in search results"""
        entity_scores = defaultdict(int)

        for result in results:
            document_id = result.get("document_id")
            if not document_id:
                continue

            # Get entity mentions for this document
            mentions = db.query(EntityMention).filter(
                EntityMention.document_id == document_id
            ).all()

            for mention in mentions:
                entity_scores[mention.entity_id] += result.get("score", 1) * mention.confidence_score / 100

        # Sort by score and return top entity IDs
        sorted_entities = sorted(entity_scores.items(), key=lambda x: x[1], reverse=True)
        return [entity_id for entity_id, _ in sorted_entities[:limit]]

    async def _expand_entities(
        self,
        entity_ids: List[str],
        db: Session,
        max_depth: int = 2
    ) -> List[Dict[str, Any]]:
        """Expand to find related entities through graph traversal"""
        visited = set(entity_ids)
        queue = [(entity_id, 0) for entity_id in entity_ids]
        related_entities = []

        while queue:
            current_id, depth = queue.pop(0)

            if depth >= max_depth:
                continue

            # Get outgoing relationships
            outgoing = db.query(EntityRelationship).filter(
                EntityRelationship.source_id == current_id
            ).all()

            for rel in outgoing:
                target_id = str(rel.target_id)
                if target_id not in visited:
                    visited.add(target_id)

                    target = db.query(Entity).get(target_id)
                    if target:
                        related_entities.append({
                            "id": target_id,
                            "name": target.name,
                            "type": target.entity_type.value,
                            "relation": rel.relation_type.value,
                            "depth": depth + 1,
                            "confidence": rel.confidence_score
                        })
                        queue.append((target_id, depth + 1))

            # Get incoming relationships
            incoming = db.query(EntityRelationship).filter(
                EntityRelationship.target_id == current_id
            ).all()

            for rel in incoming:
                source_id = str(rel.source_id)
                if source_id not in visited:
                    visited.add(source_id)

                    source = db.query(Entity).get(source_id)
                    if source:
                        related_entities.append({
                            "id": source_id,
                            "name": source.name,
                            "type": source.entity_type.value,
                            "relation": f"incoming_{rel.relation_type.value}",
                            "depth": depth + 1,
                            "confidence": rel.confidence_score
                        })
                        queue.append((source_id, depth + 1))

        # Sort by depth and confidence
        related_entities.sort(key=lambda x: (x["depth"], -x["confidence"]))
        return related_entities

    async def _build_graph_context(
        self,
        core_entities: List[str],
        related_entities: List[Dict[str, Any]],
        db: Session
    ) -> Dict[str, Any]:
        """Build context string from graph structure"""
        context = {
            "core_entities": [],
            "relationships": [],
            "paths": []
        }

        # Get details of core entities
        for entity_id in core_entities:
            entity = db.query(Entity).get(entity_id)
            if entity:
                context["core_entities"].append({
                    "id": entity_id,
                    "name": entity.name,
                    "type": entity.entity_type.value,
                    "aliases": entity.aliases,
                    "attributes": entity.attributes
                })

        # Get relationships between core entities
        for i, id1 in enumerate(core_entities):
            for id2 in core_entities[i+1:]:
                rel = db.query(EntityRelationship).filter(
                    and_(
                        EntityRelationship.source_id == id1,
                        EntityRelationship.target_id == id2
                    )
                ).first()

                if not rel:
                    rel = db.query(EntityRelationship).filter(
                        and_(
                            EntityRelationship.source_id == id2,
                            EntityRelationship.target_id == id1
                        )
                    ).first()

                if rel:
                    e1 = db.query(Entity).get(id1)
                    e2 = db.query(Entity).get(id2)
                    if e1 and e2:
                        context["relationships"].append({
                            "from": e1.name,
                            "to": e2.name,
                            "type": rel.relation_type.value,
                            "confidence": rel.confidence_score
                        })

        return context

    async def _rank_results_with_graph(
        self,
        initial_results: List[Dict[str, Any]],
        core_entities: List[str],
        related_entities: List[Dict[str, Any]],
        db: Session
    ) -> List[Dict[str, Any]]:
        """Re-rank search results based on graph relevance"""
        all_entity_ids = set(core_entities + [e["id"] for e in related_entities])

        for result in initial_results:
            graph_boost = 0.0
            document_id = result.get("document_id")

            if document_id:
                # Get entity mentions for this document
                mentions = db.query(EntityMention).filter(
                    and_(
                        EntityMention.document_id == document_id,
                        EntityMention.entity_id.in_(all_entity_ids)
                    )
                ).all()

                for mention in mentions:
                    # Boost score based on entity relevance
                    if mention.entity_id in core_entities:
                        graph_boost += 0.15 * (mention.confidence_score / 100)
                    else:
                        # Find in related entities
                        for re in related_entities:
                            if re["id"] == mention.entity_id:
                                depth_factor = 1.0 / (re["depth"] + 1)
                                graph_boost += 0.05 * depth_factor * (re["confidence"] / 100)
                                break

            # Apply graph boost
            original_score = result.get("score", 0.5)
            boosted_score = min(1.0, original_score + graph_boost)
            result["score"] = boosted_score
            result["graph_boost"] = graph_boost

        # Re-sort by boosted score
        return sorted(initial_results, key=lambda x: x.get("score", 0), reverse=True)

    async def generate_graph_aware_answer(
        self,
        query: str,
        enhanced_results: Dict[str, Any],
        db: Session,
        stream: bool = True
    ) -> Any:
        """
        Generate an answer using graph-aware context

        Args:
            query: User's question
            enhanced_results: Results from enhance_search_with_graph
            db: Database session
            stream: Whether to stream the response

        Returns:
            Generated answer with graph citations
        """
        try:
            # Build context from graph
            graph_context = enhanced_results.get("graph_context", {})
            related_entities = enhanced_results.get("related_entities", [])

            # Build system prompt
            system_prompt = """You are SOWKNOW, an AI assistant for a knowledge management system.
When answering questions, use the knowledge graph information provided to give more
complete and contextually relevant answers.

Key Principles:
1. Reference entities and relationships from the knowledge graph
2. Explain connections between related concepts
3. Use timeline information when discussing historical events
4. Cite the specific documents that support your claims
5. If graph information is sparse, fall back to the document content
6. Be explicit about uncertainty in graph relationships"""

            # Build user prompt with graph context
            user_prompt = f"Question: {query}\n\n"

            # Add core entity information
            if graph_context and graph_context.get("core_entities"):
                user_prompt += "Key Entities:\n"
                for entity in graph_context["core_entities"]:
                    user_prompt += f"- {entity['name']} ({entity['type']})"
                    if entity.get("aliases"):
                        user_prompt += f" [Aliases: {', '.join(entity['aliases'])}]"
                    user_prompt += "\n"
                user_prompt += "\n"

            # Add relationships
            if graph_context and graph_context.get("relationships"):
                user_prompt += "Relationships:\n"
                for rel in graph_context["relationships"]:
                    user_prompt += f"- {rel['from']} → {rel['to']} ({rel['type']})\n"
                user_prompt += "\n"

            # Add related entities
            if related_entities:
                user_prompt += f"Related Concepts ({len(related_entities)}):\n"
                for re in related_entities[:10]:
                    user_prompt += f"- {re['name']} ({re['relation']})\n"
                user_prompt += "\n"

            # Add document results
            user_prompt += "Relevant Documents:\n"
            for i, result in enumerate(enhanced_results.get("results", [])[:5]):
                user_prompt += f"{i+1}. {result.get('filename', 'Unknown')}"
                if result.get("graph_boost"):
                    user_prompt += f" [graph relevance: +{result['graph_boost']:.2f}]"
                user_prompt += "\n"
                if result.get("content"):
                    user_prompt += f"   {result['content'][:200]}...\n"
                user_prompt += "\n"

            user_prompt += "\nPlease provide a comprehensive answer using the graph information above:"

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]

            if stream:
                return self.gemini_service.chat_completion(
                    messages=messages,
                    stream=True,
                    temperature=0.7,
                    max_tokens=2048
                )
            else:
                response = []
                async for chunk in self.gemini_service.chat_completion(
                    messages=messages,
                    stream=False,
                    temperature=0.7,
                    max_tokens=2048
                ):
                    if chunk and not chunk.startswith("Error:") and not chunk.startswith("__USAGE__"):
                        response.append(chunk)
                return "".join(response)

        except Exception as e:
            logger.error(f"Graph-aware answer generation error: {e}")
            raise

    async def find_entity_paths(
        self,
        source_entity_name: str,
        target_entity_name: str,
        db: Session,
        max_path_length: int = 4
    ) -> List[Dict[str, Any]]:
        """
        Find paths between two entities in the knowledge graph

        Args:
            source_entity_name: Starting entity name
            target_entity_name: Target entity name
            db: Database session
            max_path_length: Maximum path length to consider

        Returns:
            List of paths with relationship details
        """
        from collections import deque

        # Find entities
        source = db.query(Entity).filter(
            Entity.name.ilike(f"%{source_entity_name}%")
        ).first()

        target = db.query(Entity).filter(
            Entity.name.ilike(f"%{target_entity_name}%")
        ).first()

        if not source or not target:
            return []

        # BFS to find paths
        queue = deque([(source.id, [])])
        visited = {str(source.id)}
        paths = []

        while queue and len(paths) < 5:  # Limit to 5 paths
            current_id, path = queue.popleft()

            if current_id == target.id:
                paths.append(path)
                continue

            if len(path) >= max_path_length:
                continue

            # Get neighbors
            relationships = db.query(EntityRelationship).filter(
                or_(
                    EntityRelationship.source_id == current_id,
                    EntityRelationship.target_id == current_id
                )
            ).all()

            for rel in relationships:
                next_id = rel.target_id if rel.source_id == current_id else rel.source_id
                next_id_str = str(next_id)

                if next_id_str not in visited:
                    visited.add(next_id_str)
                    entity = db.query(Entity).get(next_id)
                    if entity:
                        new_path = path + [{
                            "entity": entity.name,
                            "entity_type": entity.entity_type.value,
                            "relation": rel.relation_type.value,
                            "direction": "outgoing" if rel.source_id == current_id else "incoming"
                        }]
                        queue.append((next_id, new_path))

        return paths

    async def get_entity_neighborhood(
        self,
        entity_name: str,
        db: Session,
        radius: int = 2
    ) -> Dict[str, Any]:
        """
        Get the neighborhood around an entity

        Args:
            entity_name: Entity name
            db: Database session
            radius: How many hops to include

        Returns:
            Neighborhood graph data
        """
        entity = db.query(Entity).filter(
            Entity.name.ilike(f"%{entity_name}%")
        ).first()

        if not entity:
            return {"error": "Entity not found"}

        nodes = {str(entity.id): {"name": entity.name, "type": entity.entity_type.value}}
        edges = []

        # Expand outward
        visited = {str(entity.id)}
        current_frontier = [str(entity.id)]

        for hop in range(radius):
            next_frontier = []

            for node_id in current_frontier:
                # Get outgoing relationships
                outgoing = db.query(EntityRelationship).filter(
                    EntityRelationship.source_id == node_id
                ).all()

                for rel in outgoing:
                    target_id = str(rel.target_id)
                    target = db.query(Entity).get(target_id)

                    if target and target_id not in visited:
                        visited.add(target_id)
                        next_frontier.append(target_id)
                        nodes[target_id] = {"name": target.name, "type": target.entity_type.value}

                    edges.append({
                        "source": node_id,
                        "target": target_id,
                        "type": rel.relation_type.value,
                        "weight": rel.document_count
                    })

                # Get incoming relationships
                incoming = db.query(EntityRelationship).filter(
                    EntityRelationship.target_id == node_id
                ).all()

                for rel in incoming:
                    source_id = str(rel.source_id)
                    source = db.query(Entity).get(source_id)

                    if source and source_id not in visited:
                        visited.add(source_id)
                        next_frontier.append(source_id)
                        nodes[source_id] = {"name": source.name, "type": source.entity_type.value}

                    edges.append({
                        "source": source_id,
                        "target": node_id,
                        "type": rel.relation_type.value,
                        "weight": rel.document_count
                    })

            current_frontier = next_frontier

        return {
            "center": entity.name,
            "center_type": entity.entity_type.value,
            "nodes": nodes,
            "edges": edges,
            "node_count": len(nodes),
            "edge_count": len(edges),
            "radius": radius
        }


# Global Graph-RAG service instance
graph_rag_service = GraphRAGService()
