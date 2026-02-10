"""
Knowledge Graph API endpoints for Phase 3

Provides endpoints for entity extraction, relationship mapping, timeline
construction, and graph visualization data.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional, List
from uuid import UUID

from app.database import get_db
from app.models.user import User
from app.models.knowledge_graph import Entity, EntityRelationship, EntityType, RelationType
from app.services.entity_extraction_service import entity_extraction_service
from app.services.relationship_service import relationship_service
from app.services.timeline_service import timeline_service
from app.api.auth import get_current_user

router = APIRouter(prefix="/knowledge-graph", tags=["knowledge-graph"])


@router.post("/extract/{document_id}", response_model=dict)
async def extract_entities_from_document(
    document_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Extract entities from a document using Gemini Flash

    Analyzes the document and extracts people, organizations, locations,
    concepts, and events for the knowledge graph.
    """
    from app.models.document import Document, DocumentChunk, DocumentStatus

    # Get document
    document = db.query(Document).filter(
        Document.id == document_id
    ).first()

    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    # Get document chunks
    chunks = db.query(DocumentChunk).filter(
        DocumentChunk.document_id == document_id
    ).all()

    if not chunks:
        raise HTTPException(status_code=400, detail="Document has no extracted text")

    # Extract entities
    result = await entity_extraction_service.extract_entities_from_document(
        document=document,
        chunks=chunks,
        db=db
    )

    return result


