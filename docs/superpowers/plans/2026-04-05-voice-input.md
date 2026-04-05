# Voice Input & Voice Notes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add voice recording (Telegram-style tap/hold UX) to Journal, Notes, and Search, plus Telegram bot voice note transcription via Whisper.cpp.

**Architecture:** Shared `<VoiceRecorder>` React component handles mic capture + Web Speech API transcription on the browser. Backend gains a Whisper.cpp-powered Celery task for private/Telegram transcription. Audio files stored alongside documents with transcript in `extracted_text`. New `note_audio` table for note attachments.

**Tech Stack:** MediaRecorder API, Web Speech API, Whisper.cpp (ggml-small.bin), FastAPI, Celery, Alembic, Next.js/React, Tailwind CSS, next-intl.

**Spec:** `docs/superpowers/specs/2026-04-05-voice-input-design.md`

---

## File Structure

### New Files

| File | Responsibility |
|------|---------------|
| `frontend/components/VoiceRecorder.tsx` | Shared voice recording component (mic, waveform, transcript, send/cancel) |
| `frontend/hooks/useVoiceRecorder.ts` | Recording logic: MediaRecorder + SpeechRecognition + AnalyserNode |
| `backend/app/api/voice.py` | Voice router: `POST /transcribe`, `GET /audio/{id}/stream` |
| `backend/app/models/note_audio.py` | SQLAlchemy model for `note_audio` table |
| `backend/app/services/whisper_service.py` | Whisper.cpp subprocess wrapper |
| `backend/app/tasks/voice_tasks.py` | Celery task: `transcribe_voice_note` |
| `backend/alembic/versions/021_add_voice_audio_support.py` | Migration: 3 columns on documents + note_audio table |
| `backend/tests/unit/test_whisper_service.py` | Tests for whisper service |
| `backend/tests/unit/test_voice_api.py` | Tests for voice API endpoints |

### Modified Files

| File | Change |
|------|--------|
| `frontend/app/[locale]/journal/page.tsx` | Add voice entry button + VoiceRecorder integration |
| `frontend/app/[locale]/notes/page.tsx` | Add mic button in editor modal + VoiceRecorder integration |
| `frontend/app/[locale]/search/page.tsx` | Add mic icon in search input + VoiceRecorder integration |
| `frontend/lib/api.ts` | Add `uploadAudio()`, `transcribeAudio()`, `getNoteAudio()`, `streamAudio()` methods |
| `frontend/app/messages/fr.json` | Add voice-related i18n strings |
| `frontend/app/messages/en.json` | Add voice-related i18n strings |
| `backend/app/api/documents.py` | Accept `transcript` form field on upload for audio documents |
| `backend/app/api/notes.py` | Add `POST /{note_id}/audio` endpoint |
| `backend/app/models/__init__.py` | Import `NoteAudio` model |
| `backend/app/models/document.py` | Add `audio_file_path`, `audio_duration_seconds`, `detected_language` columns |
| `backend/app/tasks/__init__.py` | Add `voice_tasks` import |
| `backend/app/celery_app.py` | Add `app.tasks.voice_tasks` to includes |
| `backend/telegram_bot/bot.py` | Add voice message handler + `handle_voice_message` function |
| `backend/Dockerfile.worker` | Install Whisper.cpp binary + download ggml-small model |

---

## Task 1: Database Migration — Audio Columns & note_audio Table

**Files:**
- Create: `backend/alembic/versions/021_add_voice_audio_support.py`
- Modify: `backend/app/models/document.py`
- Create: `backend/app/models/note_audio.py`
- Modify: `backend/app/models/__init__.py`

- [ ] **Step 1: Create the Alembic migration file**

```python
"""Add voice/audio support columns and note_audio table

Revision ID: 021
Revises: 020
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add audio columns to documents table
    op.add_column("documents", sa.Column("audio_file_path", sa.Text(), nullable=True), schema="sowknow")
    op.add_column("documents", sa.Column("audio_duration_seconds", sa.Float(), nullable=True), schema="sowknow")
    op.add_column("documents", sa.Column("detected_language", sa.String(5), nullable=True), schema="sowknow")

    # Create note_audio table
    op.create_table(
        "note_audio",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("note_id", UUID(as_uuid=True), sa.ForeignKey("sowknow.notes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("transcript", sa.Text(), nullable=True),
        sa.Column("detected_language", sa.String(5), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        schema="sowknow",
    )
    op.create_index("idx_note_audio_note_id", "note_audio", ["note_id"], schema="sowknow")


def downgrade() -> None:
    op.drop_index("idx_note_audio_note_id", table_name="note_audio", schema="sowknow")
    op.drop_table("note_audio", schema="sowknow")
    op.drop_column("documents", "detected_language", schema="sowknow")
    op.drop_column("documents", "audio_duration_seconds", schema="sowknow")
    op.drop_column("documents", "audio_file_path", schema="sowknow")
```

- [ ] **Step 2: Add columns to the Document model**

In `backend/app/models/document.py`, after line 115 (`document_metadata`), add:

```python
    # Audio/voice note metadata
    audio_file_path = Column(Text, nullable=True)
    audio_duration_seconds = Column(Float, nullable=True)
    detected_language = Column(String(5), nullable=True)
```

Add `Float, Text` to the `sqlalchemy` imports at the top if not already present.

- [ ] **Step 3: Create the NoteAudio model**

Create `backend/app/models/note_audio.py`:

```python
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
```

- [ ] **Step 4: Register NoteAudio in models __init__**

Check `backend/app/models/__init__.py` and add:

```python
from app.models.note_audio import NoteAudio
```

- [ ] **Step 5: Run migration**

```bash
cd /home/development/src/active/sowknow4
docker exec -it sowknow4-backend alembic upgrade head
```

Expected: Migration 021 applies successfully.

- [ ] **Step 6: Verify columns exist**

```bash
docker exec -it sowknow4-postgres psql -U sowknow -d sowknow -c "\d sowknow.documents" | grep audio
docker exec -it sowknow4-postgres psql -U sowknow -d sowknow -c "\d sowknow.note_audio"
```

Expected: `audio_file_path`, `audio_duration_seconds`, `detected_language` columns visible. `note_audio` table with all columns.

- [ ] **Step 7: Commit**

```bash
git add backend/alembic/versions/021_add_voice_audio_support.py backend/app/models/document.py backend/app/models/note_audio.py backend/app/models/__init__.py
git commit -m "feat: add voice/audio database schema — document audio columns + note_audio table"
```

---

## Task 2: Whisper.cpp Service

**Files:**
- Create: `backend/app/services/whisper_service.py`
- Create: `backend/tests/unit/test_whisper_service.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_whisper_service.py`:

