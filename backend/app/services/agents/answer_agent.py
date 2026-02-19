"""
Answer Agent for Multi-Agent Search System

Synthesizes verified research into clear, accurate, and
well-sourced answers for the user.
"""
import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from app.services.gemini_service import gemini_service
from app.services.ollama_service import ollama_service

logger = logging.getLogger(__name__)


@dataclass
class AnswerRequest:
    """Request for answer generation"""
    query: str
    research_findings: List[Dict[str, Any]]
    verification_results: List[Dict[str, Any]]
    context: Optional[Dict[str, Any]] = None
    answer_style: str = "comprehensive"  # comprehensive, concise, conversational
    language: str = "en"


@dataclass
class AnswerResult:
    """Result of answer generation"""
    query: str
    answer: str
    key_points: List[str]
    sources: List[Dict[str, Any]]
    confidence: float
    caveats: List[str]
    followup_suggestions: List[str]
    llm_used: str = "unknown"

    def __post_init__(self):
        if self.key_points is None:
            self.key_points = []
        if self.caveats is None:
            self.caveats = []
        if self.followup_suggestions is None:
            self.followup_suggestions = []


class AnswerAgent:
    """
    Agent responsible for generating final answers

    The Answer Agent:
    1. Synthesizes verified research into coherent answers
    2. Structures information clearly
    3. Cites sources appropriately
    4. Includes caveats where information is uncertain
    5. Suggests follow-up questions
    """

    def __init__(self):
        self.gemini_service = gemini_service
        self.ollama_service = ollama_service

    def _has_confidential_documents(self, findings: List[Dict[str, Any]]) -> bool:
        """Check if any findings contain confidential documents"""
        if not findings:
            return False
        return any(
            finding.get("document_bucket") == "confidential"
            for finding in findings
        )

    def _get_llm_service(self, findings: List[Dict[str, Any]]):
        """Get appropriate LLM service based on document confidentiality"""
        if self._has_confidential_documents(findings):
            logger.info("Answer: Using Ollama for confidential documents")
            return self.ollama_service
        return self.gemini_service

    async def generate_answer(
        self,
        request: AnswerRequest
    ) -> AnswerResult:
        """
        Generate a comprehensive answer from research

        Args:
            request: Answer request with research and verification

        Returns:
            Structured answer with sources and confidence
        """
        # Determine which LLM to use based on document confidentiality
        all_findings = request.research_findings + request.verification_results
        self._use_ollama = self._has_confidential_documents(all_findings)
        if self._use_ollama:
            logger.info("AnswerAgent: Using Ollama for confidential documents")
        self._llm_service = self.ollama_service if self._use_ollama else self.gemini_service

        try:
            # Step 1: Analyze what type of answer is needed
            answer_type = await self._determine_answer_type(request.query)

            # Step 2: Build context for generation
            generation_context = await self._build_generation_context(
                request.research_findings,
                request.verification_results,
                request.context
            )

            # Step 3: Generate the answer
            answer = await self._generate_answer_content(
                request.query,
                generation_context,
                request.answer_style,
                request.language
            )

            # Step 4: Extract key points
            key_points = await self._extract_key_points(answer)

            # Step 5: Prepare sources
            sources = self._prepare_sources(request.research_findings)

            # Step 6: Generate caveats
            caveats = await self._generate_caveats(
                request.verification_results,
                generation_context
            )

            # Step 7: Suggest follow-up questions
            followup = await self._suggest_followup_questions(
                request.query,
                answer,
                generation_context
            )

            # Step 8: Calculate confidence
            confidence = self._calculate_answer_confidence(
                request.verification_results,
                generation_context
            )

            # Determine which LLM was used
            llm_used = "ollama" if self._use_ollama else "gemini"

            return AnswerResult(
                query=request.query,
                answer=answer,
                key_points=key_points,
                sources=sources,
                confidence=confidence,
                caveats=caveats,
                followup_suggestions=followup,
                llm_used=llm_used
            )

        except Exception as e:
            logger.error(f"Answer generation error: {e}")
            return AnswerResult(
                query=request.query,
                answer=f"I apologize, but I encountered an error while generating the answer: {str(e)}",
                key_points=[],
                sources=[],
                confidence=0.0,
                caveats=["An error occurred during answer generation"],
                followup_suggestions=[],
                llm_used="error"
            )

    async def _determine_answer_type(self, query: str) -> str:
        """Determine what type of answer the query requires"""
        system_prompt = """Classify the query type. Return one of:
- factual: Asking for facts/information
- how_to: Asking for instructions/process
- explanation: Asking for understanding/explanation
- comparison: Asking to compare things
- opinion: Asking for opinion/judgment
- timeline: Asking about time/sequence
- list: Asking for a list of items

Return just the type name."""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Query: {query}"}
        ]

        try:
            response = []
            async for chunk in self._llm_service.chat_completion(
                messages=messages,
                stream=False,
                temperature=0.3,
                max_tokens=256
            ):
                if chunk and not chunk.startswith("Error:") and not chunk.startswith("__USAGE__"):
                    response.append(chunk)

            result = "".join(response).strip().lower()
            valid_types = ["factual", "how_to", "explanation", "comparison", "opinion", "timeline", "list"]
            for vt in valid_types:
                if vt in result:
                    return vt

        except Exception as e:
            logger.warning(f"Answer type detection error: {e}")

        return "factual"  # Default

    async def _build_generation_context(
        self,
        findings: List[Dict[str, Any]],
        verification: List[Dict[str, Any]],
        context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Build context for answer generation"""
        gen_context = {
            "verified_claims": [],
            "unverified_claims": [],
            "contradicted_info": [],
            "high_confidence_findings": [],
            "entities": [],
            "themes": []
        }

        # Process verification results
        for v in verification:
            claim_data = {
                "claim": v.get("claim"),
                "confidence": v.get("confidence", 0.5),
                "reliability": v.get("reliability_score", 0.5)
            }

            if v.get("is_verified") is True:
                gen_context["verified_claims"].append(claim_data)
            elif v.get("is_verified") is False:
                gen_context["unverified_claims"].append(claim_data)

            if v.get("contradicting_evidence"):
                gen_context["contradicted_info"].append(claim_data)

        # Extract high-confidence findings
        for f in findings:
            if f.get("score", 0) > 0.7:
                gen_context["high_confidence_findings"].append(f)

        # Add context info
        if context:
            gen_context["entities"] = context.get("entities", [])
            gen_context["themes"] = context.get("key_themes", [])

        return gen_context

    async def _generate_answer_content(
        self,
        query: str,
        context: Dict[str, Any],
        style: str,
        language: str
    ) -> str:
        """Generate the actual answer content"""
        style_instructions = {
            "comprehensive": "Provide a detailed, thorough answer with multiple sections",
            "concise": "Provide a brief, focused answer with only essential information",
            "conversational": "Provide a friendly, conversational answer"
        }

        system_prompt = f"""You are the Answer Agent for SOWKNOW. Generate clear, accurate answers based on research.

Style: {style_instructions.get(style, style_instructions["comprehensive"])}
Language: {language}

Guidelines:
1. Start with a direct answer to the question
2. Provide supporting details and context
3. Be transparent about uncertainty
4. Use clear, structured formatting
5. Include relevant caveats where appropriate

Structure your answer with:
- A brief opening summary
- Main content with clear sections
- Concluding summary if relevant"""

        # Build research summary
        research_parts = []

        if context.get("verified_claims"):
            research_parts.append("Verified Information:")
            for claim in context["verified_claims"][:5]:
                research_parts.append(f"- {claim['claim']} (confidence: {claim['confidence']:.2f})")

        if context.get("high_confidence_findings"):
            research_parts.append("\nKey Sources:")
            for finding in context["high_confidence_findings"][:5]:
                filename = finding.get("filename", "Unknown")
                research_parts.append(f"- {filename}")

        if context.get("contradicted_info"):
            research_parts.append("\nNote: Some sources may contradict on certain points.")

        research_text = "\n".join(research_parts)

        user_prompt = f"""Question: {query}

Research Context:
{research_text}

Please provide a comprehensive answer:"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        try:
            response = []
            async for chunk in self._llm_service.chat_completion(
                messages=messages,
                stream=False,
                temperature=0.7,
                max_tokens=3072
            ):
                if chunk and not chunk.startswith("Error:") and not chunk.startswith("__USAGE__"):
                    response.append(chunk)

            return "".join(response).strip()

        except Exception as e:
            logger.error(f"Answer content generation error: {e}")
            return "I apologize, but I encountered an error while generating the answer."

    async def _extract_key_points(self, answer: str) -> List[str]:
        """Extract key points from the answer"""
        system_prompt = """Extract 3-5 key points from the answer.
Return as a JSON array of strings."""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Answer:\n{answer[:3000]}"}
        ]

        try:
            response = []
            async for chunk in self._llm_service.chat_completion(
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
                return result

        except Exception as e:
            logger.warning(f"Key point extraction error: {e}")

        # Fallback: split by sentences
        import re
        sentences = re.split(r'[.!?]+', answer)
        return [s.strip() for s in sentences if s.strip()][:5]

    def _prepare_sources(self, findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Prepare source list for answer"""
        sources = []
        seen = set()

        for finding in findings:
            doc_id = finding.get("document_id")
            if doc_id and doc_id not in seen:
                seen.add(doc_id)
                sources.append({
                    "document_id": doc_id,
                    "filename": finding.get("filename", "Unknown"),
                    "relevance": finding.get("score", 0)
                })

        return sources[:10]  # Limit to top 10

    async def _generate_caveats(
        self,
        verification: List[Dict[str, Any]],
        context: Dict[str, Any]
    ) -> List[str]:
        """Generate appropriate caveats"""
        caveats = []

        # Check for unverified claims
        unverified_count = len([v for v in verification if v.get("is_verified") is False])
        if unverified_count > 0:
            caveats.append(f"{unverified_count} claim(s) could not be fully verified")

        # Check for contradictions
        if context.get("contradicted_info"):
            caveats.append("Some sources may contain conflicting information")

        # Check reliability
        avg_reliability = 0.0
        if verification:
            avg_reliability = sum(v.get("reliability_score", 0.5) for v in verification) / len(verification)
            if avg_reliability < 0.5:
                caveats.append("Source reliability is moderate - verify important details")

        return caveats if caveats else ["Information based on available sources"]

    async def _suggest_followup_questions(
        self,
        query: str,
        answer: str,
        context: Dict[str, Any]
    ) -> List[str]:
        """Suggest relevant follow-up questions"""
        system_prompt = """Based on the original question and answer, suggest 3-5 relevant follow-up questions.
Return as a JSON array of question strings."""

        user_prompt = f"""Original question: {query}

Answer summary: {answer[:500]}

Suggest follow-up questions:"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        try:
            response = []
            async for chunk in self._llm_service.chat_completion(
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
            logger.warning(f"Follow-up question generation error: {e}")

        # Fallback suggestions
        return [
            "Can you provide more details about this?",
            "What are the main sources for this information?",
            "How has this changed over time?"
        ]

    def _calculate_answer_confidence(
        self,
        verification: List[Dict[str, Any]],
        context: Dict[str, Any]
    ) -> float:
        """Calculate overall confidence in the answer"""
        if not verification:
            return 0.5

        # Average verification confidence
        avg_confidence = sum(v.get("confidence", 0.5) for v in verification) / len(verification)

        # Adjust for reliability
        avg_reliability = sum(v.get("reliability_score", 0.5) for v in verification) / len(verification)

        # Combine
        confidence = (avg_confidence * 0.6) + (avg_reliability * 0.4)

        # Penalty for contradictions
        if context.get("contradicted_info"):
            confidence *= 0.8

        return max(0.0, min(1.0, confidence))


# Global answer agent instance
answer_agent = AnswerAgent()
