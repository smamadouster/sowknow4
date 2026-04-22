"""
Search feedback endpoint for relevance signals.

POST /api/v1/search/feedback
"""

import hashlib
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/search", tags=["Search Feedback"])


class FeedbackRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    document_id: UUID
    chunk_id: UUID | None = None
    feedback_type: str = Field(..., pattern="^(thumbs_up|thumbs_down|dismiss)$")


@router.post("/feedback", status_code=status.HTTP_201_CREATED)
async def submit_feedback(
    request: FeedbackRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Record user feedback on a search result.
    The query is hashed so the raw query text is not stored permanently.
    """
    query_hash = hashlib.sha256(request.query.lower().strip().encode()).hexdigest()[:32]

    try:
        await db.execute(
            text("""
                INSERT INTO sowknow.search_feedback
                    (id, user_id, query_hash, document_id, chunk_id, feedback_type)
                VALUES
                    (gen_random_uuid(), :user_id, :query_hash, :document_id, :chunk_id, :feedback_type)
            """),
            {
                "user_id": str(current_user.id),
                "query_hash": query_hash,
                "document_id": str(request.document_id),
                "chunk_id": str(request.chunk_id) if request.chunk_id else None,
                "feedback_type": request.feedback_type,
            },
        )
        await db.commit()
        return {"status": "recorded"}
    except Exception as exc:
        logger.warning("Failed to save search feedback: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save feedback",
        ) from exc


@router.get("/feedback/stats", status_code=status.HTTP_200_OK)
async def get_feedback_stats(
    document_id: UUID | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Aggregate feedback stats (admin/debug only)."""
    if document_id:
        rows = await db.execute(
            text("""
                SELECT feedback_type, COUNT(*) as cnt
                FROM sowknow.search_feedback
                WHERE document_id = :doc_id
                GROUP BY feedback_type
            """),
            {"doc_id": str(document_id)},
        )
    else:
        rows = await db.execute(
            text("""
                SELECT feedback_type, COUNT(*) as cnt
                FROM sowknow.search_feedback
                GROUP BY feedback_type
            """),
        )
    return {row[0]: row[1] for row in rows}
