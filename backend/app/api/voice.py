import io
import logging
import os
import tempfile
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models.document import Document
from app.models.note import Note
from app.models.note_audio import NoteAudio
from app.models.user import User
from app.services.storage_service import storage_service
from app.services.whisper_service import whisper_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/voice", tags=["voice"])

ALLOWED_AUDIO_TYPES = {"audio/webm", "audio/ogg", "audio/wav", "audio/mpeg", "audio/mp4"}

# Maps audio file extension to browser-compatible MIME type.
# .ogg.encrypted → strip .encrypted first, then look up .ogg
_EXT_TO_MIME: dict[str, str] = {
    ".webm": "audio/webm",
    ".ogg": "audio/ogg",
    ".opus": "audio/ogg",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".flac": "audio/flac",
    ".aac": "audio/aac",
}


def _stream_audio_file(file_path: str) -> FileResponse | StreamingResponse:
    """Return a streaming response for an audio file, decrypting if needed.

    Confidential files are stored Fernet-encrypted with a .encrypted suffix
    (e.g. voice_123_abc.ogg.encrypted).  FileResponse would serve the raw
    ciphertext which browsers cannot play.  This helper decrypts on the fly
    and returns the plaintext audio bytes.
    """
    # Determine real extension (strip .encrypted suffix if present)
    real_path = file_path[: -len(".encrypted")] if file_path.endswith(".encrypted") else file_path
    ext = os.path.splitext(real_path)[1].lower()
    content_type = _EXT_TO_MIME.get(ext, "audio/ogg")

    if file_path.endswith(".encrypted") and storage_service.encryption_enabled:
        # Decrypt in memory; never write plaintext back to disk
        bucket = "confidential" if "/confidential/" in file_path else "public"
        filename = os.path.basename(file_path)
        file_bytes = storage_service.get_file(filename, bucket, decrypt=True)
        if file_bytes is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to decrypt audio file",
            )
        return StreamingResponse(
            io.BytesIO(file_bytes),
            media_type=content_type,
            headers={"Content-Length": str(len(file_bytes)), "Accept-Ranges": "none"},
        )

    return FileResponse(file_path, media_type=content_type)


MAX_AUDIO_SIZE = 10 * 1024 * 1024  # 10MB


@router.post("/transcribe")
async def transcribe_audio(
    file: UploadFile = File(...),
    language: str = Form("auto"),
    current_user: User = Depends(get_current_user),
):
    """Transcribe audio using Whisper.cpp (private, server-side transcription).

    Accepts audio files up to 10MB / ~60 seconds.
    `language` is an ISO 639-1 code (e.g. 'fr', 'en') or 'auto' for detection.
    Returns: {"transcript": str}
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
        result = await whisper_service.transcribe(tmp_path, language=language)
        return {"transcript": result["transcript"]}
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
    try:
        audio_uuid = uuid.UUID(audio_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invalid audio ID")

    # Check document audio first
    result = await db.execute(
        select(Document).where(Document.id == audio_uuid)
    )
    doc = result.scalar_one_or_none()

    if doc:
        if doc.bucket.value == "confidential" and current_user.role.value not in ["admin", "superuser"]:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

        # application/ogg is what python-magic returns for Telegram OGG Opus files.
        # Both audio/* and application/ogg are valid audio MIME types.
        _AUDIO_MIME_PREFIXES = ("audio/", "application/ogg")
        is_audio_mime = doc.mime_type and any(doc.mime_type.startswith(p) for p in _AUDIO_MIME_PREFIXES)
        # Web-recorded notes store path in audio_file_path; Telegram OGGs use file_path
        audio_path = doc.audio_file_path or (doc.file_path if is_audio_mime else None)
        if audio_path:
            if not os.path.exists(audio_path):
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audio file not found on disk")
            return _stream_audio_file(audio_path)

    # Check note audio
    result = await db.execute(
        select(NoteAudio).where(NoteAudio.id == audio_uuid)
    )
    note_audio = result.scalar_one_or_none()

    if note_audio:
        # RBAC: check parent note's bucket
        note_result = await db.execute(
            select(Note).where(Note.id == note_audio.note_id)
        )
        parent_note = note_result.scalar_one_or_none()
        if parent_note and parent_note.bucket.value == "confidential" and current_user.role.value not in ["admin", "superuser"]:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
        if not os.path.exists(note_audio.file_path):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audio file not found on disk")
        return _stream_audio_file(note_audio.file_path)

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audio not found")
