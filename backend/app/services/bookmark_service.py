import logging
import uuid
from urllib.parse import urlparse

from sqlalchemy import func, select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bookmark import Bookmark, BookmarkBucket
from app.models.tag import Tag, TagType, TargetType
from app.models.user import User, UserRole

logger = logging.getLogger(__name__)


def _escape_like(value: str) -> str:
    """Escape ILIKE wildcard characters in user input."""
    return value.replace("%", r"\%").replace("_", r"\_")


class BookmarkService:
    async def create_bookmark(
        self, db: AsyncSession, user: User, url: str, tags: list[dict],
        title: str | None = None, description: str | None = None,
        bucket: str = "public",
    ) -> Bookmark:
        bookmark = Bookmark(
            id=uuid.uuid4(),
            user_id=user.id,
            url=url,
            title=title or self._extract_domain(url),
            description=description,
            bucket=BookmarkBucket(bucket),
        )
        db.add(bookmark)
        await db.flush()

        for tag_data in tags:
            tag = Tag(
                id=uuid.uuid4(),
                tag_name=tag_data["tag_name"].lower().strip(),
                tag_type=TagType(tag_data.get("tag_type", "custom")),
                target_type=TargetType.BOOKMARK,
                target_id=bookmark.id,
                auto_generated=False,
            )
            db.add(tag)

        await db.commit()
        await db.refresh(bookmark)
        return bookmark

    async def get_bookmark(self, db: AsyncSession, bookmark_id: uuid.UUID, user: User) -> Bookmark | None:
        query = select(Bookmark).where(Bookmark.id == bookmark_id)
        query = self._apply_access_filter(query, user)
        result = await db.execute(query)
        return result.scalar_one_or_none()

    async def list_bookmarks(
        self, db: AsyncSession, user: User, page: int = 1, page_size: int = 50,
        tag: str | None = None,
    ) -> tuple[list[Bookmark], int]:
        query = select(Bookmark)
        query = self._apply_access_filter(query, user)

        if tag:
            tag_subq = select(Tag.target_id).where(
                Tag.target_type == TargetType.BOOKMARK,
                func.lower(Tag.tag_name) == tag.lower(),
            )
            query = query.where(Bookmark.id.in_(tag_subq))

        count_query = select(func.count()).select_from(query.subquery())
        total_result = await db.execute(count_query)
        total = total_result.scalar() or 0

        query = query.order_by(Bookmark.created_at.desc())
        query = query.offset((page - 1) * page_size).limit(page_size)
        result = await db.execute(query)
        return list(result.scalars().all()), total

    async def update_bookmark(
        self, db: AsyncSession, bookmark: Bookmark, update_data: dict,
    ) -> Bookmark:
        for key, value in update_data.items():
            if key == "tags":
                continue
            if value is not None:
                setattr(bookmark, key, value)

        if "tags" in update_data and update_data["tags"] is not None:
            existing = await db.execute(
                select(Tag).where(
                    Tag.target_type == TargetType.BOOKMARK,
                    Tag.target_id == bookmark.id,
                )
            )
            for old_tag in existing.scalars().all():
                await db.delete(old_tag)
            for tag_data in update_data["tags"]:
                tag = Tag(
                    id=uuid.uuid4(),
                    tag_name=tag_data["tag_name"].lower().strip(),
                    tag_type=TagType(tag_data.get("tag_type", "custom")),
                    target_type=TargetType.BOOKMARK,
                    target_id=bookmark.id,
                    auto_generated=False,
                )
                db.add(tag)

        await db.commit()
        await db.refresh(bookmark)
        return bookmark

    async def delete_bookmark(self, db: AsyncSession, bookmark: Bookmark) -> None:
        existing = await db.execute(
            select(Tag).where(
                Tag.target_type == TargetType.BOOKMARK,
                Tag.target_id == bookmark.id,
            )
        )
        for old_tag in existing.scalars().all():
            await db.delete(old_tag)
        await db.delete(bookmark)
        await db.commit()

    async def search_bookmarks(
        self, db: AsyncSession, user: User, query_str: str, page: int = 1, page_size: int = 50,
    ) -> tuple[list[Bookmark], int]:
        query = select(Bookmark)
        query = self._apply_access_filter(query, user)

        tag_subq = select(Tag.target_id).where(
            Tag.target_type == TargetType.BOOKMARK,
            func.lower(Tag.tag_name).contains(query_str.lower()),
        )
        query = query.where(
            or_(
                Bookmark.title.ilike(f"%{_escape_like(query_str)}%"),
                Bookmark.description.ilike(f"%{_escape_like(query_str)}%"),
                Bookmark.url.ilike(f"%{_escape_like(query_str)}%"),
                Bookmark.id.in_(tag_subq),
            )
        )

        count_query = select(func.count()).select_from(query.subquery())
        total_result = await db.execute(count_query)
        total = total_result.scalar() or 0

        query = query.order_by(Bookmark.created_at.desc())
        query = query.offset((page - 1) * page_size).limit(page_size)
        result = await db.execute(query)
        return list(result.scalars().all()), total

    async def get_tags_for_bookmark(self, db: AsyncSession, bookmark_id: uuid.UUID) -> list[Tag]:
        result = await db.execute(
            select(Tag).where(
                Tag.target_type == TargetType.BOOKMARK,
                Tag.target_id == bookmark_id,
            )
        )
        return list(result.scalars().all())

    def _apply_access_filter(self, query, user: User):
        query = query.where(Bookmark.user_id == user.id)
        if user.role == UserRole.USER:
            query = query.where(Bookmark.bucket == BookmarkBucket.PUBLIC)
        return query

    def _extract_domain(self, url: str) -> str:
        try:
            parsed = urlparse(url)
            return parsed.netloc or url[:100]
        except Exception:
            return url[:100]


bookmark_service = BookmarkService()
