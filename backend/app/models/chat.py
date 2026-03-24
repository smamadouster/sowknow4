import enum
import uuid

from sqlalchemy import Column, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.models.base import Base, GUIDType, TimestampMixin


class LLMProvider(enum.StrEnum):
    """LLM providers used for chat responses"""

    MINIMAX = "minimax"  # MiniMax M2.7 — search agent, article generation (direct API)
    KIMI = "kimi"  # Moonshot direct API (legacy — phased out)
    OLLAMA = "ollama"  # Local Ollama (mistral:7b) — confidential documents (privacy guarantee)
    OPENROUTER = "openrouter"  # OpenRouter gateway — Mistral Small 2603 for chat/collections/telegram


class MessageRole(enum.StrEnum):
    """Chat message roles"""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ChatSession(Base, TimestampMixin):
    """
    Chat session for managing conversation history
    """

    __tablename__ = "chat_sessions"
    __table_args__ = {"schema": "sowknow"}

    id = Column(
        GUIDType(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        unique=True,
        nullable=False,
    )
    user_id = Column(
        GUIDType(as_uuid=True),
        ForeignKey("sowknow.users.id", ondelete="CASCADE"),
        nullable=False,
    )
    title = Column(String(512), nullable=False)

    # Document scope for this session (optional list of document IDs)
    document_scope = Column(JSONB, default=list)

    # Session metadata
    model_preference = Column(String(50))  # User's preferred LLM for this session

    # Relationships
    messages = relationship(
        "ChatMessage",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ChatMessage.created_at",
    )

    def __repr__(self) -> str:
        return f"<ChatSession {self.title}>"


class ChatMessage(Base, TimestampMixin):
    """
    Individual chat messages with source citations
    """

    __tablename__ = "chat_messages"
    __table_args__ = {"schema": "sowknow"}

    id = Column(
        GUIDType(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        unique=True,
        nullable=False,
    )
    session_id = Column(
        GUIDType(as_uuid=True),
        ForeignKey("sowknow.chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Message content
    role = Column(
        Enum(MessageRole, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
    )
    content = Column(Text, nullable=False)

    # AI response metadata
    llm_used = Column(
        Enum(LLMProvider, values_callable=lambda obj: [e.value for e in obj])
    )  # Which LLM generated this response
    sources = Column(JSONB)  # List of source documents with chunks

    # Quality metrics
    confidence_score = Column(Integer)  # 0-100 for AI responses

    # Token usage tracking
    prompt_tokens = Column(Integer)
    completion_tokens = Column(Integer)
    total_tokens = Column(Integer)

    # Relationships
    session = relationship("ChatSession", back_populates="messages")

    def __repr__(self) -> str:
        return f"<ChatMessage {self.role} in session {self.session_id}>"
