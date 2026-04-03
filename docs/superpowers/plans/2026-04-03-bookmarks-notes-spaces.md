# Bookmarks, Notes & Spaces Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add bookmarks (lightweight link saving with mandatory tags), notes (plain text with tags), and spaces (permanent curated workspaces with auto-rules) to SOWKNOW.

**Architecture:** Three new SQLAlchemy models (Bookmark, Note, Space) with SpaceItem join table and SpaceRule for auto-population. Existing DocumentTag is replaced by a generalized polymorphic Tag model. Each feature gets its own FastAPI router, service, and Next.js page. Global search is extended with type filters.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 (async), Alembic, Celery, Next.js 14, Tailwind CSS, Zustand, next-intl, PostgreSQL

**Spec:** `docs/superpowers/specs/2026-04-03-bookmarks-notes-spaces-design.md`

---

## File Map

### Backend — New Files
- `backend/app/models/bookmark.py` — Bookmark model
- `backend/app/models/note.py` — Note model
- `backend/app/models/space.py` — Space, SpaceItem, SpaceRule models
- `backend/app/models/tag.py` — Generalized Tag model (replaces DocumentTag)
- `backend/app/schemas/bookmark.py` — Bookmark Pydantic schemas
- `backend/app/schemas/note.py` — Note Pydantic schemas
- `backend/app/schemas/space.py` — Space/SpaceItem/SpaceRule Pydantic schemas
- `backend/app/schemas/tag.py` — Tag Pydantic schemas
- `backend/app/api/bookmarks.py` — Bookmarks router
- `backend/app/api/notes.py` — Notes router
- `backend/app/api/spaces.py` — Spaces router
- `backend/app/services/bookmark_service.py` — Bookmark business logic
- `backend/app/services/note_service.py` — Note business logic
- `backend/app/services/space_service.py` — Space business logic + rule engine
- `backend/app/tasks/space_tasks.py` — Celery tasks for space sync
- `backend/alembic/versions/011_add_tag_model.py` — Tag table migration
- `backend/alembic/versions/012_add_bookmarks_notes_spaces.py` — New tables migration
- `backend/alembic/versions/013_migrate_document_tags.py` — Data migration from DocumentTag to Tag

### Backend — Modified Files
- `backend/app/models/__init__.py` — Register new models
- `backend/app/main.py` — Include new routers
- `backend/app/services/auto_tagging_service.py` — Write to Tag instead of DocumentTag
- `backend/app/services/search_service.py` — Extend with type filters
- `backend/app/api/documents.py` — Update tag endpoints to use Tag model

### Frontend — New Files
- `frontend/app/[locale]/bookmarks/page.tsx` — Bookmarks page
- `frontend/app/[locale]/notes/page.tsx` — Notes page
- `frontend/app/[locale]/spaces/page.tsx` — Spaces list page
- `frontend/app/[locale]/spaces/[id]/page.tsx` — Space detail page
- `frontend/components/TagSelector.tsx` — Reusable tag selector component

### Frontend — Modified Files
- `frontend/lib/api.ts` — Add bookmark, note, space, tag API methods
- `frontend/lib/store.ts` — (no new store needed — local state per page)
- `frontend/components/Navigation.tsx` — Add 3 new nav items
- `frontend/app/messages/en.json` — English translations
- `frontend/app/messages/fr.json` — French translations
- `frontend/app/[locale]/search/page.tsx` — Add type filter chips

---

## Task 1: Generalized Tag Model

**Files:**
- Create: `backend/app/models/tag.py`
- Create: `backend/app/schemas/tag.py`
- Create: `backend/alembic/versions/011_add_tag_model.py`
- Modify: `backend/app/models/__init__.py`
- Test: `backend/tests/unit/test_tag_model.py`

- [ ] **Step 1: Write the Tag model test**

```python
# backend/tests/unit/test_tag_model.py
import enum
import pytest
from app.models.tag import Tag, TagType, TargetType


class TestTagEnums:
    def test_tag_type_values(self):
        assert TagType.TOPIC.value == "topic"
        assert TagType.ENTITY.value == "entity"
        assert TagType.PROJECT.value == "project"
        assert TagType.IMPORTANCE.value == "importance"
        assert TagType.CUSTOM.value == "custom"

    def test_target_type_values(self):
        assert TargetType.DOCUMENT.value == "document"
        assert TargetType.BOOKMARK.value == "bookmark"
        assert TargetType.NOTE.value == "note"
        assert TargetType.SPACE.value == "space"


class TestTagModel:
    def test_tag_has_required_columns(self):
        from sqlalchemy import inspect
        mapper = inspect(Tag)
        column_names = [c.key for c in mapper.column_attrs]
        required = ["id", "tag_name", "tag_type", "target_type", "target_id",
                     "auto_generated", "confidence_score", "created_at"]
        for col in required:
            assert col in column_names, f"Missing column: {col}"

    def test_tag_table_name(self):
        assert Tag.__tablename__ == "tags"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/development/src/active/sowknow4/backend && python -m pytest tests/unit/test_tag_model.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.models.tag'`

- [ ] **Step 3: Write the Tag model**

```python
# backend/app/models/tag.py
import enum
import uuid

from sqlalchemy import (
    Boolean, Column, DateTime, Enum, Index, Integer, String, func
)
from app.models.base import Base, GUIDType


class TagType(enum.StrEnum):
    TOPIC = "topic"
    ENTITY = "entity"
    PROJECT = "project"
    IMPORTANCE = "importance"
    CUSTOM = "custom"


class TargetType(enum.StrEnum):
    DOCUMENT = "document"
    BOOKMARK = "bookmark"
    NOTE = "note"
    SPACE = "space"


class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = (
        Index("ix_tags_target", "target_type", "target_id"),
        Index("ix_tags_name", "tag_name"),
        Index("ix_tags_type_name", "tag_type", "tag_name"),
        {"schema": "sowknow"},
    )

    id = Column(GUIDType(as_uuid=True), primary_key=True, default=uuid.uuid4, unique=True, nullable=False)
    tag_name = Column(String(255), nullable=False, index=True)
    tag_type = Column(
        Enum(TagType, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
        default=TagType.CUSTOM,
    )
    target_type = Column(
        Enum(TargetType, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
    )
    target_id = Column(GUIDType(as_uuid=True), nullable=False)
    auto_generated = Column(Boolean, default=False, nullable=False)
    confidence_score = Column(Integer, default=0, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
```

- [ ] **Step 4: Write Tag Pydantic schemas**

```python
# backend/app/schemas/tag.py
from datetime import datetime
from enum import StrEnum
from uuid import UUID
from pydantic import BaseModel, Field


class TagType(StrEnum):
    TOPIC = "topic"
    ENTITY = "entity"
    PROJECT = "project"
    IMPORTANCE = "importance"
    CUSTOM = "custom"


class TargetType(StrEnum):
    DOCUMENT = "document"
    BOOKMARK = "bookmark"
    NOTE = "note"
    SPACE = "space"


class TagCreate(BaseModel):
    tag_name: str = Field(..., min_length=1, max_length=255)
    tag_type: TagType = Field(default=TagType.CUSTOM)


class TagResponse(BaseModel):
    id: UUID
    tag_name: str
    tag_type: TagType
    target_type: TargetType
    target_id: UUID
    auto_generated: bool
    confidence_score: int | None
    created_at: datetime

    class Config:
        from_attributes = True


class TagListResponse(BaseModel):
    tags: list[TagResponse]
```

- [ ] **Step 5: Register Tag model in __init__.py**

Add to `backend/app/models/__init__.py`:
```python
from app.models.tag import Tag, TagType, TargetType  # noqa: F401
```

- [ ] **Step 6: Create Alembic migration for Tag table**

```python
# backend/alembic/versions/011_add_tag_model.py
"""Add generalized Tag model"""

from alembic import op
import sqlalchemy as sa

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tags",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("tag_name", sa.String(255), nullable=False),
        sa.Column("tag_type", sa.Enum("topic", "entity", "project", "importance", "custom",
                                       name="tagtype", schema="sowknow"), nullable=False),
        sa.Column("target_type", sa.Enum("document", "bookmark", "note", "space",
                                          name="targettype", schema="sowknow"), nullable=False),
        sa.Column("target_id", sa.CHAR(36), nullable=False),
        sa.Column("auto_generated", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("confidence_score", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        schema="sowknow",
    )
    op.create_index("ix_tags_target", "tags", ["target_type", "target_id"], schema="sowknow")
    op.create_index("ix_tags_name", "tags", ["tag_name"], schema="sowknow")
    op.create_index("ix_tags_type_name", "tags", ["tag_type", "tag_name"], schema="sowknow")


def downgrade() -> None:
    op.drop_table("tags", schema="sowknow")
    op.execute("DROP TYPE IF EXISTS sowknow.tagtype")
    op.execute("DROP TYPE IF EXISTS sowknow.targettype")
```

- [ ] **Step 7: Run test to verify it passes**

Run: `cd /home/development/src/active/sowknow4/backend && python -m pytest tests/unit/test_tag_model.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add backend/app/models/tag.py backend/app/schemas/tag.py backend/app/models/__init__.py backend/alembic/versions/011_add_tag_model.py backend/tests/unit/test_tag_model.py
git commit -m "feat: add generalized Tag model replacing DocumentTag"
```

---

## Task 2: Bookmark Model + Schema + API

**Files:**
- Create: `backend/app/models/bookmark.py`
- Create: `backend/app/schemas/bookmark.py`
- Create: `backend/app/services/bookmark_service.py`
- Create: `backend/app/api/bookmarks.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/unit/test_bookmark_api.py`

- [ ] **Step 1: Write the Bookmark model test**

```python
# backend/tests/unit/test_bookmark_api.py
import pytest
from app.models.bookmark import Bookmark, BookmarkBucket


class TestBookmarkModel:
    def test_bucket_enum_values(self):
        assert BookmarkBucket.PUBLIC.value == "public"
        assert BookmarkBucket.CONFIDENTIAL.value == "confidential"

    def test_bookmark_has_required_columns(self):
        from sqlalchemy import inspect
        mapper = inspect(Bookmark)
        column_names = [c.key for c in mapper.column_attrs]
        required = ["id", "user_id", "url", "title", "description",
                     "favicon_url", "bucket", "created_at", "updated_at"]
        for col in required:
            assert col in column_names, f"Missing column: {col}"

    def test_bookmark_table_name(self):
        assert Bookmark.__tablename__ == "bookmarks"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/development/src/active/sowknow4/backend && python -m pytest tests/unit/test_bookmark_api.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.models.bookmark'`

- [ ] **Step 3: Write the Bookmark model**

```python
# backend/app/models/bookmark.py
import enum
import uuid

from sqlalchemy import Column, DateTime, Enum, ForeignKey, String, Text, func
from app.models.base import Base, GUIDType


class BookmarkBucket(enum.StrEnum):
    PUBLIC = "public"
    CONFIDENTIAL = "confidential"


class Bookmark(Base):
    __tablename__ = "bookmarks"
    __table_args__ = ({"schema": "sowknow"},)

    id = Column(GUIDType(as_uuid=True), primary_key=True, default=uuid.uuid4, unique=True, nullable=False)
    user_id = Column(GUIDType(as_uuid=True), ForeignKey("sowknow.users.id", ondelete="CASCADE"), nullable=False, index=True)
    url = Column(String(2048), nullable=False)
    title = Column(String(512), nullable=False)
    description = Column(Text, nullable=True)
    favicon_url = Column(String(2048), nullable=True)
    bucket = Column(
        Enum(BookmarkBucket, values_callable=lambda obj: [e.value for e in obj]),
        default=BookmarkBucket.PUBLIC,
        nullable=False,
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
```

- [ ] **Step 4: Write Bookmark Pydantic schemas**

```python
# backend/app/schemas/bookmark.py
from datetime import datetime
from enum import StrEnum
from uuid import UUID
from pydantic import BaseModel, Field

from app.schemas.tag import TagCreate, TagResponse


class BookmarkBucket(StrEnum):
    PUBLIC = "public"
    CONFIDENTIAL = "confidential"


class BookmarkCreate(BaseModel):
    url: str = Field(..., min_length=1, max_length=2048)
    title: str | None = Field(None, max_length=512)
    description: str | None = Field(None)
    bucket: BookmarkBucket = Field(default=BookmarkBucket.PUBLIC)
    tags: list[TagCreate] = Field(..., min_length=1)


class BookmarkUpdate(BaseModel):
    title: str | None = Field(None, max_length=512)
    description: str | None = None
    bucket: BookmarkBucket | None = None
    tags: list[TagCreate] | None = None


class BookmarkResponse(BaseModel):
    id: UUID
    user_id: UUID
    url: str
    title: str
    description: str | None
    favicon_url: str | None
    bucket: BookmarkBucket
    tags: list[TagResponse] = []
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class BookmarkListResponse(BaseModel):
    bookmarks: list[BookmarkResponse]
    total: int
    page: int
    page_size: int
```

- [ ] **Step 5: Write bookmark service**

```python
# backend/app/services/bookmark_service.py
import logging
import uuid
from urllib.parse import urlparse

from sqlalchemy import func, select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bookmark import Bookmark, BookmarkBucket
from app.models.tag import Tag, TagType, TargetType
from app.models.user import User, UserRole

logger = logging.getLogger(__name__)


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
            # Delete existing tags
            existing = await db.execute(
                select(Tag).where(
                    Tag.target_type == TargetType.BOOKMARK,
                    Tag.target_id == bookmark.id,
                )
            )
            for old_tag in existing.scalars().all():
                await db.delete(old_tag)
            # Add new tags
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
        # Delete associated tags
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

        # Search in title, description, and tags
        tag_subq = select(Tag.target_id).where(
            Tag.target_type == TargetType.BOOKMARK,
            func.lower(Tag.tag_name).contains(query_str.lower()),
        )
        query = query.where(
            or_(
                Bookmark.title.ilike(f"%{query_str}%"),
                Bookmark.description.ilike(f"%{query_str}%"),
                Bookmark.url.ilike(f"%{query_str}%"),
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
```

- [ ] **Step 6: Write bookmarks API router**

```python
# backend/app/api/bookmarks.py
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
```

