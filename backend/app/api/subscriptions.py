import logging
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.subscription import BillingCycle, Subscription, SubscriptionStatus
from app.models.user import User
from app.schemas.subscription import SubscriptionListResponse, SubscriptionResponse, SubscriptionSyncItem

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])
logger = logging.getLogger(__name__)


def _parse_uuid(s: str | None) -> UUID | None:
    if not s:
        return None
    try:
        return UUID(s)
    except ValueError:
        return None


@router.get("", response_model=SubscriptionListResponse)
async def list_subscriptions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubscriptionListResponse:
    result = await db.execute(
        select(Subscription).where(Subscription.user_id == current_user.id)
    )
    subs = result.scalars().all()
    return SubscriptionListResponse(
        subscriptions=[
            SubscriptionResponse.model_validate(s) for s in subs
        ]
    )


@router.post("/test-email")
async def test_email(
    current_user: User = Depends(get_current_user),
) -> dict:
    """Send a test payment reminder email to the current user."""
    from app.tasks.subscription_tasks import _send_email, _smtp_configured

    if not _smtp_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SMTP not configured — set GMAIL_SMTP_USER and GMAIL_SMTP_PASSWORD",
        )

    subject = "Payment Reminder (TEST)"
    text_body = (
        f"Hi {current_user.full_name or current_user.email},\n\n"
        f"This is a test reminder from SOWKNOW.\n\n"
        f"Subscription: Test Subscription\n"
        f"Amount: 99.99\n"
        f"Billing: monthly\n"
        f"Due date: 2099-12-31\n\n"
        f"Thanks,\nSOWKNOW"
    )
    html_body = """
    <html><body style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px">
      <h2 style="color:#1f2937">Payment Reminder (TEST)</h2>
      <p>This is a test reminder from SOWKNOW.</p>
      <p style="margin-top:24px;color:#6b7280;font-size:12px">
        If you received this, your SMTP setup is working correctly.
      </p>
    </body></html>
    """

    ok = _send_email(current_user.email, subject, html_body, text_body)
    return {"sent": ok, "recipient": current_user.email}


@router.put("/sync", response_model=SubscriptionListResponse)
async def sync_subscriptions(
    items: list[SubscriptionSyncItem],
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubscriptionListResponse:
    try:
        # Delete existing subscriptions for user
        await db.execute(
            delete(Subscription).where(Subscription.user_id == current_user.id)
        )

        # Insert new ones
        for item in items:
            sub = Subscription(
                id=_parse_uuid(item.id) or UUID(int=0),
                user_id=current_user.id,
                name=item.name,
                domain=item.domain,
                price=item.price,
                billing_cycle=BillingCycle(item.billing_cycle),
                description=item.description,
                last_payment=item.last_payment,
                status=SubscriptionStatus(item.status),
                color=item.color,
            )
            # Override the id if it was provided and valid
            parsed_id = _parse_uuid(item.id)
            if parsed_id:
                sub.id = parsed_id
            else:
                sub.id = uuid4()
            db.add(sub)

        await db.commit()

        result = await db.execute(
            select(Subscription).where(Subscription.user_id == current_user.id)
        )
        subs = result.scalars().all()
        return SubscriptionListResponse(
            subscriptions=[
                SubscriptionResponse.model_validate(s) for s in subs
            ]
        )
    except Exception as e:
        logger.error(f"Failed to sync subscriptions: {e}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to sync subscriptions",
        )
