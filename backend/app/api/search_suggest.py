"""
SOWKNOW Search Suggestions — Prefix-based autocomplete

Target latency: p99 < 50ms
Scope: documents, bookmarks, notes, tags
"""

import logging

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.document import DocumentBucket
from app.models.user import User, UserRole

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/search", tags=["Search Suggestions"])

SUGGESTION_LIMIT = 5
MIN_PREFIX_LENGTH = 1


def _get_user_bucket_filter(user: User) -> list[str]:
    if user.role in (UserRole.ADMIN, UserRole.SUPERUSER):
        return [DocumentBucket.PUBLIC.value, DocumentBucket.CONFIDENTIAL.value]
    return [DocumentBucket.PUBLIC.value]


@router.get("/suggest", status_code=status.HTTP_200_OK)
async def search_suggest(
    q: str = Query(..., min_length=MIN_PREFIX_LENGTH, max_length=100),
    limit: int = Query(default=SUGGESTION_LIMIT, ge=1, le=10),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Prefix-based autocomplete across vault contents.

    1. Primary: prefix match (ILIKE 'prefix%') on titles/names — uses B-tree indexes
    2. Fallback: trigram similarity if prefix yields nothing and len >= 2
    3. Fallback: empty result set (frontend shows recent items if desired)
    """
    prefix = q.strip()
    if not prefix:
        return {"query": q, "suggestions": []}

    buckets = _get_user_bucket_filter(current_user)
    pattern = prefix + "%"

    # Primary: prefix match on titles (fast, indexed)
    sql = text("""
        WITH matches AS (
            SELECT
                id,
                COALESCE(original_filename, filename) as display_title,
                'document' as type,
                bucket
            FROM sowknow.documents
            WHERE status = 'indexed'
              AND bucket = ANY(:buckets)
              AND (
                  title ILIKE :prefix_pattern
                  OR original_filename ILIKE :prefix_pattern
                  OR filename ILIKE :prefix_pattern
              )
            UNION ALL
            SELECT
                id,
                title as display_title,
                'bookmark' as type,
                NULL as bucket
            FROM sowknow.bookmarks
            WHERE user_id = :user_id
              AND title ILIKE :prefix_pattern
            UNION ALL
            SELECT
                id,
                title as display_title,
                'note' as type,
                NULL as bucket
            FROM sowknow.notes
            WHERE user_id = :user_id
              AND title ILIKE :prefix_pattern
            UNION ALL
            SELECT DISTINCT
                target_id as id,
                tag_name as display_title,
                'tag' as type,
                NULL as bucket
            FROM sowknow.tags
            WHERE tag_name ILIKE :prefix_pattern
        )
        SELECT * FROM matches
        ORDER BY type, display_title
        LIMIT :limit
    """)

    result = await db.execute(
        sql,
        {
            "buckets": buckets,
            "user_id": str(current_user.id),
            "prefix_pattern": pattern,
            "limit": limit,
        },
    )
    rows = result.mappings().all()

    # Fallback: trigram similarity for typos (only if prefix yielded nothing and len >= 2)
    if not rows and len(prefix) >= 2:
        fuzzy_sql = text("""
            SELECT
                id,
                COALESCE(original_filename, filename) as display_title,
                'document' as type,
                bucket
            FROM sowknow.documents
            WHERE status = 'indexed'
              AND bucket = ANY(:buckets)
              AND (
                  title % :prefix
                  OR original_filename % :prefix
                  OR filename % :prefix
              )
            ORDER BY GREATEST(
                similarity(COALESCE(title, ''), :prefix),
                similarity(COALESCE(original_filename, ''), :prefix),
                similarity(COALESCE(filename, ''), :prefix)
            ) DESC
            LIMIT :limit
        """)
        result = await db.execute(
            fuzzy_sql,
            {"buckets": buckets, "prefix": prefix, "limit": limit},
        )
        rows = result.mappings().all()

    suggestions = [
        {
            "id": str(row["id"]),
            "title": row["display_title"],
            "type": row["type"],
            "bucket": row["bucket"],
        }
        for row in rows
    ]

    return {"query": q, "suggestions": suggestions}
