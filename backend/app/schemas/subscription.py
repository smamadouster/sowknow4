from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field


class SubscriptionSyncItem(BaseModel):
    id: str | None = Field(default=None)
    name: str = Field(..., min_length=1, max_length=255)
    domain: str | None = Field(default=None, max_length=512)
    price: float = Field(..., ge=0)
    billing_cycle: str = Field(..., pattern="^(monthly|yearly)$")
    description: str | None = Field(default=None)
    last_payment: date
    status: str = Field(..., pattern="^(active|unused)$")
    color: str | None = Field(default=None, max_length=128)


class SubscriptionResponse(BaseModel):
    id: UUID
    user_id: UUID
    name: str
    domain: str | None
    price: float
    billing_cycle: str
    description: str | None
    last_payment: date
    status: str
    color: str | None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class SubscriptionListResponse(BaseModel):
    subscriptions: list[SubscriptionResponse]