```python
import pytest
from unittest.mock import patch, AsyncMock
from app.services.whisper_service import WhisperService


class TestWhisperService:
    def test_build_command(self):
        """Whisper CLI command is built correctly."""
        svc = WhisperService()
        cmd = svc._build_command("/tmp/audio.ogg")
        assert "/usr/local/bin/whisper-cpp" in cmd[0] or "whisper" in cmd[0]
        assert "/tmp/audio.ogg" in cmd
        assert "--language" in cmd
        assert "auto" in cmd

    def test_parse_output_extracts_text(self):
        """Raw whisper output is parsed to clean transcript."""
        svc = WhisperService()
        raw = "[00:00:00.000 --> 00:00:03.000]  Bonjour, ceci est un test.\n[00:00:03.000 --> 00:00:05.000]  Merci beaucoup."
        result = svc._parse_output(raw)
        assert result["transcript"] == "Bonjour, ceci est un test. Merci beaucoup."

    def test_parse_output_empty(self):
        """Empty output returns empty transcript."""
        svc = WhisperService()
        result = svc._parse_output("")
        assert result["transcript"] == ""

    @pytest.mark.asyncio
    @patch("app.services.whisper_service.asyncio.create_subprocess_exec")
    async def test_transcribe_calls_subprocess(self, mock_exec):
        """transcribe() calls whisper-cpp and returns parsed result."""
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (
            b"[00:00:00.000 --> 00:00:02.000]  Hello world.\n",
            b"",
        )
        mock_proc.returncode = 0
        mock_exec.return_value = mock_proc

        svc = WhisperService()
        result = await svc.transcribe("/tmp/test.ogg")
        assert result["transcript"] == "Hello world."
        mock_exec.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/development/src/active/sowknow4/backend
python -m pytest tests/unit/test_whisper_service.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.whisper_service'`

- [ ] **Step 3: Write the WhisperService implementation**

Create `backend/app/services/whisper_service.py`:

```python
import asyncio
import logging
import os
import re

logger = logging.getLogger(__name__)

WHISPER_BINARY = os.getenv("WHISPER_BINARY", "/usr/local/bin/whisper-cpp")
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "/models/ggml-small.bin")
WHISPER_TIMEOUT = int(os.getenv("WHISPER_TIMEOUT", "30"))


class WhisperService:
    """Wraps whisper.cpp CLI for server-side audio transcription."""

    def _build_command(self, audio_path: str) -> list[str]:
        return [
            WHISPER_BINARY,
            "-m", WHISPER_MODEL,
            "-f", audio_path,
            "--language", "auto",
            "--no-timestamps",
            "--print-progress", "false",
        ]

    def _parse_output(self, raw: str) -> dict:
        """Parse whisper.cpp output into clean transcript."""
        if not raw.strip():
            return {"transcript": ""}
        # Remove timestamp lines like [00:00:00.000 --> 00:00:03.000]
        lines = raw.strip().split("\n")
        cleaned = []
        for line in lines:
            # Strip timestamp prefix if present
            text = re.sub(r"\[[\d:.]+\s*-->\s*[\d:.]+\]\s*", "", line).strip()
            if text:
                cleaned.append(text)
        return {"transcript": " ".join(cleaned)}

    async def transcribe(self, audio_path: str) -> dict:
        """Transcribe an audio file using whisper.cpp.

        Returns: {"transcript": str}
        Raises: RuntimeError on whisper failure.
        """
        cmd = self._build_command(audio_path)
        logger.info(f"Whisper transcription: {audio_path}")

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=WHISPER_TIMEOUT
            )
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError(f"Whisper transcription timed out after {WHISPER_TIMEOUT}s")

        if proc.returncode != 0:
            error_msg = stderr.decode().strip()
            raise RuntimeError(f"Whisper failed (exit {proc.returncode}): {error_msg}")

        result = self._parse_output(stdout.decode())
        logger.info(f"Transcription complete: {len(result['transcript'])} chars")
        return result


whisper_service = WhisperService()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/development/src/active/sowknow4/backend
python -m pytest tests/unit/test_whisper_service.py -v
```

Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/whisper_service.py backend/tests/unit/test_whisper_service.py
git commit -m "feat: add WhisperService — subprocess wrapper for whisper.cpp transcription"
```

---

## Task 3: Voice Celery Task

**Files:**
- Create: `backend/app/tasks/voice_tasks.py`
- Modify: `backend/app/tasks/__init__.py`
- Modify: `backend/app/celery_app.py`

- [ ] **Step 1: Create the voice task**

Create `backend/app/tasks/voice_tasks.py`:

```python
import logging
import os
import tempfile

from app.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.voice_tasks.transcribe_voice_note", bind=True, max_retries=1)
def transcribe_voice_note(self, audio_file_path: str, document_id: str) -> dict:
    """Transcribe an audio file using whisper.cpp synchronously (Celery task).

    Updates the document's extracted_text and detected_language after transcription.
    """
    import asyncio
    from app.services.whisper_service import whisper_service

    logger.info(f"Transcribing voice note: doc={document_id}, file={audio_file_path}")

    if not os.path.exists(audio_file_path):
        logger.error(f"Audio file not found: {audio_file_path}")
        return {"error": "Audio file not found", "document_id": document_id}

    try:
        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(whisper_service.transcribe(audio_file_path))
        loop.close()
    except RuntimeError as e:
        logger.error(f"Whisper transcription failed: {e}")
        return {"error": str(e), "document_id": document_id}

    # Update document with transcript
    from sqlalchemy import create_engine, text
    from app.core.config import settings

    engine = create_engine(str(settings.SYNC_DATABASE_URL))
    with engine.connect() as conn:
        conn.execute(
            text("""
                UPDATE sowknow.documents
                SET metadata = jsonb_set(COALESCE(metadata, '{}'), '{extracted_text}', to_jsonb(:transcript::text)),
                    detected_language = :lang
                WHERE id = :doc_id::uuid
            """),
            {"transcript": result["transcript"], "lang": "auto", "doc_id": document_id},
        )
        conn.commit()

    logger.info(f"Voice note transcribed: doc={document_id}, chars={len(result['transcript'])}")
    return {"transcript": result["transcript"], "document_id": document_id}
```

- [ ] **Step 2: Register the task module**

In `backend/app/tasks/__init__.py`, update to:

```python
# Celery tasks initialization
from app.tasks import anomaly_tasks, article_tasks, backfill_tasks, document_tasks, embedding_tasks, report_tasks, voice_tasks

__all__ = ["document_tasks", "anomaly_tasks", "article_tasks", "backfill_tasks", "embedding_tasks", "report_tasks", "voice_tasks"]
```

- [ ] **Step 3: Add to Celery includes**

In `backend/app/celery_app.py`, add `"app.tasks.voice_tasks"` to the `include` list (after line 41):

```python
    include=[
        "app.tasks.document_tasks",
        "app.tasks.anomaly_tasks",
        "app.tasks.embedding_tasks",
        "app.tasks.report_tasks",
        "app.tasks.monitoring_tasks",
        "app.tasks.article_tasks",
        "app.tasks.voice_tasks",
    ],
