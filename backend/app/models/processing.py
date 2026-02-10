from sqlalchemy import Column, String, UUID, ForeignKey, Text, Enum, Integer, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
import enum
from app.models.base import Base, TimestampMixin


class TaskType(str, enum.Enum):
    """Types of async processing tasks"""
    OCR_PROCESSING = "ocr_processing"
    TEXT_EXTRACTION = "text_extraction"
    CHUNKING = "chunking"
    EMBEDDING_GENERATION = "embedding_generation"
    INDEXING = "indexing"


class TaskStatus(str, enum.Enum):
    """Processing task status"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ProcessingQueue(Base, TimestampMixin):
    """
    Async processing task queue for document processing
    """
    __tablename__ = "processing_queue"
    __table_args__ = {"schema": "sowknow"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, unique=True, nullable=False)
    document_id = Column(UUID(as_uuid=True), ForeignKey("sowknow.documents.id", ondelete="CASCADE"), nullable=False)

    # Task information
    task_type = Column(Enum(TaskType), nullable=False)
    status = Column(Enum(TaskStatus), default=TaskStatus.PENDING, nullable=False, index=True)

    # Celery task tracking
    celery_task_id = Column(String(255), index=True)

    # Processing metadata
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    retry_count = Column(Integer, default=0)

    # Error handling
    error_message = Column(Text)
    error_details = Column(Text)

    # Progress tracking
    total_steps = Column(Integer)
    completed_steps = Column(Integer, default=0)
    progress_percentage = Column(Integer, default=0)

    # Priority (higher = more important)
    priority = Column(Integer, default=5)

    # Relationships
    document = relationship("Document", back_populates="processing_queue")

    def __repr__(self):
        return f"<ProcessingQueue {self.task_type} - {self.status}>"

    def update_progress(self, completed: int, total: int = None):
        """Update progress percentage"""
        if total is not None:
            self.total_steps = total
        self.completed_steps = completed
        if self.total_steps and self.total_steps > 0:
            self.progress_percentage = int((self.completed_steps / self.total_steps) * 100)
