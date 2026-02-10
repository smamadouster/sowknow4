"""
Search API endpoints for hybrid semantic and keyword search
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional

from app.database import get_db
from app.models.user import User
from app.schemas.search import SearchRequest, SearchResponse, SearchResultChunk
from app.services.search_service import search_service

router = APIRouter(prefix="/search", tags=["search"])


@router.post("", response_model=SearchResponse)
async def search_documents(
    request: SearchRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Perform hybrid search combining semantic and keyword search

    Results are filtered based on user role:
    - Admin: All documents
    - Super User: All documents
    - User: Public documents only

    The LLM routing is determined based on whether confidential
    documents are in the results.
    """
    if not request.query or not request.query.strip():
        raise HTTPException(status_code=400, detail="Search query cannot be empty")

    try:
        # Perform hybrid search
        result = await search_service.hybrid_search(
            query=request.query,
            limit=request.limit,
            offset=request.offset,
            db=db,
            user=current_user
        )

        # Check if any confidential documents are in results
        has_confidential = any(
            r.document_bucket == "confidential" for r in result["results"]
        )

        # Determine which LLM would be used for follow-up
        llm_used = "ollama" if has_confidential else "kimi"

        # Convert results to response format
        search_results = []
        for r in result["results"]:
            search_results.append(SearchResultChunk(
                chunk_id=r.chunk_id,
                document_id=r.document_id,
                document_name=r.document_name,
                document_bucket=r.document_bucket,
                chunk_text=r.chunk_text[:500] + "..." if len(r.chunk_text) > 500 else r.chunk_text,
                chunk_index=r.chunk_index,
                page_number=r.page_number,
                relevance_score=round(r.final_score, 4),
                semantic_score=round(r.semantic_score, 4),
                keyword_score=round(r.keyword_score, 4)
            ))

        return SearchResponse(
            query=request.query,
            results=search_results,
            total=result["total"],
            llm_used=llm_used
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search error: {str(e)}")


@router.get("/suggest")
async def search_suggestions(
    q: str = Query(..., min_length=2, max_length=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get search suggestions based on partial query

    Returns filename suggestions and document count
    """
    try:
        from app.models.document import Document, DocumentBucket

        # Build bucket filter
        if current_user.role.value == "user":
            buckets = [DocumentBucket.PUBLIC]
        else:
            buckets = [DocumentBucket.PUBLIC, DocumentBucket.CONFIDENTIAL]

        # Get filename suggestions
        suggestions = db.query(Document.filename).filter(
            Document.bucket.in_(buckets),
            Document.filename.ilike(f"%{q}%")
        ).limit(10).all()

        return {
            "query": q,
            "suggestions": [s.filename for s in suggestions]
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Suggestion error: {str(e)}")
