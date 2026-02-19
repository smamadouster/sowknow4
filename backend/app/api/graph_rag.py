"""
Graph-RAG API endpoints for Phase 3

Provides endpoints for graph-augmented retrieval, synthesis,
temporal reasoning, and progressive revelation.
"""
import json
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional, List
from uuid import UUID
import logging

from app.database import get_db
from app.models.user import User
from app.models.document import DocumentBucket
from app.models.audit import AuditLog, AuditAction
from app.services.graph_rag_service import graph_rag_service
from app.services.synthesis_service import (
    synthesis_service,
    SynthesisRequest
)
from app.services.temporal_reasoning_service import temporal_reasoning_service
from app.services.progressive_revelation_service import (
    progressive_revelation_service,
    RevelationLayer
)
from app.api.deps import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/graph-rag", tags=["graph-rag"])


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
async def graph_augmented_search(
    query: str,
    document_ids: List[str] = Query([]),
    top_k: int = Query(10, ge=1, le=50),
    expansion_depth: int = Query(2, ge=1, le=3),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Perform graph-augmented search

    Enhances semantic search with knowledge graph information,
    entity relationships, and expanded context.
    """
    from app.services.search_service import search_service

    # First perform initial search
    initial_results = await search_service.search(
        query=query,
        limit=top_k,
        offset=0,
        user=current_user,
        db=db
    )

    # Enhance with graph
    enhanced = await graph_rag_service.enhance_search_with_graph(
        query=query,
        initial_results=initial_results.get("results", []),
        db=db,
        top_k_entities=10,
        expansion_depth=expansion_depth
    )

    return enhanced


@router.post("/answer", response_model=dict)
async def graph_aware_answer(
    query: str,
    document_ids: List[str] = Query([]),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Generate an answer using graph-aware context

    Uses knowledge graph information to provide more
    comprehensive and contextually relevant answers.
    """
    from app.services.search_service import search_service

    # Get search results
    search_results = await search_service.search(
        query=query,
        limit=10,
        offset=0,
        user=current_user,
        db=db
    )

    # Enhance with graph
    enhanced = await graph_rag_service.enhance_search_with_graph(
        query=query,
        initial_results=search_results.get("results", []),
        db=db
    )

    # Generate answer
    answer_stream = await graph_rag_service.generate_graph_aware_answer(
        query=query,
        enhanced_results=enhanced,
        db=db,
        stream=False
    )

    return {
        "query": query,
        "answer": answer_stream,
        "graph_context": enhanced.get("graph_context"),
        "sources": enhanced.get("results", [])[:5]
    }


@router.get("/paths/{source}/{target}", response_model=dict)
async def find_entity_paths(
    source: str,
    target: str,
    max_length: int = Query(4, ge=1, le=6),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Find paths between two entities in the knowledge graph

    Returns multiple paths with relationship details.
    """
    paths = await graph_rag_service.find_entity_paths(
        source_entity_name=source,
        target_entity_name=target,
        db=db,
        max_path_length=max_length
    )

    return {
        "source": source,
        "target": target,
        "paths": paths,
        "path_count": len(paths)
    }


@router.get("/neighborhood/{entity_name}", response_model=dict)
async def get_entity_neighborhood(
    entity_name: str,
    radius: int = Query(2, ge=1, le=3),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get the neighborhood around an entity

    Returns all entities and relationships within
    the specified radius.
    """
    neighborhood = await graph_rag_service.get_entity_neighborhood(
        entity_name=entity_name,
        db=db,
        radius=radius
    )

    return neighborhood


@router.post("/synthesize", response_model=dict)
async def synthesize_documents(
    topic: str,
    document_ids: List[str],
    synthesis_type: str = Query("comprehensive", regex="^(comprehensive|brief|analytical|timeline)$"),
    style: str = Query("informative", regex="^(informative|professional|creative|casual)$"),
    language: str = Query("en", regex="^(en|fr)$"),
    max_length: int = Query(2000, ge=500, le=5000),
    include_timeline: bool = True,
    include_entities: bool = True,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Synthesize information from multiple documents

    Uses Map-Reduce pattern with Gemini Flash to create
    comprehensive summaries from multiple sources.
    """
    from app.models.document import Document

    # Check for confidential documents in the requested IDs
    documents = db.query(Document).filter(Document.id.in_(document_ids)).all()
    confidential_docs = [
        {"id": str(doc.id), "filename": doc.filename}
        for doc in documents
        if doc.bucket == DocumentBucket.CONFIDENTIAL
    ]

    # AUDIT LOG: Log confidential document access in synthesis
    if confidential_docs:
        create_audit_log(
            db=db,
            user_id=current_user.id,
            action=AuditAction.CONFIDENTIAL_ACCESSED,
            resource_type="synthesis",
            resource_id=None,
            details={
                "topic": topic,
                "confidential_document_count": len(confidential_docs),
                "confidential_documents": confidential_docs,
                "action": "synthesize_documents"
            }
        )
        logger.info(f"CONFIDENTIAL_ACCESSED: User {current_user.email} accessed confidential documents in synthesis")

    request = SynthesisRequest(
        topic=topic,
        document_ids=document_ids,
        synthesis_type=synthesis_type,
        style=style,
        language=language,
        max_length=max_length,
        include_timeline=include_timeline,
        include_entities=include_entities
    )

    result = await synthesis_service.synthesize(
        request=request,
        db=db
    )

    return {
        "topic": result.topic,
        "synthesis": result.synthesis,
        "key_points": result.key_points,
        "sources": result.sources,
        "entities": result.entities,
        "timeline": result.timeline,
        "confidence": result.confidence,
        "generated_at": result.generated_at.isoformat()
    }


@router.get("/temporal/event/{event_id}/reasoning", response_model=dict)
async def reason_about_event(
    event_id: UUID,
    time_window_days: int = Query(365, ge=1, le=3650),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Perform temporal reasoning on an event

    Analyzes before/after relationships, causal inferences,
    and entity temporal context.
    """
    reasoning = await temporal_reasoning_service.reason_about_temporal_relationships(
        event_id=str(event_id),
        db=db,
        time_window_days=time_window_days
    )

    return reasoning


@router.get("/temporal/evolution/{entity_name}", response_model=dict)
async def analyze_entity_evolution(
    entity_name: str,
    time_months: int = Query(12, ge=1, le=120),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Analyze how an entity evolves over time

    Returns evolution stages, trends, and timeline.
    """
    evolution = await temporal_reasoning_service.analyze_evolution(
        entity_name=entity_name,
        db=db,
        time_months=time_months
    )

    return evolution


@router.get("/temporal/patterns", response_model=dict)
async def find_temporal_patterns(
    min_occurrences: int = Query(3, ge=2, le=10),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Find recurring temporal patterns in the knowledge graph

    Returns seasonal patterns, event sequences, and
    entity co-occurrences.
    """
    patterns = await temporal_reasoning_service.find_temporal_patterns(
        db=db,
        min_occurrences=min_occurrences
    )

    return {
        "patterns": patterns,
        "pattern_count": len(patterns)
    }


@router.get("/reveal/entity/{entity_id}", response_model=dict)
async def reveal_entity(
    entity_id: UUID,
    layer: str = Query("surface", regex="^(surface|context|detailed|comprehensive)$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Reveal entity information at specified layer

    Progressive disclosure based on user role and
    requested detail level.
    """
    entity_info = await progressive_revelation_service.reveal_entity_info(
        entity_id=str(entity_id),
        user=current_user,
        layer=layer,
        db=db
    )

    return entity_info


@router.get("/family/{focus_person}/context", response_model=dict)
async def get_family_context(
    focus_person: str,
    depth: int = Query(2, ge=1, le=3),
    include_timeline: bool = True,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Generate family context and narrative

    Returns family members, relationships, key events,
    and a generated narrative.
    """
    family_context = await progressive_revelation_service.generate_family_context(
        focus_person=focus_person,
        db=db,
        depth=depth,
        include_timeline=include_timeline
    )

    return {
        "focus_person": focus_person,
        "family_members": family_context.family_members,
        "relationships": family_context.relationships,
        "key_events": family_context.key_events,
        "narrative": family_context.family_narrative
    }


@router.post("/search/progressive", response_model=dict)
async def progressive_search(
    query: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Search with progressive revelation based on user role

    Returns results filtered according to user's access level.
    """
    from app.services.search_service import search_service

    # Get raw search results
    raw_results = await search_service.search(
        query=query,
        limit=50,
        offset=0,
        user=current_user,
        db=db
    )

    # Apply progressive disclosure
    progressive_results = await progressive_revelation_service.get_progressive_search_results(
        query=query,
        user=current_user,
        results=raw_results.get("results", []),
        db=db
    )

    return progressive_results
