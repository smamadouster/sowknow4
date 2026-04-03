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
                SpaceItem.space_id == space_id, SpaceItem.is_excluded == False  # noqa: E712
            )
        )
        return result.scalar() or 0

    # --- SpaceItem ---

    async def add_item(self, db: AsyncSession, space_id: uuid.UUID,
                       item_type: str, item_id: uuid.UUID,
                       added_by: str = "user", note: str | None = None) -> SpaceItem:
        # Check for existing (including excluded -- re-include it)
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
            SpaceItem.space_id == space_id, SpaceItem.is_excluded == False  # noqa: E712
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
            note_obj = (await db.execute(select(Note).where(Note.id == item.note_id))).scalar_one_or_none()
            if note_obj:
                title = note_obj.title
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
                SpaceItem.space_id == rule.space_id, SpaceItem.is_excluded == False  # noqa: E712
            )
        )).scalar() or 0

    # --- Rule Sync Engine ---

    async def sync_space_rules(self, db: AsyncSession, space: Space) -> int:
        """Evaluate all active rules and add matching items. Returns count of new items added."""
        rules = await db.execute(
            select(SpaceRule).where(SpaceRule.space_id == space.id, SpaceRule.is_active == True)  # noqa: E712
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
            select(SpaceRule).where(SpaceRule.is_active == True)  # noqa: E712
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
