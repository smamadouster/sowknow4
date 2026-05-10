import logging
import os
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.push_subscription import PushSubscription
from app.models.user import User
from app.schemas.push import PushSubscriptionCreate, PushSubscriptionResponse

router = APIRouter(prefix="/push", tags=["push"])
logger = logging.getLogger(__name__)


@router.get("/vapid-public-key")
async def get_vapid_public_key() -> dict:
    """Return the VAPID public key for frontend push subscription."""
    public_key = os.getenv("VAPID_PUBLIC_KEY", "")
    return {"public_key": public_key}


@router.post("/subscribe", response_model=PushSubscriptionResponse, status_code=status.HTTP_201_CREATED)
async def subscribe_push(
    data: PushSubscriptionCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PushSubscriptionResponse:
    # Check if subscription already exists for this endpoint + user
    result = await db.execute(
        select(PushSubscription).where(
            PushSubscription.user_id == current_user.id,
            PushSubscription.endpoint == data.endpoint,
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        existing.p256dh = data.p256dh
        existing.auth = data.auth
        await db.commit()
        await db.refresh(existing)
        return PushSubscriptionResponse.model_validate(existing)

    sub = PushSubscription(
        user_id=current_user.id,
        endpoint=data.endpoint,
        p256dh=data.p256dh,
        auth=data.auth,
    )
    db.add(sub)
    await db.commit()
    await db.refresh(sub)
    return PushSubscriptionResponse.model_validate(sub)


@router.post("/unsubscribe", status_code=status.HTTP_204_NO_CONTENT)
async def unsubscribe_push(
    data: PushSubscriptionCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    result = await db.execute(
        select(PushSubscription).where(
            PushSubscription.user_id == current_user.id,
            PushSubscription.endpoint == data.endpoint,
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        await db.delete(existing)
        await db.commit()
