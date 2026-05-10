from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class PushSubscriptionCreate(BaseModel):
    endpoint: str = Field(..., min_length=1)
    p256dh: str = Field(..., min_length=1)
    auth: str = Field(..., min_length=1)


class PushSubscriptionResponse(BaseModel):
    id: UUID
    user_id: UUID
    endpoint: str
    p256dh: str
    auth: str
    created_at: datetime

    class Config:
        from_attributes = True
