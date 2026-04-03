import logging
import uuid

from sqlalchemy import func, select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.note import Note, NoteBucket
from app.models.tag import Tag, TagType, TargetType
from app.models.user import User, UserRole

logger = logging.getLogger(__name__)


class NoteService:
    async def create_note(
        self, db: AsyncSession, user: User, title: str, tags: list[dict],
        content: str | None = None,
        bucket: str = "public",
    ) -> Note:
        note = Note(
            id=uuid.uuid4(),
            user_id=user.id,
            title=title,
            content=content,
            bucket=NoteBucket(bucket),
        )
        db.add(note)
        await db.flush()

        for tag_data in tags:
            tag = Tag(
                id=uuid.uuid4(),
                tag_name=tag_data["tag_name"].lower().strip(),
                tag_type=TagType(tag_data.get("tag_type", "custom")),
                target_type=TargetType.NOTE,
                target_id=note.id,
                auto_generated=False,
            )
            db.add(tag)

        await db.commit()
        await db.refresh(note)
        return note

    async def get_note(self, db: AsyncSession, note_id: uuid.UUID, user: User) -> Note | None:
        query = select(Note).where(Note.id == note_id)
        query = self._apply_access_filter(query, user)
        result = await db.execute(query)
        return result.scalar_one_or_none()

    async def list_notes(
        self, db: AsyncSession, user: User, page: int = 1, page_size: int = 50,
        tag: str | None = None,
    ) -> tuple[list[Note], int]:
        query = select(Note)
        query = self._apply_access_filter(query, user)

        if tag:
            tag_subq = select(Tag.target_id).where(
                Tag.target_type == TargetType.NOTE,
                func.lower(Tag.tag_name) == tag.lower(),
            )
            query = query.where(Note.id.in_(tag_subq))

        count_query = select(func.count()).select_from(query.subquery())
        total_result = await db.execute(count_query)
        total = total_result.scalar() or 0

        query = query.order_by(Note.created_at.desc())
        query = query.offset((page - 1) * page_size).limit(page_size)
        result = await db.execute(query)
        return list(result.scalars().all()), total

    async def update_note(
        self, db: AsyncSession, note: Note, update_data: dict,
    ) -> Note:
        for key, value in update_data.items():
            if key == "tags":
                continue
            if value is not None:
                setattr(note, key, value)

        if "tags" in update_data and update_data["tags"] is not None:
            existing = await db.execute(
                select(Tag).where(
                    Tag.target_type == TargetType.NOTE,
                    Tag.target_id == note.id,
                )
            )
            for old_tag in existing.scalars().all():
                await db.delete(old_tag)
            for tag_data in update_data["tags"]:
                tag = Tag(
                    id=uuid.uuid4(),
                    tag_name=tag_data["tag_name"].lower().strip(),
                    tag_type=TagType(tag_data.get("tag_type", "custom")),
                    target_type=TargetType.NOTE,
                    target_id=note.id,
                    auto_generated=False,
                )
                db.add(tag)

        await db.commit()
        await db.refresh(note)
        return note

    async def delete_note(self, db: AsyncSession, note: Note) -> None:
        existing = await db.execute(
            select(Tag).where(
                Tag.target_type == TargetType.NOTE,
                Tag.target_id == note.id,
            )
        )
        for old_tag in existing.scalars().all():
            await db.delete(old_tag)
        await db.delete(note)
        await db.commit()

    async def search_notes(
        self, db: AsyncSession, user: User, query_str: str, page: int = 1, page_size: int = 50,
    ) -> tuple[list[Note], int]:
        query = select(Note)
        query = self._apply_access_filter(query, user)

        tag_subq = select(Tag.target_id).where(
            Tag.target_type == TargetType.NOTE,
            func.lower(Tag.tag_name).contains(query_str.lower()),
        )
        query = query.where(
            or_(
                Note.title.ilike(f"%{query_str}%"),
                Note.content.ilike(f"%{query_str}%"),
                Note.id.in_(tag_subq),
            )
        )

        count_query = select(func.count()).select_from(query.subquery())
        total_result = await db.execute(count_query)
        total = total_result.scalar() or 0

        query = query.order_by(Note.created_at.desc())
        query = query.offset((page - 1) * page_size).limit(page_size)
        result = await db.execute(query)
        return list(result.scalars().all()), total

    async def get_tags_for_note(self, db: AsyncSession, note_id: uuid.UUID) -> list[Tag]:
        result = await db.execute(
            select(Tag).where(
                Tag.target_type == TargetType.NOTE,
                Tag.target_id == note_id,
            )
        )
        return list(result.scalars().all())

    def _apply_access_filter(self, query, user: User):
        query = query.where(Note.user_id == user.id)
        if user.role == UserRole.USER:
            query = query.where(Note.bucket == NoteBucket.PUBLIC)
        return query


note_service = NoteService()
