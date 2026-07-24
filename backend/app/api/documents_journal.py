"""
Journal entry endpoints for confidential text and voice uploads.

Split from documents.py to reduce the god-router surface area.
"""

import logging
import os
import hmac
import tempfile
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.documents_common import (
    BOT_API_KEY,
    JournalEntryRequest,
    create_audit_log,
    _queue_document_for_processing,
)
from app.database import get_db
from app.models.audit import AuditAction
from app.models.document import Document, DocumentBucket, DocumentLanguage, DocumentStatus, DocumentTag
from app.models.user import User
from app.schemas.document import DocumentUploadResponse
from app.services.storage_service import storage_service
from app.services.whisper_service import whisper_service

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/journal", response_model=DocumentUploadResponse)
async def create_journal_entry(
    entry: JournalEntryRequest,
    x_bot_api_key: str | None = Header(None, alias="X-Bot-Api-Key"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentUploadResponse:
    """Create a text-only journal entry in the confidential bucket."""
    if current_user.role.value not in ["admin", "superuser"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin or Super User role required for journal entries",
        )

    if x_bot_api_key:
        if not BOT_API_KEY or not hmac.compare_digest(x_bot_api_key, BOT_API_KEY):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Bot API Key")

    now = datetime.now(UTC)
    timestamp = entry.timestamp or now.isoformat()
    content = entry.text.encode("utf-8")
    filename = f"journal_{now.strftime('%Y%m%d_%H%M%S')}.txt"

    save_result = await storage_service.save_file_async(file_content=content, original_filename=filename, bucket="confidential")

    document = Document(
        filename=save_result["filename"],
        original_filename=filename,
        file_path=save_result["file_path"],
        bucket=DocumentBucket.CONFIDENTIAL,
        status=DocumentStatus.PENDING,
        size=save_result["size"],
        mime_type="text/plain",
        language=DocumentLanguage.UNKNOWN,
        uploaded_by=current_user.id,
        document_metadata={
            "document_type": "journal",
            "journal_timestamp": timestamp,
            "journal_text": entry.text[:500],
        },
    )

    db.add(document)
    await db.flush()

    for tag_name in entry.tags:
        tag = DocumentTag(
            document_id=document.id,
            tag_name=tag_name.strip().lower(),
            tag_type="user",
            auto_generated=False,
        )
        db.add(tag)

    await db.commit()
    await db.refresh(document)

    await create_audit_log(
        db=db,
        user_id=current_user.id,
        action=AuditAction.CONFIDENTIAL_UPLOADED,
        resource_type="journal_entry",
        resource_id=str(document.id),
        details={"filename": filename, "type": "journal"},
    )

    return await _queue_document_for_processing(
        document, db, success_message="Journal entry created and queued for processing"
    )


@router.post("/journal/voice", response_model=DocumentUploadResponse)
async def create_journal_entry_from_voice(
    file: UploadFile = File(...),
    language: str = Form("auto"),
    x_bot_api_key: str | None = Header(None, alias="X-Bot-Api-Key"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentUploadResponse:
    """Create a journal entry from a voice recording."""
    if current_user.role.value not in ["admin", "superuser"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin or Super User role required for journal entries",
        )

    if x_bot_api_key:
        if not BOT_API_KEY or not hmac.compare_digest(x_bot_api_key, BOT_API_KEY):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Bot API Key")

    MAX_AUDIO_SIZE = 10 * 1024 * 1024
    ALLOWED_AUDIO_TYPES = {
        "audio/webm", "audio/ogg", "audio/wav", "audio/mpeg",
        "audio/mp4", "audio/aac", "audio/x-m4a",
    }
    if file.content_type not in ALLOWED_AUDIO_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported audio format: {file.content_type}",
        )

    content = await file.read()
    if len(content) > MAX_AUDIO_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Audio file exceeds maximum size of {MAX_AUDIO_SIZE // (1024 * 1024)}MB",
        )

    file_ext = os.path.splitext(file.filename)[1] if file.filename else ".webm"
    with tempfile.NamedTemporaryFile(suffix=file_ext, delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        result = await whisper_service.transcribe(tmp_path, language=language)
        transcript = result.get("transcript", "").strip()
        if not transcript:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Could not transcribe audio. Please speak clearly and try again.",
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Transcription failed for journal voice entry: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Transcription failed. Please try again.",
        )
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass

    now = datetime.now(UTC)
    filename = f"journal_{now.strftime('%Y%m%d_%H%M%S')}.txt"
    text_content = transcript.encode("utf-8")

    save_result = await storage_service.save_file_async(file_content=text_content, original_filename=filename, bucket="confidential")

    document = Document(
        filename=save_result["filename"],
        original_filename=filename,
        file_path=save_result["file_path"],
        bucket=DocumentBucket.CONFIDENTIAL,
        status=DocumentStatus.PENDING,
        size=save_result["size"],
        mime_type="text/plain",
        language=DocumentLanguage.UNKNOWN,
        uploaded_by=current_user.id,
        document_metadata={
            "document_type": "journal",
            "journal_timestamp": now.isoformat(),
            "journal_text": transcript[:500],
            "voice_transcript": transcript,
        },
    )

    db.add(document)
    await db.commit()
    await db.refresh(document)

    await create_audit_log(
        db=db,
        user_id=current_user.id,
        action=AuditAction.CONFIDENTIAL_UPLOADED,
        resource_type="journal_entry",
        resource_id=str(document.id),
        details={"filename": filename, "type": "journal_voice"},
    )

    return await _queue_document_for_processing(
        document, db, success_message="Voice journal entry created and queued for processing"
    )
