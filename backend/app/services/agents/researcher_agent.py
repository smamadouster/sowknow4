"""
Researcher Agent for Multi-Agent Search System

Conducts deep research across documents and knowledge graph
to gather comprehensive information for a query.
"""
import logging
from typing import List, Dict, Any, Optional, Set
from dataclasses import dataclass
from collections import defaultdict

from app.services.gemini_service import gemini_service
from app.services.ollama_service import ollama_service
from app.services.search_service import search_service
from app.services.graph_rag_service import graph_rag_service

logger = logging.getLogger(__name__)


@dataclass
class ResearchQuery:
    """Query for research agent"""
    query: str
    clarified_query: Optional[str] = None
    filters: Dict[str, Any] = None
    max_results: int = 20
    use_graph: bool = True
    gather_context: bool = True


@dataclass
class ResearchResult:
    """Result of research operation"""
    query: str
    findings: List[Dict[str, Any]]
    entities: List[Dict[str, Any]]
    relationships: List[Dict[str, Any]]
    context: Dict[str, Any]
    sources: List[Dict[str, Any]]
    confidence: float
    gaps: List[str]
    next_queries: List[str]
    llm_used: str = "unknown"

    def __post_init__(self):
        if self.findings is None:
            self.findings = []
        if self.entities is None:
            self.entities = []
        if self.relationships is None:
            self.relationships = []
        if self.gaps is None:
            self.gaps = []
        if self.next_queries is None:
            self.next_queries = []


