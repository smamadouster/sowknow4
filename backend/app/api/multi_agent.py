"""
Multi-Agent Search API endpoints for Phase 3

Provides endpoints for the orchestrated multi-agent search system
with clarification, research, verification, and answer generation.
"""
import json
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional, List
from uuid import UUID
import logging

from app.database import get_db
from app.models.user import User
from app.models.document import Document, DocumentBucket
from app.models.audit import AuditLog, AuditAction
from app.services.agents.agent_orchestrator import (
    agent_orchestrator,
    OrchestratorRequest,
    OrchestratorState
)
from app.services.agents.clarification_agent import (
    clarification_agent,
    ClarificationRequest
)
from app.services.agents.researcher_agent import (
    researcher_agent,
    ResearchQuery
)
from app.services.agents.verification_agent import (
    verification_agent,
    VerificationRequest
)
from app.services.agents.answer_agent import (
    answer_agent,
    AnswerRequest
)
from app.api.deps import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/multi-agent", tags=["multi-agent"])


def create_audit_log(
    db: Session,
    user_id: UUID,
    action: AuditAction,
    resource_type: str,
    resource_id: Optional[str] = None,
    details: Optional[dict] = None
):
    """Helper function to create audit log entries for confidential access"""
    try:
        audit_entry = AuditLog(
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=json.dumps(details) if details else None
        )
        db.add(audit_entry)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Audit logging failed: {str(e)}")


