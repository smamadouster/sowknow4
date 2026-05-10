import enum
import uuid

from sqlalchemy import Column, Date, DateTime, Enum, ForeignKey, Numeric, String, Text, func

from app.models.base import Base, GUIDType


class BillingCycle(enum.StrEnum):
    MONTHLY = "monthly"
    YEARLY = "yearly"


class SubscriptionStatus(enum.StrEnum):
    ACTIVE = "active"
    UNUSED = "unused"


class Subscription(Base):
    __tablename__ = "subscriptions"
    __table_args__ = {"schema": "sowknow"}

    id = Column(GUIDType(as_uuid=True), primary_key=True, default=uuid.uuid4, unique=True, nullable=False)
    user_id = Column(
        GUIDType(as_uuid=True),
        ForeignKey("sowknow.users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String(255), nullable=False)
    domain = Column(String(512), nullable=True)
    price = Column(Numeric(12, 2), nullable=False)
    billing_cycle = Column(
        Enum(BillingCycle, native_enum=False, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    description = Column(Text, nullable=True)
    last_payment = Column(Date, nullable=False)
    status = Column(
        Enum(SubscriptionStatus, native_enum=False, values_callable=lambda x: [e.value for e in x]),
        default=SubscriptionStatus.ACTIVE,
        nullable=False,
    )
    color = Column(String(128), nullable=True)
    reminder_sent_for_date = Column(Date, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
