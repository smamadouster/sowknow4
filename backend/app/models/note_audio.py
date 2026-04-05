import uuid

from sqlalchemy import Column, DateTime, Float, ForeignKey, String, Text, func

from app.models.base import Base, GUIDType


class NoteAudio(Base):
    __tablename__ = "note_audio"
    __table_args__ = ({"schema": "sowknow"},)

    id = Column(GUIDType(as_uuid=True), primary_key=True, default=uuid.uuid4, unique=True, nullable=False)
    note_id = Column(GUIDType(as_uuid=True), ForeignKey("sowknow.notes.id", ondelete="CASCADE"), nullable=False, index=True)
    file_path = Column(Text, nullable=False)
    duration_seconds = Column(Float, nullable=True)
    transcript = Column(Text, nullable=True)
    detected_language = Column(String(5), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