- [ ] **Step 7: Register Bookmark model and router**

Add to `backend/app/models/__init__.py`:
```python
from app.models.bookmark import Bookmark, BookmarkBucket  # noqa: F401
```

Add to `backend/app/main.py` (in the router inclusion section):
```python
from app.api import bookmarks
app.include_router(bookmarks.router, prefix="/api/v1")
```

- [ ] **Step 8: Run test to verify it passes**

Run: `cd /home/development/src/active/sowknow4/backend && python -m pytest tests/unit/test_bookmark_api.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add backend/app/models/bookmark.py backend/app/schemas/bookmark.py backend/app/services/bookmark_service.py backend/app/api/bookmarks.py backend/app/models/__init__.py backend/app/main.py backend/tests/unit/test_bookmark_api.py
git commit -m "feat: add Bookmark model, service, and API router"
```

---

## Task 3: Note Model + Schema + API

**Files:**
- Create: `backend/app/models/note.py`
- Create: `backend/app/schemas/note.py`
- Create: `backend/app/services/note_service.py`
- Create: `backend/app/api/notes.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/unit/test_note_api.py`

- [ ] **Step 1: Write the Note model test**

```python
# backend/tests/unit/test_note_api.py
import pytest
from app.models.note import Note, NoteBucket


class TestNoteModel:
    def test_bucket_enum_values(self):
        assert NoteBucket.PUBLIC.value == "public"
        assert NoteBucket.CONFIDENTIAL.value == "confidential"

    def test_note_has_required_columns(self):
        from sqlalchemy import inspect
        mapper = inspect(Note)
        column_names = [c.key for c in mapper.column_attrs]
        required = ["id", "user_id", "title", "content", "bucket", "created_at", "updated_at"]
        for col in required:
            assert col in column_names, f"Missing column: {col}"

    def test_note_table_name(self):
        assert Note.__tablename__ == "notes"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/development/src/active/sowknow4/backend && python -m pytest tests/unit/test_note_api.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write the Note model**

```python
# backend/app/models/note.py
import enum
import uuid

from sqlalchemy import Column, DateTime, Enum, ForeignKey, String, Text, func
from app.models.base import Base, GUIDType


class NoteBucket(enum.StrEnum):
    PUBLIC = "public"
    CONFIDENTIAL = "confidential"