class ResearcherAgent:
    """
    Agent responsible for conducting deep research

    The Researcher Agent:
    1. Performs comprehensive search across documents
    2. Leverages knowledge graph for related information
    3. Gathers context from multiple sources
    4. Identifies information gaps
    5. Suggests follow-up queries
    """

    def __init__(self):
        self.gemini_service = gemini_service
        self.ollama_service = ollama_service
        self.search_service = search_service
        self.graph_rag_service = graph_rag_service

    def _has_confidential_documents(self, findings: List[Dict[str, Any]]) -> bool:
        """Check if any findings contain confidential documents"""
        return any(
            finding.get("document_bucket") == "confidential"
            for finding in findings
        )

    def _get_llm_service(self, findings: List[Dict[str, Any]]):
        """Get appropriate LLM service based on document confidentiality"""
        if self._has_confidential_documents(findings):
            logger.info("Researcher: Using Ollama for confidential documents")
            return self.ollama_service, "ollama"
        return self.gemini_service, "gemini"

    async def research(
        self,
        request: ResearchQuery,
        user,
        db
    ) -> ResearchResult:
        """
        Conduct comprehensive research on a query

        Args:
            request: Research query with parameters
            user: Current user
            db: Database session

        Returns:
            Comprehensive research results
        """
        try:
            # Use clarified query if available
            search_query = request.clarified_query or request.query

            # Step 1: Initial document search
            logger.info(f"Researcher: Starting search for '{search_query}'")
            search_results = await self.search_service.search(
                query=search_query,
                limit=request.max_results,
                offset=0,
                user=user,
                db=db
            )

            findings = search_results.get("results", [])

            # Step 2: Enhance with knowledge graph
            entities = []
            relationships = []
            graph_context = {}

            if request.use_graph and findings:
                logger.info("Researcher: Enhancing with knowledge graph")
                enhanced = await self.graph_rag_service.enhance_search_with_graph(
                    query=search_query,
                    initial_results=findings,
                    db=db,
                    top_k_entities=15,
                    expansion_depth=2
                )

                findings = enhanced.get("results", findings)
                entities = enhanced.get("related_entities", [])
                graph_context = enhanced.get("graph_context", {})

                # Extract entities from context
                if graph_context.get("core_entities"):
                    entities.extend(graph_context["core_entities"])

                if graph_context.get("relationships"):
                    relationships = graph_context["relationships"]

            # Step 3: Gather additional context
            context = await self._gather_context(
                search_query,
                findings,
                db
            )

            # Determine which LLM was used based on document confidentiality
            llm_used = "ollama" if self._has_confidential_documents(findings) else "gemini"

            # Step 4: Identify gaps
            gaps = await self._identify_information_gaps(
                search_query,
                findings,
                context
            )

            # Step 5: Generate follow-up queries
            next_queries = await self._suggest_followup_queries(
                search_query,
                findings,
                gaps
            )

            # Step 6: Prepare sources
            sources = self._prepare_sources(findings)

            # Calculate confidence
            confidence = self._calculate_research_confidence(
                findings,
                entities,
                gaps
            )

            return ResearchResult(
                query=request.query,
                findings=findings[:request.max_results],
                entities=entities[:20],
                relationships=relationships,
                context=context,
                sources=sources,
                confidence=confidence,
                gaps=gaps,
                next_queries=next_queries[:5],
                llm_used=llm_used
            )

        except Exception as e:
            logger.error("Research error: " + str(e))
            error_msg = "Research error: " + str(e)
            return ResearchResult(
                query=request.query,
                findings=[],
                entities=[],
                relationships=[],
                context={},
                sources=[],
                confidence=0.0,
                gaps=[error_msg],
                next_queries=[],
                llm_used="error"
            )

    async def _gather_context(
        self,
        query: str,
        findings: List[Dict[str, Any]],
        db
    ) -> Dict[str, Any]:
        """Gather additional context around findings"""
        context = {
            "related_topics": [],
            "temporal_spread": None,
            "document_types": defaultdict(int),
            "key_themes": []
        }

        if not findings:
            return context

        # Analyze document types
        for finding in findings:
            doc_type = finding.get("metadata", {}).get("document_type", "unknown")
            context["document_types"][doc_type] += 1

        # Extract key themes using Gemini
        try:
            themes = await self._extract_themes(query, findings)
            context["key_themes"] = themes
        except Exception as e:
            logger.warning(f"Could not extract themes: {e}")

        # Find related topics
        try:
            related = await self._find_related_topics(query, findings, db)
            context["related_topics"] = related
        except Exception as e:
            logger.warning(f"Could not find related topics: {e}")

        return context

    async def _extract_themes(
        self,
        query: str,
        findings: List[Dict[str, Any]]
    ) -> List[str]:
        """Extract key themes from search results"""
        system_prompt = """Analyze the search results and extract 3-5 key themes.
Return as a JSON array of theme strings."""

        # Build summary of findings
        findings_summary = "\n".join([
            f"- {f.get('filename', 'Unknown')}: {f.get('content', '')[:200]}"
            for f in findings[:10]
        ])

        user_prompt = f"""Query: {query}

Findings:
{findings_summary}

Extract the key themes:"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        try:
            llm_service, _ = self._get_llm_service(findings)
            response = []
            async for chunk in llm_service.chat_completion(
                messages=messages,
                stream=False,
                temperature=0.5,
                max_tokens=512
            ):
                if chunk and not chunk.startswith("Error:") and not chunk.startswith("__USAGE__"):
                    response.append(chunk)

            import json
            result = json.loads("".join(response).strip())
            if isinstance(result, list):
                return result[:5]

        except Exception as e:
            logger.warning(f"Theme extraction error: {e}")

        return []

    async def _find_related_topics(
        self,
        query: str,
        findings: List[Dict[str, Any]],
        db
    ) -> List[str]:
        """Find topics related to the query"""
        related = []

        # Extract entities from findings
        entity_names = set()
        for finding in findings:
            entities = finding.get("entities", [])
            for entity in entities:
                if entity.get("name"):
                    entity_names.add(entity["name"])

        # Use top entities as related topics
        related = list(entity_names)[:10]

        return related

    async def _identify_information_gaps(
        self,
        query: str,
        findings: List[Dict[str, Any]],
        context: Dict[str, Any]
    ) -> List[str]:
        """Identify gaps in the research"""
        gaps = []

        if len(findings) < 5:
            gaps.append("Limited number of sources found")

        # Check for temporal gaps
        if context.get("temporal_spread"):
            # Could analyze for temporal gaps
            pass

        # Check for missing entity types
        found_types = set(e.get("type") for e in context.get("entities", []))
        expected_types = {"person", "organization", "location"}

        missing = expected_types - found_types
        if missing:
            gaps.append(f"No information found for: {', '.join(missing)}")

        return gaps

    async def _suggest_followup_queries(
        self,
        original_query: str,
        findings: List[Dict[str, Any]],
        gaps: List[str]
    ) -> List[str]:
        """Suggest follow-up queries based on research"""
        system_prompt = """Based on the original query and research findings,
