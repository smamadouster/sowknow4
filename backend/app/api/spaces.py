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

    try:
        from app.tasks.space_tasks import sync_space_rules_task
        sync_space_rules_task.delay(str(space_id))
    except ImportError:
        logger.warning("space_tasks not yet available; sync will be available after Task 5")
        raise HTTPException(status_code=501, detail="Sync task not yet implemented")
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
