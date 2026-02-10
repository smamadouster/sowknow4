"""
Agent Orchestrator for Multi-Agent Search System

Coordinates the Clarification, Researcher, Verification, and
Answer agents to provide comprehensive, reliable answers.
"""
import logging
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from app.services.agents.clarification_agent import (
    clarification_agent,
    ClarificationRequest,
    ClarificationResult
)
from app.services.agents.researcher_agent import (
    researcher_agent,
    ResearchQuery,
    ResearchResult
)
from app.services.agents.verification_agent import (
    verification_agent,
    VerificationRequest,
    VerificationResult
)
from app.services.agents.answer_agent import (
    answer_agent,
    AnswerRequest,
    AnswerResult
)

logger = logging.getLogger(__name__)


class OrchestratorState(Enum):
    """States of the orchestration process"""
    IDLE = "idle"
    CLARIFYING = "clarifying"
    RESEARCHING = "researching"
    VERIFYING = "verifying"
    ANSWERING = "answering"
    COMPLETE = "complete"
    ERROR = "error"


@dataclass
class AgentResult:
    """Result from a single agent"""
    agent_name: str
    state: str
    result: Any = None
    error: Optional[str] = None
    duration_ms: int = 0


@dataclass
class OrchestratorRequest:
    """Request for agent orchestration"""
    query: str
    user: Any
    db: Any
    context: Optional[str] = None
    conversation_history: List[Dict[str, str]] = field(default_factory=list)
    user_preferences: Dict[str, Any] = field(default_factory=dict)
    require_clarification: bool = True
    require_verification: bool = True
    stream: bool = False
    on_progress: Optional[Callable[[str, OrchestratorState], None]] = None