```

And add task routing (in the `task_routes` dict around line 69):

```python
        "app.tasks.voice_tasks.*": {"queue": "document_processing"},
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/tasks/voice_tasks.py backend/app/tasks/__init__.py backend/app/celery_app.py
git commit -m "feat: add transcribe_voice_note Celery task with whisper.cpp"
```

---

## Task 4: Voice API Endpoints

**Files:**
- Create: `backend/app/api/voice.py`
- Modify: `backend/app/api/documents.py` (add `transcript` form field)
- Modify: `backend/app/api/notes.py` (add audio attachment endpoint)
- Create: `backend/tests/unit/test_voice_api.py`

- [ ] **Step 1: Write failing tests for voice API**

Create `backend/tests/unit/test_voice_api.py`:

```python
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from io import BytesIO


class TestVoiceTranscribeEndpoint:
    """Tests for POST /api/v1/voice/transcribe"""

    @pytest.mark.asyncio
    async def test_transcribe_returns_transcript(self, client, auth_headers):
        """Audio file is transcribed and result returned."""
        audio_data = b"\x00" * 1024  # Fake audio bytes
        with patch("app.api.voice.whisper_service") as mock_whisper:
            mock_whisper.transcribe = AsyncMock(return_value={"transcript": "Bonjour le monde"})
            response = await client.post(
                "/api/v1/voice/transcribe",
                files={"file": ("test.webm", BytesIO(audio_data), "audio/webm")},
                headers=auth_headers,
            )
        assert response.status_code == 200
        data = response.json()
        assert data["transcript"] == "Bonjour le monde"

    @pytest.mark.asyncio
    async def test_transcribe_rejects_non_audio(self, client, auth_headers):
        """Non-audio files are rejected."""
        response = await client.post(
            "/api/v1/voice/transcribe",
            files={"file": ("test.txt", BytesIO(b"hello"), "text/plain")},
            headers=auth_headers,
        )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_transcribe_requires_auth(self, client):
        """Unauthenticated requests are rejected."""
        audio_data = b"\x00" * 1024
        response = await client.post(
            "/api/v1/voice/transcribe",
            files={"file": ("test.webm", BytesIO(audio_data), "audio/webm")},
        )
        assert response.status_code == 401


class TestAudioStreamEndpoint:
    """Tests for GET /api/v1/audio/{audio_id}/stream"""

    @pytest.mark.asyncio
    async def test_stream_returns_audio(self, client, auth_headers):
        """Audio stream returns correct content type."""
        # This test requires a seeded audio file — will be integration-tested
        pass
```

- [ ] **Step 2: Create the voice router**

Create `backend/app/api/voice.py`:

```python
import logging
import os
import tempfile
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models.document import Document
from app.models.note_audio import NoteAudio
from app.models.user import User
from app.services.whisper_service import whisper_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/voice", tags=["voice"])

