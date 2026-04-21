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
