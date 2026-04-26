"""
Clarification Agent for Multi-Agent Search System

Clarifies ambiguous user queries by asking targeted questions
to understand intent, context, and scope.
"""

import logging
from dataclasses import dataclass
from typing import Any

from app.services.agent_identity import CLARIFICATION_IDENTITY
from app.services.minimax_service import minimax_service

logger = logging.getLogger(__name__)


@dataclass
class ClarificationRequest:
    """Request for clarification"""

    query: str
    context: str | None = None
    conversation_history: list[dict[str, str]] | None = None
    user_preferences: dict[str, Any] | None = None
    # Sources from a prior retrieval step (used for auto-detecting confidential docs)
    sources: list[dict[str, Any]] | None = None
    # Explicit override: set to True when the caller already knows confidential
    # content is involved (e.g. first-turn clarification with no sources yet)
    has_confidential: bool = False


@dataclass
class ClarificationResult:
    """Result of clarification analysis"""

    is_clear: bool
    confidence: float
    clarified_query: str | None = None
    questions: list[str] = None
    assumptions: list[str] = None
    suggested_filters: dict[str, Any] = None
    reasoning: str = ""

    def __post_init__(self):
        if self.questions is None:
            self.questions = []
        if self.assumptions is None:
            self.assumptions = []


class ClarificationAgent:
    """
    Agent responsible for clarifying user queries

    The Clarification Agent analyzes user queries to determine:
    1. If the query is clear enough to proceed
    2. What assumptions can be reasonably made
    3. What questions would help clarify intent
    4. What filters/scope should be applied
    """

    def __init__(self):
        self.minimax_service = minimax_service

    def _has_confidential_documents(self, sources: list[dict[str, Any]] | None) -> bool:
        """Check if any sources contain confidential documents."""
        if not sources:
            return False
        return any(s.get("document_bucket") == "confidential" for s in sources)

    def _get_llm_service(self, request: "ClarificationRequest"):
        """Select LLM – always MiniMax."""
        return self.minimax_service

    async def clarify(self, request: ClarificationRequest) -> ClarificationResult:
        """
        Analyze and potentially clarify a user query.

        Args:
            request: Clarification request with query, optional sources, and
                     optional has_confidential flag.

        Returns:
            Clarification result with questions and assumptions.
        """
        llm_service = self._get_llm_service(request)

        # Build the messages for the LLM
        system_prompt = CLARIFICATION_IDENTITY + """

## Task
Analyze user queries to determine if they are clear enough to proceed.

Return a JSON object with:
{
  "is_clear": true/false,
  "confidence": 0.0-1.0,
  "clarified_query": "improved version of query if needed",
  "questions": ["question1", "question2"],
  "assumptions": ["assumption1", "assumption2"],
  "suggested_filters": {"key": "value"},
  "reasoning": "explanation of your analysis"
}"""

        user_prompt = f"Query: {request.query}"
        if request.context:
            user_prompt += f"\nContext: {request.context}"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            response_parts = []
            async for chunk in llm_service.chat_completion(
                messages=messages, stream=False, temperature=0.3, max_tokens=1024
            ):
                if chunk and not chunk.startswith("Error:") and not chunk.startswith("__USAGE__"):
                    response_parts.append(chunk)

            response_text = "".join(response_parts).strip()

            # Parse JSON response
            import json

            try:
                result_data = json.loads(self._extract_json(response_text))

                return ClarificationResult(
                    is_clear=result_data.get("is_clear", True),
                    confidence=result_data.get("confidence", 0.5),
                    clarified_query=result_data.get("clarified_query"),
                    questions=result_data.get("questions", []),
                    assumptions=result_data.get("assumptions", []),
                    suggested_filters=result_data.get("suggested_filters", {}),
                    reasoning=result_data.get("reasoning", ""),
                )

            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse clarification response: {e}")

                # Fallback: basic analysis
                return self._fallback_clarification(request)

        except Exception as e:
            logger.error(f"Clarification error: {e}")
            return ClarificationResult(
                is_clear=True,
                confidence=0.5,
                clarified_query=request.query,
                reasoning="Error during clarification, proceeding with original query",
            )

    def _fallback_clarification(self, request: ClarificationRequest) -> ClarificationResult:
        """Fallback clarification using rule-based analysis"""
        query = request.query.lower()
        questions = []
        assumptions = []
        suggested_filters = {}

        # Check for temporal terms
        temporal_keywords = ["recent", "latest", "last", "past", "current", "old"]
        has_temporal = any(kw in query for kw in temporal_keywords)

        if has_temporal:
            assumptions.append("User is interested in recent information")
            suggested_filters["sort"] = "date_desc"

        # Check for entity types
        if "person" in query or "who" in query:
            suggested_filters["entity_types"] = ["person"]
            assumptions.append("Focus on people/individuals")
        elif "company" in query or "organization" in query:
            suggested_filters["entity_types"] = ["organization"]
            assumptions.append("Focus on organizations")

        # Check for document types
        if "email" in query:
            suggested_filters["document_types"] = ["email", "message"]
        elif "report" in query or "document" in query:
            suggested_filters["document_types"] = ["pdf", "docx"]

        # Determine clarity
        question_words = ["what", "how", "why", "when", "where", "who", "which"]
        has_question_word = any(qw in query.split() for qw in question_words)
        word_count = len(query.split())

        is_clear = has_question_word and word_count >= 4
        confidence = min(1.0, 0.3 + word_count * 0.1)

        if not is_clear:
            if word_count < 4:
                questions.append("Could you provide more details about what you're looking for?")
            if not has_question_word:
                questions.append("What specific question are you trying to answer?")

        return ClarificationResult(
            is_clear=is_clear,
            confidence=confidence,
            clarified_query=request.query,
            questions=questions,
            assumptions=assumptions,
            suggested_filters=suggested_filters,
            reasoning="Rule-based fallback analysis",
        )

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

        return text

    async def suggest_search_improvements(
        self, query: str, results: list[dict[str, Any]], result_count: int
    ) -> list[str]:
        """
        Suggest ways to improve the search based on results

        Args:
            query: Original search query
            results: Search results returned
            result_count: Total number of results

        Returns:
            List of improvement suggestions
        """
        suggestions = []

        if result_count == 0:
            suggestions.append("Try using different keywords or a more general query")
            suggestions.append("Check for spelling variations or synonyms")
        elif result_count < 5:
            suggestions.append("Consider broadening your search terms")
            suggestions.append("Try searching for related concepts")
        else:
            # Check result quality
            scores = [r.get("score", 0) for r in results]
            avg_score = sum(scores) / len(scores) if scores else 0

            if avg_score < 0.5:
                suggestions.append("Results have low relevance. Try rephrasing your query.")
                suggestions.append("Consider adding specific entities or dates")

        # Check query characteristics
        query_lower = query.lower()
        if len(query.split()) < 3:
            suggestions.append("Add more context to your query for better results")

        if not any(
            kw in query_lower
            for kw in [
                "what",
                "how",
                "why",
                "when",
                "where",
                "who",
                "find",
                "search",
                "look for",
            ]
        ):
            suggestions.append("Try framing your query as a question")

        return suggestions


# Global clarification agent instance
clarification_agent = ClarificationAgent()