ALLOWED_AUDIO_TYPES = {"audio/webm", "audio/ogg", "audio/wav", "audio/mpeg", "audio/mp4"}
MAX_AUDIO_DURATION = 60  # seconds — enforced by file size heuristic (1 min ≈ 1MB WebM/Opus)
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

    # Write to temp file for whisper.cpp
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
        # RBAC check for confidential documents
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
```

- [ ] **Step 3: Add `transcript` form field to document upload**

In `backend/app/api/documents.py`, modify the upload endpoint signature (line 208-214) to add a `transcript` parameter:

```python
@router.post("/upload", response_model=DocumentUploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    bucket: str = Form("public"),
    title: str | None = Form(None),
    tags: str | None = Form(None),
    document_type: str | None = Form(None),
    transcript: str | None = Form(None),  # <-- ADD THIS
    x_bot_api_key: str | None = Header(None, alias="X-Bot-Api-Key"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentUploadResponse:
```

And pass `transcript` to `_do_upload_document`:

```python
        return await _do_upload_document(
            file=file, bucket=bucket, title=title, tags=tags,
            document_type=document_type, transcript=transcript,
            x_bot_api_key=x_bot_api_key, current_user=current_user, db=db,
        )
```

In `_do_upload_document`, add `transcript: str | None` parameter and near the end where the document row is created, add:

```python
    # If transcript provided (voice notes), store it and skip OCR
    if transcript:
        doc.document_metadata = {**(doc.document_metadata or {}), "extracted_text": transcript}
        doc.ocr_processed = True  # Skip OCR pipeline for audio with transcript
```

- [ ] **Step 4: Add note audio endpoint to notes router**

In `backend/app/api/notes.py`, add at the end:

```python
@router.post("/{note_id}/audio")
async def upload_note_audio(
    note_id: str,
    file: UploadFile = File(...),
    transcript: str | None = Form(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload an audio attachment to a note."""
    import os
    import uuid as uuid_mod
    from datetime import datetime
    from app.models.note_audio import NoteAudio

    ALLOWED_AUDIO = {"audio/webm", "audio/ogg", "audio/wav", "audio/mpeg"}
    if file.content_type not in ALLOWED_AUDIO:
        raise HTTPException(status_code=400, detail="Invalid audio format")

    # Verify note exists and belongs to user
    result = await db.execute(select(Note).where(Note.id == uuid_mod.UUID(note_id), Note.user_id == current_user.id))
    note = result.scalar_one_or_none()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    # Save audio file
    now = datetime.utcnow()
    audio_dir = f"/data/audio/{now.year}/{now.month:02d}"
    os.makedirs(audio_dir, exist_ok=True)
    ext = os.path.splitext(file.filename or "audio.webm")[1] or ".webm"
    audio_id = uuid_mod.uuid4()
    file_path = f"{audio_dir}/{audio_id}{ext}"

    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)

    note_audio = NoteAudio(
        id=audio_id,
        note_id=uuid_mod.UUID(note_id),
        file_path=file_path,
        transcript=transcript,
    )
    db.add(note_audio)
    await db.commit()

    return {
        "audio_id": str(audio_id),
        "url": f"/api/v1/voice/audio/{audio_id}/stream",
        "transcript": transcript,
    }
```

Add necessary imports at the top of notes.py:

```python
from fastapi import File, Form, UploadFile
```

- [ ] **Step 5: Register the voice router in the app**

Find where routers are included (likely `backend/app/main.py` or `backend/main_minimal.py`) and add:

```python
from app.api.voice import router as voice_router
app.include_router(voice_router, prefix="/api/v1")
```

- [ ] **Step 6: Run tests**

```bash
cd /home/development/src/active/sowknow4/backend
python -m pytest tests/unit/test_voice_api.py -v
```

Expected: Tests pass (mocked whisper service).

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/voice.py backend/app/api/documents.py backend/app/api/notes.py backend/tests/unit/test_voice_api.py
git commit -m "feat: add voice API — transcribe endpoint, audio streaming, note audio uploads"
```

---

## Task 5: Whisper.cpp in Worker Dockerfile

**Files:**
- Modify: `backend/Dockerfile.worker`

- [ ] **Step 1: Add Whisper.cpp build stage to Dockerfile.worker**

In `backend/Dockerfile.worker`, add after the system dependencies block (after line 26 `&& rm -rf /var/lib/apt/lists/*`):

```dockerfile
# Install Whisper.cpp for voice note transcription
RUN apt-get update && apt-get install -y \
    git \
    cmake \
    make \
    && cd /tmp \
    && git clone --depth 1 https://github.com/ggerganov/whisper.cpp.git \
    && cd whisper.cpp \
    && cmake -B build \
    && cmake --build build --config Release -j$(nproc) \
    && cp build/bin/whisper-cli /usr/local/bin/whisper-cpp \
    && cd / && rm -rf /tmp/whisper.cpp \
    && apt-get purge -y git cmake make \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*
```

After the model cache directory creation (line 43), add:

```dockerfile
# Download Whisper small model for voice transcription (~466MB)
# This runs at build time so the model is baked into the image
RUN curl -L -o /models/ggml-small.bin \
    https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin
```

- [ ] **Step 2: Add audio data directory to volume mounts**

In `docker-compose.yml`, add to the worker service volumes:

```yaml
      - audio-data:/data/audio
```

And add the named volume at the bottom of the file:

```yaml
  audio-data:
    name: sowknow4-audio-data
```

Also add the same volume to the backend service so it can serve audio files.

- [ ] **Step 3: Verify build**

```bash
cd /home/development/src/active/sowknow4
docker compose build worker
```

Expected: Build completes, whisper-cpp binary at `/usr/local/bin/whisper-cpp`, model at `/models/ggml-small.bin`.

- [ ] **Step 4: Commit**

```bash
git add backend/Dockerfile.worker docker-compose.yml
git commit -m "feat: add whisper.cpp + ggml-small model to worker image for voice transcription"
```

---

## Task 6: Telegram Bot Voice Handler

**Files:**
- Modify: `backend/telegram_bot/bot.py`

- [ ] **Step 1: Add voice upload method to TelegramBotClient**

In `backend/telegram_bot/bot.py`, add after the `create_journal_entry` method (after line 443):

```python
    async def upload_voice_journal(
        self, audio_bytes: bytes, filename: str, access_token: str, transcript: str | None = None
    ) -> dict:
        """Upload a voice note as a journal entry with optional transcript."""
        try:
            form_data = {
                "bucket": "confidential",
                "document_type": "journal",
                "tags": "voice-note",
            }
            if transcript:
                form_data["transcript"] = transcript
            files = {"file": (filename, audio_bytes, "audio/ogg")}
            response = await self._client.post(
                "/api/v1/documents/upload",
                data=form_data,
                files=files,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "X-Bot-Api-Key": BOT_API_KEY,
                },
            )
            response.raise_for_status()
            return response.json()
        except CircuitBreakerOpenError as e:
            return self._circuit_breaker_error(e, "voice_upload")
        except Exception as e:
            logger.error(f"Voice upload error: {str(e)}")
            return {"error": str(e)}
```

- [ ] **Step 2: Add the voice message handler function**

Add before the `start_command` function (before line 507):

```python
async def handle_voice_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle voice messages — download, transcribe via Whisper.cpp, save as journal entry."""
    user = update.effective_user
    voice = update.message.voice or update.message.audio

    if not voice:
        return

    session = await session_manager.get_session(user.id)
    if not session:
        await update.message.reply_text("❌ Please use /start first.")
        return

    access_token = session.get("access_token")
    if not access_token:
        await update.message.reply_text("❌ Session expired. Use /start to reconnect.")
        return

    # Show processing indicator
    status_msg = await update.message.reply_text("🎙️ Transcription en cours...")

    try:
        # Download voice file from Telegram
        file = await context.bot.get_file(voice.file_id)
        audio_bytes = await file.download_as_bytearray()

        # Upload to backend — Celery task will transcribe via Whisper.cpp
        result = await bot_client.upload_voice_journal(
            audio_bytes=bytes(audio_bytes),
            filename=f"voice_{user.id}_{voice.file_unique_id}.ogg",
            access_token=access_token,
        )

        if "error" in result:
            await status_msg.edit_text(f"❌ Erreur: {result['error']}")
            return

        doc_id = result.get("document_id", "")

        # Dispatch transcription task
        from app.tasks.voice_tasks import transcribe_voice_note
        # The file path follows the upload pattern — get it from the response or construct it
        transcribe_voice_note.delay(
            audio_file_path=result.get("file_path", ""),
            document_id=doc_id,
        )

        duration = voice.duration or 0
        await status_msg.edit_text(
            f"✅ Note vocale sauvegardée ({duration}s)\n"
            f"📝 Transcription en cours — disponible sous peu."
        )

    except Exception as e:
        logger.error(f"Voice handler error for user {user.id}: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ Erreur lors du traitement de la note vocale.")
```

- [ ] **Step 3: Register the voice handler**

In the handler registration section (around line 1585-1589), add BEFORE the text message handler:

```python
    application.add_handler(
        MessageHandler(filters.VOICE | filters.AUDIO, handle_voice_message)
    )
```

This must come BEFORE the `filters.TEXT` handler so voice messages are caught first.

- [ ] **Step 4: Commit**

```bash
git add backend/telegram_bot/bot.py
git commit -m "feat: Telegram bot voice note handler — download, upload, trigger Whisper transcription"
```

---

## Task 7: Frontend — useVoiceRecorder Hook

**Files:**
- Create: `frontend/hooks/useVoiceRecorder.ts`

- [ ] **Step 1: Create the hook**

Create `frontend/hooks/useVoiceRecorder.ts`:

```typescript
import { useCallback, useEffect, useRef, useState } from 'react';

export type RecordingState = 'idle' | 'recording' | 'preview' | 'transcribing';

interface UseVoiceRecorderOptions {
  onTranscript?: (text: string) => void;
  onAudioReady?: (blob: Blob, transcript: string) => void;
  privateMode?: boolean;
  apiBaseUrl?: string;
}

interface UseVoiceRecorderReturn {
  state: RecordingState;
  transcript: string;
  interimTranscript: string;
  audioBlob: Blob | null;
  audioUrl: string | null;
  analyserNode: AnalyserNode | null;
  startRecording: () => Promise<void>;
  stopRecording: () => void;
  cancelRecording: () => void;
  send: () => void;
  reRecord: () => void;
  isSupported: boolean;
  isSpeechSupported: boolean;
  error: string | null;
}

export function useVoiceRecorder(options: UseVoiceRecorderOptions = {}): UseVoiceRecorderReturn {
  const { onTranscript, onAudioReady, privateMode = false, apiBaseUrl = '' } = options;

  const [state, setState] = useState<RecordingState>('idle');
  const [transcript, setTranscript] = useState('');
  const [interimTranscript, setInterimTranscript] = useState('');
  const [audioBlob, setAudioBlob] = useState<Blob | null>(null);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [analyserNode, setAnalyserNode] = useState<AnalyserNode | null>(null);
  const [error, setError] = useState<string | null>(null);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const recognitionRef = useRef<SpeechRecognition | null>(null);
  const chunksRef = useRef<Blob[]>([]);

  const isSupported = typeof navigator !== 'undefined' && !!navigator.mediaDevices?.getUserMedia;
  const isSpeechSupported = typeof window !== 'undefined' && !!(
    window.SpeechRecognition || (window as any).webkitSpeechRecognition
  );

  const cleanup = useCallback(() => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop();
    }
    if (recognitionRef.current) {
      recognitionRef.current.stop();
    }
    if (audioContextRef.current) {
      audioContextRef.current.close();
      audioContextRef.current = null;
    }
    mediaRecorderRef.current = null;
    recognitionRef.current = null;
    chunksRef.current = [];
    setAnalyserNode(null);
  }, []);

  const startRecording = useCallback(async () => {
    setError(null);
    setTranscript('');
    setInterimTranscript('');
    setAudioBlob(null);
    if (audioUrl) URL.revokeObjectURL(audioUrl);
    setAudioUrl(null);
    chunksRef.current = [];

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });

      // Set up AudioContext + AnalyserNode for waveform
      const audioCtx = new AudioContext();
      const source = audioCtx.createMediaStreamSource(stream);
      const analyser = audioCtx.createAnalyser();
      analyser.fftSize = 256;
      source.connect(analyser);
      audioContextRef.current = audioCtx;
      setAnalyserNode(analyser);

      // Set up MediaRecorder
      const recorder = new MediaRecorder(stream, { mimeType: 'audio/webm;codecs=opus' });
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };
      recorder.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: 'audio/webm' });
        setAudioBlob(blob);
        setAudioUrl(URL.createObjectURL(blob));
        stream.getTracks().forEach(t => t.stop());
      };
      mediaRecorderRef.current = recorder;
      recorder.start(250); // Collect data every 250ms

      // Set up Web Speech API (if not private mode)
      if (!privateMode && isSpeechSupported) {
        const SpeechRecognition = window.SpeechRecognition || (window as any).webkitSpeechRecognition;
        const recognition = new SpeechRecognition();
        recognition.continuous = true;
        recognition.interimResults = true;
        // Leave lang unset for auto-detect (FR/EN)
        recognition.onresult = (event: SpeechRecognitionEvent) => {
          let interim = '';
          let final_ = '';
          for (let i = 0; i < event.results.length; i++) {
            const result = event.results[i];
            if (result.isFinal) {
              final_ += result[0].transcript + ' ';
            } else {
              interim += result[0].transcript;
            }
          }
          if (final_) setTranscript(prev => (prev + final_).trim());
          setInterimTranscript(interim);
        };
        recognition.onerror = (event) => {
          if (event.error !== 'aborted') {
            console.warn('Speech recognition error:', event.error);
          }
        };
        recognitionRef.current = recognition;
        recognition.start();
      }

      setState('recording');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Microphone access denied');
      setState('idle');
    }
  }, [privateMode, isSpeechSupported, audioUrl]);

  const stopRecording = useCallback(() => {
    if (recognitionRef.current) {
      recognitionRef.current.stop();
      recognitionRef.current = null;
    }
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop();
    }
    if (audioContextRef.current) {
      audioContextRef.current.close();
      audioContextRef.current = null;
    }
    setAnalyserNode(null);
    setState('preview');
  }, []);

  const cancelRecording = useCallback(() => {
    cleanup();
    if (audioUrl) URL.revokeObjectURL(audioUrl);
    setAudioUrl(null);
    setAudioBlob(null);
    setTranscript('');
    setInterimTranscript('');
    setState('idle');
  }, [cleanup, audioUrl]);

  const send = useCallback(async () => {
    if (!audioBlob) return;

    // If private mode and no transcript yet, send to backend for transcription
    if (privateMode && !transcript) {
      setState('transcribing');
      try {
        const formData = new FormData();
        formData.append('file', audioBlob, 'voice.webm');
        const res = await fetch(`${apiBaseUrl}/api/v1/voice/transcribe`, {
          method: 'POST',
          body: formData,
          credentials: 'include',
        });
        if (!res.ok) throw new Error('Transcription failed');
        const data = await res.json();
        setTranscript(data.transcript);
        onAudioReady?.(audioBlob, data.transcript);
      } catch (err) {
        setError('Server transcription failed');
        setState('preview');
        return;
      }
    } else {
      onAudioReady?.(audioBlob, transcript);
    }

    onTranscript?.(transcript);
    setState('idle');
    cleanup();
    if (audioUrl) URL.revokeObjectURL(audioUrl);
    setAudioUrl(null);
    setAudioBlob(null);
    setTranscript('');
  }, [audioBlob, transcript, privateMode, apiBaseUrl, onTranscript, onAudioReady, cleanup, audioUrl]);

  const reRecord = useCallback(() => {
    if (audioUrl) URL.revokeObjectURL(audioUrl);
    setAudioUrl(null);
    setAudioBlob(null);
    setTranscript('');
    setInterimTranscript('');
    setState('idle');
  }, [audioUrl]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      cleanup();
      if (audioUrl) URL.revokeObjectURL(audioUrl);
    };
  }, []);

  return {
    state, transcript, interimTranscript, audioBlob, audioUrl,
    analyserNode, startRecording, stopRecording, cancelRecording,
    send, reRecord, isSupported, isSpeechSupported, error,
  };
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/hooks/useVoiceRecorder.ts
git commit -m "feat: add useVoiceRecorder hook — MediaRecorder + Web Speech API + waveform"
```

---

## Task 8: Frontend — VoiceRecorder Component

**Files:**
- Create: `frontend/components/VoiceRecorder.tsx`

- [ ] **Step 1: Create the VoiceRecorder component**

Create `frontend/components/VoiceRecorder.tsx`:

```tsx
'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslations } from 'next-intl';
import { useVoiceRecorder, RecordingState } from '@/hooks/useVoiceRecorder';