class Note(Base):
    __tablename__ = "notes"
    __table_args__ = ({"schema": "sowknow"},)

    id = Column(GUIDType(as_uuid=True), primary_key=True, default=uuid.uuid4, unique=True, nullable=False)
    user_id = Column(GUIDType(as_uuid=True), ForeignKey("sowknow.users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(512), nullable=False)
    content = Column(Text, nullable=True)
    bucket = Column(
        Enum(NoteBucket, values_callable=lambda obj: [e.value for e in obj]),
        default=NoteBucket.PUBLIC,
        nullable=False,
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
```

- [ ] **Step 4: Write Note Pydantic schemas**

```python
# backend/app/schemas/note.py
from datetime import datetime
from enum import StrEnum
from uuid import UUID
from pydantic import BaseModel, Field

from app.schemas.tag import TagCreate, TagResponse


class NoteBucket(StrEnum):
    PUBLIC = "public"
    CONFIDENTIAL = "confidential"


class NoteCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=512)
    content: str | None = Field(None)
    bucket: NoteBucket = Field(default=NoteBucket.PUBLIC)
    tags: list[TagCreate] = Field(default_factory=list)


class NoteUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=512)
    content: str | None = None
    bucket: NoteBucket | None = None
    tags: list[TagCreate] | None = None


class NoteResponse(BaseModel):
    id: UUID
    user_id: UUID
    title: str
    content: str | None
    bucket: NoteBucket
    tags: list[TagResponse] = []
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class NoteListResponse(BaseModel):
    notes: list[NoteResponse]
    total: int
    page: int
    page_size: int
```

- [ ] **Step 5: Write note service**

```python
# backend/app/services/note_service.py
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
        self, db: AsyncSession, user: User, title: str, content: str | None = None,
        bucket: str = "public", tags: list[dict] | None = None,
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

        for tag_data in (tags or []):
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

    async def update_note(self, db: AsyncSession, note: Note, update_data: dict) -> Note:
        for key, value in update_data.items():
            if key == "tags":
                continue
            if value is not None:
                setattr(note, key, value)

        if "tags" in update_data and update_data["tags"] is not None:
            existing = await db.execute(
                select(Tag).where(Tag.target_type == TargetType.NOTE, Tag.target_id == note.id)
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
            select(Tag).where(Tag.target_type == TargetType.NOTE, Tag.target_id == note.id)
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
            select(Tag).where(Tag.target_type == TargetType.NOTE, Tag.target_id == note_id)
        )
        return list(result.scalars().all())

    def _apply_access_filter(self, query, user: User):
        query = query.where(Note.user_id == user.id)
        if user.role == UserRole.USER:
            query = query.where(Note.bucket == NoteBucket.PUBLIC)
        return query


note_service = NoteService()
```

- [ ] **Step 6: Write notes API router**

```python
# backend/app/api/notes.py
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.note import NoteCreate, NoteListResponse, NoteResponse, NoteUpdate
from app.schemas.tag import TagResponse
from app.services.note_service import note_service

router = APIRouter(prefix="/notes", tags=["notes"])
logger = logging.getLogger(__name__)


@router.post("", response_model=NoteResponse, status_code=status.HTTP_201_CREATED)
async def create_note(
    data: NoteCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NoteResponse:
    note = await note_service.create_note(
        db=db, user=current_user, title=data.title, content=data.content,
        bucket=data.bucket.value, tags=[t.model_dump() for t in data.tags],
    )
    tags = await note_service.get_tags_for_note(db, note.id)
    return _to_response(note, tags)


@router.get("", response_model=NoteListResponse)
async def list_notes(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    tag: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NoteListResponse:
    notes, total = await note_service.list_notes(
        db=db, user=current_user, page=page, page_size=page_size, tag=tag,
    )
    items = []
    for n in notes:
        tags = await note_service.get_tags_for_note(db, n.id)
        items.append(_to_response(n, tags))
    return NoteListResponse(notes=items, total=total, page=page, page_size=page_size)


@router.get("/search", response_model=NoteListResponse)
async def search_notes(
    q: str = Query(..., min_length=1),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NoteListResponse:
    notes, total = await note_service.search_notes(
        db=db, user=current_user, query_str=q, page=page, page_size=page_size,
    )
    items = []
    for n in notes:
        tags = await note_service.get_tags_for_note(db, n.id)
        items.append(_to_response(n, tags))
    return NoteListResponse(notes=items, total=total, page=page, page_size=page_size)


@router.get("/{note_id}", response_model=NoteResponse)
async def get_note(
    note_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NoteResponse:
    note = await note_service.get_note(db, note_id, current_user)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    tags = await note_service.get_tags_for_note(db, note.id)
    return _to_response(note, tags)


@router.put("/{note_id}", response_model=NoteResponse)
async def update_note(
    note_id: UUID,
    data: NoteUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NoteResponse:
    note = await note_service.get_note(db, note_id, current_user)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    if note.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    update_dict = data.model_dump(exclude_unset=True)
    if "tags" in update_dict and update_dict["tags"] is not None:
        update_dict["tags"] = [t.model_dump() for t in data.tags]

    note = await note_service.update_note(db, note, update_dict)
    tags = await note_service.get_tags_for_note(db, note.id)
    return _to_response(note, tags)


@router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_note(
    note_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    note = await note_service.get_note(db, note_id, current_user)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    if note.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    await note_service.delete_note(db, note)


def _to_response(note, tags) -> NoteResponse:
    return NoteResponse(
        id=note.id, user_id=note.user_id, title=note.title, content=note.content,
        bucket=note.bucket, tags=[TagResponse.model_validate(t) for t in tags],
        created_at=note.created_at, updated_at=note.updated_at,
    )
```

- [ ] **Step 7: Register Note model and router**

Add to `backend/app/models/__init__.py`:
```python
from app.models.note import Note, NoteBucket  # noqa: F401
```

Add to `backend/app/main.py`:
```python
from app.api import notes
app.include_router(notes.router, prefix="/api/v1")
```

- [ ] **Step 8: Run test to verify it passes**

Run: `cd /home/development/src/active/sowknow4/backend && python -m pytest tests/unit/test_note_api.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add backend/app/models/note.py backend/app/schemas/note.py backend/app/services/note_service.py backend/app/api/notes.py backend/app/models/__init__.py backend/app/main.py backend/tests/unit/test_note_api.py
git commit -m "feat: add Note model, service, and API router"
```

---

## Task 4: Space Model + Schema + API

**Files:**
- Create: `backend/app/models/space.py`
- Create: `backend/app/schemas/space.py`
- Create: `backend/app/services/space_service.py`
- Create: `backend/app/api/spaces.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/unit/test_space_model.py`

- [ ] **Step 1: Write the Space model test**

```python
# backend/tests/unit/test_space_model.py
import pytest
from app.models.space import Space, SpaceItem, SpaceRule, SpaceBucket, SpaceItemType, SpaceRuleType


class TestSpaceEnums:
    def test_bucket_values(self):
        assert SpaceBucket.PUBLIC.value == "public"
        assert SpaceBucket.CONFIDENTIAL.value == "confidential"

    def test_item_type_values(self):
        assert SpaceItemType.DOCUMENT.value == "document"
        assert SpaceItemType.BOOKMARK.value == "bookmark"
        assert SpaceItemType.NOTE.value == "note"

    def test_rule_type_values(self):
        assert SpaceRuleType.TAG.value == "tag"
        assert SpaceRuleType.KEYWORD.value == "keyword"


class TestSpaceModel:
    def test_space_has_required_columns(self):
        from sqlalchemy import inspect
        mapper = inspect(Space)
        column_names = [c.key for c in mapper.column_attrs]
        for col in ["id", "user_id", "name", "description", "icon", "bucket", "is_pinned", "created_at", "updated_at"]:
            assert col in column_names, f"Missing column: {col}"

    def test_space_item_has_required_columns(self):
        from sqlalchemy import inspect
        mapper = inspect(SpaceItem)
        column_names = [c.key for c in mapper.column_attrs]
        for col in ["id", "space_id", "item_type", "document_id", "bookmark_id", "note_id", "added_by", "added_at", "note", "is_excluded"]:
            assert col in column_names, f"Missing column: {col}"

    def test_space_rule_has_required_columns(self):
        from sqlalchemy import inspect
        mapper = inspect(SpaceRule)
        column_names = [c.key for c in mapper.column_attrs]
        for col in ["id", "space_id", "rule_type", "rule_value", "is_active", "created_at"]:
            assert col in column_names, f"Missing column: {col}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/development/src/active/sowknow4/backend && python -m pytest tests/unit/test_space_model.py -v`
Expected: FAIL

- [ ] **Step 3: Write the Space models**

```python
# backend/app/models/space.py
import enum
import uuid

from sqlalchemy import (
    Boolean, Column, DateTime, Enum, ForeignKey, String, Text, func
)
from app.models.base import Base, GUIDType


class SpaceBucket(enum.StrEnum):
    PUBLIC = "public"
    CONFIDENTIAL = "confidential"


class SpaceItemType(enum.StrEnum):
    DOCUMENT = "document"
    BOOKMARK = "bookmark"
    NOTE = "note"


class SpaceRuleType(enum.StrEnum):
    TAG = "tag"
    KEYWORD = "keyword"


class Space(Base):
    __tablename__ = "spaces"
    __table_args__ = ({"schema": "sowknow"},)

    id = Column(GUIDType(as_uuid=True), primary_key=True, default=uuid.uuid4, unique=True, nullable=False)
    user_id = Column(GUIDType(as_uuid=True), ForeignKey("sowknow.users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(512), nullable=False)
    description = Column(Text, nullable=True)
    icon = Column(String(64), nullable=True)
    bucket = Column(
        Enum(SpaceBucket, values_callable=lambda obj: [e.value for e in obj]),
        default=SpaceBucket.PUBLIC,
        nullable=False,
    )
    is_pinned = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class SpaceItem(Base):
    __tablename__ = "space_items"
    __table_args__ = ({"schema": "sowknow"},)

    id = Column(GUIDType(as_uuid=True), primary_key=True, default=uuid.uuid4, unique=True, nullable=False)
    space_id = Column(GUIDType(as_uuid=True), ForeignKey("sowknow.spaces.id", ondelete="CASCADE"), nullable=False, index=True)
    item_type = Column(
        Enum(SpaceItemType, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
    )
    document_id = Column(GUIDType(as_uuid=True), ForeignKey("sowknow.documents.id", ondelete="CASCADE"), nullable=True)
    bookmark_id = Column(GUIDType(as_uuid=True), ForeignKey("sowknow.bookmarks.id", ondelete="CASCADE"), nullable=True)
    note_id = Column(GUIDType(as_uuid=True), ForeignKey("sowknow.notes.id", ondelete="CASCADE"), nullable=True)
    added_by = Column(String(16), nullable=False, default="user")
    added_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    note = Column(Text, nullable=True)
    is_excluded = Column(Boolean, default=False, nullable=False)


class SpaceRule(Base):
    __tablename__ = "space_rules"
    __table_args__ = ({"schema": "sowknow"},)

    id = Column(GUIDType(as_uuid=True), primary_key=True, default=uuid.uuid4, unique=True, nullable=False)
    space_id = Column(GUIDType(as_uuid=True), ForeignKey("sowknow.spaces.id", ondelete="CASCADE"), nullable=False, index=True)
    rule_type = Column(
        Enum(SpaceRuleType, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
    )
    rule_value = Column(String(512), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
```

- [ ] **Step 4: Write Space Pydantic schemas**

```python
# backend/app/schemas/space.py
from datetime import datetime
from enum import StrEnum
from uuid import UUID
from pydantic import BaseModel, Field

from app.schemas.tag import TagResponse


class SpaceBucket(StrEnum):
    PUBLIC = "public"
    CONFIDENTIAL = "confidential"


class SpaceItemType(StrEnum):
    DOCUMENT = "document"
    BOOKMARK = "bookmark"
    NOTE = "note"


class SpaceRuleType(StrEnum):
    TAG = "tag"
    KEYWORD = "keyword"


# --- Space ---

class SpaceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=512)
    description: str | None = None
    icon: str | None = Field(None, max_length=64)
    bucket: SpaceBucket = Field(default=SpaceBucket.PUBLIC)


class SpaceUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=512)
    description: str | None = None
    icon: str | None = None
    bucket: SpaceBucket | None = None
    is_pinned: bool | None = None


class SpaceItemResponse(BaseModel):
    id: UUID
    space_id: UUID
    item_type: SpaceItemType
    document_id: UUID | None
    bookmark_id: UUID | None
    note_id: UUID | None
    added_by: str
    added_at: datetime
    note: str | None
    is_excluded: bool
    # Denormalized item info for display
    item_title: str | None = None
    item_url: str | None = None
    item_tags: list[TagResponse] = []

    class Config:
        from_attributes = True


class SpaceRuleResponse(BaseModel):
    id: UUID
    space_id: UUID
    rule_type: SpaceRuleType
    rule_value: str
    is_active: bool
    match_count: int = 0
    created_at: datetime

    class Config:
        from_attributes = True


class SpaceResponse(BaseModel):
    id: UUID
    user_id: UUID
    name: str
    description: str | None
    icon: str | None
    bucket: SpaceBucket
    is_pinned: bool
    item_count: int = 0
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class SpaceDetailResponse(SpaceResponse):
    items: list[SpaceItemResponse] = []
    rules: list[SpaceRuleResponse] = []


class SpaceListResponse(BaseModel):
    spaces: list[SpaceResponse]
    total: int
    page: int
    page_size: int


# --- SpaceItem ---

class SpaceItemAdd(BaseModel):
    item_type: SpaceItemType
    item_id: UUID
    note: str | None = None


# --- SpaceRule ---

class SpaceRuleCreate(BaseModel):
    rule_type: SpaceRuleType
    rule_value: str = Field(..., min_length=1, max_length=512)


class SpaceRuleUpdate(BaseModel):
    rule_value: str | None = Field(None, min_length=1, max_length=512)
    is_active: bool | None = None
```

- [ ] **Step 5: Write space service**

```python
# backend/app/services/space_service.py
import logging
import uuid

from sqlalchemy import func, select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bookmark import Bookmark
from app.models.document import Document, DocumentBucket, DocumentChunk
from app.models.note import Note
from app.models.space import Space, SpaceBucket, SpaceItem, SpaceItemType, SpaceRule, SpaceRuleType
from app.models.tag import Tag, TargetType
from app.models.user import User, UserRole

logger = logging.getLogger(__name__)


class SpaceService:

    # --- Space CRUD ---

    async def create_space(self, db: AsyncSession, user: User, name: str,
                           description: str | None = None, icon: str | None = None,
                           bucket: str = "public") -> Space:
        space = Space(
            id=uuid.uuid4(), user_id=user.id, name=name,
            description=description, icon=icon, bucket=SpaceBucket(bucket),
        )
        db.add(space)
        await db.commit()
        await db.refresh(space)
        return space

    async def get_space(self, db: AsyncSession, space_id: uuid.UUID, user: User) -> Space | None:
        query = select(Space).where(Space.id == space_id)
        query = self._apply_access_filter(query, user)
        result = await db.execute(query)
        return result.scalar_one_or_none()

    async def list_spaces(self, db: AsyncSession, user: User, page: int = 1,
                          page_size: int = 50, search: str | None = None) -> tuple[list[Space], int]:
        query = select(Space)
        query = self._apply_access_filter(query, user)
        if search:
            query = query.where(Space.name.ilike(f"%{search}%"))

        count_query = select(func.count()).select_from(query.subquery())
        total = (await db.execute(count_query)).scalar() or 0

        query = query.order_by(Space.is_pinned.desc(), Space.updated_at.desc())
        query = query.offset((page - 1) * page_size).limit(page_size)
        result = await db.execute(query)
        return list(result.scalars().all()), total

    async def update_space(self, db: AsyncSession, space: Space, update_data: dict) -> Space:
        for key, value in update_data.items():
            if value is not None:
                setattr(space, key, value)
        await db.commit()
        await db.refresh(space)
        return space

    async def delete_space(self, db: AsyncSession, space: Space) -> None:
        await db.delete(space)
        await db.commit()

    async def get_item_count(self, db: AsyncSession, space_id: uuid.UUID) -> int:
        result = await db.execute(
            select(func.count()).where(
                SpaceItem.space_id == space_id, SpaceItem.is_excluded == False
            )
        )
        return result.scalar() or 0

    # --- SpaceItem ---

    async def add_item(self, db: AsyncSession, space_id: uuid.UUID,
                       item_type: str, item_id: uuid.UUID,
                       added_by: str = "user", note: str | None = None) -> SpaceItem:
        # Check for existing (including excluded — re-include it)
        existing = await db.execute(
            select(SpaceItem).where(
                SpaceItem.space_id == space_id,
                SpaceItem.item_type == SpaceItemType(item_type),
                getattr(SpaceItem, f"{item_type}_id") == item_id,
            )
        )
        item = existing.scalar_one_or_none()
        if item:
            if item.is_excluded:
                item.is_excluded = False
                item.added_by = added_by
                await db.commit()
                await db.refresh(item)
            return item

        space_item = SpaceItem(
            id=uuid.uuid4(), space_id=space_id, item_type=SpaceItemType(item_type),
            added_by=added_by, note=note,
        )
        setattr(space_item, f"{item_type}_id", item_id)
        db.add(space_item)
        await db.commit()
        await db.refresh(space_item)
        return space_item

    async def remove_item(self, db: AsyncSession, space_item: SpaceItem) -> None:
        if space_item.added_by == "rule":
            space_item.is_excluded = True
            await db.commit()
        else:
            await db.delete(space_item)
            await db.commit()

    async def get_space_item(self, db: AsyncSession, item_id: uuid.UUID) -> SpaceItem | None:
        result = await db.execute(select(SpaceItem).where(SpaceItem.id == item_id))
        return result.scalar_one_or_none()

    async def get_space_items(self, db: AsyncSession, space_id: uuid.UUID,
                              item_type: str | None = None) -> list[SpaceItem]:
        query = select(SpaceItem).where(
            SpaceItem.space_id == space_id, SpaceItem.is_excluded == False
        )
        if item_type:
            query = query.where(SpaceItem.item_type == SpaceItemType(item_type))
        query = query.order_by(SpaceItem.added_at.desc())
        result = await db.execute(query)
        return list(result.scalars().all())

    async def enrich_space_item(self, db: AsyncSession, item: SpaceItem) -> dict:
        """Get denormalized title/url/tags for a SpaceItem."""
        title = None
        url = None
        tags = []

        if item.item_type == SpaceItemType.DOCUMENT and item.document_id:
            doc = (await db.execute(select(Document).where(Document.id == item.document_id))).scalar_one_or_none()
            if doc:
                title = doc.filename
            tag_result = await db.execute(
                select(Tag).where(Tag.target_type == TargetType.DOCUMENT, Tag.target_id == item.document_id)
            )
            tags = list(tag_result.scalars().all())

        elif item.item_type == SpaceItemType.BOOKMARK and item.bookmark_id:
            bm = (await db.execute(select(Bookmark).where(Bookmark.id == item.bookmark_id))).scalar_one_or_none()
            if bm:
                title = bm.title
                url = bm.url
            tag_result = await db.execute(
                select(Tag).where(Tag.target_type == TargetType.BOOKMARK, Tag.target_id == item.bookmark_id)
            )
            tags = list(tag_result.scalars().all())

        elif item.item_type == SpaceItemType.NOTE and item.note_id:
            note = (await db.execute(select(Note).where(Note.id == item.note_id))).scalar_one_or_none()
            if note:
                title = note.title
            tag_result = await db.execute(
                select(Tag).where(Tag.target_type == TargetType.NOTE, Tag.target_id == item.note_id)
            )
            tags = list(tag_result.scalars().all())

        return {"item_title": title, "item_url": url, "item_tags": tags}

    # --- SpaceRule ---

    async def add_rule(self, db: AsyncSession, space_id: uuid.UUID,
                       rule_type: str, rule_value: str) -> SpaceRule:
        rule = SpaceRule(
            id=uuid.uuid4(), space_id=space_id,
            rule_type=SpaceRuleType(rule_type), rule_value=rule_value,
        )
        db.add(rule)
        await db.commit()
        await db.refresh(rule)
        return rule

    async def update_rule(self, db: AsyncSession, rule: SpaceRule, update_data: dict) -> SpaceRule:
        for key, value in update_data.items():
            if value is not None:
                setattr(rule, key, value)
        await db.commit()
        await db.refresh(rule)
        return rule

    async def delete_rule(self, db: AsyncSession, rule: SpaceRule) -> None:
        await db.delete(rule)
        await db.commit()

    async def get_rule(self, db: AsyncSession, rule_id: uuid.UUID) -> SpaceRule | None:
        result = await db.execute(select(SpaceRule).where(SpaceRule.id == rule_id))
        return result.scalar_one_or_none()

    async def get_rules(self, db: AsyncSession, space_id: uuid.UUID) -> list[SpaceRule]:
        result = await db.execute(
            select(SpaceRule).where(SpaceRule.space_id == space_id).order_by(SpaceRule.created_at)
        )
        return list(result.scalars().all())

    async def get_rule_match_count(self, db: AsyncSession, rule: SpaceRule) -> int:
        return (await db.execute(
            select(func.count()).where(
                SpaceItem.space_id == rule.space_id, SpaceItem.is_excluded == False
            )
        )).scalar() or 0

    # --- Rule Sync Engine ---

    async def sync_space_rules(self, db: AsyncSession, space: Space) -> int:
        """Evaluate all active rules and add matching items. Returns count of new items added."""
        rules = await db.execute(
            select(SpaceRule).where(SpaceRule.space_id == space.id, SpaceRule.is_active == True)
        )
        active_rules = list(rules.scalars().all())
        if not active_rules:
            return 0

        added = 0
        for rule in active_rules:
            if rule.rule_type == SpaceRuleType.TAG:
                added += await self._sync_tag_rule(db, space, rule)
            elif rule.rule_type == SpaceRuleType.KEYWORD:
                added += await self._sync_keyword_rule(db, space, rule)
        return added

    async def _sync_tag_rule(self, db: AsyncSession, space: Space, rule: SpaceRule) -> int:
        """Find all items with matching tag and add to space."""
        tag_matches = await db.execute(
            select(Tag.target_type, Tag.target_id).where(
                func.lower(Tag.tag_name) == rule.rule_value.lower()
            )
        )
        added = 0
        for target_type, target_id in tag_matches.all():
            if await self._is_accessible(db, space, target_type, target_id):
                item = await self.add_item(db, space.id, target_type, target_id, added_by="rule")
                if item and not item.is_excluded:
                    added += 1
        return added

    async def _sync_keyword_rule(self, db: AsyncSession, space: Space, rule: SpaceRule) -> int:
        """Find items matching keyword and add to space."""
        added = 0
        keyword = rule.rule_value

        # Documents: use full-text search on chunks
        doc_results = await db.execute(
            select(Document.id).where(
                Document.id.in_(
                    select(DocumentChunk.document_id).where(
                        DocumentChunk.search_vector.op("@@")(func.plainto_tsquery("simple", keyword))
                    )
                )
            )
        )
        for (doc_id,) in doc_results.all():
            if await self._is_accessible(db, space, "document", doc_id):
                await self.add_item(db, space.id, "document", doc_id, added_by="rule")
                added += 1

        # Bookmarks: ILIKE on title/description
        bm_results = await db.execute(
            select(Bookmark.id).where(
                or_(Bookmark.title.ilike(f"%{keyword}%"), Bookmark.description.ilike(f"%{keyword}%"))
            )
        )
        for (bm_id,) in bm_results.all():
            if await self._is_accessible(db, space, "bookmark", bm_id):
                await self.add_item(db, space.id, "bookmark", bm_id, added_by="rule")
                added += 1

        # Notes: ILIKE on title/content
        note_results = await db.execute(
            select(Note.id).where(
                or_(Note.title.ilike(f"%{keyword}%"), Note.content.ilike(f"%{keyword}%"))
            )
        )
        for (note_id,) in note_results.all():
            if await self._is_accessible(db, space, "note", note_id):
                await self.add_item(db, space.id, "note", note_id, added_by="rule")
                added += 1

        return added

    async def _is_accessible(self, db: AsyncSession, space: Space, target_type: str, target_id) -> bool:
        """Check if item's bucket is compatible with space's bucket."""
        if space.bucket == SpaceBucket.CONFIDENTIAL:
            return True
        # Public space can only contain public items
        model_map = {"document": Document, "bookmark": Bookmark, "note": Note}
        model = model_map.get(target_type)
        if not model:
            return False
        result = await db.execute(select(model.bucket).where(model.id == target_id))
        bucket = result.scalar_one_or_none()
        return bucket == "public" if bucket else False

    # --- Search within Space ---

    async def search_space_items(self, db: AsyncSession, space_id: uuid.UUID,
                                 query_str: str, item_type: str | None = None) -> list[SpaceItem]:
        items = await self.get_space_items(db, space_id, item_type)
        # Filter by enriched data
        results = []
        for item in items:
            enriched = await self.enrich_space_item(db, item)
            title = (enriched.get("item_title") or "").lower()
            tag_names = [t.tag_name.lower() for t in enriched.get("item_tags", [])]
            if query_str.lower() in title or any(query_str.lower() in tn for tn in tag_names):
                results.append(item)
        return results

    # --- On-creation hook ---

    async def check_rules_for_new_item(self, db: AsyncSession, target_type: str, target_id: uuid.UUID) -> None:
        """Called when a new document/bookmark/note is created. Check all active rules."""
        all_rules = await db.execute(
            select(SpaceRule).where(SpaceRule.is_active == True)
        )
        for rule in all_rules.scalars().all():
            space = (await db.execute(select(Space).where(Space.id == rule.space_id))).scalar_one_or_none()
            if not space:
                continue

            match = False
            if rule.rule_type == SpaceRuleType.TAG:
                tag_match = await db.execute(
                    select(Tag).where(
                        Tag.target_type == TargetType(target_type),
                        Tag.target_id == target_id,
                        func.lower(Tag.tag_name) == rule.rule_value.lower(),
                    )
                )
                match = tag_match.scalar_one_or_none() is not None

            elif rule.rule_type == SpaceRuleType.KEYWORD:
                match = await self._keyword_matches_item(db, target_type, target_id, rule.rule_value)

            if match and await self._is_accessible(db, space, target_type, target_id):
                await self.add_item(db, space.id, target_type, target_id, added_by="rule")

    async def _keyword_matches_item(self, db: AsyncSession, target_type: str, target_id, keyword: str) -> bool:
        if target_type == "document":
            result = await db.execute(
                select(func.count()).where(
                    DocumentChunk.document_id == target_id,
                    DocumentChunk.search_vector.op("@@")(func.plainto_tsquery("simple", keyword)),
                )
            )
            return (result.scalar() or 0) > 0
        elif target_type == "bookmark":
            result = await db.execute(
                select(func.count()).where(
                    Bookmark.id == target_id,
                    or_(Bookmark.title.ilike(f"%{keyword}%"), Bookmark.description.ilike(f"%{keyword}%")),
                )
            )
            return (result.scalar() or 0) > 0
        elif target_type == "note":
            result = await db.execute(
                select(func.count()).where(
                    Note.id == target_id,
                    or_(Note.title.ilike(f"%{keyword}%"), Note.content.ilike(f"%{keyword}%")),
                )
            )
            return (result.scalar() or 0) > 0
        return False

    def _apply_access_filter(self, query, user: User):
        query = query.where(Space.user_id == user.id)
        if user.role == UserRole.USER:
            query = query.where(Space.bucket == SpaceBucket.PUBLIC)
        return query


space_service = SpaceService()
```

- [ ] **Step 6: Write spaces API router**

```python
# backend/app/api/spaces.py
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.space import (
    SpaceCreate, SpaceDetailResponse, SpaceItemAdd, SpaceItemResponse,
    SpaceListResponse, SpaceResponse, SpaceRuleCreate, SpaceRuleResponse,
    SpaceRuleUpdate, SpaceUpdate,
)
from app.schemas.tag import TagResponse
from app.services.space_service import space_service

router = APIRouter(prefix="/spaces", tags=["spaces"])
logger = logging.getLogger(__name__)


@router.post("", response_model=SpaceResponse, status_code=status.HTTP_201_CREATED)
async def create_space(
    data: SpaceCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SpaceResponse:
    space = await space_service.create_space(
        db=db, user=current_user, name=data.name, description=data.description,
        icon=data.icon, bucket=data.bucket.value,
    )
    return SpaceResponse.model_validate(space, from_attributes=True)


@router.get("", response_model=SpaceListResponse)
async def list_spaces(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    search: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SpaceListResponse:
    spaces, total = await space_service.list_spaces(db, current_user, page, page_size, search)
    items = []
    for s in spaces:
        count = await space_service.get_item_count(db, s.id)
        resp = SpaceResponse.model_validate(s, from_attributes=True)
        resp.item_count = count
        items.append(resp)
    return SpaceListResponse(spaces=items, total=total, page=page, page_size=page_size)


@router.get("/{space_id}", response_model=SpaceDetailResponse)
async def get_space(
    space_id: UUID,
    item_type: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SpaceDetailResponse:
    space = await space_service.get_space(db, space_id, current_user)
    if not space:
        raise HTTPException(status_code=404, detail="Space not found")

    items = await space_service.get_space_items(db, space_id, item_type)
    enriched_items = []
    for item in items:
        enriched = await space_service.enrich_space_item(db, item)
        enriched_items.append(SpaceItemResponse(
            id=item.id, space_id=item.space_id, item_type=item.item_type,
            document_id=item.document_id, bookmark_id=item.bookmark_id, note_id=item.note_id,
            added_by=item.added_by, added_at=item.added_at, note=item.note,
            is_excluded=item.is_excluded, item_title=enriched["item_title"],
            item_url=enriched.get("item_url"),
            item_tags=[TagResponse.model_validate(t) for t in enriched.get("item_tags", [])],
        ))

    rules = await space_service.get_rules(db, space_id)
    rule_responses = []
    for r in rules:
        count = await space_service.get_rule_match_count(db, r)
        resp = SpaceRuleResponse.model_validate(r, from_attributes=True)
        resp.match_count = count
        rule_responses.append(resp)

    count = await space_service.get_item_count(db, space_id)
    detail = SpaceDetailResponse.model_validate(space, from_attributes=True)
    detail.item_count = count
    detail.items = enriched_items
    detail.rules = rule_responses
    return detail


@router.put("/{space_id}", response_model=SpaceResponse)
async def update_space(
    space_id: UUID,
    data: SpaceUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SpaceResponse:
    space = await space_service.get_space(db, space_id, current_user)
    if not space:
        raise HTTPException(status_code=404, detail="Space not found")
    if space.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    space = await space_service.update_space(db, space, data.model_dump(exclude_unset=True))
    return SpaceResponse.model_validate(space, from_attributes=True)


@router.delete("/{space_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_space(
    space_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    space = await space_service.get_space(db, space_id, current_user)
    if not space:
        raise HTTPException(status_code=404, detail="Space not found")
    if space.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    await space_service.delete_space(db, space)


# --- Items ---

@router.post("/{space_id}/items", response_model=SpaceItemResponse, status_code=status.HTTP_201_CREATED)
async def add_item_to_space(
    space_id: UUID,
    data: SpaceItemAdd,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SpaceItemResponse:
    space = await space_service.get_space(db, space_id, current_user)
    if not space:
        raise HTTPException(status_code=404, detail="Space not found")
    if space.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    item = await space_service.add_item(
        db, space_id, data.item_type.value, data.item_id, added_by="user", note=data.note,
    )
    enriched = await space_service.enrich_space_item(db, item)
    return SpaceItemResponse(
        id=item.id, space_id=item.space_id, item_type=item.item_type,
        document_id=item.document_id, bookmark_id=item.bookmark_id, note_id=item.note_id,
        added_by=item.added_by, added_at=item.added_at, note=item.note,
        is_excluded=item.is_excluded, item_title=enriched["item_title"],
        item_url=enriched.get("item_url"),
        item_tags=[TagResponse.model_validate(t) for t in enriched.get("item_tags", [])],
    )


@router.delete("/{space_id}/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_item_from_space(
    space_id: UUID,
    item_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    space = await space_service.get_space(db, space_id, current_user)
    if not space or space.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Space not found")
    item = await space_service.get_space_item(db, item_id)
    if not item or item.space_id != space_id:
        raise HTTPException(status_code=404, detail="Item not found")
    await space_service.remove_item(db, item)


# --- Rules ---

@router.post("/{space_id}/rules", response_model=SpaceRuleResponse, status_code=status.HTTP_201_CREATED)
async def add_rule(
    space_id: UUID,
    data: SpaceRuleCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SpaceRuleResponse:
    space = await space_service.get_space(db, space_id, current_user)
    if not space or space.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    rule = await space_service.add_rule(db, space_id, data.rule_type.value, data.rule_value)
    return SpaceRuleResponse.model_validate(rule, from_attributes=True)


@router.put("/{space_id}/rules/{rule_id}", response_model=SpaceRuleResponse)
async def update_rule(
    space_id: UUID,
    rule_id: UUID,
    data: SpaceRuleUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SpaceRuleResponse:
    space = await space_service.get_space(db, space_id, current_user)
    if not space or space.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    rule = await space_service.get_rule(db, rule_id)
    if not rule or rule.space_id != space_id:
        raise HTTPException(status_code=404, detail="Rule not found")
    rule = await space_service.update_rule(db, rule, data.model_dump(exclude_unset=True))
    count = await space_service.get_rule_match_count(db, rule)
    resp = SpaceRuleResponse.model_validate(rule, from_attributes=True)
    resp.match_count = count
    return resp


@router.delete("/{space_id}/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(
    space_id: UUID,
    rule_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    space = await space_service.get_space(db, space_id, current_user)
    if not space or space.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    rule = await space_service.get_rule(db, rule_id)
    if not rule or rule.space_id != space_id:
        raise HTTPException(status_code=404, detail="Rule not found")
    await space_service.delete_rule(db, rule)


# --- Sync ---

@router.post("/{space_id}/sync", status_code=status.HTTP_202_ACCEPTED)
async def sync_space(
    space_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    space = await space_service.get_space(db, space_id, current_user)
    if not space:
        raise HTTPException(status_code=404, detail="Space not found")

    from app.tasks.space_tasks import sync_space_rules_task
    sync_space_rules_task.delay(str(space_id))
    return {"status": "syncing", "space_id": str(space_id)}


# --- Search within Space ---

@router.get("/{space_id}/search")
async def search_in_space(
    space_id: UUID,
    q: str = Query(..., min_length=1),
    item_type: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    space = await space_service.get_space(db, space_id, current_user)
    if not space:
        raise HTTPException(status_code=404, detail="Space not found")

    items = await space_service.search_space_items(db, space_id, q, item_type)
    enriched_items = []
    for item in items:
        enriched = await space_service.enrich_space_item(db, item)
        enriched_items.append(SpaceItemResponse(
            id=item.id, space_id=item.space_id, item_type=item.item_type,
            document_id=item.document_id, bookmark_id=item.bookmark_id, note_id=item.note_id,
            added_by=item.added_by, added_at=item.added_at, note=item.note,
            is_excluded=item.is_excluded, item_title=enriched["item_title"],
            item_url=enriched.get("item_url"),
            item_tags=[TagResponse.model_validate(t) for t in enriched.get("item_tags", [])],
        ))
    return {"items": enriched_items, "total": len(enriched_items)}
```

- [ ] **Step 7: Register Space models and router**

Add to `backend/app/models/__init__.py`:
```python
from app.models.space import Space, SpaceItem, SpaceRule, SpaceBucket, SpaceItemType, SpaceRuleType  # noqa: F401
```

Add to `backend/app/main.py`:
```python
from app.api import spaces
app.include_router(spaces.router, prefix="/api/v1")
```

- [ ] **Step 8: Run test to verify it passes**

Run: `cd /home/development/src/active/sowknow4/backend && python -m pytest tests/unit/test_space_model.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add backend/app/models/space.py backend/app/schemas/space.py backend/app/services/space_service.py backend/app/api/spaces.py backend/app/models/__init__.py backend/app/main.py backend/tests/unit/test_space_model.py
git commit -m "feat: add Space model with SpaceItem, SpaceRule, service, and API router"
```

---

## Task 5: Celery Task for Space Sync + On-Creation Hooks

**Files:**
- Create: `backend/app/tasks/space_tasks.py`
- Modify: `backend/app/api/bookmarks.py` (add rule check after create)
- Modify: `backend/app/api/notes.py` (add rule check after create)
- Test: `backend/tests/unit/test_space_tasks.py`

- [ ] **Step 1: Write the Celery task test**

```python
# backend/tests/unit/test_space_tasks.py
import pytest
from unittest.mock import patch, AsyncMock


class TestSpaceTaskExists:
    def test_sync_space_rules_task_is_importable(self):
        from app.tasks.space_tasks import sync_space_rules_task
        assert callable(sync_space_rules_task)

    def test_task_is_celery_shared_task(self):
        from app.tasks.space_tasks import sync_space_rules_task
        assert hasattr(sync_space_rules_task, "delay")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/development/src/active/sowknow4/backend && python -m pytest tests/unit/test_space_tasks.py -v`
Expected: FAIL

- [ ] **Step 3: Write the Celery task**

```python
# backend/app/tasks/space_tasks.py
import logging

from celery import shared_task
from app.tasks.base import log_task_memory

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=2)
def sync_space_rules_task(self, space_id: str):
    """Evaluate all active rules for a space and add matching items."""
    log_task_memory("sync_space_rules", "start")
    try:
        from app.database import SessionLocal
        from app.models.space import Space
        from app.services.space_service import space_service
        import asyncio

        async def _run():
            db = SessionLocal()
            try:
                space = db.query(Space).filter(Space.id == space_id).first()
                if not space:
                    logger.warning(f"Space {space_id} not found for sync")
                    return 0
                # Use sync session for Celery — need to adapt or use sync queries
                # For simplicity, use the async service with asyncio.run
                from sqlalchemy.ext.asyncio import AsyncSession
                from app.database import AsyncSessionLocal
                async with AsyncSessionLocal() as async_db:
                    from sqlalchemy import select as sa_select
                    from app.models.space import Space as SpaceModel
                    space = (await async_db.execute(
                        sa_select(SpaceModel).where(SpaceModel.id == space_id)
                    )).scalar_one_or_none()
                    if not space:
                        return 0
                    added = await space_service.sync_space_rules(async_db, space)
                    logger.info(f"Space {space_id} sync complete: {added} items added")
                    return added
            finally:
                db.close()

        return asyncio.run(_run())

    except Exception as exc:
        logger.error(f"Space sync failed for {space_id}: {exc}")
        raise self.retry(exc=exc, countdown=30)
    finally:
        log_task_memory("sync_space_rules", "end")
```

- [ ] **Step 4: Add on-creation hook to bookmarks API**

In `backend/app/api/bookmarks.py`, add after the `await bookmark_service.create_bookmark(...)` call in `create_bookmark`:

```python
    # Check space rules for new bookmark
    try:
        from app.services.space_service import space_service
        await space_service.check_rules_for_new_item(db, "bookmark", bookmark.id)
    except Exception as e:
        logger.warning(f"Space rule check failed for bookmark {bookmark.id}: {e}")
```

- [ ] **Step 5: Add on-creation hook to notes API**

In `backend/app/api/notes.py`, add after the `await note_service.create_note(...)` call in `create_note`:

```python
    # Check space rules for new note
    try:
        from app.services.space_service import space_service
        await space_service.check_rules_for_new_item(db, "note", note.id)
    except Exception as e:
        logger.warning(f"Space rule check failed for note {note.id}: {e}")
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd /home/development/src/active/sowknow4/backend && python -m pytest tests/unit/test_space_tasks.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/tasks/space_tasks.py backend/app/api/bookmarks.py backend/app/api/notes.py backend/tests/unit/test_space_tasks.py
git commit -m "feat: add Celery task for space rule sync and on-creation hooks"
```

---

## Task 6: Database Migrations for All New Tables

**Files:**
- Create: `backend/alembic/versions/012_add_bookmarks_notes_spaces.py`
- Create: `backend/alembic/versions/013_migrate_document_tags.py`

- [ ] **Step 1: Write migration for bookmarks, notes, spaces tables**

```python
# backend/alembic/versions/012_add_bookmarks_notes_spaces.py
"""Add bookmarks, notes, spaces, space_items, space_rules tables"""

from alembic import op
import sqlalchemy as sa

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Bookmarks
    op.create_table(
        "bookmarks",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("user_id", sa.CHAR(36), sa.ForeignKey("sowknow.users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("favicon_url", sa.String(2048), nullable=True),
        sa.Column("bucket", sa.Enum("public", "confidential", name="bookmarkbucket", schema="sowknow"), nullable=False, server_default="public"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        schema="sowknow",
    )
    op.create_index("ix_bookmarks_user_id", "bookmarks", ["user_id"], schema="sowknow")

    # Notes
    op.create_table(
        "notes",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("user_id", sa.CHAR(36), sa.ForeignKey("sowknow.users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("bucket", sa.Enum("public", "confidential", name="notebucket", schema="sowknow"), nullable=False, server_default="public"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        schema="sowknow",
    )
    op.create_index("ix_notes_user_id", "notes", ["user_id"], schema="sowknow")

    # Spaces
    op.create_table(
        "spaces",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("user_id", sa.CHAR(36), sa.ForeignKey("sowknow.users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(512), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("icon", sa.String(64), nullable=True),
        sa.Column("bucket", sa.Enum("public", "confidential", name="spacebucket", schema="sowknow"), nullable=False, server_default="public"),
        sa.Column("is_pinned", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        schema="sowknow",
    )
    op.create_index("ix_spaces_user_id", "spaces", ["user_id"], schema="sowknow")

    # Space Items
    op.create_table(
        "space_items",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("space_id", sa.CHAR(36), sa.ForeignKey("sowknow.spaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("item_type", sa.Enum("document", "bookmark", "note", name="spaceitemtype", schema="sowknow"), nullable=False),
        sa.Column("document_id", sa.CHAR(36), sa.ForeignKey("sowknow.documents.id", ondelete="CASCADE"), nullable=True),
        sa.Column("bookmark_id", sa.CHAR(36), sa.ForeignKey("sowknow.bookmarks.id", ondelete="CASCADE"), nullable=True),
        sa.Column("note_id", sa.CHAR(36), sa.ForeignKey("sowknow.notes.id", ondelete="CASCADE"), nullable=True),
        sa.Column("added_by", sa.String(16), nullable=False, server_default="user"),
        sa.Column("added_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("is_excluded", sa.Boolean(), nullable=False, server_default="false"),
        schema="sowknow",
    )
    op.create_index("ix_space_items_space_id", "space_items", ["space_id"], schema="sowknow")

    # Space Rules
    op.create_table(
        "space_rules",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("space_id", sa.CHAR(36), sa.ForeignKey("sowknow.spaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rule_type", sa.Enum("tag", "keyword", name="spaceruletype", schema="sowknow"), nullable=False),
        sa.Column("rule_value", sa.String(512), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        schema="sowknow",
    )
    op.create_index("ix_space_rules_space_id", "space_rules", ["space_id"], schema="sowknow")


def downgrade() -> None:
    op.drop_table("space_rules", schema="sowknow")
    op.drop_table("space_items", schema="sowknow")
    op.drop_table("spaces", schema="sowknow")
    op.drop_table("notes", schema="sowknow")
    op.drop_table("bookmarks", schema="sowknow")
    for enum_name in ["bookmarkbucket", "notebucket", "spacebucket", "spaceitemtype", "spaceruletype"]:
        op.execute(f"DROP TYPE IF EXISTS sowknow.{enum_name}")
```

- [ ] **Step 2: Write data migration from DocumentTag to Tag**

```python
# backend/alembic/versions/013_migrate_document_tags.py
"""Migrate DocumentTag data to Tag table"""

from alembic import op

revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Copy data from document_tags to tags
    op.execute("""
        INSERT INTO sowknow.tags (id, tag_name, tag_type, target_type, target_id, auto_generated, confidence_score, created_at)
        SELECT
            id,
            tag_name,
            COALESCE(tag_type, 'custom'),
            'document',
            document_id,
            COALESCE(auto_generated, false),
            confidence_score,
            COALESCE(created_at, NOW())
        FROM sowknow.document_tags
        WHERE document_id IS NOT NULL
        ON CONFLICT DO NOTHING
    """)


def downgrade() -> None:
    # Remove migrated document tags
    op.execute("DELETE FROM sowknow.tags WHERE target_type = 'document'")
```

- [ ] **Step 3: Commit**

```bash
git add backend/alembic/versions/012_add_bookmarks_notes_spaces.py backend/alembic/versions/013_migrate_document_tags.py
git commit -m "feat: add database migrations for bookmarks, notes, spaces, and tag data migration"
```

---

## Task 7: Frontend — API Client Methods

**Files:**
- Modify: `frontend/lib/api.ts`

- [ ] **Step 1: Read current api.ts to find insertion point**

Run: Read the end of the ApiClient class in `frontend/lib/api.ts` to find where to add new methods.

- [ ] **Step 2: Add bookmark, note, space, and tag API methods**

Add the following methods to the `ApiClient` class in `frontend/lib/api.ts`, before the closing brace of the class:

```typescript
  // --- Bookmarks ---

  async getBookmarks(page: number = 1, pageSize: number = 50, tag?: string) {
    const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
    if (tag) params.set('tag', tag);
    return this.request<any>(`/v1/bookmarks?${params}`);
  }

  async createBookmark(url: string, tags: Array<{ tag_name: string; tag_type?: string }>, title?: string, description?: string, bucket: string = 'public') {
    return this.request<any>('/v1/bookmarks', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, title, description, bucket, tags }),
    });
  }

  async getBookmark(id: string) {
    return this.request<any>(`/v1/bookmarks/${id}`);
  }

  async updateBookmark(id: string, data: { title?: string; description?: string; tags?: Array<{ tag_name: string; tag_type?: string }> }) {
    return this.request<any>(`/v1/bookmarks/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
  }

  async deleteBookmark(id: string) {
    return this.request<any>(`/v1/bookmarks/${id}`, { method: 'DELETE' });
  }

  async searchBookmarks(query: string, page: number = 1, pageSize: number = 50) {
    const params = new URLSearchParams({ q: query, page: String(page), page_size: String(pageSize) });
    return this.request<any>(`/v1/bookmarks/search?${params}`);
  }

  // --- Notes ---

  async getNotes(page: number = 1, pageSize: number = 50, tag?: string) {
    const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
    if (tag) params.set('tag', tag);
    return this.request<any>(`/v1/notes?${params}`);
  }

  async createNote(title: string, content?: string, tags: Array<{ tag_name: string; tag_type?: string }> = [], bucket: string = 'public') {
    return this.request<any>('/v1/notes', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title, content, bucket, tags }),
    });
  }

  async getNote(id: string) {
    return this.request<any>(`/v1/notes/${id}`);
  }

  async updateNote(id: string, data: { title?: string; content?: string; tags?: Array<{ tag_name: string; tag_type?: string }> }) {
    return this.request<any>(`/v1/notes/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
  }

  async deleteNote(id: string) {
    return this.request<any>(`/v1/notes/${id}`, { method: 'DELETE' });
  }

  async searchNotes(query: string, page: number = 1, pageSize: number = 50) {
    const params = new URLSearchParams({ q: query, page: String(page), page_size: String(pageSize) });
    return this.request<any>(`/v1/notes/search?${params}`);
  }

  // --- Spaces ---

  async getSpaces(page: number = 1, pageSize: number = 50, search?: string) {
    const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
    if (search) params.set('search', search);
    return this.request<any>(`/v1/spaces?${params}`);
  }

  async createSpace(name: string, description?: string, icon?: string, bucket: string = 'public') {
    return this.request<any>('/v1/spaces', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, description, icon, bucket }),
    });
  }

  async getSpace(id: string, itemType?: string) {
    const params = new URLSearchParams();
    if (itemType) params.set('item_type', itemType);
    const qs = params.toString();
    return this.request<any>(`/v1/spaces/${id}${qs ? `?${qs}` : ''}`);
  }

  async updateSpace(id: string, data: { name?: string; description?: string; icon?: string; is_pinned?: boolean }) {
    return this.request<any>(`/v1/spaces/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
  }

  async deleteSpace(id: string) {
    return this.request<any>(`/v1/spaces/${id}`, { method: 'DELETE' });
  }

  async addSpaceItem(spaceId: string, itemType: string, itemId: string, note?: string) {
    return this.request<any>(`/v1/spaces/${spaceId}/items`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ item_type: itemType, item_id: itemId, note }),
    });
  }

  async removeSpaceItem(spaceId: string, itemId: string) {
    return this.request<any>(`/v1/spaces/${spaceId}/items/${itemId}`, { method: 'DELETE' });
  }

  async addSpaceRule(spaceId: string, ruleType: string, ruleValue: string) {
    return this.request<any>(`/v1/spaces/${spaceId}/rules`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rule_type: ruleType, rule_value: ruleValue }),
    });
  }

  async updateSpaceRule(spaceId: string, ruleId: string, data: { rule_value?: string; is_active?: boolean }) {
    return this.request<any>(`/v1/spaces/${spaceId}/rules/${ruleId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
  }

  async deleteSpaceRule(spaceId: string, ruleId: string) {
    return this.request<any>(`/v1/spaces/${spaceId}/rules/${ruleId}`, { method: 'DELETE' });
  }

  async syncSpace(spaceId: string) {
    return this.request<any>(`/v1/spaces/${spaceId}/sync`, { method: 'POST' });
  }

  async searchInSpace(spaceId: string, query: string, itemType?: string) {
    const params = new URLSearchParams({ q: query });
    if (itemType) params.set('item_type', itemType);
    return this.request<any>(`/v1/spaces/${spaceId}/search?${params}`);
  }
```

- [ ] **Step 3: Commit**

```bash
git add frontend/lib/api.ts
git commit -m "feat: add bookmark, note, and space API client methods"
```

---

## Task 8: Frontend — i18n Translations

**Files:**
- Modify: `frontend/app/messages/en.json`
- Modify: `frontend/app/messages/fr.json`

- [ ] **Step 1: Add English translations**

Add the following keys to `frontend/app/messages/en.json`:

```json
{
  "nav": {
    "bookmarks": "Bookmarks",
    "notes": "Notes",
    "spaces": "Spaces"
  },
  "bookmarks": {
    "title": "Bookmarks",
    "add": "Add Bookmark",
    "url_placeholder": "Paste URL here...",
    "title_label": "Title",
    "description_label": "Description",
    "tags_label": "Tags (required)",
    "search_placeholder": "Search bookmarks...",
    "empty": "No bookmarks yet. Save your first link!",
    "delete_confirm": "Delete this bookmark?",
    "added": "Bookmark saved",
    "deleted": "Bookmark deleted"
  },
  "notes": {
    "title": "Notes",
    "new": "New Note",
    "title_label": "Title",
    "content_label": "Content",
    "tags_label": "Tags",
    "search_placeholder": "Search notes...",
    "empty": "No notes yet. Create your first note!",
    "delete_confirm": "Delete this note?",
    "saved": "Note saved",
    "deleted": "Note deleted"
  },
  "spaces": {
    "title": "Spaces",
    "create": "Create Space",
    "name_label": "Name",
    "description_label": "Description",
    "icon_label": "Icon",
    "search_placeholder": "Search spaces...",
    "empty": "No spaces yet. Create your first space!",
    "delete_confirm": "Delete this space and all its contents?",
    "items_tab": "Items",
    "rules_tab": "Rules",
    "add_items": "Add Items",
    "sync_now": "Sync Now",
    "syncing": "Syncing...",
    "add_rule": "Add Rule",
    "rule_tag": "Tag",
    "rule_keyword": "Keyword",
    "rule_value_placeholder": "Enter tag name or keyword...",
    "items_count": "{count} items",
    "added_by_user": "Manual",
    "added_by_rule": "Auto",
    "no_items": "No items in this space yet.",
    "search_items_placeholder": "Search in this space...",
    "filter_all": "All",
    "filter_documents": "Documents",
    "filter_bookmarks": "Bookmarks",
    "filter_notes": "Notes",
    "created": "Space created",
    "deleted": "Space deleted"
  }
}
```

- [ ] **Step 2: Add French translations**

Add the following keys to `frontend/app/messages/fr.json`:

```json
{
  "nav": {
    "bookmarks": "Favoris",
    "notes": "Notes",
    "spaces": "Espaces"
  },
  "bookmarks": {
    "title": "Favoris",
    "add": "Ajouter un favori",
    "url_placeholder": "Collez l'URL ici...",
    "title_label": "Titre",
    "description_label": "Description",
    "tags_label": "Tags (obligatoire)",
    "search_placeholder": "Rechercher dans les favoris...",
    "empty": "Aucun favori. Enregistrez votre premier lien !",
    "delete_confirm": "Supprimer ce favori ?",
    "added": "Favori enregistr\u00e9",
    "deleted": "Favori supprim\u00e9"
  },
  "notes": {
    "title": "Notes",
    "new": "Nouvelle note",
    "title_label": "Titre",
    "content_label": "Contenu",
    "tags_label": "Tags",
    "search_placeholder": "Rechercher dans les notes...",
    "empty": "Aucune note. Cr\u00e9ez votre premi\u00e8re note !",
    "delete_confirm": "Supprimer cette note ?",
    "saved": "Note enregistr\u00e9e",
    "deleted": "Note supprim\u00e9e"
  },
  "spaces": {
    "title": "Espaces",
    "create": "Cr\u00e9er un espace",
    "name_label": "Nom",
    "description_label": "Description",
    "icon_label": "Ic\u00f4ne",
    "search_placeholder": "Rechercher dans les espaces...",
    "empty": "Aucun espace. Cr\u00e9ez votre premier espace !",
    "delete_confirm": "Supprimer cet espace et tout son contenu ?",
    "items_tab": "\u00c9l\u00e9ments",
    "rules_tab": "R\u00e8gles",
    "add_items": "Ajouter des \u00e9l\u00e9ments",
    "sync_now": "Synchroniser",
    "syncing": "Synchronisation...",
    "add_rule": "Ajouter une r\u00e8gle",
    "rule_tag": "Tag",
    "rule_keyword": "Mot-cl\u00e9",
    "rule_value_placeholder": "Entrez un tag ou mot-cl\u00e9...",
    "items_count": "{count} \u00e9l\u00e9ments",
    "added_by_user": "Manuel",
    "added_by_rule": "Auto",
    "no_items": "Aucun \u00e9l\u00e9ment dans cet espace.",
    "search_items_placeholder": "Rechercher dans cet espace...",
    "filter_all": "Tous",
    "filter_documents": "Documents",
    "filter_bookmarks": "Favoris",
    "filter_notes": "Notes",
    "created": "Espace cr\u00e9\u00e9",
    "deleted": "Espace supprim\u00e9"
  }
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/app/messages/en.json frontend/app/messages/fr.json
git commit -m "feat: add i18n translations for bookmarks, notes, and spaces"
```

---

## Task 9: Frontend — Navigation Update

**Files:**
- Modify: `frontend/components/Navigation.tsx`

- [ ] **Step 1: Read current Navigation.tsx to find the navItems array**

Read `frontend/components/Navigation.tsx` and locate the `navItems` array.

- [ ] **Step 2: Add three new nav items**

Add the following entries to the `navItems` array in `frontend/components/Navigation.tsx`, after the existing entries (before `knowledge-graph`):

```typescript
  {
    href: '/bookmarks',
    labelKey: 'bookmarks' as NavLabelKey,
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
      </svg>
    ),
  },
  {
    href: '/notes',
    labelKey: 'notes' as NavLabelKey,
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
      </svg>
    ),
  },
  {
    href: '/spaces',
    labelKey: 'spaces' as NavLabelKey,
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
      </svg>
    ),
  },
```

Also update the `NavLabelKey` type to include the new keys:

```typescript
type NavLabelKey =
  | 'home' | 'search' | 'documents' | 'chat' | 'collections' | 'smart_folders'
  | 'knowledge_graph' | 'dashboard' | 'monitoring' | 'settings' | 'journal'
  | 'bookmarks' | 'notes' | 'spaces';
```

- [ ] **Step 3: Commit**

```bash
git add frontend/components/Navigation.tsx
git commit -m "feat: add bookmarks, notes, spaces to navigation sidebar"
```

---

## Task 10: Frontend — TagSelector Component

**Files:**
- Create: `frontend/components/TagSelector.tsx`

- [ ] **Step 1: Write the TagSelector component**

```tsx
// frontend/components/TagSelector.tsx
'use client';

import { useState, useCallback } from 'react';
import { useTranslations } from 'next-intl';

interface TagItem {
  tag_name: string;
  tag_type?: string;
}

interface TagSelectorProps {
  tags: TagItem[];
  onChange: (tags: TagItem[]) => void;
  required?: boolean;
  placeholder?: string;
}

export default function TagSelector({ tags, onChange, required = false, placeholder }: TagSelectorProps) {
  const tCommon = useTranslations('common');
  const [input, setInput] = useState('');

  const addTag = useCallback(() => {
    const trimmed = input.trim().toLowerCase();
    if (!trimmed) return;
    if (tags.some(t => t.tag_name === trimmed)) {
      setInput('');
      return;
    }
    onChange([...tags, { tag_name: trimmed, tag_type: 'custom' }]);
    setInput('');
  }, [input, tags, onChange]);

  const removeTag = useCallback((tagName: string) => {
    onChange(tags.filter(t => t.tag_name !== tagName));
  }, [tags, onChange]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault();
      addTag();
    }
    if (e.key === 'Backspace' && !input && tags.length > 0) {
      removeTag(tags[tags.length - 1].tag_name);
    }
  }, [addTag, input, tags, removeTag]);

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2 min-h-[32px]">
        {tags.map(tag => (
          <span
            key={tag.tag_name}
            className="inline-flex items-center gap-1 px-2 py-1 text-sm rounded-full bg-amber-100 dark:bg-amber-900 text-amber-800 dark:text-amber-200"
          >
            {tag.tag_name}
            <button
              type="button"
              onClick={() => removeTag(tag.tag_name)}
              className="ml-1 text-amber-600 dark:text-amber-400 hover:text-amber-800 dark:hover:text-amber-200"
            >
              &times;
            </button>
          </span>
        ))}
      </div>
      <div className="flex gap-2">
        <input
          type="text"
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder || 'Add tag...'}
          className="flex-1 px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 focus:ring-2 focus:ring-amber-500 focus:border-transparent"
        />
        <button
          type="button"
          onClick={addTag}
          disabled={!input.trim()}
          className="px-3 py-2 rounded-lg bg-amber-500 text-white hover:bg-amber-600 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          +
        </button>
      </div>
      {required && tags.length === 0 && (
        <p className="text-sm text-red-500">At least one tag is required</p>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/components/TagSelector.tsx
git commit -m "feat: add reusable TagSelector component"
```

---

## Task 11: Frontend — Bookmarks Page

**Files:**
- Create: `frontend/app/[locale]/bookmarks/page.tsx`

- [ ] **Step 1: Write the Bookmarks page**

```tsx
// frontend/app/[locale]/bookmarks/page.tsx
'use client';

export const dynamic = 'force-dynamic';

import { useState, useEffect, useCallback } from 'react';
import { useTranslations, useLocale } from 'next-intl';
import TagSelector from '@/components/TagSelector';

interface TagItem {
  id: string;
  tag_name: string;
  tag_type: string;
}

interface Bookmark {
  id: string;
  url: string;
  title: string;
  description: string | null;
  favicon_url: string | null;
  bucket: string;
  tags: TagItem[];
  created_at: string;
  updated_at: string;
}

interface BookmarksResponse {
  bookmarks: Bookmark[];
  total: number;
  page: number;
  page_size: number;
}

export default function BookmarksPage() {
  const t = useTranslations('bookmarks');
  const tCommon = useTranslations('common');
  const locale = useLocale();

  const [bookmarks, setBookmarks] = useState<Bookmark[]>([]);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [searchQuery, setSearchQuery] = useState('');
  const [showCreateModal, setShowCreateModal] = useState(false);

  // Create form state
  const [newUrl, setNewUrl] = useState('');
  const [newTitle, setNewTitle] = useState('');
  const [newDescription, setNewDescription] = useState('');
  const [newTags, setNewTags] = useState<Array<{ tag_name: string; tag_type?: string }>>([]);
  const [creating, setCreating] = useState(false);

  const fetchBookmarks = useCallback(async () => {
    try {
      setLoading(true);
      const { api } = await import('@/lib/api');
      const response = searchQuery
        ? await api.searchBookmarks(searchQuery, page, 50)
        : await api.getBookmarks(page, 50);
      if (response.data && !response.error) {
        const data = response.data as BookmarksResponse;
        setBookmarks(data.bookmarks);
        setTotal(data.total);
      }
    } catch (error) {
      console.error('Error fetching bookmarks:', error);
    } finally {
      setLoading(false);
    }
  }, [page, searchQuery]);

  useEffect(() => { fetchBookmarks(); }, [fetchBookmarks]);

  const handleCreate = async () => {
    if (!newUrl || newTags.length === 0) return;
    setCreating(true);
    try {
      const { api } = await import('@/lib/api');
      const response = await api.createBookmark(newUrl, newTags, newTitle || undefined, newDescription || undefined);
      if (response.data && !response.error) {
        setShowCreateModal(false);
        setNewUrl(''); setNewTitle(''); setNewDescription(''); setNewTags([]);
        fetchBookmarks();
      }
    } catch (error) {
      console.error('Error creating bookmark:', error);
    } finally {
      setCreating(false);
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm(t('delete_confirm'))) return;
    try {
      const { api } = await import('@/lib/api');
      await api.deleteBookmark(id);
      fetchBookmarks();
    } catch (error) {
      console.error('Error deleting bookmark:', error);
    }
  };

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    setPage(1);
    fetchBookmarks();
  };

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900">
      <div className="max-w-6xl mx-auto px-4 py-8">
        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">{t('title')}</h1>
          <button
            onClick={() => setShowCreateModal(true)}
            className="px-4 py-2 bg-amber-500 text-white rounded-lg hover:bg-amber-600 transition-colors"
          >
            {t('add')}
          </button>
        </div>

        {/* Search */}
        <form onSubmit={handleSearch} className="mb-6">
          <input
            type="text"
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            placeholder={t('search_placeholder')}
            className="w-full px-4 py-3 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:ring-2 focus:ring-amber-500"
          />
        </form>

        {/* Loading / Empty / List */}
        {loading ? (
          <div className="flex justify-center py-12">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-amber-500" />
          </div>
        ) : bookmarks.length === 0 ? (
          <p className="text-center text-gray-500 dark:text-gray-400 py-12">{t('empty')}</p>
        ) : (
          <div className="grid gap-4">
            {bookmarks.map(bookmark => (
              <div key={bookmark.id} className="p-4 bg-white dark:bg-gray-800 rounded-lg shadow-sm border border-gray-200 dark:border-gray-700">
                <div className="flex items-start justify-between">
                  <div className="flex-1 min-w-0">
                    <a
                      href={bookmark.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-lg font-medium text-amber-600 dark:text-amber-400 hover:underline truncate block"
                    >
                      {bookmark.favicon_url && (
                        <img src={bookmark.favicon_url} alt="" className="inline w-4 h-4 mr-2" />
                      )}
                      {bookmark.title}
                    </a>
                    <p className="text-sm text-gray-500 dark:text-gray-400 truncate mt-1">{bookmark.url}</p>
                    {bookmark.description && (
                      <p className="text-sm text-gray-600 dark:text-gray-300 mt-2">{bookmark.description}</p>
                    )}
                    <div className="flex flex-wrap gap-1 mt-3">
                      {bookmark.tags.map(tag => (
                        <span key={tag.id} className="px-2 py-0.5 text-xs rounded-full bg-amber-100 dark:bg-amber-900 text-amber-700 dark:text-amber-300">
                          {tag.tag_name}
                        </span>
                      ))}
                    </div>
                  </div>
                  <button
                    onClick={() => handleDelete(bookmark.id)}
                    className="ml-4 text-gray-400 hover:text-red-500 transition-colors"
                  >
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                    </svg>
                  </button>
                </div>
                <p className="text-xs text-gray-400 mt-2">
                  {new Date(bookmark.created_at).toLocaleDateString(locale)}
                </p>
              </div>
            ))}
          </div>
        )}

        {/* Pagination */}
        {total > 50 && (
          <div className="flex justify-center gap-2 mt-6">
            <button
              disabled={page <= 1}
              onClick={() => setPage(p => p - 1)}
              className="px-3 py-1 rounded bg-gray-200 dark:bg-gray-700 disabled:opacity-50"
            >
              &laquo;
            </button>
            <span className="px-3 py-1 text-gray-600 dark:text-gray-300">
              {page} / {Math.ceil(total / 50)}
            </span>
            <button
              disabled={page >= Math.ceil(total / 50)}
              onClick={() => setPage(p => p + 1)}
              className="px-3 py-1 rounded bg-gray-200 dark:bg-gray-700 disabled:opacity-50"
            >
              &raquo;
            </button>
          </div>
        )}
      </div>

      {/* Create Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-xl max-w-lg w-full p-6">
            <h2 className="text-xl font-bold text-gray-900 dark:text-white mb-4">{t('add')}</h2>
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">URL *</label>
                <input
                  type="url"
                  value={newUrl}
                  onChange={e => setNewUrl(e.target.value)}
                  placeholder={t('url_placeholder')}
                  className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100"
                  required
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">{t('title_label')}</label>
                <input
                  type="text"
                  value={newTitle}
                  onChange={e => setNewTitle(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">{t('description_label')}</label>
                <textarea
                  value={newDescription}
                  onChange={e => setNewDescription(e.target.value)}
                  rows={2}
                  className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">{t('tags_label')}</label>
                <TagSelector tags={newTags} onChange={setNewTags} required />
              </div>
            </div>
            <div className="flex justify-end gap-3 mt-6">
              <button
                onClick={() => setShowCreateModal(false)}
                className="px-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700"
              >
                {tCommon('cancel')}
              </button>
              <button
                onClick={handleCreate}
                disabled={creating || !newUrl || newTags.length === 0}
                className="px-4 py-2 rounded-lg bg-amber-500 text-white hover:bg-amber-600 disabled:opacity-50"
              >
                {creating ? tCommon('loading') : tCommon('save')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/app/\\[locale\\]/bookmarks/page.tsx
git commit -m "feat: add Bookmarks frontend page"
```

---

## Task 12: Frontend — Notes Page

**Files:**
- Create: `frontend/app/[locale]/notes/page.tsx`

- [ ] **Step 1: Write the Notes page**

```tsx
// frontend/app/[locale]/notes/page.tsx
'use client';

export const dynamic = 'force-dynamic';

import { useState, useEffect, useCallback } from 'react';
import { useTranslations, useLocale } from 'next-intl';
import TagSelector from '@/components/TagSelector';

interface TagItem {
  id: string;
  tag_name: string;
  tag_type: string;
}

interface NoteItem {
  id: string;
  title: string;
  content: string | null;
  bucket: string;
  tags: TagItem[];
  created_at: string;
  updated_at: string;
}

interface NotesResponse {
  notes: NoteItem[];
  total: number;
  page: number;
  page_size: number;
}

export default function NotesPage() {
  const t = useTranslations('notes');
  const tCommon = useTranslations('common');
  const locale = useLocale();

  const [notes, setNotes] = useState<NoteItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [searchQuery, setSearchQuery] = useState('');
  const [showEditor, setShowEditor] = useState(false);
  const [editingNote, setEditingNote] = useState<NoteItem | null>(null);

  // Editor state
  const [editTitle, setEditTitle] = useState('');
  const [editContent, setEditContent] = useState('');
  const [editTags, setEditTags] = useState<Array<{ tag_name: string; tag_type?: string }>>([]);
  const [saving, setSaving] = useState(false);

  const fetchNotes = useCallback(async () => {
    try {
      setLoading(true);
      const { api } = await import('@/lib/api');
      const response = searchQuery
        ? await api.searchNotes(searchQuery, page, 50)
        : await api.getNotes(page, 50);
      if (response.data && !response.error) {
        const data = response.data as NotesResponse;
        setNotes(data.notes);
        setTotal(data.total);
      }
    } catch (error) {
      console.error('Error fetching notes:', error);
    } finally {
      setLoading(false);
    }
  }, [page, searchQuery]);

  useEffect(() => { fetchNotes(); }, [fetchNotes]);

  const openEditor = (note?: NoteItem) => {
    if (note) {
      setEditingNote(note);
      setEditTitle(note.title);
      setEditContent(note.content || '');
      setEditTags(note.tags.map(t => ({ tag_name: t.tag_name, tag_type: t.tag_type })));
    } else {
      setEditingNote(null);
      setEditTitle('');
      setEditContent('');
      setEditTags([]);
    }
    setShowEditor(true);
  };

  const handleSave = async () => {
    if (!editTitle) return;
    setSaving(true);
    try {
      const { api } = await import('@/lib/api');
      if (editingNote) {
        await api.updateNote(editingNote.id, { title: editTitle, content: editContent, tags: editTags });
      } else {
        await api.createNote(editTitle, editContent || undefined, editTags);
      }
      setShowEditor(false);
      fetchNotes();
    } catch (error) {
      console.error('Error saving note:', error);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm(t('delete_confirm'))) return;
    try {
      const { api } = await import('@/lib/api');
      await api.deleteNote(id);
      fetchNotes();
    } catch (error) {
      console.error('Error deleting note:', error);
    }
  };

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    setPage(1);
    fetchNotes();
  };

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900">
      <div className="max-w-6xl mx-auto px-4 py-8">
        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">{t('title')}</h1>
          <button
            onClick={() => openEditor()}
            className="px-4 py-2 bg-amber-500 text-white rounded-lg hover:bg-amber-600 transition-colors"
          >
            {t('new')}
          </button>
        </div>

        {/* Search */}
        <form onSubmit={handleSearch} className="mb-6">
          <input
            type="text"
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            placeholder={t('search_placeholder')}
            className="w-full px-4 py-3 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:ring-2 focus:ring-amber-500"
          />
        </form>

        {/* Loading / Empty / Grid */}
        {loading ? (
          <div className="flex justify-center py-12">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-amber-500" />
          </div>
        ) : notes.length === 0 ? (
          <p className="text-center text-gray-500 dark:text-gray-400 py-12">{t('empty')}</p>
        ) : (
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {notes.map(note => (
              <div
                key={note.id}
                className="p-4 bg-white dark:bg-gray-800 rounded-lg shadow-sm border border-gray-200 dark:border-gray-700 cursor-pointer hover:shadow-md transition-shadow"
                onClick={() => openEditor(note)}
              >
                <div className="flex items-start justify-between">
                  <h3 className="font-medium text-gray-900 dark:text-white truncate flex-1">{note.title}</h3>
                  <button
                    onClick={e => { e.stopPropagation(); handleDelete(note.id); }}
                    className="ml-2 text-gray-400 hover:text-red-500 transition-colors"
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                    </svg>
                  </button>
                </div>
                {note.content && (
                  <p className="text-sm text-gray-600 dark:text-gray-300 mt-2 line-clamp-3">{note.content}</p>
                )}
                <div className="flex flex-wrap gap-1 mt-3">
                  {note.tags.map(tag => (
                    <span key={tag.id} className="px-2 py-0.5 text-xs rounded-full bg-amber-100 dark:bg-amber-900 text-amber-700 dark:text-amber-300">
                      {tag.tag_name}
                    </span>
                  ))}
                </div>
                <p className="text-xs text-gray-400 mt-2">
                  {new Date(note.created_at).toLocaleDateString(locale)}
                </p>
              </div>
            ))}
          </div>
        )}

        {/* Pagination */}
        {total > 50 && (
          <div className="flex justify-center gap-2 mt-6">
            <button disabled={page <= 1} onClick={() => setPage(p => p - 1)} className="px-3 py-1 rounded bg-gray-200 dark:bg-gray-700 disabled:opacity-50">&laquo;</button>
            <span className="px-3 py-1 text-gray-600 dark:text-gray-300">{page} / {Math.ceil(total / 50)}</span>
            <button disabled={page >= Math.ceil(total / 50)} onClick={() => setPage(p => p + 1)} className="px-3 py-1 rounded bg-gray-200 dark:bg-gray-700 disabled:opacity-50">&raquo;</button>
          </div>
        )}
      </div>

      {/* Editor Modal */}
      {showEditor && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-xl max-w-lg w-full p-6">
            <h2 className="text-xl font-bold text-gray-900 dark:text-white mb-4">
              {editingNote ? editingNote.title : t('new')}
            </h2>
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">{t('title_label')} *</label>
                <input
                  type="text"
                  value={editTitle}
                  onChange={e => setEditTitle(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100"
                  required
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">{t('content_label')}</label>
                <textarea
                  value={editContent}
                  onChange={e => setEditContent(e.target.value)}
                  rows={8}
                  className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 font-mono text-sm"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">{t('tags_label')}</label>
                <TagSelector tags={editTags} onChange={setEditTags} />
              </div>
            </div>
            <div className="flex justify-end gap-3 mt-6">
              <button
                onClick={() => setShowEditor(false)}
                className="px-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700"
              >
                {tCommon('cancel')}
              </button>
              <button
                onClick={handleSave}
                disabled={saving || !editTitle}
                className="px-4 py-2 rounded-lg bg-amber-500 text-white hover:bg-amber-600 disabled:opacity-50"
              >
                {saving ? tCommon('loading') : tCommon('save')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/app/\\[locale\\]/notes/page.tsx
git commit -m "feat: add Notes frontend page"
```

---

## Task 13: Frontend — Spaces List Page

**Files:**
- Create: `frontend/app/[locale]/spaces/page.tsx`

- [ ] **Step 1: Write the Spaces list page**

```tsx
// frontend/app/[locale]/spaces/page.tsx
'use client';

export const dynamic = 'force-dynamic';

import { useState, useEffect, useCallback } from 'react';
import { useTranslations, useLocale } from 'next-intl';
import { Link as IntlLink } from '@/i18n/routing';

interface SpaceItem {
  id: string;
  name: string;
  description: string | null;
  icon: string | null;
  bucket: string;
  is_pinned: boolean;
  item_count: number;
  created_at: string;
  updated_at: string;
}

interface SpacesResponse {
  spaces: SpaceItem[];
  total: number;
  page: number;
  page_size: number;
}

export default function SpacesPage() {
  const t = useTranslations('spaces');
  const tCommon = useTranslations('common');
  const locale = useLocale();

  const [spaces, setSpaces] = useState<SpaceItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [searchQuery, setSearchQuery] = useState('');
  const [showCreateModal, setShowCreateModal] = useState(false);

  const [newName, setNewName] = useState('');
  const [newDescription, setNewDescription] = useState('');
  const [newIcon, setNewIcon] = useState('');
  const [creating, setCreating] = useState(false);

  const fetchSpaces = useCallback(async () => {
    try {
      setLoading(true);
      const { api } = await import('@/lib/api');
      const response = await api.getSpaces(page, 50, searchQuery || undefined);
      if (response.data && !response.error) {
        const data = response.data as SpacesResponse;
        setSpaces(data.spaces);
        setTotal(data.total);
      }
    } catch (error) {
      console.error('Error fetching spaces:', error);
    } finally {
      setLoading(false);
    }
  }, [page, searchQuery]);

  useEffect(() => { fetchSpaces(); }, [fetchSpaces]);

  const handleCreate = async () => {
    if (!newName) return;
    setCreating(true);
    try {
      const { api } = await import('@/lib/api');
      const response = await api.createSpace(newName, newDescription || undefined, newIcon || undefined);
      if (response.data && !response.error) {
        setShowCreateModal(false);
        setNewName(''); setNewDescription(''); setNewIcon('');
        fetchSpaces();
      }
    } catch (error) {
      console.error('Error creating space:', error);
    } finally {
      setCreating(false);
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm(t('delete_confirm'))) return;
    try {
      const { api } = await import('@/lib/api');
      await api.deleteSpace(id);
      fetchSpaces();
    } catch (error) {
      console.error('Error deleting space:', error);
    }
  };

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    setPage(1);
    fetchSpaces();
  };

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900">
      <div className="max-w-6xl mx-auto px-4 py-8">
        <div className="flex items-center justify-between mb-8">
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">{t('title')}</h1>
          <button onClick={() => setShowCreateModal(true)} className="px-4 py-2 bg-amber-500 text-white rounded-lg hover:bg-amber-600 transition-colors">
            {t('create')}
          </button>
        </div>

        <form onSubmit={handleSearch} className="mb-6">
          <input type="text" value={searchQuery} onChange={e => setSearchQuery(e.target.value)}
            placeholder={t('search_placeholder')}
            className="w-full px-4 py-3 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:ring-2 focus:ring-amber-500" />
        </form>

        {loading ? (
          <div className="flex justify-center py-12">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-amber-500" />
          </div>
        ) : spaces.length === 0 ? (
          <p className="text-center text-gray-500 dark:text-gray-400 py-12">{t('empty')}</p>
        ) : (
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {spaces.map(space => (
              <div key={space.id} className="relative bg-white dark:bg-gray-800 rounded-lg shadow-sm border border-gray-200 dark:border-gray-700 hover:shadow-md transition-shadow">
                <IntlLink href={`/spaces/${space.id}`} className="block p-4">
                  <div className="flex items-center gap-3 mb-2">
                    <span className="text-2xl">{space.icon || '📁'}</span>
                    <div className="flex-1 min-w-0">
                      <h3 className="font-medium text-gray-900 dark:text-white truncate">{space.name}</h3>
                      <p className="text-sm text-gray-500 dark:text-gray-400">
                        {t('items_count', { count: space.item_count })}
                      </p>
                    </div>
                    {space.is_pinned && <span className="text-amber-500">📌</span>}
                  </div>
                  {space.description && (
                    <p className="text-sm text-gray-600 dark:text-gray-300 line-clamp-2">{space.description}</p>
                  )}
                  <p className="text-xs text-gray-400 mt-3">
                    {new Date(space.updated_at).toLocaleDateString(locale)}
                  </p>
                </IntlLink>
                <button
                  onClick={e => { e.preventDefault(); handleDelete(space.id); }}
                  className="absolute top-4 right-4 text-gray-400 hover:text-red-500 transition-colors"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                  </svg>
                </button>
              </div>
            ))}
          </div>
        )}

        {total > 50 && (
          <div className="flex justify-center gap-2 mt-6">
            <button disabled={page <= 1} onClick={() => setPage(p => p - 1)} className="px-3 py-1 rounded bg-gray-200 dark:bg-gray-700 disabled:opacity-50">&laquo;</button>
            <span className="px-3 py-1 text-gray-600 dark:text-gray-300">{page} / {Math.ceil(total / 50)}</span>
            <button disabled={page >= Math.ceil(total / 50)} onClick={() => setPage(p => p + 1)} className="px-3 py-1 rounded bg-gray-200 dark:bg-gray-700 disabled:opacity-50">&raquo;</button>
          </div>
        )}
      </div>

      {/* Create Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-xl max-w-lg w-full p-6">
            <h2 className="text-xl font-bold text-gray-900 dark:text-white mb-4">{t('create')}</h2>
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">{t('name_label')} *</label>
                <input type="text" value={newName} onChange={e => setNewName(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100" required />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">{t('description_label')}</label>
                <textarea value={newDescription} onChange={e => setNewDescription(e.target.value)} rows={2}
                  className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100" />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">{t('icon_label')}</label>
                <input type="text" value={newIcon} onChange={e => setNewIcon(e.target.value)} placeholder="📁"
                  className="w-20 px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 text-center text-xl" />
              </div>
            </div>
            <div className="flex justify-end gap-3 mt-6">
              <button onClick={() => setShowCreateModal(false)}
                className="px-4 py-2 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700">
                {tCommon('cancel')}
              </button>
              <button onClick={handleCreate} disabled={creating || !newName}
                className="px-4 py-2 rounded-lg bg-amber-500 text-white hover:bg-amber-600 disabled:opacity-50">
                {creating ? tCommon('loading') : tCommon('save')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/app/\\[locale\\]/spaces/page.tsx
git commit -m "feat: add Spaces list frontend page"
```

---

## Task 14: Frontend — Space Detail Page

**Files:**
- Create: `frontend/app/[locale]/spaces/[id]/page.tsx`

- [ ] **Step 1: Write the Space detail page**

This is the largest frontend component. It includes: items tab, rules tab, add items modal, sync button, local search, type filters.

```tsx
// frontend/app/[locale]/spaces/[id]/page.tsx
'use client';

export const dynamic = 'force-dynamic';

import { useState, useEffect, useCallback } from 'react';
import { useTranslations, useLocale } from 'next-intl';
import { useParams } from 'next/navigation';

interface TagItem { id: string; tag_name: string; tag_type: string; }

interface SpaceItemData {
  id: string;
  space_id: string;
  item_type: string;
  document_id: string | null;
  bookmark_id: string | null;
  note_id: string | null;
  added_by: string;
  added_at: string;
  note: string | null;
  is_excluded: boolean;
  item_title: string | null;
  item_url: string | null;
  item_tags: TagItem[];
}

interface SpaceRuleData {
  id: string;
  space_id: string;
  rule_type: string;
  rule_value: string;
  is_active: boolean;
  match_count: number;
  created_at: string;
}

interface SpaceDetail {
  id: string;
  name: string;
  description: string | null;
  icon: string | null;
  bucket: string;
  is_pinned: boolean;
  item_count: number;
  items: SpaceItemData[];
  rules: SpaceRuleData[];
  created_at: string;
  updated_at: string;
}

export default function SpaceDetailPage() {
  const t = useTranslations('spaces');
  const tCommon = useTranslations('common');
  const locale = useLocale();
  const params = useParams();
  const spaceId = params.id as string;

  const [space, setSpace] = useState<SpaceDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<'items' | 'rules'>('items');
  const [typeFilter, setTypeFilter] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [syncing, setSyncing] = useState(false);

  // Rule form
  const [showRuleForm, setShowRuleForm] = useState(false);
  const [newRuleType, setNewRuleType] = useState<'tag' | 'keyword'>('tag');
  const [newRuleValue, setNewRuleValue] = useState('');

  const fetchSpace = useCallback(async () => {
    try {
      setLoading(true);
      const { api } = await import('@/lib/api');
      const response = await api.getSpace(spaceId, typeFilter || undefined);
      if (response.data && !response.error) {
        setSpace(response.data as SpaceDetail);
      }
    } catch (error) {
      console.error('Error fetching space:', error);
    } finally {
      setLoading(false);
    }
  }, [spaceId, typeFilter]);

  useEffect(() => { fetchSpace(); }, [fetchSpace]);

  const handleSync = async () => {
    setSyncing(true);
    try {
      const { api } = await import('@/lib/api');
      await api.syncSpace(spaceId);
      // Wait a moment then refresh
      setTimeout(() => { fetchSpace(); setSyncing(false); }, 3000);
    } catch (error) {
      console.error('Error syncing space:', error);
      setSyncing(false);
    }
  };

  const handleRemoveItem = async (itemId: string) => {
    try {
      const { api } = await import('@/lib/api');
      await api.removeSpaceItem(spaceId, itemId);
      fetchSpace();
    } catch (error) {
      console.error('Error removing item:', error);
    }
  };

  const handleAddRule = async () => {
    if (!newRuleValue) return;
    try {
      const { api } = await import('@/lib/api');
      await api.addSpaceRule(spaceId, newRuleType, newRuleValue);
      setNewRuleValue('');
      setShowRuleForm(false);
      fetchSpace();
    } catch (error) {
      console.error('Error adding rule:', error);
    }
  };

  const handleToggleRule = async (ruleId: string, isActive: boolean) => {
    try {
      const { api } = await import('@/lib/api');
      await api.updateSpaceRule(spaceId, ruleId, { is_active: !isActive });
      fetchSpace();
    } catch (error) {
      console.error('Error toggling rule:', error);
    }
  };

  const handleDeleteRule = async (ruleId: string) => {
    try {
      const { api } = await import('@/lib/api');
      await api.deleteSpaceRule(spaceId, ruleId);
      fetchSpace();
    } catch (error) {
      console.error('Error deleting rule:', error);
    }
  };

  const filteredItems = space?.items.filter(item => {
    if (!searchQuery) return true;
    const q = searchQuery.toLowerCase();
    return (item.item_title || '').toLowerCase().includes(q) ||
      item.item_tags.some(t => t.tag_name.toLowerCase().includes(q));
  }) || [];

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50 dark:bg-gray-900 flex justify-center items-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-amber-500" />
      </div>
    );
  }

  if (!space) {
    return (
      <div className="min-h-screen bg-gray-50 dark:bg-gray-900 flex justify-center items-center">
        <p className="text-gray-500">Space not found</p>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900">
      <div className="max-w-6xl mx-auto px-4 py-8">
        {/* Header */}
        <div className="flex items-center gap-4 mb-6">
          <span className="text-3xl">{space.icon || '📁'}</span>
          <div className="flex-1">
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">{space.name}</h1>
            {space.description && (
              <p className="text-gray-600 dark:text-gray-300 mt-1">{space.description}</p>
            )}
          </div>
          <span className="text-sm text-gray-500 dark:text-gray-400">
            {t('items_count', { count: space.item_count })}
          </span>
        </div>

        {/* Tabs */}
        <div className="flex gap-4 border-b border-gray-200 dark:border-gray-700 mb-6">
          <button
            onClick={() => setActiveTab('items')}
            className={`pb-3 px-1 text-sm font-medium border-b-2 transition-colors ${
              activeTab === 'items' ? 'border-amber-500 text-amber-600 dark:text-amber-400' : 'border-transparent text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'
            }`}
          >
            {t('items_tab')}
          </button>
          <button
            onClick={() => setActiveTab('rules')}
            className={`pb-3 px-1 text-sm font-medium border-b-2 transition-colors ${
              activeTab === 'rules' ? 'border-amber-500 text-amber-600 dark:text-amber-400' : 'border-transparent text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'
            }`}
          >
            {t('rules_tab')} ({space.rules.length})
          </button>
        </div>

        {/* Items Tab */}
        {activeTab === 'items' && (
          <div>
            {/* Search + Filters */}
            <div className="flex gap-3 mb-4 flex-wrap">
              <input
                type="text"
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
                placeholder={t('search_items_placeholder')}
                className="flex-1 min-w-[200px] px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100"
              />
              {[null, 'document', 'bookmark', 'note'].map(ft => (
                <button
                  key={ft || 'all'}
                  onClick={() => setTypeFilter(ft)}
                  className={`px-3 py-2 rounded-lg text-sm ${
                    typeFilter === ft ? 'bg-amber-500 text-white' : 'bg-gray-200 dark:bg-gray-700 text-gray-700 dark:text-gray-300'
                  }`}
                >
                  {ft === null ? t('filter_all') : t(`filter_${ft}s`)}
                </button>
              ))}
            </div>

            {/* Items List */}
            {filteredItems.length === 0 ? (
              <p className="text-center text-gray-500 dark:text-gray-400 py-8">{t('no_items')}</p>
            ) : (
              <div className="space-y-3">
                {filteredItems.map(item => (
                  <div key={item.id} className="flex items-center gap-3 p-3 bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700">
                    {/* Type icon */}
                    <span className="text-lg">
                      {item.item_type === 'document' ? '📄' : item.item_type === 'bookmark' ? '🔗' : '📝'}
                    </span>
                    <div className="flex-1 min-w-0">
                      <p className="font-medium text-gray-900 dark:text-white truncate">
                        {item.item_url ? (
                          <a href={item.item_url} target="_blank" rel="noopener noreferrer" className="hover:underline text-amber-600 dark:text-amber-400">
                            {item.item_title || 'Untitled'}
                          </a>
                        ) : (
                          item.item_title || 'Untitled'
                        )}
                      </p>
                      <div className="flex flex-wrap gap-1 mt-1">
                        {item.item_tags.map(tag => (
                          <span key={tag.id} className="px-1.5 py-0.5 text-xs rounded bg-amber-100 dark:bg-amber-900 text-amber-700 dark:text-amber-300">
                            {tag.tag_name}
                          </span>
                        ))}
                      </div>
                    </div>
                    <span className={`text-xs px-2 py-1 rounded ${
                      item.added_by === 'rule' ? 'bg-blue-100 dark:bg-blue-900 text-blue-700 dark:text-blue-300' : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400'
                    }`}>
                      {item.added_by === 'rule' ? t('added_by_rule') : t('added_by_user')}
                    </span>
                    <button
                      onClick={() => handleRemoveItem(item.id)}
                      className="text-gray-400 hover:text-red-500"
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                      </svg>
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Rules Tab */}
        {activeTab === 'rules' && (
          <div>
            <div className="flex gap-3 mb-4">
              <button onClick={() => setShowRuleForm(true)}
                className="px-4 py-2 bg-amber-500 text-white rounded-lg hover:bg-amber-600">
                {t('add_rule')}
              </button>
              <button onClick={handleSync} disabled={syncing}
                className="px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 disabled:opacity-50">
                {syncing ? t('syncing') : t('sync_now')}
              </button>
            </div>

            {/* Add Rule Form */}
            {showRuleForm && (
              <div className="p-4 mb-4 bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700">
                <div className="flex gap-3">
                  <select
                    value={newRuleType}
                    onChange={e => setNewRuleType(e.target.value as 'tag' | 'keyword')}
                    className="px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100"
                  >
                    <option value="tag">{t('rule_tag')}</option>
                    <option value="keyword">{t('rule_keyword')}</option>
                  </select>
                  <input
                    type="text"
                    value={newRuleValue}
                    onChange={e => setNewRuleValue(e.target.value)}
                    placeholder={t('rule_value_placeholder')}
                    className="flex-1 px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100"
                  />
                  <button onClick={handleAddRule} disabled={!newRuleValue}
                    className="px-4 py-2 bg-amber-500 text-white rounded-lg hover:bg-amber-600 disabled:opacity-50">
                    {tCommon('save')}
                  </button>
                  <button onClick={() => { setShowRuleForm(false); setNewRuleValue(''); }}
                    className="px-4 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-gray-700 dark:text-gray-300">
                    {tCommon('cancel')}
                  </button>
                </div>
              </div>
            )}

            {/* Rules List */}
            {space.rules.length === 0 ? (
              <p className="text-center text-gray-500 dark:text-gray-400 py-8">No rules defined yet.</p>
            ) : (
              <div className="space-y-3">
                {space.rules.map(rule => (
                  <div key={rule.id} className="flex items-center gap-3 p-3 bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700">
                    <span className={`text-xs px-2 py-1 rounded font-mono ${
                      rule.rule_type === 'tag' ? 'bg-purple-100 dark:bg-purple-900 text-purple-700 dark:text-purple-300' : 'bg-green-100 dark:bg-green-900 text-green-700 dark:text-green-300'
                    }`}>
                      {rule.rule_type}
                    </span>
                    <span className="flex-1 text-gray-900 dark:text-white font-medium">{rule.rule_value}</span>
                    <span className="text-sm text-gray-500">{rule.match_count} matches</span>
                    <button
                      onClick={() => handleToggleRule(rule.id, rule.is_active)}
                      className={`px-3 py-1 rounded text-sm ${
                        rule.is_active ? 'bg-green-100 dark:bg-green-900 text-green-700 dark:text-green-300' : 'bg-gray-200 dark:bg-gray-700 text-gray-500'
                      }`}
                    >
                      {rule.is_active ? 'Active' : 'Inactive'}
                    </button>
                    <button onClick={() => handleDeleteRule(rule.id)} className="text-gray-400 hover:text-red-500">
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                      </svg>
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/app/\\[locale\\]/spaces/\\[id\\]/page.tsx
git commit -m "feat: add Space detail frontend page with items and rules tabs"
```

---

## Task 15: Update Auto-Tagging Service to Use New Tag Model

**Files:**
- Modify: `backend/app/services/auto_tagging_service.py`

- [ ] **Step 1: Read the current auto_tagging_service.py**

Read `backend/app/services/auto_tagging_service.py` to understand how DocumentTag is used.

- [ ] **Step 2: Replace DocumentTag references with Tag model**

Replace all imports and usages of `DocumentTag` with the new `Tag` model from `app.models.tag`. Change:

```python
# Old:
from app.models.document import DocumentTag
# ...
tag = DocumentTag(
    document_id=document_id,
    tag_name=name,
    tag_type=tag_type,
    auto_generated=True,
    confidence_score=score,
)

# New:
from app.models.tag import Tag, TagType, TargetType
# ...
tag = Tag(
    id=uuid.uuid4(),
    tag_name=name,
    tag_type=TagType(tag_type),
    target_type=TargetType.DOCUMENT,
    target_id=document_id,
    auto_generated=True,
    confidence_score=score,
)
```

Also update any queries that filter by `DocumentTag.document_id` to use `Tag.target_type == TargetType.DOCUMENT` and `Tag.target_id`.

- [ ] **Step 3: Run existing tests to verify nothing breaks**

Run: `cd /home/development/src/active/sowknow4/backend && python -m pytest tests/unit/ -v --timeout=60`
Expected: All existing tests should still pass.

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/auto_tagging_service.py
git commit -m "refactor: update auto_tagging_service to use generalized Tag model"
```

---

## Task 16: Extend Global Search with Type Filters

**Files:**
- Modify: `backend/app/services/search_service.py`
- Modify: `frontend/app/[locale]/search/page.tsx`

- [ ] **Step 1: Read current search_service.py to find the main search method**

Read `backend/app/services/search_service.py` to understand the main `search()` or `hybrid_search()` method signature.

- [ ] **Step 2: Add type-filtered search to the search service**

Add a new method `search_all_types()` to `HybridSearchService` that searches across documents, bookmarks, notes, and spaces, returning results with a `result_type` field. This method should:
- Accept a `types` parameter (list of strings: "document", "bookmark", "note", "space")
- For documents: use existing hybrid search
- For bookmarks: ILIKE on title/description/url + tag search
- For notes: ILIKE on title/content + tag search
- For spaces: ILIKE on name/description
- Merge and return results with `result_type` field

- [ ] **Step 3: Update the search page to show type filter chips**

Read `frontend/app/[locale]/search/page.tsx`, then add type filter chips (All, Documents, Bookmarks, Notes, Spaces) above the search results. Pass the selected type(s) as a query parameter.

- [ ] **Step 4: Run tests**

Run: `cd /home/development/src/active/sowknow4/backend && python -m pytest tests/unit/ -v --timeout=60`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/search_service.py frontend/app/\\[locale\\]/search/page.tsx
git commit -m "feat: extend global search with type filters for bookmarks, notes, spaces"
```

---

## Review Checkpoint

After completing all 16 tasks:

- [ ] **Verify backend starts**: `cd /home/development/src/active/sowknow4/backend && python -c "from app.main import app; print('OK')"`
- [ ] **Verify frontend builds**: `cd /home/development/src/active/sowknow4/frontend && npx next build`
- [ ] **Run all unit tests**: `cd /home/development/src/active/sowknow4/backend && python -m pytest tests/unit/ -v`
- [ ] **Run migration dry-run**: `cd /home/development/src/active/sowknow4/backend && alembic upgrade head --sql` (review SQL output)
- [ ] **Manual smoke test**: Start containers, create a bookmark with tags, create a note, create a space, add items, add rules, sync, verify global search returns all types
