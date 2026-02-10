"""
Collections API endpoints for Smart Collections feature

Provides endpoints for creating, managing, and querying Smart Collections.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional, List
from uuid import UUID

from app.database import get_db
from app.models.user import User
from app.models.collection import Collection, CollectionItem, CollectionVisibility, CollectionType
from app.schemas.collection import (
    CollectionCreate,
    CollectionUpdate,
    CollectionResponse,
    CollectionDetailResponse,
    CollectionListResponse,
    CollectionPreviewRequest,
    CollectionPreviewResponse,
    CollectionItemCreate,
    CollectionItemUpdate,
    CollectionItemResponse,
    CollectionRefreshRequest,
    CollectionStatsResponse,
    ParsedIntentResponse,
    CollectionChatResponse,
)
from app.services.collection_service import collection_service
from app.services.collection_chat_service import collection_chat_service
from app.api.auth import get_current_user

router = APIRouter(prefix="/collections", tags=["collections"])


@router.post("", response_model=CollectionResponse, status_code=201)
async def create_collection(
    collection_data: CollectionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Create a new Smart Collection from natural language query

    The query is parsed to extract keywords, date ranges, entities, and
    document types. Documents are gathered based on the parsed intent,
    and an AI summary is generated.
    """
    try:
        collection = await collection_service.create_collection(
            collection_data=collection_data,
            user=current_user,
            db=db
        )
        return collection
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create collection: {str(e)}")


