import uuid

from sqlalchemy import Column, DateTime, ForeignKey, String, Text, func

from app.models.base import Base, GUIDType


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"
    __table_args__ = ({"schema": "sowknow"},)

    id = Column(GUIDType(as_uuid=True), primary_key=True, default=uuid.uuid4, unique=True, nullable=False)
    user_id = Column(GUIDType(as_uuid=True), ForeignKey("sowknow.users.id", ondelete="CASCADE"), nullable=False, index=True)
    endpoint = Column(Text, nullable=False)
    p256dh = Column(String(255), nullable=False)
    auth = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