@router.post("/search", response_model=dict)
async def multi_agent_search(
    query: str,
    context: Optional[str] = None,
    require_clarification: bool = True,
    require_verification: bool = True,
    answer_style: str = Query("comprehensive", regex="^(comprehensive|concise|conversational)$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Perform multi-agent search with full orchestration

    Coordinates clarification, research, verification, and
    answer generation for comprehensive, reliable results.
    """
    request = OrchestratorRequest(
        query=query,
        user=current_user,
        db=db,
        context=context,
        require_clarification=require_clarification,
        require_verification=require_verification,
        user_preferences={"answer_style": answer_style}
    )

    result = await agent_orchestrator.orchestrate(request)

    # AUDIT LOG: Log confidential document access in multi-agent search
    if result.llm_used == "ollama" and result.research and result.research.sources:
        confidential_sources = [
            {"source": s} for s in result.research.sources
            if isinstance(s, dict) and s.get("bucket") == "confidential"
        ]
        if confidential_sources:
            create_audit_log(
                db=db,
                user_id=current_user.id,
                action=AuditAction.CONFIDENTIAL_ACCESSED,
                resource_type="multi_agent",
                resource_id=None,
                details={
                    "query": query,
                    "llm_used": result.llm_used,
                    "confidential_source_count": len(confidential_sources),
                    "action": "multi_agent_search"
                }
            )
            logger.info(f"CONFIDENTIAL_ACCESSED: User {current_user.email} accessed confidential documents via multi-agent search")

    return {
        "query": result.query,
        "answer": result.answer,
        "state": result.state.value,
        "llm_used": result.llm_used,
        "clarification": {
            "is_clear": result.clarification.is_clear if result.clarification else True,
            "questions": result.clarification.questions if result.clarification else [],
            "assumptions": result.clarification.assumptions if result.clarification else []
        },
        "research_summary": {
            "findings_count": len(result.research.findings) if result.research else 0,
            "entities_count": len(result.research.entities) if result.research else 0,
            "sources_count": len(result.research.sources) if result.research else 0
        },
        "verification_summary": {
            "verified_count": sum(1 for v in (result.verification or []) if v.is_verified),
            "total_claims": len(result.verification or [])
        },
        "metadata": result.metadata,
        "duration_ms": result.total_duration_ms
    }


@router.get("/stream", response_model=dict)
async def multi_agent_search_stream(
    query: str,
    context: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Stream multi-agent search progress

    Returns SSE stream with progress updates.
    """
    from fastapi.responses import StreamingResponse
    import json

    async def event_generator():
        request = OrchestratorRequest(
            query=query,
            user=current_user,
            db=db,
            context=context
        )

        async for update in agent_orchestrator.stream_orchestrate(request):
            yield f"data: {json.dumps(update)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


@router.post("/clarify", response_model=dict)
async def clarify_query(
    query: str,
    context: Optional[str] = None,
    conversation_history: Optional[List[dict]] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Clarify an ambiguous query

    Analyzes the query and suggests clarifying questions
    or reasonable assumptions.
    """
    request = ClarificationRequest(
        query=query,
        context=context,
        conversation_history=conversation_history or []
    )

    result = await clarification_agent.clarify(request)

    return {
        "query": query,
        "is_clear": result.is_clear,
        "confidence": result.confidence,
        "clarified_query": result.clarified_query,
        "questions": result.questions,
        "assumptions": result.assumptions,
        "suggested_filters": result.suggested_filters,
        "reasoning": result.reasoning
    }


@router.post("/research", response_model=dict)
async def research_query(
    query: str,
    clarified_query: Optional[str] = None,
    max_results: int = Query(20, ge=5, le=50),
    use_graph: bool = True,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Conduct deep research on a query

    Performs comprehensive search across documents
    and knowledge graph.
    """
    request = ResearchQuery(
        query=query,
        clarified_query=clarified_query,
        max_results=max_results,
        use_graph=use_graph
    )

    result = await researcher_agent.research(
        request=request,
        user=current_user,
        db=db
    )

    return {
        "query": result.query,
        "findings": result.findings,
        "entities": result.entities,
        "relationships": result.relationships,
        "context": result.context,
        "sources": result.sources,
        "confidence": result.confidence,
        "gaps": result.gaps,
        "next_queries": result.next_queries
    }


@router.post("/verify", response_model=dict)
async def verify_claim(
    claim: str,
    source_ids: Optional[List[str]] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Verify a claim against available sources

    Cross-checks the claim across documents and
    assesses reliability.
    """
    # Get sources if specified, otherwise search
    sources = []
    if source_ids:
        from app.models.document import Document
        for doc_id in source_ids:
            doc = db.query(Document).get(doc_id)
            if doc:
                sources.append({
                    "document_id": str(doc.id),
                    "filename": doc.filename,
                    "content": ""  # Would need to fetch chunks
                })
    else:
        # Search for relevant sources
        from app.services.search_service import search_service
        search_results = await search_service.search(
            query=claim,
            limit=10,
            offset=0,
            user=current_user,
            db=db
        )
        sources = search_results.get("results", [])

    request = VerificationRequest(
        claim=claim,
        sources=sources
    )

    result = await verification_agent.verify(request)

    return {
        "claim": result.claim,
        "is_verified": result.is_verified,
        "confidence": result.confidence,
        "supporting_evidence": result.supporting_evidence,
        "contradicting_evidence": result.contradicting_evidence,
        "source_count": result.source_count,
        "reliability_score": result.reliability_score,
        "notes": result.notes
    }


@router.post("/answer", response_model=dict)
async def generate_answer(
    query: str,
    findings: Optional[List[dict]] = None,
    verification: Optional[List[dict]] = None,
    answer_style: str = Query("comprehensive", regex="^(comprehensive|concise|conversational)$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Generate an answer from research findings

    Synthesizes verified information into a
    clear, well-sourced answer.
    """
    # If no findings provided, do quick research
    if not findings:
        research_request = ResearchQuery(
            query=query,
            max_results=15
        )
        research_result = await researcher_agent.research(
            request=research_request,
            user=current_user,
            db=db
        )
        findings = research_result.findings

    request = AnswerRequest(
        query=query,
        research_findings=findings or [],
        verification_results=verification or [],
        answer_style=answer_style
    )

    result = await answer_agent.generate_answer(request)

    return {
        "query": result.query,
        "answer": result.answer,
        "key_points": result.key_points,
        "sources": result.sources,
        "confidence": result.confidence,
        "caveats": result.caveats,
        "followup_suggestions": result.followup_suggestions
    }


@router.get("/explore/entity/{entity_name}", response_model=dict)
async def explore_entity_connections(
    entity_name: str,
    max_depth: int = Query(2, ge=1, le=3),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Explore connections around an entity

    Uses graph traversal to find related entities
    and relationships.
    """
    result = await researcher_agent.explore_entity_connections(
        entity_name=entity_name,
        db=db,
        max_depth=max_depth
    )

    return result


@router.get("/detect/inconsistencies", response_model=dict)
async def detect_inconsistencies(
    document_ids: List[str],
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Detect inconsistencies between documents

    Analyzes multiple sources to find conflicting
    information.
    """
    from app.models.document import Document

    sources = []
    confidential_docs = []
    for doc_id in document_ids:
        doc = db.query(Document).get(doc_id)
        if doc:
            sources.append({
                "document_id": str(doc.id),
                "filename": doc.filename
            })
            # Track confidential documents for audit
            if doc.bucket == DocumentBucket.CONFIDENTIAL:
                confidential_docs.append({
                    "id": str(doc.id),
                    "filename": doc.filename
                })

    # AUDIT LOG: Log confidential document access in inconsistency detection
    if confidential_docs:
        create_audit_log(
            db=db,
            user_id=current_user.id,
            action=AuditAction.CONFIDENTIAL_ACCESSED,
            resource_type="multi_agent",
            resource_id=None,
            details={
                "confidential_document_count": len(confidential_docs),
                "confidential_documents": confidential_docs,
                "action": "detect_inconsistencies"
            }
        )
        logger.info(f"CONFIDENTIAL_ACCESSED: User {current_user.email} accessed confidential documents in inconsistency detection")

    inconsistencies = await verification_agent.detect_inconsistencies(sources)

    return {
        "document_count": len(sources),
        "inconsistencies": inconsistencies,
        "inconsistency_count": len(inconsistencies)
    }


@router.get("/improve-search", response_model=dict)
async def suggest_search_improvements(
    query: str,
    result_count: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Suggest ways to improve search results

    Analyzes query and results to provide
    actionable suggestions.
    """
    # Get sample results for analysis
    from app.services.search_service import search_service
    search_results = await search_service.search(
        query=query,
        limit=10,
        offset=0,
        user=current_user,
        db=db
    )

    suggestions = await clarification_agent.suggest_search_improvements(
        query=query,
        results=search_results.get("results", []),
        result_count=result_count
    )

    return {
        "query": query,
        "result_count": result_count,
        "suggestions": suggestions
    }


@router.get("/status", response_model=dict)
async def get_agent_system_status(
    current_user: User = Depends(get_current_user)
):
    """
    Get status of the multi-agent system

    Returns information about available agents
    and their capabilities.
    """
    return {
        "system": "Multi-Agent Search",
        "version": "1.0.0",
        "agents": [
            {
                "name": "Clarification Agent",
                "description": "Analyzes and clarifies user queries",
                "status": "active"
            },
            {
                "name": "Researcher Agent",
                "description": "Conducts deep research across documents and knowledge graph",
                "status": "active"
            },
            {
                "name": "Verification Agent",
                "description": "Verifies claims and assesses source reliability",
                "status": "active"
            },
            {
                "name": "Answer Agent",
                "description": "Synthesizes verified information into clear answers",
                "status": "active"
            }
        ],
        "capabilities": [
            "Query clarification and refinement",
            "Graph-augmented search",
            "Multi-source verification",
            "Comprehensive answer generation",
            "Entity exploration",
            "Inconsistency detection"
        ]
    }