@router.post("/preview", response_model=CollectionPreviewResponse)
async def preview_collection(
    request: CollectionPreviewRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Preview a collection without saving it

    Returns the parsed intent, matching documents, and AI summary
    without persisting the collection.
    """
    try:
        preview = await collection_service.preview_collection(
            query=request.query,
            user=current_user,
            db=db
        )

        # Convert to response format
        return CollectionPreviewResponse(
            intent=ParsedIntentResponse(**preview["intent"].to_dict()),
            documents=preview["documents"],
            estimated_count=preview["estimated_count"],
            ai_summary=preview["ai_summary"],
            suggested_name=preview["suggested_name"]
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to preview collection: {str(e)}")


@router.get("", response_model=CollectionListResponse)
async def list_collections(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    visibility: Optional[CollectionVisibility] = None,
    collection_type: Optional[CollectionType] = None,
    pinned_only: bool = False,
    favorites_only: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List user's collections with pagination and filtering

    Users can see:
    - Their own collections (all visibility levels)
    - Public collections from other users
    - Shared collections (for superusers and admins)
    """
    # Build base query
    from sqlalchemy import or_, and_, desc

    visibility_filter = collection_service._get_user_visibility_filter(current_user)

    query = db.query(Collection).filter(
        or_(
            Collection.user_id == current_user.id,
            Collection.visibility.in_(visibility_filter)
        )
    )

    # Apply filters
    if visibility:
        query = query.filter(Collection.visibility == visibility)

    if collection_type:
        query = query.filter(Collection.collection_type == collection_type)

    if pinned_only:
        query = query.filter(Collection.is_pinned == True)

    if favorites_only:
        query = query.filter(Collection.is_favorite == True)

    # Order: pinned first, then by created_at desc
    query = query.order_by(desc(Collection.is_pinned), desc(Collection.created_at))

    # Get total count
    total = query.count()

    # Apply pagination
    offset = (page - 1) * page_size
    collections = query.offset(offset).limit(page_size).all()

    return CollectionListResponse(
        collections=collections,
        total=total,
        page=page,
        page_size=page_size
    )


@router.get("/stats", response_model=CollectionStatsResponse)
async def get_collection_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get statistics about user's collections

    Includes totals, counts by type, and recent activity.
    """
    try:
        stats = collection_service.get_collection_stats(
            user=current_user,
            db=db
        )
        return CollectionStatsResponse(**stats)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get stats: {str(e)}")


@router.get("/{collection_id}", response_model=CollectionDetailResponse)
async def get_collection(
    collection_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get collection details with items

    Returns full collection information including all documents
    in the collection with their relevance scores and notes.
    """
    from sqlalchemy import or_

    visibility_filter = collection_service._get_user_visibility_filter(current_user)

    collection = db.query(Collection).filter(
        and_(
            Collection.id == collection_id,
            or_(
                Collection.user_id == current_user.id,
                Collection.visibility.in_(visibility_filter)
            )
        )
    ).first()

    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")

    # Get collection items with document info
    items = db.query(CollectionItem).filter(
        CollectionItem.collection_id == collection_id
    ).order_by(CollectionItem.order_index).all()

    # Enrich items with document info
    enriched_items = []
    for item in items:
        item_dict = CollectionItemResponse.model_validate(item).model_dump()
        # Add basic document info
        if item.document:
            item_dict["document"] = {
                "id": str(item.document.id),
                "filename": item.document.filename,
                "bucket": item.document.bucket.value,
                "created_at": item.document.created_at.isoformat()
            }
        enriched_items.append(item_dict)

    return CollectionDetailResponse(
        **CollectionResponse.model_validate(collection).model_dump(),
        items=enriched_items
    )


@router.patch("/{collection_id}", response_model=CollectionResponse)
async def update_collection(
    collection_id: UUID,
    update_data: CollectionUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Update collection metadata

    Can update name, description, visibility, pinned status, and favorite status.
    """
    collection = db.query(Collection).filter(
        and_(
            Collection.id == collection_id,
            Collection.user_id == current_user.id
        )
    ).first()

    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")

    # Update fields
    if update_data.name is not None:
        collection.name = update_data.name
    if update_data.description is not None:
        collection.description = update_data.description
    if update_data.visibility is not None:
        collection.visibility = update_data.visibility
    if update_data.is_pinned is not None:
        collection.is_pinned = update_data.is_pinned
    if update_data.is_favorite is not None:
        collection.is_favorite = update_data.is_favorite

    db.commit()
    db.refresh(collection)

    return collection


@router.delete("/{collection_id}", status_code=204)
async def delete_collection(
    collection_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Delete a collection

    Only the collection owner can delete it.
    """
    collection = db.query(Collection).filter(
        and_(
            Collection.id == collection_id,
            Collection.user_id == current_user.id
        )
    ).first()

    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")

    db.delete(collection)
    db.commit()

    return None


@router.post("/{collection_id}/refresh", response_model=CollectionResponse)
async def refresh_collection(
    collection_id: UUID,
    refresh_data: Optional[CollectionRefreshRequest] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Refresh collection documents

    Re-runs the original query to find new/updated documents.
    Can optionally regenerate the AI summary.
    """
    try:
        collection = await collection_service.refresh_collection(
            collection_id=collection_id,
            user=current_user,
            db=db,
            update_summary=refresh_data.update_summary if refresh_data else True
        )
        return collection
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to refresh collection: {str(e)}")


@router.post("/{collection_id}/items", response_model=CollectionItemResponse, status_code=201)
async def add_collection_item(
    collection_id: UUID,
    item_data: CollectionItemCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Manually add a document to a collection

    Allows manual curation of collections beyond AI-generated results.
    """
    # Verify collection ownership
    collection = db.query(Collection).filter(
        and_(
            Collection.id == collection_id,
            Collection.user_id == current_user.id
        )
    ).first()

    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")

    # Check if item already exists
    existing = db.query(CollectionItem).filter(
        and_(
            CollectionItem.collection_id == collection_id,
            CollectionItem.document_id == item_data.document_id
        )
    ).first()

    if existing:
        raise HTTPException(status_code=400, detail="Document already in collection")

    # Get current max order
    max_order = db.query(CollectionItem.order_index).filter(
        CollectionItem.collection_id == collection_id
    ).order_by(CollectionItem.order_index.desc()).first()

    order_index = (max_order[0] + 1) if max_order else collection.document_count

    # Create item
    item = CollectionItem(
        collection_id=collection_id,
        document_id=item_data.document_id,
        relevance_score=item_data.relevance_score,
        notes=item_data.notes,
        is_highlighted=item_data.is_highlighted,
        order_index=order_index,
        added_by=current_user.email,
        added_reason="Manual addition"
    )

    db.add(item)

    # Update collection count
    collection.document_count += 1

    db.commit()
    db.refresh(item)

    return item


@router.patch("/{collection_id}/items/{item_id}", response_model=CollectionItemResponse)
async def update_collection_item(
    collection_id: UUID,
    item_id: UUID,
    update_data: CollectionItemUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Update collection item metadata

    Can update relevance score, notes, highlight status, and order.
    """
    # Verify collection ownership
    collection = db.query(Collection).filter(
        and_(
            Collection.id == collection_id,
            Collection.user_id == current_user.id
        )
    ).first()

    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")

    # Get item
    item = db.query(CollectionItem).filter(
        and_(
            CollectionItem.id == item_id,
            CollectionItem.collection_id == collection_id
        )
    ).first()

    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    # Update fields
    if update_data.relevance_score is not None:
        item.relevance_score = update_data.relevance_score
    if update_data.notes is not None:
        item.notes = update_data.notes
    if update_data.is_highlighted is not None:
        item.is_highlighted = update_data.is_highlighted
    if update_data.order_index is not None:
        item.order_index = update_data.order_index

    db.commit()
    db.refresh(item)

    return item


@router.delete("/{collection_id}/items/{item_id}", status_code=204)
async def remove_collection_item(
    collection_id: UUID,
    item_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Remove a document from a collection
    """
    # Verify collection ownership
    collection = db.query(Collection).filter(
        and_(
            Collection.id == collection_id,
            Collection.user_id == current_user.id
        )
    ).first()

    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")

    # Get item
    item = db.query(CollectionItem).filter(
        and_(
            CollectionItem.id == item_id,
            CollectionItem.collection_id == collection_id
        )
    ).first()

    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    db.delete(item)

    # Update collection count
    collection.document_count = max(0, collection.document_count - 1)

    db.commit()

    return None


@router.post("/{collection_id}/pin", response_model=CollectionResponse)
async def pin_collection(
    collection_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Toggle collection pinned status"""
    collection = db.query(Collection).filter(
        and_(
            Collection.id == collection_id,
            Collection.user_id == current_user.id
        )
    ).first()

    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")

    collection.is_pinned = not collection.is_pinned
    db.commit()
    db.refresh(collection)

    return collection


@router.post("/{collection_id}/favorite", response_model=CollectionResponse)
async def favorite_collection(
    collection_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Toggle collection favorite status"""
    collection = db.query(Collection).filter(
        and_(
            Collection.id == collection_id,
            Collection.user_id == current_user.id
        )
    ).first()

    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")

    collection.is_favorite = not collection.is_favorite
    db.commit()
    db.refresh(collection)

    return collection


@router.post("/{collection_id}/chat", response_model=CollectionChatResponse)
async def chat_with_collection(
    collection_id: UUID,
    chat_data: CollectionChatCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Send a message to a collection-scoped chat

    The chat is scoped to documents in the collection and uses
    context caching for cost optimization on recurring queries.
    """
    from sqlalchemy import or_

    # Verify user has access to collection
    visibility_filter = collection_service._get_user_visibility_filter(current_user)

    collection = db.query(Collection).filter(
        and_(
            Collection.id == collection_id,
            or_(
                Collection.user_id == current_user.id,
                Collection.visibility.in_(visibility_filter)
            )
        )
    ).first()

    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")

    try:
        response = await collection_chat_service.chat_with_collection(
            collection_id=collection_id,
            message=chat_data.message,
            user=current_user,
            db=db,
            session_name=chat_data.session_name
        )
        return CollectionChatResponse(**response)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Chat error: {str(e)}")


@router.get("/{collection_id}/chat/sessions")
async def get_collection_chat_sessions(
    collection_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all chat sessions for a collection"""
    from app.models.collection import CollectionChatSession

    sessions = db.query(CollectionChatSession).filter(
        CollectionChatSession.collection_id == collection_id
    ).order_by(CollectionChatSession.created_at.desc()).all()

    return {
        "sessions": [
            {
                "id": str(s.id),
                "session_name": s.session_name,
                "message_count": s.message_count,
                "llm_used": s.llm_used,
                "created_at": s.created_at.isoformat()
            }
            for s in sessions
        ]
    }
