"""
Chat API endpoints for AI-powered conversations with RAG
"""
from fastapi import status, APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from app.limiter import limiter
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import Optional, List
from uuid import uuid4, UUID
import json

from app.database import get_db, AsyncSessionLocal
from app.models.user import User
from app.models.chat import ChatSession, ChatMessage, MessageRole, LLMProvider
from app.api.deps import get_current_user
from app.services.chat_service import chat_service
from app.services.llm_router import llm_router
from app.schemas.chat import (
    ChatSessionCreate,
    ChatSessionResponse,
    ChatSessionListResponse,
    ChatMessageCreate,
    ChatMessageResponse,
    ChatMessageListResponse,
    SourceDocument
)

router = APIRouter(prefix="/chat", tags=["chat"])


# Helper functions
def determine_llm_provider(has_confidential: bool) -> LLMProvider:
    """Determine which LLM to use based on document context.

    Routes confidential queries to OLLAMA (privacy guarantee).
    Public queries follow the llm_router fallback chain defined as:
        "kimi" → "minimax" → "openrouter" → "ollama"
    (see llm_router.fallback_chains["general_chat"]).
    """
    return LLMProvider.OLLAMA if has_confidential else LLMProvider.OPENROUTER


@router.post("/sessions", response_model=ChatSessionResponse)
@limiter.limit("20/minute")
async def create_chat_session(
    http_request: Request,
    session_data: ChatSessionCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a new chat session"""
    try:
        session = ChatSession(
            id=uuid4(),
            user_id=current_user.id,
            title=session_data.title,
            document_scope=session_data.document_scope or [],
            model_preference=session_data.model_preference
        )

        db.add(session)
        await db.commit()
        await db.refresh(session)

        return ChatSessionResponse.model_validate(session)

    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error creating session: {str(e)}")


@router.get("/sessions", response_model=ChatSessionListResponse)
async def list_chat_sessions(
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List user's chat sessions"""
    result = await db.execute(
        select(ChatSession)
        .where(ChatSession.user_id == current_user.id)
        .order_by(ChatSession.updated_at.desc())
        .offset(offset)
        .limit(limit)
    )
    sessions = result.scalars().all()

    count_result = await db.execute(
        select(func.count()).select_from(ChatSession).where(ChatSession.user_id == current_user.id)
    )
    total = count_result.scalar_one()

    return ChatSessionListResponse(
        sessions=[ChatSessionResponse.model_validate(s) for s in sessions],
        total=total
    )


@router.get("/sessions/{session_id}", response_model=ChatSessionResponse)
async def get_chat_session(
    session_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get a specific chat session"""
    result = await db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.user_id == current_user.id
        )
    )
    session = result.scalar_one_or_none()

    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    return ChatSessionResponse.model_validate(session)


@router.post("/sessions/{session_id}/message")
async def send_message(
    session_id: UUID,
    message_data: ChatMessageCreate,
    stream: bool = True,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Send a message to the chat session

    If stream=True, returns SSE stream of response chunks.
    If stream=False, returns complete response.
    """
    # Verify session exists and belongs to user
    result = await db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.user_id == current_user.id
        )
    )
    session = result.scalar_one_or_none()

    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    # Save user message
    user_message = ChatMessage(
        id=uuid4(),
        session_id=session_id,
        role=MessageRole.USER,
        content=message_data.content
    )
    db.add(user_message)
    await db.commit()

    if stream:
        # Use a dedicated async session for the streaming generator so the lifecycle
        # is tied to the generator itself, not the request dependency scope.
        async def _stream_with_session():
            async with AsyncSessionLocal() as stream_db:
                async for chunk in chat_service.generate_chat_response_stream(
                    session_id=session_id,
                    user_message=message_data.content,
                    db=stream_db,
                    current_user=current_user,
                ):
                    yield chunk

        return StreamingResponse(
            _stream_with_session(),
            media_type="text/event-stream",
        )
    else:
        # Return complete response
        try:
            response_data = await chat_service.generate_chat_response(
                session_id=session_id,
                user_message=message_data.content,
                db=db,
                current_user=current_user,
            )

            # Save assistant message
            assistant_message = ChatMessage(
                id=uuid4(),
                session_id=session_id,
                role=MessageRole.ASSISTANT,
                content=response_data["content"],
                llm_used=response_data["llm_used"],
                sources=response_data.get("sources"),
                prompt_tokens=response_data.get("prompt_tokens"),
                completion_tokens=response_data.get("completion_tokens"),
                total_tokens=response_data.get("total_tokens")
            )
            db.add(assistant_message)
            await db.commit()

            return ChatMessageResponse.model_validate(assistant_message)

        except Exception as e:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error generating response: {str(e)}")


@router.get("/sessions/{session_id}/messages", response_model=ChatMessageListResponse)
async def get_session_messages(
    session_id: UUID,
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get messages in a session with offset-based pagination."""
    # Verify session ownership
    session_result = await db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.user_id == current_user.id
        )
    )
    session = session_result.scalar_one_or_none()

    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.asc())
        .offset(offset)
        .limit(limit)
    )
    messages = result.scalars().all()

    count_result = await db.execute(
        select(func.count()).select_from(ChatMessage).where(ChatMessage.session_id == session_id)
    )
    total = count_result.scalar_one()

    return ChatMessageListResponse(
        messages=[ChatMessageResponse.model_validate(m) for m in messages],
        total=total
    )


@router.delete("/sessions/{session_id}")
async def delete_chat_session(
    session_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete a chat session"""
    result = await db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.user_id == current_user.id
        )
    )
    session = result.scalar_one_or_none()

    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    await db.delete(session)
    await db.commit()

    return {"message": "Session deleted successfully"}
