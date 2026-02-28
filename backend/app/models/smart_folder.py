"""SmartFolder model — rule-based dynamic subsets of a Collection.

Smart folders automatically populate themselves based on a rule_config
(JSONB) evaluated against documents whenever the parent collection is
refreshed. They are owned by a collection and cascade-delete with it.
"""

import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.models.base import Base, GUIDType, TimestampMixin


class SmartFolder(Base, TimestampMixin):
    """A rule-driven folder within a collection."""

    __tablename__ = "smart_folders"
    __table_args__ = {"schema": "sowknow"}

    id = Column(
        GUIDType(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    collection_id = Column(
        GUIDType(as_uuid=True),
        ForeignKey("sowknow.collections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String(512), nullable=False, default="")
    rule_config = Column(JSONB, nullable=False, default=dict)
    auto_update = Column(Boolean, nullable=False, default=True)
    last_synced_at = Column(DateTime(timezone=True), nullable=True)

    collection = relationship("Collection", back_populates="smart_folders")
