from sqlalchemy import Column, String, Integer, UUID, ForeignKey, Text, Enum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
import enum
from app.models.base import Base, TimestampMixin


class LLMProvider(str, enum.Enum):
    """LLM providers used for chat responses"""
    KIMI = "kimi"           # Moonshot AI (Kimi 2.5) - for chatbot, telegram, search agentic
    OPENROUTER = "openrouter"  # OpenRouter (MiniMax, etc.) - for smart folders, RAG, collections, knowledge graph
    OLLAMA = "ollama"       # Shared local Ollama instance - for confidential documents


class MessageRole(str, enum.Enum):
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

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, unique=True, nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("sowknow.users.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(512), nullable=False)

    # Document scope for this session (optional list of document IDs)
    document_scope = Column(JSONB, default=list)

    # Session metadata
    model_preference = Column(String(50))  # User's preferred LLM for this session

    # Relationships
    messages = relationship("ChatMessage", back_populates="session", cascade="all, delete-orphan", order_by="ChatMessage.created_at")

    def __repr__(self):
        return f"<ChatSession {self.title}>"


class ChatMessage(Base, TimestampMixin):
    """
    Individual chat messages with source citations
    """
    __tablename__ = "chat_messages"
    __table_args__ = {"schema": "sowknow"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, unique=True, nullable=False)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sowknow.chat_sessions.id", ondelete="CASCADE"), nullable=False)

    # Message content
    role = Column(Enum(MessageRole), nullable=False)
    content = Column(Text, nullable=False)

    # AI response metadata
    llm_used = Column(Enum(LLMProvider))  # Which LLM generated this response
    sources = Column(JSONB)  # List of source documents with chunks

    # Quality metrics
    confidence_score = Column(Integer)  # 0-100 for AI responses

    # Token usage tracking
    prompt_tokens = Column(Integer)
    completion_tokens = Column(Integer)
    total_tokens = Column(Integer)

    # Relationships
    session = relationship("ChatSession", back_populates="messages")

    def __repr__(self):
        return f"<ChatMessage {self.role} in session {self.session_id}>"
