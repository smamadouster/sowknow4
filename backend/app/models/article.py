import enum
import uuid

from sqlalchemy import Column, Enum, ForeignKey, Index, Integer, String, Text, event
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import relationship

try:
    from pgvector.sqlalchemy import Vector
except ImportError:
    Vector = None

from app.models.base import Base, GUIDType, TimestampMixin
from app.models.document import DocumentBucket


class ArticleStatus(enum.StrEnum):
    PENDING = "pending"
    GENERATING = "generating"
    INDEXED = "indexed"
    ERROR = "error"


class Article(Base, TimestampMixin):
    """
    AI-generated knowledge article extracted from document chunks.

    Articles are self-contained knowledge units with title, summary, and body.
    They are searchable via both semantic (pgvector) and keyword (tsvector) search,
    and appear alongside document chunks in search results.
    """

    __tablename__ = "articles"

    id = Column(
        GUIDType(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        unique=True,
        nullable=False,
    )
    document_id = Column(
        GUIDType(as_uuid=True),
        ForeignKey("sowknow.documents.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Article content
    title = Column(String(512), nullable=False)
    summary = Column(Text, nullable=False)
    body = Column(Text, nullable=False)

    # Inherited from source document for search RBAC (avoids JOIN)
    bucket = Column(
        Enum(DocumentBucket, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
    )
    status = Column(
        Enum(ArticleStatus, values_callable=lambda obj: [e.value for e in obj]),
        default=ArticleStatus.PENDING,
        nullable=False,
    )
    language = Column(String(10), nullable=False, server_default="french")

    # Source traceability
    source_chunk_ids = Column(JSONB, default=list)

    # AI-generated metadata
    tags = Column(JSONB, default=list)
    categories = Column(JSONB, default=list)
    entities = Column(JSONB, default=list)
    confidence = Column(Integer, default=0)

    # Generation metadata
    llm_provider = Column(String(50), nullable=True)
    content_hash = Column(String(64), nullable=True, index=True)

    # Search: embedding vector (pgvector)
    if Vector is not None:
        embedding_vector = Column(Vector(1024), nullable=True)
    else:
        embedding_vector = Column(Text, nullable=True)

    # Search: full-text (auto-updated by DB trigger)
    search_vector = Column(TSVECTOR, nullable=True)
    search_language = Column(String(10), nullable=False, server_default="french")

    # Relationships
    document = relationship("Document", backref="articles")

    if Vector is not None:
        __table_args__ = (
            Index("ix_articles_document_id", "document_id"),
            Index("ix_articles_bucket_status", "bucket", "status"),
            Index("ix_articles_content_hash", "content_hash"),
            Index("ix_articles_tags", "tags", postgresql_using="gin"),
            {"schema": "sowknow"},
        )
    else:
        __table_args__ = (
            Index("ix_articles_document_id", "document_id"),
            Index("ix_articles_bucket_status", "bucket", "status"),
            Index("ix_articles_content_hash", "content_hash"),
            {"schema": "sowknow"},
        )

    def __repr__(self) -> str:
        return f"<Article {self.title[:50]} ({self.bucket}/{self.status})>"


@event.listens_for(Article, "init", propagate=True)
def _article_init(target, args, kwargs) -> None:
    kwargs.setdefault("status", ArticleStatus.PENDING)
    kwargs.setdefault("source_chunk_ids", [])
    kwargs.setdefault("tags", [])
    kwargs.setdefault("categories", [])
    kwargs.setdefault("entities", [])
    kwargs.setdefault("confidence", 0)