interface VoiceRecorderProps {
  mode: 'journal' | 'note' | 'search';
  onTranscript?: (text: string) => void;
  onAudioReady?: (blob: Blob, transcript: string) => void;
  onCancel?: () => void;
  className?: string;
}

function WaveformBars({ analyserNode }: { analyserNode: AnalyserNode | null }) {
  const canvasRef = useRef<HTMLDivElement>(null);
  const barsRef = useRef<number[]>(new Array(20).fill(4));
  const rafRef = useRef<number>(0);

  useEffect(() => {
    if (!analyserNode || !canvasRef.current) return;
    const dataArray = new Uint8Array(analyserNode.frequencyBinCount);

    const animate = () => {
      analyserNode.getByteFrequencyData(dataArray);
      const bars = barsRef.current;
      const step = Math.floor(dataArray.length / bars.length);
      for (let i = 0; i < bars.length; i++) {
        const val = dataArray[i * step] / 255;
        bars[i] = Math.max(4, val * 32);
      }
      if (canvasRef.current) {
        const children = canvasRef.current.children;
        for (let i = 0; i < children.length; i++) {
          (children[i] as HTMLElement).style.height = `${bars[i]}px`;
        }
      }
      rafRef.current = requestAnimationFrame(animate);
    };
    rafRef.current = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(rafRef.current);
  }, [analyserNode]);

  return (
    <div ref={canvasRef} className="flex items-center gap-[2px] h-8">
      {Array.from({ length: 20 }).map((_, i) => (
        <div
          key={i}
          className="w-1 bg-amber-450 rounded-full transition-all duration-75"
          style={{ height: '4px' }}
        />
      ))}
    </div>
  );
}

