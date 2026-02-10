from sqlalchemy import Column, String, Integer, BigInteger, Boolean, UUID, Enum, ForeignKey, Text, Index, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
import enum
from app.models.base import Base, TimestampMixin


class DocumentBucket(str, enum.Enum):
    """Document storage bucket classification"""
    PUBLIC = "public"
    CONFIDENTIAL = "confidential"


class DocumentStatus(str, enum.Enum):
    """Document processing status"""
    PENDING = "pending"
    UPLOADING = "uploading"
    PROCESSING = "processing"
    INDEXED = "indexed"
    ERROR = "error"


class DocumentLanguage(str, enum.Enum):
    """Supported document languages"""
    FRENCH = "fr"
    ENGLISH = "en"
    MULTILINGUAL = "multi"
    UNKNOWN = "unknown"


class Document(Base, TimestampMixin):
    """
    Document model for storing file metadata
    """
    __tablename__ = "documents"
    __table_args__ = {"schema": "sowknow"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, unique=True, nullable=False)
    filename = Column(String(512), nullable=False)
    original_filename = Column(String(512), nullable=False)
    file_path = Column(String(1024), nullable=False)
    bucket = Column(Enum(DocumentBucket), default=DocumentBucket.PUBLIC, nullable=False, index=True)
    status = Column(Enum(DocumentStatus), default=DocumentStatus.PENDING, nullable=False, index=True)

    # File metadata
    size = Column(BigInteger, nullable=False)  # Size in bytes
    mime_type = Column(String(256), nullable=False)
    language = Column(Enum(DocumentLanguage), default=DocumentLanguage.UNKNOWN)
    page_count = Column(Integer)  # For PDFs, PPTX, etc.

    # Processing metadata
    ocr_processed = Column(Boolean, default=False)
    embedding_generated = Column(Boolean, default=False)
    chunk_count = Column(Integer, default=0)

    # Additional metadata stored as JSON
    document_metadata = Column("metadata", JSONB, default=dict)

    # Relationships
    tags = relationship("DocumentTag", back_populates="document", cascade="all, delete-orphan")
    chunks = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan")
    processing_queue = relationship("ProcessingQueue", back_populates="document", uselist=False)

    # Indexes
    __table_args__ = (
        Index("ix_documents_bucket_status", "bucket", "status"),
        Index("ix_documents_created_at", "created_at"),
        Index("ix_documents_language", "language"),
        {"schema": "sowknow"},
    )

    def __repr__(self):
        return f"<Document {self.filename} ({self.bucket}/{self.status})>"


class DocumentTag(Base, TimestampMixin):
    """
    Tags associated with documents for categorization
    """
    __tablename__ = "document_tags"
    __table_args__ = {"schema": "sowknow"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, unique=True, nullable=False)
    document_id = Column(UUID(as_uuid=True), ForeignKey("sowknow.documents.id", ondelete="CASCADE"), nullable=False)
    tag_name = Column(String(256), nullable=False, index=True)
    tag_type = Column(String(100))  # topic, entity, project, importance, etc.
    auto_generated = Column(Boolean, default=False)
    confidence_score = Column(Integer)  # 0-100 for AI-generated tags

    # Relationship
    document = relationship("Document", back_populates="tags")

    # Indexes
    __table_args__ = (
        Index("ix_document_tags_tag_name", "tag_name"),
        Index("ix_document_tags_tag_type", "tag_type"),
        {"schema": "sowknow"},
    )

    def __repr__(self):
        return f"<DocumentTag {self.tag_name} ({self.tag_type})>"


class DocumentChunk(Base, TimestampMixin):
    """
    Text chunks with embeddings for semantic search
    """
    __tablename__ = "document_chunks"
    __table_args__ = {"schema": "sowknow"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, unique=True, nullable=False)
    document_id = Column(UUID(as_uuid=True), ForeignKey("sowknow.documents.id", ondelete="CASCADE"), nullable=False)
    chunk_index = Column(Integer, nullable=False)
    chunk_text = Column(Text, nullable=False)

    # Metadata
    token_count = Column(Integer)
    page_number = Column(Integer)  # For PDFs

    # Relationships
    document = relationship("Document", back_populates="chunks")

    # Indexes
    __table_args__ = (
        Index("ix_document_chunks_document_id", "document_id"),
        Index("ix_document_chunks_chunk_index", "document_id", "chunk_index"),
        {"schema": "sowknow"},
    )

    def __repr__(self):
        return f"<DocumentChunk {self.document_id}/{self.chunk_index}>"

# Set up defaults for test instances
@event.listens_for(Document, 'init', propagate=True)
def _document_init(target, args, kwargs):
    """Set default values for fields when creating instances"""
    kwargs.setdefault('bucket', DocumentBucket.PUBLIC)
    kwargs.setdefault('status', DocumentStatus.PENDING)
    kwargs.setdefault('language', DocumentLanguage.UNKNOWN)
    kwargs.setdefault('ocr_processed', False)
    kwargs.setdefault('embedding_generated', False)
    kwargs.setdefault('chunk_count', 0)
    kwargs.setdefault('document_metadata', {})
