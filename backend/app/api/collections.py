"""
Collections API endpoints for Smart Collections feature

Provides endpoints for creating, managing, and querying Smart Collections.
"""

import json
import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.audit import AuditAction, AuditLog
from app.models.collection import (
    Collection,
    CollectionItem,
    CollectionType,
    CollectionVisibility,
)
from app.models.user import User
from app.schemas.collection import (
    CollectionChatCreate,
    CollectionChatResponse,
    CollectionCreate,
    CollectionDetailResponse,
    CollectionExportResponse,
    CollectionItemCreate,
    CollectionItemResponse,
    CollectionItemUpdate,
    CollectionListResponse,
    CollectionPreviewRequest,
    CollectionPreviewResponse,
    CollectionRefreshRequest,
    CollectionResponse,
    CollectionStatsResponse,
    CollectionUpdate,
    ExportFormat,
    ParsedIntentResponse,
)
from app.services.collection_chat_service import collection_chat_service
from app.services.collection_service import collection_service

router = APIRouter(prefix="/collections", tags=["collections"])
logger = logging.getLogger(__name__)


async def create_audit_log(
    db: AsyncSession,
    user_id: UUID,
    action: AuditAction,
    resource_type: str,
    resource_id: str | None = None,
    details: dict | None = None,
) -> None:
    """Helper function to create audit log entries for confidential access"""
    try:
        audit_entry = AuditLog(
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=json.dumps(details) if details else None,
        )
        db.add(audit_entry)
        await db.commit()
    except Exception as e:
        await db.rollback()
        import logging

        logger = logging.getLogger(__name__)
        logger.error(f"Audit logging failed: {str(e)}")


@router.post("", response_model=CollectionResponse, status_code=status.HTTP_201_CREATED)
async def create_collection(
    collection_data: CollectionCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CollectionResponse:
    """
    Create a new Smart Collection from natural language query

    The query is parsed to extract keywords, date ranges, entities, and
    document types. Documents are gathered based on the parsed intent,
    and an AI summary is generated.
    """
    try:
        collection = await collection_service.create_collection(
            collection_data=collection_data, user=current_user, db=db
        )
        return collection
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to create collection: {str(e)}"
        )


