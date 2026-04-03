import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.bookmark import (
    BookmarkCreate, BookmarkListResponse, BookmarkResponse, BookmarkUpdate,
)
from app.schemas.tag import TagResponse
from app.services.bookmark_service import bookmark_service

router = APIRouter(prefix="/bookmarks", tags=["bookmarks"])
logger = logging.getLogger(__name__)


@router.post("", response_model=BookmarkResponse, status_code=status.HTTP_201_CREATED)
async def create_bookmark(
    data: BookmarkCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BookmarkResponse:
    bookmark = await bookmark_service.create_bookmark(
        db=db,
        user=current_user,
        url=data.url,
        title=data.title,
        description=data.description,
        bucket=data.bucket.value,
        tags=[t.model_dump() for t in data.tags],
    )
    # Check space rules for new bookmark
    try:
        from app.services.space_service import space_service
        await space_service.check_rules_for_new_item(db, "bookmark", bookmark.id)
    except Exception as e:
        logger.warning(f"Space rule check failed for bookmark {bookmark.id}: {e}")
    tags = await bookmark_service.get_tags_for_bookmark(db, bookmark.id)
    return _to_response(bookmark, tags)


@router.get("", response_model=BookmarkListResponse)
async def list_bookmarks(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    tag: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BookmarkListResponse:
    bookmarks, total = await bookmark_service.list_bookmarks(
        db=db, user=current_user, page=page, page_size=page_size, tag=tag,
    )
    items = []
    for b in bookmarks:
        tags = await bookmark_service.get_tags_for_bookmark(db, b.id)
        items.append(_to_response(b, tags))
    return BookmarkListResponse(bookmarks=items, total=total, page=page, page_size=page_size)


@router.get("/search", response_model=BookmarkListResponse)
async def search_bookmarks(
    q: str = Query(..., min_length=1),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BookmarkListResponse:
    bookmarks, total = await bookmark_service.search_bookmarks(
        db=db, user=current_user, query_str=q, page=page, page_size=page_size,
    )
    items = []
    for b in bookmarks:
        tags = await bookmark_service.get_tags_for_bookmark(db, b.id)
        items.append(_to_response(b, tags))
    return BookmarkListResponse(bookmarks=items, total=total, page=page, page_size=page_size)


@router.get("/{bookmark_id}", response_model=BookmarkResponse)
async def get_bookmark(
    bookmark_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BookmarkResponse:
    bookmark = await bookmark_service.get_bookmark(db, bookmark_id, current_user)
    if not bookmark:
        raise HTTPException(status_code=404, detail="Bookmark not found")
    tags = await bookmark_service.get_tags_for_bookmark(db, bookmark.id)
    return _to_response(bookmark, tags)


@router.put("/{bookmark_id}", response_model=BookmarkResponse)
async def update_bookmark(
    bookmark_id: UUID,
    data: BookmarkUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BookmarkResponse:
    bookmark = await bookmark_service.get_bookmark(db, bookmark_id, current_user)
    if not bookmark:
        raise HTTPException(status_code=404, detail="Bookmark not found")
    if bookmark.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    update_dict = data.model_dump(exclude_unset=True)
    if "tags" in update_dict and update_dict["tags"] is not None:
        update_dict["tags"] = [t.model_dump() for t in data.tags]

    bookmark = await bookmark_service.update_bookmark(db, bookmark, update_dict)
    tags = await bookmark_service.get_tags_for_bookmark(db, bookmark.id)
    return _to_response(bookmark, tags)


@router.delete("/{bookmark_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_bookmark(
    bookmark_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    bookmark = await bookmark_service.get_bookmark(db, bookmark_id, current_user)
    if not bookmark:
        raise HTTPException(status_code=404, detail="Bookmark not found")
    if bookmark.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    await bookmark_service.delete_bookmark(db, bookmark)


def _to_response(bookmark, tags) -> BookmarkResponse:
    return BookmarkResponse(
        id=bookmark.id,
        user_id=bookmark.user_id,
        url=bookmark.url,
        title=bookmark.title,
        description=bookmark.description,
        favicon_url=bookmark.favicon_url,
        bucket=bookmark.bucket,
        tags=[TagResponse.model_validate(t) for t in tags],
        created_at=bookmark.created_at,
        updated_at=bookmark.updated_at,
    )