suggest 3-5 follow-up queries that would help explore the topic deeper.

Return as a JSON array of query strings."""

        findings_summary = f"Found {len(findings)} relevant documents."
        gaps_summary = f"Gaps: {', '.join(gaps)}" if gaps else "No major gaps identified."

        user_prompt = f"""Original query: {original_query}

{findings_summary}
{gaps_summary}

Suggest follow-up queries to deepen the research:"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        try:
            llm_service, _ = self._get_llm_service(findings)
            response = []
            async for chunk in llm_service.chat_completion(
                messages=messages,
                stream=False,
                temperature=0.7,
                max_tokens=512
            ):
                if chunk and not chunk.startswith("Error:") and not chunk.startswith("__USAGE__"):
                    response.append(chunk)

            import json
            result = json.loads("".join(response).strip())
            if isinstance(result, list):
                return result

        except Exception as e:
            logger.warning(f"Follow-up query generation error: {e}")

        # Fallback suggestions
        return [
            f"What are the key details about {original_query}?",
            f"How has {original_query} changed over time?",
            f"What are related topics to {original_query}?"
        ]

    def _prepare_sources(self, findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Prepare source citations"""
        sources = []
        seen = set()

        for finding in findings:
            doc_id = finding.get("document_id")
            if doc_id and doc_id not in seen:
                seen.add(doc_id)
                sources.append({
                    "document_id": doc_id,
                    "filename": finding.get("filename", "Unknown"),
                    "score": finding.get("score", 0),
                    "metadata": finding.get("metadata", {})
                })

        return sources

    def _calculate_research_confidence(
        self,
        findings: List[Dict[str, Any]],
        entities: List[Dict[str, Any]],
        gaps: List[str]
    ) -> float:
        """Calculate confidence in research results"""
        confidence = 0.5

        # More findings = higher confidence
        confidence += min(0.3, len(findings) * 0.02)

        # More entities = higher confidence
        confidence += min(0.15, len(entities) * 0.01)

        # Fewer gaps = higher confidence
        confidence -= min(0.2, len(gaps) * 0.05)

        return max(0.0, min(1.0, confidence))

    async def explore_entity_connections(
        self,
        entity_name: str,
        db,
        max_depth: int = 3
    ) -> Dict[str, Any]:
        """
        Explore connections around a specific entity

        Args:
            entity_name: Name of entity to explore
            db: Database session
            max_depth: How many levels to explore

        Returns:
            Connected entities and relationships
        """
        try:
            # knowledge_graph_service not needed, using graph_rag_service

            # Get entity neighborhood
            neighborhood = await self.graph_rag_service.get_entity_neighborhood(
                entity_name=entity_name,
                db=db,
                radius=max_depth
            )

            if "error" in neighborhood:
                return neighborhood

            # Get detailed information about connected entities
            node_details = []
            for node_id, node_data in neighborhood.get("nodes", {}).items():
                node_details.append({
                    "id": node_id,
                    "name": node_data.get("name"),
                    "type": node_data.get("type")
                })

            return {
                "center_entity": entity_name,
                "connected_entities": node_details,
                "relationships": neighborhood.get("edges", []),
                "total_connections": len(node_details)
            }

        except Exception as e:
            logger.error(f"Entity exploration error: {e}")
            return {"error": str(e)}


# Global researcher agent instance
researcher_agent = ResearcherAgent()
