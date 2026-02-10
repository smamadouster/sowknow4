"""
Verification Agent for Multi-Agent Search System

Verifies the accuracy, consistency, and reliability of information
found during research before it's presented to the user.
"""
import logging
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from collections import defaultdict

from app.services.gemini_service import gemini_service

logger = logging.getLogger(__name__)


@dataclass
class VerificationRequest:
    """Request for verification"""
    claim: str
    sources: List[Dict[str, Any]]
    context: Optional[str] = None


@dataclass
class VerificationResult:
    """Result of verification"""
    claim: str
    is_verified: bool
    confidence: float
    supporting_evidence: List[Dict[str, Any]]
    contradicting_evidence: List[Dict[str, Any]]
    source_count: int
    reliability_score: float
    notes: List[str]

    def __post_init__(self):
        if self.supporting_evidence is None:
            self.supporting_evidence = []
        if self.contradicting_evidence is None:
            self.contradicting_evidence = []
        if self.notes is None:
            self.notes = []


class VerificationAgent:
    """
    Agent responsible for verifying information

    The Verification Agent:
    1. Cross-checks claims against multiple sources
    2. Identifies contradictions or inconsistencies
    3. Assesses source reliability
    4. Flags uncertain or disputed information
    5. Provides confidence scores
    """

    def __init__(self):
        self.gemini_service = gemini_service

    async def verify(
        self,
        request: VerificationRequest
    ) -> VerificationResult:
        """
        Verify a claim against available sources

        Args:
            request: Verification request with claim and sources

        Returns:
            Verification result with evidence and confidence
        """
        try:
            # Step 1: Analyze the claim
            claim_analysis = await self._analyze_claim(request.claim)

            # Step 2: Check sources for support
            supporting = []
            contradicting = []
            source_reliability = []

            for source in request.sources:
                evidence = await self._check_source_for_claim(
                    request.claim,
                    source
                )

                if evidence["supports"]:
                    supporting.append(evidence)
                elif evidence["contradicts"]:
                    contradicting.append(evidence)

                source_reliability.append(evidence.get("reliability", 0.5))

            # Step 3: Calculate overall verification
            support_count = len(supporting)
            contradiction_count = len(contradicting)

            if support_count > contradiction_count:
                is_verified = True
            elif contradiction_count > support_count:
                is_verified = False
            else:
                # Equal or no evidence - inconclusive
                is_verified = None

            # Step 4: Calculate confidence
            total_sources = len(request.sources)
            if total_sources == 0:
                confidence = 0.0
            else:
                confidence = (support_count - contradiction_count) / total_sources
                confidence = max(0.0, min(1.0, (confidence + 1) / 2))

            # Step 5: Calculate reliability score
            reliability = sum(source_reliability) / len(source_reliability) if source_reliability else 0.0

            # Step 6: Generate notes
            notes = await self._generate_verification_notes(
                request.claim,
                supporting,
                contradicting,
                reliability
            )

            return VerificationResult(
                claim=request.claim,
                is_verified=is_verified,
                confidence=confidence,
                supporting_evidence=supporting,
                contradicting_evidence=contradicting,
                source_count=total_sources,
                reliability_score=reliability,
                notes=notes
            )

        except Exception as e:
            logger.error(f"Verification error: {e}")
            return VerificationResult(
                claim=request.claim,
                is_verified=None,
                confidence=0.0,
                supporting_evidence=[],
                contradicting_evidence=[],
                source_count=0,
                reliability_score=0.0,
                notes=[f"Verification error: {str(e)}"]
            )

    async def verify_batch(
        self,
        claims: List[str],
        sources: List[Dict[str, Any]]
    ) -> List[VerificationResult]:
        """Verify multiple claims in batch"""
        results = []

        for claim in claims:
            request = VerificationRequest(
                claim=claim,
                sources=sources
            )
            result = await self.verify(request)
            results.append(result)

        return results

    async def _analyze_claim(self, claim: str) -> Dict[str, Any]:
        """Analyze the structure and type of claim"""
        system_prompt = """Analyze the claim and identify its type and key components.

Return JSON:
{
  "claim_type": "factual|opinion|prediction|causal",
  "entities": ["entity1", "entity2"],
  "attributes": ["attribute1", "attribute2"],
  "certainty_language": "definite|uncertain|conditional",
  "verifiable": true/false
}"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Claim: {claim}"}
        ]

        try:
            response = []
            async for chunk in self.gemini_service.chat_completion(
                messages=messages,
                stream=False,
                temperature=0.3,
                max_tokens=512
            ):
                if chunk and not chunk.startswith("Error:") and not chunk.startswith("__USAGE__"):
                    response.append(chunk)

            import json
            result = json.loads("".join(response).strip())
            return result

        except Exception as e:
            logger.warning(f"Claim analysis error: {e}")
            return {
                "claim_type": "unknown",
                "entities": [],
                "attributes": [],
                "certainty_language": "uncertain",
                "verifiable": True
            }

    async def _check_source_for_claim(
        self,
        claim: str,
        source: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Check if a source supports or contradicts the claim"""
        system_prompt = """Analyze whether the source text supports, contradicts, or is neutral to the claim.

Return JSON:
{
  "supports": true/false,
  "contradicts": true/false,
  "relevant": true/false,
  "evidence": "relevant excerpt",
  "reliability": 0.0-1.0,
  "reasoning": "explanation"
}"""

        source_text = source.get("content", source.get("snippet", ""))[:2000]

        if not source_text:
            return {
                "supports": False,
                "contradicts": False,
                "relevant": False,
                "evidence": "",
                "reliability": 0.0,
                "reasoning": "No content available"
            }

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Claim: {claim}\n\nSource: {source_text}"}
        ]

        try:
            response = []
            async for chunk in self.gemini_service.chat_completion(
                messages=messages,
                stream=False,
                temperature=0.3,
                max_tokens=512
            ):
                if chunk and not chunk.startswith("Error:") and not chunk.startswith("__USAGE__"):
                    response.append(chunk)

            import json
            result = json.loads("".join(response).strip())

            # Add source info
            result["source_id"] = source.get("document_id")
            result["source_filename"] = source.get("filename")

            return result

        except Exception as e:
            logger.warning(f"Source check error: {e}")
            return {
                "supports": False,
                "contradicts": False,
                "relevant": False,
                "evidence": "",
                "reliability": 0.0,
                "reasoning": f"Error: {str(e)}"
            }

    async def _generate_verification_notes(
        self,
        claim: str,
        supporting: List[Dict[str, Any]],
        contradicting: List[Dict[str, Any]],
        reliability: float
    ) -> List[str]:
        """Generate human-readable verification notes"""
        notes = []

        if not supporting and not contradicting:
            notes.append("No direct evidence found to verify or contradict this claim.")
            notes.append("The claim may need further investigation.")
            return notes

        if supporting:
            notes.append(f"Supported by {len(supporting)} source(s).")

            if reliability > 0.7:
                notes.append("Sources appear reliable.")
            elif reliability > 0.4:
                notes.append("Source reliability is moderate.")
            else:
                notes.append("Source reliability is low - consider corroborating.")

        if contradicting:
            notes.append(f"Contradicted by {len(contradicting)} source(s).")
            notes.append("Review conflicting evidence for more context.")

        if len(supporting) == len(contradicting):
            notes.append("Mixed evidence found - claim may be disputed.")

        return notes

    async def detect_inconsistencies(
        self,
        sources: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Detect inconsistencies between multiple sources

        Args:
            sources: List of source documents

        Returns:
            List of detected inconsistencies
        """
        inconsistencies = []

        # Compare pairs of sources
        for i, source1 in enumerate(sources):
            for source2 in sources[i+1:]:
                # Check for conflicting information
                conflicts = await self._find_conflicts(source1, source2)
                inconsistencies.extend(conflicts)

        return inconsistencies

    async def _find_conflicts(
        self,
        source1: Dict[str, Any],
        source2: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Find conflicts between two sources"""
        system_prompt = """Identify any factual conflicts between the two source texts.

Return JSON array of conflicts:
[
  {
    "topic": "what the conflict is about",
    "source1_position": "what source1 says",
    "source2_position": "what source2 says",
    "severity": "major|minor"
  }
]"""

        text1 = source1.get("content", "")[:1500]
        text2 = source2.get("content", "")[:1500]

        if not text1 or not text2:
            return []

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Source 1:\n{text1}\n\nSource 2:\n{text2}"}
        ]

        try:
            response = []
            async for chunk in self.gemini_service.chat_completion(
                messages=messages,
                stream=False,
                temperature=0.3,
                max_tokens=1024
            ):
                if chunk and not chunk.startswith("Error:") and not chunk.startswith("__USAGE__"):
                    response.append(chunk)

            import json
            result = json.loads("".join(response).strip())

            if isinstance(result, list):
                # Add source info
                for conflict in result:
                    conflict["source1_id"] = source1.get("document_id")
                    conflict["source2_id"] = source2.get("document_id")

                return result

        except Exception as e:
            logger.warning(f"Conflict detection error: {e}")

        return []

    async def assess_source_reliability(
        self,
        source: Dict[str, Any]
    ) -> float:
        """
        Assess the reliability of a source

        Args:
            source: Source document

        Returns:
            Reliability score 0.0-1.0
        """
        score = 0.5  # Base score

        # Check for metadata indicators
        metadata = source.get("metadata", {})

        # Document type considerations
        doc_type = metadata.get("document_type", "")
        if doc_type in ["official_record", "contract", "certificate"]:
            score += 0.2
        elif doc_type in ["email", "note", "draft"]:
            score -= 0.1

        # Date recency (for some types of info)
        # This could be more sophisticated

        # Source origin
        origin = metadata.get("origin", "")
        if origin in ["official", "verified"]:
            score += 0.1

        return max(0.0, min(1.0, score))


# Global verification agent instance
verification_agent = VerificationAgent()