@router.get("/entities", response_model=dict)
async def list_entities(
    entity_type: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    search: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List all entities in the knowledge graph

    Can filter by type, search by name, and paginate results.
    """
    query = db.query(Entity)

    # Apply type filter
    if entity_type:
        try:
            entity_type_enum = EntityType(entity_type)
            query = query.filter(Entity.entity_type == entity_type_enum)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid entity type: {entity_type}")

    # Apply search filter
    if search:
        query = query.filter(Entity.name.ilike(f"%{search}%"))

    # Get total count
    total = query.count()

    # Apply pagination
    offset = (page - 1) * page_size
    entities = query.offset(offset).limit(page_size).all()

    return {
        "entities": [
            {
                "id": str(e.id),
                "name": e.name,
                "type": e.entity_type.value,
                "canonical_id": e.canonical_id,
                "document_count": e.document_count,
                "relationship_count": e.relationship_count,
                "first_seen": e.first_seen_at.isoformat() if e.first_seen_at else None,
                "last_seen": e.last_seen_at.isoformat() if e.last_seen_at else None
            }
            for e in entities
        ],
        "total": total,
        "page": page,
        "page_size": page_size
    }


@router.get("/entities/{entity_id}", response_model=dict)
async def get_entity_details(
    entity_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get detailed information about a specific entity

    Includes relationships, mentions, and related documents.
    """
    entity = db.query(Entity).filter(Entity.id == entity_id).first()

    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")

    # Get relationships
    outgoing = db.query(EntityRelationship).filter(
        EntityRelationship.source_id == entity_id
    ).all()

    incoming = db.query(EntityRelationship).filter(
        EntityRelationship.target_id == entity_id
    ).all()

    # Get mentions
    from app.models.knowledge_graph import EntityMention
    mentions = db.query(EntityMention).filter(
        EntityMention.entity_id == entity_id
        ).limit(20).all()

    return {
        "entity": {
            "id": str(entity.id),
            "name": entity.name,
            "type": entity.entity_type.value,
            "canonical_id": entity.canonical_id,
            "aliases": entity.aliases,
            "attributes": entity.attributes,
            "confidence": entity.confidence_score,
            "document_count": entity.document_count,
            "relationship_count": entity.relationship_count
        },
        "relationships": {
            "outgoing": [
                {
                    "id": str(rel.id),
                    "target_id": str(rel.target_id),
                    "type": rel.relation_type.value,
                    "confidence": rel.confidence_score,
                    "document_count": rel.document_count
                }
                for rel in outgoing
            ],
            "incoming": [
                {
                    "id": str(rel.id),
                    "source_id": str(rel.source_id),
                    "type": rel.relation_type.value,
                    "confidence": rel.confidence_score,
                    "document_count": rel.document_count
                }
                for rel in incoming
            ]
        },
        "mentions": [
            {
                "id": str(m.id),
                "document_id": str(m.document_id),
                "context": m.context_text[:200] if m.context_text else None,
                "page_number": m.page_number,
                "confidence": m.confidence_score
            }
            for m in mentions
        ]
    }


@router.get("/graph", response_model=dict)
async def get_knowledge_graph(
    entity_type: Optional[str] = None,
    limit: int = Query(100, ge=10, le=500),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get knowledge graph data for visualization

    Returns nodes (entities) and edges (relationships) for graph visualization.
    """
    graph = await entity_extraction_service.get_entity_graph(
        db=db,
        entity_type=EntityType(entity_type) if entity_type else None,
        limit=limit
    )

    return graph


@router.get("/entities/{entity_name}/connections", response_model=dict)
async def get_entity_connections(
    entity_name: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get all entities connected to a given entity

    Returns a graph showing direct and indirect connections.
    """
    connections = await relationship_service.mapper.find_entity_connections(
        entity_name=entity_name,
        db=db,
        max_depth=2
    )

    return connections


@router.get("/entities/{entity_id}/neighbors", response_model=dict)
async def get_entity_neighbors(
    entity_id: UUID,
    relation_type: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get direct neighbors of an entity

    Returns entities connected by relationships, optionally filtered by type.
    """
    neighbors = await relationship_service.get_entity_neighbors(
        entity_id=str(entity_id),
        db=db,
        relation_type=RelationType(relation_type) if relation_type else None
    )

    return {"neighbors": neighbors}


@router.get("/entities/{source_name}/path/{target_name}", response_model=dict)
async def get_shortest_path(
    source_name: str,
    target_name: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Find shortest path between two entities

    Returns the sequence of entities connecting them, or null if no path exists.
    """
    path = await relationship_service.get_shortest_path(
        source_entity_name=source_name,
        target_entity_name=target_name,
        db=db
    )

    if path is None:
        raise HTTPException(status_code=404, detail="No path found between entities")

    return {"path": path}


@router.get("/timeline", response_model=dict)
async def get_timeline(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get timeline events within a date range

    Returns all events sorted chronologically.
    """
    if start_date and end_date:
        from datetime import date
        try:
            start = date.fromisoformat(start_date)
            end = date.fromisoformat(end_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    else:
        # Default to last 30 days
        from datetime import date, timedelta
        end = date.today()
        start = end - timedelta(days=30)

    events = await timeline_service.get_timeline_for_period(
        start_date=start,
        end_date=end,
        db=db
    )

    return {
        "events": events,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "event_count": len(events)
    }


@router.get("/timeline/{entity_name}", response_model=dict)
async def get_entity_timeline(
    entity_name: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get timeline for a specific entity

    Returns all events involving this entity across all documents.
    """
    timeline = await timeline_service.build_entity_timeline(
        entity_name=entity_name,
        db=db
    )

    return {
        "entity": entity_name,
        "timeline": timeline,
        "event_count": len(timeline)
    }


@router.get("/insights", response_model=dict)
async def get_timeline_insights(
    limit: int = Query(10, ge=1, le=20),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get timeline insights and patterns

    Returns interesting patterns and evolution trends.
    """
    insights = await timeline_service.suggest_timeline_insights(
        db=db,
        limit=limit
    )

    return {"insights": insights}


@router.get("/clusters", response_model=dict)
async def get_entity_clusters(
    min_size: int = Query(2, ge=2, le=10),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get clusters of highly connected entities

    Useful for identifying groups (e.g., people from the same company).
    """
    clusters = await relationship_service.mapper.build_entity_clusters(
        db=db,
        min_cluster_size=min_size
    )

    return {
        "clusters": clusters,
        "cluster_count": len(clusters)
    }


@router.post("/extract-batch", response_model=dict)
async def extract_entities_batch(
    document_ids: List[UUID],
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Extract entities from multiple documents in batch

    Processes documents asynchronously and returns task IDs.
    """
    from app.models.document import Document, DocumentChunk

    results = {
        "total": len(document_ids),
        "processed": 0,
        "failed": 0,
        "results": []
    }

    for doc_id in document_ids:
        document = db.query(Document).get(doc_id)
        if not document:
            results["failed"] += 1
            continue

        chunks = db.query(DocumentChunk).filter(
            DocumentChunk.document_id == doc_id
        ).all()

        if not chunks:
            results["failed"] += 1
            continue

        try:
            extracted = await entity_extraction_service.extract_entities_from_document(
                document=document,
                chunks=chunks,
                db=db
            )
            results["processed"] += 1
            results["results"].append({
                "document_id": str(doc_id),
                "entity_count": len(extracted.get("entities", [])),
                "relationship_count": len(extracted.get("relationships", []))
            })
        except Exception as e:
            logger.error(f"Batch extraction error for {doc_id}: {e}")
            results["failed"] += 1

    return results
