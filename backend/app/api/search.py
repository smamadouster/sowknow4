"""
Search API endpoints for hybrid semantic and keyword search
"""

import asyncio
import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.limiter import limiter
from app.models.audit import AuditAction, AuditLog
from app.models.user import User
from app.schemas.pagination import decode_cursor, encode_cursor
from app.schemas.search import SearchRequest, SearchResponse, SearchResultChunk
from app.services.search_service import search_service

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Concurrency guardrail — cap simultaneous search operations at 5.
# Requests that arrive when all slots are taken receive HTTP 429 immediately
# (non-blocking: no request is ever queued and starved).
# ---------------------------------------------------------------------------
MAX_CONCURRENT_SEARCHES = 5
_search_semaphore = asyncio.Semaphore(MAX_CONCURRENT_SEARCHES)

# Wall-clock timeout for a single hybrid search operation (seconds).
SEARCH_TIMEOUT_SECONDS = 3.0

router = APIRouter(prefix="/search", tags=["search"])


async def create_audit_log(
    db: AsyncSession,
    user_id: uuid.UUID,
    action: AuditAction,
    resource_type: str,
    resource_id: str | None = None,
    details: dict | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> None:
    """Helper function to create audit log entries for search."""
    try:
        audit_entry = AuditLog(
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=json.dumps(details) if details else None,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        db.add(audit_entry)
        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.error(f"Audit logging failed: {str(e)}")


@router.post("", response_model=None)
@limiter.limit("30/minute")
async def search_documents(
    request: Request,
    search_request: SearchRequest,
    cursor: str | None = Query(None, description="Cursor for pagination (base64 encoded)"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Perform hybrid search combining semantic and keyword search.

    Results are filtered based on user role:
    - Admin: All documents
    - Super User: All documents
    - User: Public documents only

    The LLM routing is determined based on whether confidential
    documents are in the results.

    SECURITY: All searches require authentication via get_current_user.
    Confidential searches are logged for audit trail.

    Reliability guardrails:
    - Max {MAX_CONCURRENT_SEARCHES} simultaneous searches; returns 429 when full.
    - Hard {SEARCH_TIMEOUT_SECONDS}s timeout; returns partial results with warning.
    """
    if not search_request.query or not search_request.query.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Search query cannot be empty")

    # Cursor overrides offset when provided (T09)
    if cursor:
        try:
            cursor_data = decode_cursor(cursor)
            search_request.offset = cursor_data.get("offset", 0)
        except Exception:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid cursor")

    # -----------------------------------------------------------------------
    # Concurrency check — non-blocking.  If all slots are taken, reject with
    # 429 + Retry-After so clients can back off gracefully.
    # -----------------------------------------------------------------------
    if _search_semaphore._value == 0:
        logger.warning(
            f"Search capacity reached ({MAX_CONCURRENT_SEARCHES} concurrent). "
            f"Rejecting request from user {current_user.email}."
        )
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={
                "detail": (
                    f"Search capacity reached ({MAX_CONCURRENT_SEARCHES} concurrent "
                    "searches). Please retry in a few seconds."
                )
            },
            headers={"Retry-After": "5"},
        )

    async with _search_semaphore:
        try:
            # Perform hybrid search with built-in timeout
            result = await search_service.hybrid_search(
                query=search_request.query,
                limit=search_request.limit,
                offset=search_request.offset,
                db=db,
                user=current_user,
                timeout=SEARCH_TIMEOUT_SECONDS,
            )

            # Check if any confidential documents are in results
            has_confidential = any(r.document_bucket == "confidential" for r in result["results"])

            # AUDIT LOG: Log confidential searches for compliance
            if has_confidential:
                logger.info(
                    f"CONFIDENTIAL_SEARCH - User: {current_user.email} (ID: {current_user.id}, "
                    f"Role: {current_user.role.value}) | Query: {search_request.query[:100]} | "
                    f"Results: {len(result['results'])} items"
                )
                await create_audit_log(
                    db=db,
                    user_id=current_user.id,
                    action=AuditAction.CONFIDENTIAL_ACCESSED,
                    resource_type="search",
                    resource_id=None,
                    details={
                        "query": search_request.query[:200],
                        "result_count": len(result["results"]),
                        "action": "confidential_search",
                        "partial": result.get("partial", False),
                    },
                )

            # Determine which LLM would be used for follow-up
            llm_used = "ollama" if has_confidential else "kimi"

            # Convert results to response format
            search_results = []
            for r in result["results"]:
                search_results.append(
                    SearchResultChunk(
                        chunk_id=r.chunk_id,
                        document_id=r.document_id,
                        document_name=r.document_name,
                        document_bucket=r.document_bucket,
                        chunk_text=r.chunk_text[:500] + "..." if len(r.chunk_text) > 500 else r.chunk_text,
                        chunk_index=r.chunk_index,
                        page_number=r.page_number,
                        relevance_score=round(r.final_score, 4),
                        semantic_score=round(r.semantic_score, 4),
                        keyword_score=round(r.keyword_score, 4),
                    )
                )

            # Build next cursor when there may be more results
            next_offset = search_request.offset + search_request.limit
            next_cursor = (
                encode_cursor({"offset": next_offset}) if len(search_results) == search_request.limit else None
            )

            return SearchResponse(
                query=search_request.query,
                results=search_results,
                total=result["total"],
                llm_used=llm_used,
                partial=result.get("partial", False),
                warning=result.get("warning"),
                next_cursor=next_cursor,
            )

        except Exception as e:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Search error: {str(e)}")


@router.get("/suggest")
async def search_suggestions(
    q: str = Query(..., min_length=2, max_length=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Get search suggestions based on partial query

    Returns filename suggestions and document count filtered by user role.

    SECURITY: Requires authentication. Results respect bucket permissions.
    """
    try:
        from app.models.document import Document, DocumentBucket

        # Build bucket filter based on user role
        if current_user.role.value == "user":
            buckets = [DocumentBucket.PUBLIC]
        else:
            buckets = [DocumentBucket.PUBLIC, DocumentBucket.CONFIDENTIAL]

        # Get filename suggestions
        result = await db.execute(
            select(Document.filename).where(Document.bucket.in_(buckets), Document.filename.ilike(f"%{q}%")).limit(10)
        )
        suggestions = result.scalars().all()

        return {"query": q, "suggestions": list(suggestions)}

    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Suggestion error: {str(e)}")