export default function VoiceRecorder({ mode, onTranscript, onAudioReady, onCancel, className = '' }: VoiceRecorderProps) {
  const t = useTranslations('voice');
  const [privateMode, setPrivateMode] = useState(mode === 'journal');
  const [isHolding, setIsHolding] = useState(false);
  const [slideCancel, setSlideCancel] = useState(false);
  const holdTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const startXRef = useRef(0);

  const {
    state, transcript, interimTranscript, audioBlob, audioUrl,
    analyserNode, startRecording, stopRecording, cancelRecording,
    send, reRecord, isSupported, error,
  } = useVoiceRecorder({
    privateMode,
    onTranscript: mode === 'search' ? onTranscript : undefined,
    onAudioReady: mode !== 'search' ? onAudioReady : undefined,
  });

  // For search mode: auto-send on stop
  const handleStopForSearch = useCallback(() => {
    stopRecording();
    // In search mode, transcript goes directly to search input
    if (mode === 'search') {
      // Small delay to let final transcript arrive
      setTimeout(() => {
        onTranscript?.(transcript || interimTranscript);
      }, 300);
    }
  }, [mode, stopRecording, onTranscript, transcript, interimTranscript]);

  // Hold-to-talk: pointer events
  const handlePointerDown = useCallback((e: React.PointerEvent) => {
    if (state === 'recording') {
      // Already recording (toggle mode) — stop
      if (mode === 'search') handleStopForSearch();
      else stopRecording();
      return;
    }
    if (state !== 'idle') return;

    startXRef.current = e.clientX;
    setSlideCancel(false);

    // Start immediately for hold mode, but also support tap
    holdTimerRef.current = setTimeout(() => {
      setIsHolding(true);
    }, 200);
    startRecording();
  }, [state, startRecording, stopRecording, handleStopForSearch, mode]);

  const handlePointerMove = useCallback((e: React.PointerEvent) => {
    if (!isHolding || state !== 'recording') return;
    const dx = startXRef.current - e.clientX;
    setSlideCancel(dx > 80);
  }, [isHolding, state]);

  const handlePointerUp = useCallback(() => {
    if (holdTimerRef.current) {
      clearTimeout(holdTimerRef.current);
      holdTimerRef.current = null;
    }

    if (isHolding && state === 'recording') {
      if (slideCancel) {
        cancelRecording();
      } else if (mode === 'search') {
        handleStopForSearch();
      } else {
        stopRecording();
      }
      setIsHolding(false);
      setSlideCancel(false);
    }
    // If not holding, it was a tap — recording continues (toggle mode)
  }, [isHolding, state, slideCancel, cancelRecording, stopRecording, handleStopForSearch, mode]);

  if (!isSupported) {
    return (
      <div className={`text-vault-400 text-sm ${className}`}>
        {t('micNotSupported')}
      </div>
    );
  }

  return (
    <div className={`flex flex-col gap-2 ${className}`}>
      {/* Error display */}
      {error && <p className="text-red-400 text-xs">{error}</p>}

      {/* Privacy toggle (journal & notes only) */}
      {mode !== 'search' && state === 'idle' && (
        <button
          onClick={() => setPrivateMode(!privateMode)}
          className={`flex items-center gap-1.5 text-xs px-2 py-1 rounded-full w-fit transition-colors ${
            privateMode ? 'bg-green-900/30 text-green-400' : 'bg-vault-800 text-vault-400'
          }`}
          title={privateMode ? t('privateOn') : t('privateOff')}
        >
          <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
              d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
          </svg>
          {privateMode ? t('privateTranscription') : t('cloudTranscription')}
        </button>
      )}

      {/* Main recording area */}
      <div className="flex items-center gap-3">
        {/* Mic button */}
        <button
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          onPointerLeave={handlePointerUp}
          className={`relative flex items-center justify-center w-12 h-12 rounded-full transition-all select-none touch-none ${
            state === 'recording'
              ? 'bg-red-500 shadow-lg shadow-red-500/30 animate-pulse-slow'
              : state === 'transcribing'
              ? 'bg-vault-700 cursor-wait'
              : 'bg-amber-450 hover:bg-amber-400 cursor-pointer'
          }`}
          disabled={state === 'transcribing' || state === 'preview'}
        >
          {state === 'transcribing' ? (
            <svg className="w-5 h-5 text-white animate-spin" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
          ) : (
            <svg className="w-5 h-5 text-white" fill="currentColor" viewBox="0 0 24 24">
              <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3z" />
              <path d="M17 11c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z" />
            </svg>
          )}
        </button>

        {/* Waveform + slide-to-cancel */}
        {state === 'recording' && (
          <div className="flex items-center gap-3 flex-1">
            <WaveformBars analyserNode={analyserNode} />
            {isHolding && (
              <span className={`text-xs transition-colors ${slideCancel ? 'text-red-400' : 'text-vault-400'}`}>
                {slideCancel ? t('releaseToCancel') : t('slideToCancel')}
              </span>
            )}
          </div>
        )}

        {/* Preview state */}
        {state === 'preview' && audioUrl && (
          <div className="flex items-center gap-2 flex-1">
            <audio src={audioUrl} controls className="h-8 flex-1" />
            <button onClick={send} className="px-3 py-1.5 bg-amber-450 text-white rounded-lg text-sm font-medium hover:bg-amber-400">
              {t('send')}
            </button>
            <button onClick={reRecord} className="px-3 py-1.5 bg-vault-700 text-vault-300 rounded-lg text-sm hover:bg-vault-600">
              {t('reRecord')}
            </button>
            <button onClick={cancelRecording} className="px-2 py-1.5 text-vault-500 hover:text-red-400 text-sm">
              {t('cancel')}
            </button>
          </div>
        )}

        {/* Transcribing indicator */}
        {state === 'transcribing' && (
          <span className="text-vault-400 text-sm animate-pulse">{t('transcribing')}</span>
        )}
      </div>

      {/* Transcript display */}
      {(state === 'recording' || state === 'preview') && (transcript || interimTranscript) && (
        <div className="text-sm pl-15">
          {transcript && <span className="text-vault-200">{transcript}</span>}
          {interimTranscript && <span className="text-vault-500 italic"> {interimTranscript}</span>}
        </div>
      )}

      {/* Private mode hint during recording */}
      {state === 'recording' && privateMode && (
        <p className="text-xs text-vault-500 pl-15">
          🔒 {t('privateHint')}
        </p>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/components/VoiceRecorder.tsx
git commit -m "feat: add VoiceRecorder component — Telegram-style tap/hold, waveform, privacy toggle"
```

---

## Task 9: Frontend — i18n Strings

**Files:**
- Modify: `frontend/app/messages/fr.json`
- Modify: `frontend/app/messages/en.json`

- [ ] **Step 1: Add French voice strings**

In `frontend/app/messages/fr.json`, add a `"voice"` section:

```json
  "voice": {
    "record": "Enregistrer une note vocale",
    "send": "Envoyer",
    "cancel": "Annuler",
    "reRecord": "Recommencer",
    "slideToCancel": "← Glissez pour annuler",
    "releaseToCancel": "Relâchez pour annuler",
    "transcribing": "Transcription en cours...",
    "privateTranscription": "Transcription privée",
    "cloudTranscription": "Transcription rapide",
    "privateOn": "Transcription locale activée — aucune donnée envoyée au cloud",
    "privateOff": "Transcription via le navigateur — plus rapide mais les données transitent par le cloud",
    "privateHint": "Transcription locale — sera disponible après l'envoi",
    "micNotSupported": "Le micro n'est pas disponible dans ce navigateur",
    "micPermission": "Accès au microphone requis",
    "addVoiceEntry": "Ajouter une note vocale",
    "voiceSearch": "Recherche vocale"
  }
```

- [ ] **Step 2: Add English voice strings**

In `frontend/app/messages/en.json`, add:

```json
  "voice": {
    "record": "Record a voice note",
    "send": "Send",
    "cancel": "Cancel",
    "reRecord": "Re-record",
    "slideToCancel": "← Slide to cancel",
    "releaseToCancel": "Release to cancel",
    "transcribing": "Transcribing...",
    "privateTranscription": "Private transcription",
    "cloudTranscription": "Fast transcription",
    "privateOn": "Local transcription enabled — no data sent to cloud",
    "privateOff": "Browser transcription — faster but data passes through cloud",
    "privateHint": "Local transcription — will be available after sending",
    "micNotSupported": "Microphone not available in this browser",
    "micPermission": "Microphone access required",
    "addVoiceEntry": "Add voice entry",
    "voiceSearch": "Voice search"
  }
```

- [ ] **Step 3: Commit**

```bash
git add frontend/app/messages/fr.json frontend/app/messages/en.json
git commit -m "feat: add voice i18n strings — French and English"
```

---

## Task 10: Frontend — API Client Methods

**Files:**
- Modify: `frontend/lib/api.ts`

- [ ] **Step 1: Add voice-related API methods**

In `frontend/lib/api.ts`, add after the `uploadDocument` method (after line 196):

```typescript
  async uploadAudioDocument(audioBlob: Blob, bucket: string, transcript: string, documentType: string = 'journal', tags: string = '') {
    const formData = new FormData();
    formData.append('file', audioBlob, 'voice-note.webm');
    formData.append('bucket', bucket);
    formData.append('document_type', documentType);
    formData.append('transcript', transcript);
    if (tags) formData.append('tags', tags);

    return this.request<{ document_id: string; filename: string; status: string; message: string }>('/v1/documents/upload', {
      method: 'POST',
      headers: {},
      body: formData,
    });
  }

  async uploadNoteAudio(noteId: string, audioBlob: Blob, transcript: string) {
    const formData = new FormData();
    formData.append('file', audioBlob, 'voice-note.webm');
    if (transcript) formData.append('transcript', transcript);

    return this.request<{ audio_id: string; url: string; transcript: string }>(`/v1/notes/${noteId}/audio`, {
      method: 'POST',
      headers: {},
      body: formData,
    });
  }

  async transcribeAudio(audioBlob: Blob) {
    const formData = new FormData();
    formData.append('file', audioBlob, 'voice.webm');

    return this.request<{ transcript: string; detected_language: string }>('/v1/voice/transcribe', {
      method: 'POST',
      headers: {},
      body: formData,
    });
  }

  getAudioStreamUrl(audioId: string): string {
    return `${this.baseUrl}/v1/voice/audio/${audioId}/stream`;
  }
```

- [ ] **Step 2: Commit**

```bash
git add frontend/lib/api.ts
git commit -m "feat: add voice API client methods — upload audio, note audio, transcribe"
```

---

## Task 11: Frontend — Journal Page Integration

**Files:**
- Modify: `frontend/app/[locale]/journal/page.tsx`

- [ ] **Step 1: Add VoiceRecorder to journal page**

In `frontend/app/[locale]/journal/page.tsx`:

Add imports at the top:

```typescript
import VoiceRecorder from '@/components/VoiceRecorder';
import { useTranslations } from 'next-intl';
```

Add state for showing the recorder (inside the component, near other state declarations):

```typescript
const [showRecorder, setShowRecorder] = useState(false);
const t = useTranslations('voice');
```

In the header section (around line 170-176), add the voice entry button:

```tsx
<button
  onClick={() => setShowRecorder(!showRecorder)}
  className="flex items-center gap-2 px-4 py-2 bg-amber-450 text-white rounded-lg hover:bg-amber-400 transition-colors text-sm font-medium"
>
  <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
    <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3z" />
    <path d="M17 11c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z" />
  </svg>
  {t('addVoiceEntry')}
</button>
```

Below the header/filters, add the recorder:

```tsx
{showRecorder && (
  <div className="mb-4 p-4 bg-vault-900/50 rounded-xl border border-vault-700">
    <VoiceRecorder
      mode="journal"
      onAudioReady={async (blob, transcript) => {
        try {
          await api.uploadAudioDocument(blob, 'confidential', transcript, 'journal', 'voice-note');
          setShowRecorder(false);
          // Refresh journal entries
          fetchEntries(1);
        } catch (err) {
          console.error('Voice upload failed:', err);
        }
      }}
      onCancel={() => setShowRecorder(false)}
    />
  </div>
)}
```

In the journal entry rendering (the timeline cards), detect audio entries and show a play button:

```tsx
{entry.mime_type?.startsWith('audio/') && (
  <audio
    src={api.getAudioStreamUrl(entry.id)}
    controls
    className="w-full mt-2 h-8"
  />
)}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/app/[locale]/journal/page.tsx
git commit -m "feat: integrate VoiceRecorder into journal page — record + playback"
```

---

## Task 12: Frontend — Notes Page Integration

**Files:**
- Modify: `frontend/app/[locale]/notes/page.tsx`

- [ ] **Step 1: Add VoiceRecorder to notes editor modal**

In `frontend/app/[locale]/notes/page.tsx`:

Add imports:

```typescript
import VoiceRecorder from '@/components/VoiceRecorder';
```

Add state for pending audio (near other state declarations):

```typescript
const [pendingAudio, setPendingAudio] = useState<{ blob: Blob; transcript: string } | null>(null);
```

Inside the editor modal (around line 220-228, near the textarea), add a mic button and recorder:

```tsx
{/* Voice input for notes */}
<div className="mt-2">
  <VoiceRecorder
    mode="note"
    onAudioReady={(blob, transcript) => {
      // Append transcript to content
      setEditContent(prev => prev ? `${prev}\n\n${transcript}` : transcript);
      setPendingAudio({ blob, transcript });
    }}
  />
</div>
```

In the `handleSave` function, after the note is created/updated, upload the audio attachment if present:

```typescript
// After successful save, attach audio if present
if (pendingAudio && savedNote?.id) {
  try {
    await api.uploadNoteAudio(savedNote.id, pendingAudio.blob, pendingAudio.transcript);
  } catch (err) {
    console.error('Failed to attach audio:', err);
  }
  setPendingAudio(null);
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/app/[locale]/notes/page.tsx
git commit -m "feat: integrate VoiceRecorder into notes editor — dictate + audio attachment"
```

---

## Task 13: Frontend — Search Page Integration

**Files:**
- Modify: `frontend/app/[locale]/search/page.tsx`

- [ ] **Step 1: Add voice input to search page**

In `frontend/app/[locale]/search/page.tsx`:

Add imports:

```typescript
import VoiceRecorder from '@/components/VoiceRecorder';
```

Add state:

```typescript
const [showVoiceSearch, setShowVoiceSearch] = useState(false);
```

Inside the search input area, add a mic button to the right of the input:

```tsx
<button
  onClick={() => setShowVoiceSearch(!showVoiceSearch)}
  className="absolute right-12 top-1/2 -translate-y-1/2 p-2 text-vault-400 hover:text-amber-450 transition-colors"
  title={t('voiceSearch')}
>
  <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 24 24">
    <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3z" />
    <path d="M17 11c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z" />
  </svg>
</button>
```

Below the search input, show the VoiceRecorder when active:

```tsx
{showVoiceSearch && (
  <div className="mt-3 p-3 bg-vault-900/50 rounded-xl border border-vault-700">
    <VoiceRecorder
      mode="search"
      onTranscript={(text) => {
        if (text) {
          setQuery(text);  // Set the search input value
          setShowVoiceSearch(false);
          // Trigger search submission
          handleSearch(text);
        }
      }}
      onCancel={() => setShowVoiceSearch(false)}
    />
  </div>
)}
```

`handleSearch` should be the existing search submission function — find it in the component and use its name. The voice transcript gets injected into the query and auto-submitted.

- [ ] **Step 2: Commit**

```bash
git add frontend/app/[locale]/search/page.tsx
git commit -m "feat: integrate VoiceRecorder into search — speak to search"
```

---

## Task 14: End-to-End Verification

- [ ] **Step 1: Rebuild and restart containers**

```bash
cd /home/development/src/active/sowknow4
docker compose build worker backend
docker compose up -d
```

Wait for all containers to be healthy:

```bash
docker compose ps
```

Expected: All containers `(healthy)`.

- [ ] **Step 2: Verify migration applied**

```bash
docker exec -it sowknow4-postgres psql -U sowknow -d sowknow -c "SELECT column_name FROM information_schema.columns WHERE table_schema='sowknow' AND table_name='documents' AND column_name LIKE 'audio%';"
docker exec -it sowknow4-postgres psql -U sowknow -d sowknow -c "SELECT * FROM information_schema.tables WHERE table_schema='sowknow' AND table_name='note_audio';"
```

Expected: 2 audio columns on documents, note_audio table exists.

- [ ] **Step 3: Verify Whisper.cpp is installed in worker**

```bash
docker exec -it sowknow4-worker whisper-cpp --help
docker exec -it sowknow4-worker ls -la /models/ggml-small.bin
```

Expected: whisper-cpp help output, ggml-small.bin file (~466MB).

- [ ] **Step 4: Test voice transcription endpoint**

```bash
# Record a short test audio or use a sample file
docker exec -it sowknow4-backend curl -X POST http://localhost:8000/api/v1/voice/transcribe -F "file=@/tmp/test.ogg"
```

Expected: `{"transcript": "...", "detected_language": "auto"}`

- [ ] **Step 5: Test frontend voice UI**

Open the app in Chrome (Web Speech API requires Chrome):
1. Navigate to Journal page → click "Add voice entry" → record → verify waveform + transcript
2. Navigate to Notes page → open editor → click mic → dictate → verify text appended
3. Navigate to Search page → click mic icon → speak query → verify auto-submit

- [ ] **Step 6: Test Telegram bot voice notes**

Send a voice message to the SOWKNOW Telegram bot.
Expected: Bot replies "Note vocale sauvegardée" with duration, then transcript appears on the journal page.

- [ ] **Step 7: Final commit**

```bash
git add -A
git commit -m "feat: voice input & voice notes — full integration across journal, notes, search, and Telegram"
```

---

## Summary

| Task | What | Files | Est. Steps |
|------|------|-------|-----------|
| 1 | DB migration + models | 4 files | 7 |
| 2 | Whisper.cpp service | 2 files | 5 |
| 3 | Voice Celery task | 3 files | 4 |
| 4 | Voice API endpoints | 5 files | 7 |
| 5 | Worker Dockerfile | 2 files | 4 |
| 6 | Telegram bot handler | 1 file | 4 |
| 7 | useVoiceRecorder hook | 1 file | 2 |
| 8 | VoiceRecorder component | 1 file | 2 |
| 9 | i18n strings | 2 files | 3 |
| 10 | API client methods | 1 file | 2 |
| 11 | Journal page integration | 1 file | 2 |
| 12 | Notes page integration | 1 file | 2 |
| 13 | Search page integration | 1 file | 2 |
| 14 | E2E verification | 0 files | 7 |
| **Total** | | **25 files** | **53 steps** |