@router.post("/preview", response_model=CollectionPreviewResponse)
async def preview_collection(
    request: CollectionPreviewRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CollectionPreviewResponse:
    """
    Preview a collection without saving it

    Returns the parsed intent, matching documents, and AI summary
    without persisting the collection.
    """
    try:
        preview = await collection_service.preview_collection(query=request.query, user=current_user, db=db)

        # Convert to response format
        return CollectionPreviewResponse(
            intent=ParsedIntentResponse(**preview["intent"].to_dict()),
            documents=preview["documents"],
            estimated_count=preview["estimated_count"],
            ai_summary=preview["ai_summary"],
            suggested_name=preview["suggested_name"],
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to preview collection: {str(e)}"
        )


@router.get("", response_model=CollectionListResponse)
async def list_collections(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    visibility: CollectionVisibility | None = None,
    collection_type: CollectionType | None = None,
    pinned_only: bool = False,
    favorites_only: bool = False,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CollectionListResponse:
    """
    List user's collections with pagination and filtering

    Users can see:
    - Their own collections (all visibility levels)
    - Public collections from other users
    - Shared collections (for superusers and admins)
    """
    visibility_filter = collection_service._get_user_visibility_filter(current_user)

    stmt = select(Collection).where(
        or_(
            Collection.user_id == current_user.id,
            Collection.visibility.in_(visibility_filter),
        )
    )

    # Apply filters
    if visibility:
        stmt = stmt.where(Collection.visibility == visibility)

    if collection_type:
        stmt = stmt.where(Collection.collection_type == collection_type)

    if pinned_only:
        stmt = stmt.where(Collection.is_pinned == True)

    if favorites_only:
        stmt = stmt.where(Collection.is_favorite == True)

    # Get total count
    count_result = await db.execute(select(func.count()).select_from(stmt.subquery()))
    total = count_result.scalar_one()

    # Order: pinned first, then by created_at desc, apply pagination
    offset = (page - 1) * page_size
    result = await db.execute(
        stmt.order_by(desc(Collection.is_pinned), desc(Collection.created_at)).offset(offset).limit(page_size)
    )
    collections = result.scalars().all()

    return CollectionListResponse(collections=collections, total=total, page=page, page_size=page_size)


@router.get("/stats", response_model=CollectionStatsResponse)
async def get_collection_stats(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> CollectionStatsResponse:
    """
    Get statistics about user's collections

    Includes totals, counts by type, and recent activity.
    """
    try:
        stats = collection_service.get_collection_stats(user=current_user, db=db)
        return CollectionStatsResponse(**stats)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to get stats: {str(e)}")


@router.get("/{collection_id}", response_model=CollectionDetailResponse)
async def get_collection(
    collection_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CollectionDetailResponse:
    """
    Get collection details with items

    Returns full collection information including all documents
    in the collection with their relevance scores and notes.
    """
    visibility_filter = collection_service._get_user_visibility_filter(current_user)

    coll_result = await db.execute(
        select(Collection).where(
            and_(
                Collection.id == collection_id,
                or_(
                    Collection.user_id == current_user.id,
                    Collection.visibility.in_(visibility_filter),
                ),
            )
        )
    )
    collection = coll_result.scalar_one_or_none()

    if not collection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")

    # Get collection items with document info
    items_result = await db.execute(
        select(CollectionItem).where(CollectionItem.collection_id == collection_id).order_by(CollectionItem.order_index)
    )
    items = items_result.scalars().all()

    # Check for confidential documents and log access
    confidential_items = [item for item in items if item.document and item.document.bucket.value == "confidential"]
    if confidential_items:
        confidential_docs = [
            {"id": str(item.document.id), "filename": item.document.filename} for item in confidential_items
        ]
        await create_audit_log(
            db=db,
            user_id=current_user.id,
            action=AuditAction.CONFIDENTIAL_ACCESSED,
            resource_type="collection",
            resource_id=str(collection_id),
            details={
                "collection_name": collection.name,
                "confidential_document_count": len(confidential_docs),
                "confidential_documents": confidential_docs,
                "action": "view_collection",
            },
        )

    # Enrich items with document info
    enriched_items = []
    for item in items:
        item_dict = CollectionItemResponse.model_validate(item).model_dump()
        # Add basic document info (bucket intentionally excluded for privacy)
        if item.document:
            item_dict["document"] = {
                "id": str(item.document.id),
                "filename": item.document.filename,
                "created_at": item.document.created_at.isoformat(),
            }
        enriched_items.append(item_dict)

    return CollectionDetailResponse(
        **CollectionResponse.model_validate(collection).model_dump(),
        items=enriched_items,
    )


@router.patch("/{collection_id}", response_model=CollectionResponse)
async def update_collection(
    collection_id: UUID,
    update_data: CollectionUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Collection:
    """
    Update collection metadata

    Can update name, description, visibility, pinned status, and favorite status.
    """
    coll_result = await db.execute(
        select(Collection).where(and_(Collection.id == collection_id, Collection.user_id == current_user.id))
    )
    collection = coll_result.scalar_one_or_none()

    if not collection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")

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

    await db.commit()
    await db.refresh(collection)

    return collection


@router.delete("/{collection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_collection(
    collection_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """
    Delete a collection

    Only the collection owner can delete it.
    """
    coll_result = await db.execute(
        select(Collection).where(and_(Collection.id == collection_id, Collection.user_id == current_user.id))
    )
    collection = coll_result.scalar_one_or_none()

    if not collection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")

    await db.delete(collection)
    await db.commit()

    return None


@router.post("/{collection_id}/refresh", response_model=CollectionResponse)
async def refresh_collection(
    collection_id: UUID,
    refresh_data: CollectionRefreshRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CollectionResponse:
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
            update_summary=refresh_data.update_summary if refresh_data else True,
        )
        return collection
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to refresh collection: {str(e)}"
        )


@router.post("/{collection_id}/items", response_model=CollectionItemResponse, status_code=status.HTTP_201_CREATED)
async def add_collection_item(
    collection_id: UUID,
    item_data: CollectionItemCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CollectionItem:
    """
    Manually add a document to a collection

    Allows manual curation of collections beyond AI-generated results.
    """
    # Verify collection ownership
    coll_result = await db.execute(
        select(Collection).where(and_(Collection.id == collection_id, Collection.user_id == current_user.id))
    )
    collection = coll_result.scalar_one_or_none()

    if not collection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")

    # Check if item already exists
    exist_result = await db.execute(
        select(CollectionItem).where(
            and_(
                CollectionItem.collection_id == collection_id,
                CollectionItem.document_id == item_data.document_id,
            )
        )
    )
    existing = exist_result.scalar_one_or_none()

    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Document already in collection")

    # Get current max order
    max_result = await db.execute(
        select(CollectionItem.order_index)
        .where(CollectionItem.collection_id == collection_id)
        .order_by(CollectionItem.order_index.desc())
        .limit(1)
    )
    max_order = max_result.scalar_one_or_none()

    order_index = (max_order + 1) if max_order is not None else collection.document_count

    # Create item
    item = CollectionItem(
        collection_id=collection_id,
        document_id=item_data.document_id,
        relevance_score=item_data.relevance_score,
        notes=item_data.notes,
        is_highlighted=item_data.is_highlighted,
        order_index=order_index,
        added_by=current_user.email,
        added_reason="Manual addition",
    )

    db.add(item)

    # Update collection count
    collection.document_count += 1

    await db.commit()
    await db.refresh(item)

    return item


@router.patch("/{collection_id}/items/{item_id}", response_model=CollectionItemResponse)
async def update_collection_item(
    collection_id: UUID,
    item_id: UUID,
    update_data: CollectionItemUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CollectionItem:
    """
    Update collection item metadata

    Can update relevance score, notes, highlight status, and order.
    """
    # Verify collection ownership
    coll_result = await db.execute(
        select(Collection).where(and_(Collection.id == collection_id, Collection.user_id == current_user.id))
    )
    collection = coll_result.scalar_one_or_none()

    if not collection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")

    # Get item
    item_result = await db.execute(
        select(CollectionItem).where(
            and_(
                CollectionItem.id == item_id,
                CollectionItem.collection_id == collection_id,
            )
        )
    )
    item = item_result.scalar_one_or_none()

    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")

    # Update fields
    if update_data.relevance_score is not None:
        item.relevance_score = update_data.relevance_score
    if update_data.notes is not None:
        item.notes = update_data.notes
    if update_data.is_highlighted is not None:
        item.is_highlighted = update_data.is_highlighted
    if update_data.order_index is not None:
        item.order_index = update_data.order_index

    await db.commit()
    await db.refresh(item)

    return item


@router.delete("/{collection_id}/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_collection_item(
    collection_id: UUID,
    item_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """
    Remove a document from a collection
    """
    # Verify collection ownership
    coll_result = await db.execute(
        select(Collection).where(and_(Collection.id == collection_id, Collection.user_id == current_user.id))
    )
    collection = coll_result.scalar_one_or_none()

    if not collection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")

    # Get item
    item_result = await db.execute(
        select(CollectionItem).where(
            and_(
                CollectionItem.id == item_id,
                CollectionItem.collection_id == collection_id,
            )
        )
    )
    item = item_result.scalar_one_or_none()

    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")

    await db.delete(item)

    # Update collection count
    collection.document_count = max(0, collection.document_count - 1)

    await db.commit()

    return None


@router.post("/{collection_id}/pin", response_model=CollectionResponse)
async def pin_collection(
    collection_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Collection:
    """Toggle collection pinned status"""
    coll_result = await db.execute(
        select(Collection).where(and_(Collection.id == collection_id, Collection.user_id == current_user.id))
    )
    collection = coll_result.scalar_one_or_none()

    if not collection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")

    collection.is_pinned = not collection.is_pinned
    await db.commit()
    await db.refresh(collection)

    return collection


@router.post("/{collection_id}/favorite", response_model=CollectionResponse)
async def favorite_collection(
    collection_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Collection:
    """Toggle collection favorite status"""
    coll_result = await db.execute(
        select(Collection).where(and_(Collection.id == collection_id, Collection.user_id == current_user.id))
    )
    collection = coll_result.scalar_one_or_none()

    if not collection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")

    collection.is_favorite = not collection.is_favorite
    await db.commit()
    await db.refresh(collection)

    return collection


@router.post("/{collection_id}/chat", response_model=CollectionChatResponse)
async def chat_with_collection(
    collection_id: UUID,
    chat_data: CollectionChatCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CollectionChatResponse:
    """
    Send a message to a collection-scoped chat

    The chat is scoped to documents in the collection and uses
    context caching for cost optimization on recurring queries.
    """
    # Verify user has access to collection
    visibility_filter = collection_service._get_user_visibility_filter(current_user)

    coll_result = await db.execute(
        select(Collection).where(
            and_(
                Collection.id == collection_id,
                or_(
                    Collection.user_id == current_user.id,
                    Collection.visibility.in_(visibility_filter),
                ),
            )
        )
    )
    collection = coll_result.scalar_one_or_none()

    if not collection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")

    try:
        response = await collection_chat_service.chat_with_collection(
            collection_id=collection_id,
            message=chat_data.message,
            user=current_user,
            db=db,
            session_name=chat_data.session_name,
        )
        return CollectionChatResponse(**response)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Chat error: {str(e)}")


@router.get("/{collection_id}/export", response_model=None)
async def export_collection(
    collection_id: UUID,
    format: str = Query("json", pattern="^(pdf|json)$", description="Export format: pdf or json"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Export a collection in PDF or JSON format.

    PDF returns a binary file download (StreamingResponse with Content-Disposition: attachment).
    JSON returns a structured JSON response.

    RBAC: Users cannot export collections containing confidential documents.
    Only Admin and Super User roles can export collections with confidential docs.

    Args:
        collection_id: UUID of the collection to export
        format: Export format - 'pdf' or 'json' (default: json)
        current_user: Authenticated user
        db: Database session

    Returns:
        StreamingResponse (PDF) or CollectionExportResponse (JSON)

    Raises:
        403: If user lacks permission to export collection with confidential docs
        404: If collection not found
    """
    import io
    from datetime import datetime

    from fastapi.responses import StreamingResponse

    visibility_filter = collection_service._get_user_visibility_filter(current_user)

    coll_result = await db.execute(
        select(Collection).where(
            and_(
                Collection.id == collection_id,
                or_(
                    Collection.user_id == current_user.id,
                    Collection.visibility.in_(visibility_filter),
                ),
            )
        )
    )
    collection = coll_result.scalar_one_or_none()

    if not collection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")

    items_result = await db.execute(
        select(CollectionItem).where(CollectionItem.collection_id == collection_id).order_by(CollectionItem.order_index)
    )
    items = items_result.scalars().all()

    confidential_items = [item for item in items if item.document and item.document.bucket.value == "confidential"]

    if confidential_items:
        if current_user.role.value not in ["admin", "superuser"]:
            logger.warning(
                f"SECURITY: User {current_user.email} (role: {current_user.role.value}) "
                f"attempted to export collection {collection_id} containing confidential documents"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: Cannot export collection containing confidential documents",
            )

        await create_audit_log(
            db=db,
            user_id=current_user.id,
            action=AuditAction.CONFIDENTIAL_ACCESSED,
            resource_type="collection_export",
            resource_id=str(collection_id),
            details={
                "collection_name": collection.name,
                "format": format,
                "confidential_document_count": len(confidential_items),
                "action": "export_collection",
            },
        )

    # Build document data — bucket label omitted for regular users (privacy)
    show_bucket = current_user.role.value in ["admin", "superuser"]
    documents_data = []
    for item in items:
        if item.document:
            doc_entry = {
                "id": str(item.document.id),
                "filename": item.document.filename,
                "relevance_score": item.relevance_score,
                "excerpt": item.added_reason or "",
                "notes": item.notes,
                "is_highlighted": item.is_highlighted,
                "created_at": item.document.created_at.isoformat(),
            }
            if show_bucket:
                doc_entry["bucket"] = item.document.bucket.value
            documents_data.append(doc_entry)

    generated_at = datetime.utcnow()

    # Extract themes from ai_keywords (used in both PDF and JSON exports)
    themes: list = []
    if collection.ai_keywords:
        kw = collection.ai_keywords
        if isinstance(kw, list):
            themes = [str(k) for k in kw if k]
        elif isinstance(kw, str):
            themes = [t.strip() for t in kw.split(",") if t.strip()]

    if format == "pdf":
        try:
            from reportlab.lib import colors
            from reportlab.lib.pagesizes import letter
            from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
            from reportlab.lib.units import inch
            from reportlab.pdfgen import canvas as rl_canvas  # noqa: F401
            from reportlab.platypus import (
                HRFlowable,
                Paragraph,
                SimpleDocTemplate,
                Spacer,
                Table,
                TableStyle,
            )
        except ImportError:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="PDF generation library not installed. Please install reportlab.",
            )

        buffer = io.BytesIO()

        # Page number + SOWKNOW branding footer callback
        def _add_footer(canv, doc):
            canv.saveState()
            canv.setFont("Helvetica", 8)
            canv.setFillColor(colors.HexColor("#6B7280"))
            page_width = letter[0]
            footer_y = 0.3 * inch
            canv.drawString(0.75 * inch, footer_y, "SOWKNOW — Multi-Generational Legacy Knowledge System")
            canv.drawRightString(
                page_width - 0.75 * inch,
                footer_y,
                f"Page {doc.page}",
            )
            canv.restoreState()

        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            topMargin=0.75 * inch,
            bottomMargin=0.75 * inch,
            leftMargin=0.75 * inch,
            rightMargin=0.75 * inch,
        )
        styles = getSampleStyleSheet()

        brand_blue = colors.HexColor("#1E40AF")
        brand_grey = colors.HexColor("#6B7280")

        title_style = ParagraphStyle(
            "SowknowTitle",
            parent=styles["Heading1"],
            fontSize=20,
            textColor=brand_blue,
            spaceAfter=6,
            spaceBefore=0,
        )
        subtitle_style = ParagraphStyle(
            "SowknowSubtitle",
            parent=styles["Normal"],
            fontSize=10,
            textColor=brand_grey,
            spaceAfter=4,
        )
        heading_style = ParagraphStyle(
            "SowknowHeading",
            parent=styles["Heading2"],
            fontSize=13,
            textColor=brand_blue,
            spaceBefore=12,
            spaceAfter=6,
        )
        normal_style = styles["Normal"]
        small_style = ParagraphStyle(
            "SowknowSmall",
            parent=styles["Normal"],
            fontSize=9,
            textColor=brand_grey,
        )

        story = []

        # Header
        story.append(Paragraph(f"Collection: {collection.name}", title_style))
        story.append(
            Paragraph(
                f"Exported by {current_user.email} &nbsp;·&nbsp; "
                f"Generated {generated_at.strftime('%Y-%m-%d %H:%M UTC')}",
                subtitle_style,
            )
        )
        story.append(HRFlowable(width="100%", thickness=1, color=brand_blue, spaceAfter=10))

        # Metadata block
        story.append(
            Paragraph(
                f"<b>Query:</b> {collection.query or '—'}",
                normal_style,
            )
        )
        story.append(
            Paragraph(
                f"<b>Created:</b> {collection.created_at.strftime('%Y-%m-%d %H:%M')} &nbsp;·&nbsp; "
                f"<b>Documents:</b> {len(documents_data)}",
                normal_style,
            )
        )
        story.append(Spacer(1, 0.15 * inch))

        # AI Summary
        if collection.ai_summary:
            story.append(Paragraph("AI Summary", heading_style))
            story.append(Paragraph(collection.ai_summary, normal_style))
            story.append(Spacer(1, 0.1 * inch))

        if themes:
            story.append(Paragraph("Identified Themes", heading_style))
            themes_text = " &nbsp;·&nbsp; ".join(themes)
            story.append(Paragraph(themes_text, normal_style))
            story.append(Spacer(1, 0.1 * inch))

        # Documents table
        if documents_data:
            story.append(Paragraph("Documents", heading_style))

            table_data = [["#", "Filename", "Score", "Excerpt / Notes"]]
            for idx, doc_item in enumerate(documents_data, 1):
                excerpt = doc_item.get("excerpt") or doc_item.get("notes") or "—"
                if len(excerpt) > 80:
                    excerpt = excerpt[:77] + "..."
                filename = doc_item["filename"]
                if len(filename) > 45:
                    filename = filename[:42] + "..."
                score = doc_item["relevance_score"]
                score_str = f"{score}%" if score is not None else "—"
                table_data.append([str(idx), filename, score_str, excerpt])

            col_widths = [0.35 * inch, 2.8 * inch, 0.65 * inch, 3.0 * inch]
            table = Table(table_data, colWidths=col_widths)
            table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), brand_blue),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("FONTSIZE", (0, 0), (-1, 0), 9),
                        ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
                        ("TOPPADDING", (0, 0), (-1, 0), 8),
                        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                        ("ALIGN", (2, 1), (2, -1), "CENTER"),
                        ("FONTSIZE", (0, 1), (-1, -1), 8),
                        ("TOPPADDING", (0, 1), (-1, -1), 5),
                        ("BOTTOMPADDING", (0, 1), (-1, -1), 5),
                        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F3F4F6")]),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D1D5DB")),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ]
                )
            )
            story.append(table)

        doc.build(story, onFirstPage=_add_footer, onLaterPages=_add_footer)
        buffer.seek(0)

        # Safe filename for Content-Disposition
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in collection.name)
        filename = f"sowknow_collection_{safe_name}_{generated_at.strftime('%Y%m%d')}.pdf"

        return StreamingResponse(
            buffer,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "X-Collection-Id": str(collection_id),
                "X-Document-Count": str(len(documents_data)),
            },
        )

    else:
        json_content = {
            "collection": {
                "id": str(collection.id),
                "name": collection.name,
                "description": collection.description,
                "query": collection.query,
                "ai_summary": collection.ai_summary,
                "themes": themes,
                "created_at": collection.created_at.isoformat(),
                "updated_at": collection.updated_at.isoformat(),
            },
            "documents": documents_data,
            "export_metadata": {
                "generated_at": generated_at.isoformat(),
                "exported_by": current_user.email,
                "document_count": len(documents_data),
            },
        }

        return CollectionExportResponse(
            collection_id=collection_id,
            collection_name=collection.name,
            format=ExportFormat.JSON,
            content=json.dumps(json_content, indent=2),
            generated_at=generated_at,
            document_count=len(documents_data),
        )


@router.get("/{collection_id}/chat/sessions")
async def get_collection_chat_sessions(
    collection_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get all chat sessions for a collection"""
    from app.models.collection import CollectionChatSession

    sessions_result = await db.execute(
        select(CollectionChatSession)
        .where(CollectionChatSession.collection_id == collection_id)
        .order_by(CollectionChatSession.created_at.desc())
    )
    sessions = sessions_result.scalars().all()

    return {
        "sessions": [
            {
                "id": str(s.id),
                "session_name": s.session_name,
                "message_count": s.message_count,
                "llm_used": s.llm_used,
                "created_at": s.created_at.isoformat(),
            }
            for s in sessions
        ]
    }
