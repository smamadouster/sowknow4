from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models.tag import Tag

router = APIRouter(prefix="/tags", tags=["tags"])


@router.get("/suggestions")
async def get_tag_suggestions(
    q: str = Query("", min_length=0, max_length=100),
    limit: int = Query(20, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    """Return distinct tag names, optionally filtered by query. Sorted by frequency."""
    base = (
        select(
            Tag.tag_name,
            func.count(Tag.id).label("freq"),
        )
        .group_by(Tag.tag_name)
    )

    if q.strip():
        base = base.where(Tag.tag_name.ilike(f"%{q.strip()}%"))

    base = base.order_by(func.count(Tag.id).desc()).limit(limit)

    result = await db.execute(base)
    rows = result.all()

    return {
        "tags": [{"tag_name": row.tag_name, "count": row.freq} for row in rows],
    }