@dataclass
class OrchestratorResult:
    """Final result from orchestration"""
    query: str
    answer: str
    clarification: Optional[ClarificationResult] = None
    research: Optional[ResearchResult] = None
    verification: Optional[List[VerificationResult]] = None
    agent_results: List[AgentResult] = field(default_factory=list)
    total_duration_ms: int = 0
    state: OrchestratorState = OrchestratorState.COMPLETE
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class AgentOrchestrator:
    """
    Orchestrates multi-agent search workflow

    Workflow:
    1. Clarification: Clarify ambiguous queries
    2. Research: Conduct deep search and gather information
    3. Verification: Verify claims and assess reliability
    4. Answer: Synthesize into final answer

    The orchestrator can:
    - Skip steps based on request parameters
    - Stream progress updates
    - Handle errors gracefully
    - Return partial results if needed
    """

    def __init__(self):
        self.clarification_agent = clarification_agent
        self.researcher_agent = researcher_agent
        self.verification_agent = verification_agent
        self.answer_agent = answer_agent

    async def orchestrate(
        self,
        request: OrchestratorRequest
    ) -> OrchestratorResult:
        """
        Orchestrate the full multi-agent workflow

        Args:
            request: Orchestrator request with all parameters

        Returns:
            Complete orchestration result with all agent outputs
        """
        import time
        start_time = time.time()
        agent_results = []

        try:
            # Step 1: Clarification (if enabled)
            clarification = None
            if request.require_clarification:
                self._notify_progress(request, "Clarifying query...", OrchestratorState.CLARIFYING)
                step_start = time.time()

                try:
                    clarification = await self._run_clarification(request)
                    agent_results.append(AgentResult(
                        agent_name="clarification",
                        state="complete",
                        result=clarification,
                        duration_ms=int((time.time() - step_start) * 1000)
                    ))

                    # Check if clarification is needed
                    if not clarification.is_clear and clarification.questions:
                        # Return early with questions
                        return OrchestratorResult(
                            query=request.query,
                            answer="",  # No answer yet, need clarification
                            clarification=clarification,
                            agent_results=agent_results,
                            total_duration_ms=int((time.time() - start_time) * 1000),
                            state=OrchestratorState.CLARIFYING,
                            metadata={"needs_user_input": True}
                        )

                except Exception as e:
                    logger.error(f"Clarification error: {e}")
                    agent_results.append(AgentResult(
                        agent_name="clarification",
                        state="error",
                        error=str(e),
                        duration_ms=int((time.time() - step_start) * 1000)
                    ))

            # Step 2: Research
            self._notify_progress(request, "Conducting research...", OrchestratorState.RESEARCHING)
            step_start = time.time()

            try:
                research = await self._run_research(request, clarification)
                agent_results.append(AgentResult(
                    agent_name="researcher",
                    state="complete",
                    result=research,
                    duration_ms=int((time.time() - step_start) * 1000)
                ))
            except Exception as e:
                logger.error(f"Research error: {e}")
                agent_results.append(AgentResult(
                    agent_name="researcher",
                    state="error",
                    error=str(e),
                    duration_ms=int((time.time() - step_start) * 1000)
                ))
                # Continue with partial results

            # Step 3: Verification (if enabled and we have research results)
            verification = []
            if request.require_verification and research and research.findings:
                self._notify_progress(request, "Verifying information...", OrchestratorState.VERIFYING)
                step_start = time.time()

                try:
                    verification = await self._run_verification(request, research)
                    agent_results.append(AgentResult(
                        agent_name="verification",
                        state="complete",
                        result=verification,
                        duration_ms=int((time.time() - step_start) * 1000)
                    ))
                except Exception as e:
                    logger.error(f"Verification error: {e}")
                    agent_results.append(AgentResult(
                        agent_name="verification",
                        state="error",
                        error=str(e),
                        duration_ms=int((time.time() - step_start) * 1000)
                    ))

            # Step 4: Answer Generation
            self._notify_progress(request, "Generating answer...", OrchestratorState.ANSWERING)
            step_start = time.time()

            try:
                answer = await self._run_answer_generation(request, research, verification)
                agent_results.append(AgentResult(
                    agent_name="answer",
                    state="complete",
                    result=answer,
                    duration_ms=int((time.time() - step_start) * 1000)
                ))
            except Exception as e:
                logger.error(f"Answer generation error: {e}")
                agent_results.append(AgentResult(
                    agent_name="answer",
                    state="error",
                    error=str(e),
                    duration_ms=int((time.time() - step_start) * 1000)
                ))

                # Fallback answer
                answer = AnswerResult(
                    query=request.query,
                    answer=f"I apologize, but I encountered an error while processing your request: {str(e)}",
                    key_points=[],
                    sources=[],
                    confidence=0.0,
                    caveats=["An error occurred during processing"],
                    followup_suggestions=[]
                )

            # Compile final result
            return OrchestratorResult(
                query=request.query,
                answer=answer.answer if answer else "",
                clarification=clarification,
                research=research,
                verification=verification,
                agent_results=agent_results,
                total_duration_ms=int((time.time() - start_time) * 1000),
                state=OrchestratorState.COMPLETE,
                metadata={
                    "agent_count": len(agent_results),
                    "successful_agents": sum(1 for ar in agent_results if ar.state == "complete"),
                    "answer_confidence": answer.confidence if answer else 0.0,
                    "source_count": len(answer.sources) if answer else 0
                }
            )

        except Exception as e:
            logger.error(f"Orchestration error: {e}")
            return OrchestratorResult(
                query=request.query,
                answer=f"An error occurred during processing: {str(e)}",
                agent_results=agent_results,
                total_duration_ms=int((time.time() - start_time) * 1000),
                state=OrchestratorState.ERROR,
                metadata={"error": str(e)}
            )

    async def _run_clarification(
        self,
        request: OrchestratorRequest
    ) -> ClarificationResult:
        """Run the clarification agent"""
        clarification_request = ClarificationRequest(
            query=request.query,
            context=request.context,
            conversation_history=request.conversation_history,
            user_preferences=request.user_preferences
        )
        return await self.clarification_agent.clarify(clarification_request)

    async def _run_research(
        self,
        request: OrchestratorRequest,
        clarification: Optional[ClarificationResult]
    ) -> ResearchResult:
        """Run the researcher agent"""
        # Use clarified query if available
        clarified_query = clarification.clarified_query if clarification else None

        research_request = ResearchQuery(
            query=request.query,
            clarified_query=clarified_query,
            filters=clarification.suggested_filters if clarification else {},
            max_results=20,
            use_graph=True,
            gather_context=True
        )
        return await self.researcher_agent.research(
            request=research_request,
            user=request.user,
            db=request.db
        )

    async def _run_verification(
        self,
        request: OrchestratorRequest,
        research: ResearchResult
    ) -> List[VerificationResult]:
        """Run the verification agent on key claims"""
        # Extract claims from research findings
        claims = []

        # Use top findings as claims
        for finding in research.findings[:5]:
            content = finding.get("content", "")
            if content:
                # Truncate to claim-length
                claim = content[:200] + "..." if len(content) > 200 else content
                claims.append(claim)

        # Verify claims
        verification_results = []
        for claim in claims:
            verification_request = VerificationRequest(
                claim=claim,
                sources=research.findings
            )
            result = await self.verification_agent.verify(verification_request)
            verification_results.append(result)

        return verification_results

    async def _run_answer_generation(
        self,
        request: OrchestratorRequest,
        research: Optional[ResearchResult],
        verification: List[VerificationResult]
    ) -> AnswerResult:
        """Run the answer agent"""
        answer_request = AnswerRequest(
            query=request.query,
            research_findings=research.findings if research else [],
            verification_results=verification,
            context=research.context if research else None,
            answer_style=request.user_preferences.get("answer_style", "comprehensive"),
            language=request.user_preferences.get("language", "en")
        )
        return await self.answer_agent.generate_answer(answer_request)

    def _notify_progress(
        self,
        request: OrchestratorRequest,
        message: str,
        state: OrchestratorState
    ):
        """Notify progress if callback provided"""
        if request.on_progress:
            try:
                request.on_progress(message, state)
            except Exception as e:
                logger.warning(f"Progress notification error: {e}")

    async def stream_orchestrate(
        self,
        request: OrchestratorRequest
    ):
        """
        Stream orchestration progress

        Yields updates as the workflow progresses.
        """
        import time
        start_time = time.time()

        # Clarification
        yield {
            "type": "progress",
            "stage": "clarification",
            "message": "Clarifying query...",
            "timestamp": datetime.now().isoformat()
        }

        clarification = await self._run_clarification(request)

        if not clarification.is_clear and clarification.questions:
            yield {
                "type": "clarification_needed",
                "questions": clarification.questions,
                "assumptions": clarification.assumptions,
                "timestamp": datetime.now().isoformat()
            }
            return

        yield {
            "type": "progress",
            "stage": "research",
            "message": "Conducting research...",
            "timestamp": datetime.now().isoformat()
        }

        research = await self._run_research(request, clarification)

        yield {
            "type": "research_update",
            "findings_count": len(research.findings),
            "entities_count": len(research.entities),
            "timestamp": datetime.now().isoformat()
        }

        # Verification
        if request.require_verification:
            yield {
                "type": "progress",
                "stage": "verification",
                "message": "Verifying information...",
                "timestamp": datetime.now().isoformat()
            }

            verification = await self._run_verification(request, research)

            yield {
                "type": "verification_update",
                "verified_count": sum(1 for v in verification if v.is_verified),
                "total_claims": len(verification),
                "timestamp": datetime.now().isoformat()
            }
        else:
            verification = []

        # Answer
        yield {
            "type": "progress",
            "stage": "answer",
            "message": "Generating answer...",
            "timestamp": datetime.now().isoformat()
        }

        answer = await self._run_answer_generation(request, research, verification)

        # Final result
        yield {
            "type": "complete",
            "answer": answer.answer,
            "key_points": answer.key_points,
            "sources": answer.sources,
            "confidence": answer.confidence,
            "caveats": answer.caveats,
            "followup": answer.followup_suggestions,
            "duration_ms": int((time.time() - start_time) * 1000),
            "timestamp": datetime.now().isoformat()
        }


# Global agent orchestrator instance
agent_orchestrator = AgentOrchestrator()
