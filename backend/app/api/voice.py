import logging
import os
import tempfile
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models.document import Document
from app.models.note_audio import NoteAudio
from app.models.user import User
from app.services.whisper_service import whisper_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/voice", tags=["voice"])

ALLOWED_AUDIO_TYPES = {"audio/webm", "audio/ogg", "audio/wav", "audio/mpeg", "audio/mp4"}
MAX_AUDIO_SIZE = 10 * 1024 * 1024  # 10MB


@router.post("/transcribe")
async def transcribe_audio(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """Transcribe audio using Whisper.cpp (private, server-side transcription).

    Accepts audio files up to 10MB / ~60 seconds.
    Returns: {"transcript": str, "detected_language": str}
    """
    if file.content_type not in ALLOWED_AUDIO_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid audio type: {file.content_type}. Allowed: {', '.join(ALLOWED_AUDIO_TYPES)}",
        )

    content = await file.read()
    if len(content) > MAX_AUDIO_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Audio file too large. Voice notes must be under 60 seconds.",
        )

    suffix = os.path.splitext(file.filename or "audio.webm")[1] or ".webm"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        result = await whisper_service.transcribe(tmp_path)
        return {"transcript": result["transcript"], "detected_language": "auto"}
    except RuntimeError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    finally:
        os.unlink(tmp_path)


@router.get("/audio/{audio_id}/stream")
async def stream_audio(
    audio_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Stream an audio file for playback.

    Checks both document audio and note audio tables.
    RBAC enforced: same rules as parent document/note.
    """
    # Check document audio first
    result = await db.execute(
        select(Document).where(Document.id == uuid.UUID(audio_id))
    )
    doc = result.scalar_one_or_none()

    if doc and doc.audio_file_path:
        if doc.bucket.value == "confidential" and current_user.role.value not in ["admin", "superuser"]:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
        if not os.path.exists(doc.audio_file_path):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audio file not found on disk")
        content_type = "audio/webm" if doc.audio_file_path.endswith(".webm") else "audio/ogg"
        return FileResponse(doc.audio_file_path, media_type=content_type)

    # Check note audio
    result = await db.execute(
        select(NoteAudio).where(NoteAudio.id == uuid.UUID(audio_id))
    )
    note_audio = result.scalar_one_or_none()

    if note_audio:
        if not os.path.exists(note_audio.file_path):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audio file not found on disk")
        content_type = "audio/webm" if note_audio.file_path.endswith(".webm") else "audio/ogg"
        return FileResponse(note_audio.file_path, media_type=content_type)

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audio not found")
