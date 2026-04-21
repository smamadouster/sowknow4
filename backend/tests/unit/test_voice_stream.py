"""
Unit tests for voice audio streaming — regression suite for the recurring
"cannot play voice files" bug.

Root causes covered:
  1. python-magic detects Telegram OGG Opus as 'application/ogg' not 'audio/ogg'
     → get_mime_type now normalizes it; isAudio() frontend check updated.
  2. Confidential files are Fernet-encrypted on disk (.ogg.encrypted).
     → stream endpoint was serving raw ciphertext; now decrypts via storage_service.
  3. voice_tasks.py was passing the encrypted path directly to whisper.cpp.
     → task now decrypts to a temp file, runs whisper, then deletes temp.

If any of these tests fails the voice feature is broken — do not merge.
"""

import asyncio as _asyncio
import io
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException

# ---------------------------------------------------------------------------
# Helpers / minimal fake data
# ---------------------------------------------------------------------------

FAKE_OGG_BYTES = b"OggS\x00" + b"\x00" * 100  # minimal OGG header (not real audio)
FERNET_KEY = Fernet.generate_key()


def make_fernet() -> Fernet:
    return Fernet(FERNET_KEY)


def encrypt_bytes(data: bytes) -> bytes:
    return make_fernet().encrypt(data)


# ---------------------------------------------------------------------------
# 1. MIME type normalization (documents.py :: get_mime_type)
# ---------------------------------------------------------------------------

class TestGetMimeTypeOggNormalization:
    """python-magic must never store 'application/ogg' in the database."""

    def test_application_ogg_normalized_to_audio_ogg(self):
        """Magic returns application/ogg → must be stored as audio/ogg."""
        import app.api.documents as _docs
        with patch.object(_docs, "_magic_available", True), \
             patch.object(_docs, "_magic") as mock_magic:
            mock_magic.from_buffer.return_value = "application/ogg"

            result = _docs.get_mime_type("voice_123_abc.ogg", FAKE_OGG_BYTES)

        assert result == "audio/ogg", (
            f"Expected 'audio/ogg' but got '{result}'. "
            "This means future Telegram voice uploads will store the wrong MIME type "
            "and the frontend will not render an <audio> element."
        )

    def test_audio_ogg_passed_through_unchanged(self):
        """audio/ogg must not be mangled."""
        import app.api.documents as _docs
        with patch.object(_docs, "_magic_available", True), \
             patch.object(_docs, "_magic") as mock_magic:
            mock_magic.from_buffer.return_value = "audio/ogg"

            result = _docs.get_mime_type("voice.ogg", FAKE_OGG_BYTES)

        assert result == "audio/ogg"

    def test_audio_webm_not_affected(self):
        """Other audio MIME types must not be touched."""
        import app.api.documents as _docs
        with patch.object(_docs, "_magic_available", True), \
             patch.object(_docs, "_magic") as mock_magic:
            mock_magic.from_buffer.return_value = "audio/webm"

            result = _docs.get_mime_type("voice.webm", b"webm bytes")

        assert result == "audio/webm"

    def test_magic_unavailable_falls_back_to_mimetypes(self):
        """When magic is not installed, mimetypes.guess_type must return audio/ogg for .ogg."""
        import app.api.documents as _docs
        with patch.object(_docs, "_magic_available", False):
            result = _docs.get_mime_type("voice.ogg", b"")

        assert result == "audio/ogg"

    def test_magic_returns_application_ogg_no_content(self):
        """Even without content, filename-based detection returns audio/ogg for .ogg files."""
        import app.api.documents as _docs
        with patch.object(_docs, "_magic_available", False):
            result = _docs.get_mime_type("voice_216601573_AgADliIAAjk96VI.ogg", b"")

        assert result == "audio/ogg"


# ---------------------------------------------------------------------------
# 2. _stream_audio_file helper (voice.py)
# ---------------------------------------------------------------------------

class TestStreamAudioFileHelper:
    """_stream_audio_file must decrypt encrypted files and return correct MIME."""

    @pytest.fixture
    def tmp_dir(self):
        d = tempfile.mkdtemp()
        yield d
        shutil.rmtree(d)

    @pytest.fixture
    def plain_ogg(self, tmp_dir):
        """Unencrypted .ogg file on disk."""
        path = os.path.join(tmp_dir, "public", "voice.ogg")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        Path(path).write_bytes(FAKE_OGG_BYTES)
        return path

    @pytest.fixture
    def encrypted_ogg(self, tmp_dir):
        """Fernet-encrypted .ogg.encrypted file in confidential directory."""
        conf_dir = os.path.join(tmp_dir, "confidential")
        os.makedirs(conf_dir, exist_ok=True)
        enc_path = os.path.join(conf_dir, "voice.ogg.encrypted")
        Path(enc_path).write_bytes(encrypt_bytes(FAKE_OGG_BYTES))
        return enc_path

    def _make_storage(self, tmp_dir: str, *, enabled: bool):
        """Build a real StorageService pointed at tmp_dir."""
        with patch.dict(
            os.environ,
            {"STORAGE_ENCRYPTION_KEY": FERNET_KEY.decode()} if enabled else {},
            clear=not enabled,
        ):
            with patch("app.services.storage_service.StorageService._ensure_directories"):
                from app.services.storage_service import StorageService
                svc = StorageService()
                svc.public_path = Path(tmp_dir) / "public"
                svc.confidential_path = Path(tmp_dir) / "confidential"
                svc.public_path.mkdir(exist_ok=True)
                svc.confidential_path.mkdir(exist_ok=True)
                # Re-init encryption with the patched env
                if enabled:
                    svc._fernet = make_fernet()
                return svc

    @pytest.mark.asyncio
    async def test_plain_ogg_served_as_file_response(self, plain_ogg, tmp_dir):
        """Unencrypted .ogg → FileResponse with audio/ogg."""
        from fastapi.responses import FileResponse
        svc = self._make_storage(tmp_dir, enabled=True)

        with patch("app.api.voice.storage_service", svc):
            from app.api.voice import _stream_audio_file
            response = await _stream_audio_file(plain_ogg)

        assert isinstance(response, FileResponse)
        assert response.media_type == "audio/ogg"

    @pytest.mark.asyncio
    async def test_encrypted_ogg_decrypted_and_streamed(self, encrypted_ogg, tmp_dir):
        """Encrypted .ogg.encrypted → StreamingResponse with decrypted bytes, audio/ogg."""
        from fastapi.responses import StreamingResponse
        svc = self._make_storage(tmp_dir, enabled=True)

        with patch("app.api.voice.storage_service", svc):
            from app.api.voice import _stream_audio_file
            response = await _stream_audio_file(encrypted_ogg)

        assert isinstance(response, StreamingResponse), (
            "Expected StreamingResponse for encrypted file but got FileResponse. "
            "Browsers would receive ciphertext and cannot play it."
        )
        assert response.media_type == "audio/ogg"

        # body_iterator may be an async generator — collect via event loop
        async def _collect():
            chunks = []
            async for chunk in response.body_iterator:
                chunks.append(chunk)
            return b"".join(chunks)

        body = await _collect()
        assert body == FAKE_OGG_BYTES, (
            "Decrypted bytes do not match original audio. Decryption is broken."
        )

    @pytest.mark.asyncio
    async def test_encrypted_ogg_content_length_header(self, encrypted_ogg, tmp_dir):
        """Content-Length header must reflect decrypted size."""
        svc = self._make_storage(tmp_dir, enabled=True)

        with patch("app.api.voice.storage_service", svc):
            from app.api.voice import _stream_audio_file
            response = await _stream_audio_file(encrypted_ogg)

        assert "Content-Length" in response.headers
        assert int(response.headers["Content-Length"]) == len(FAKE_OGG_BYTES)

    @pytest.mark.asyncio
    async def test_encryption_disabled_encrypted_file_served_raw(self, encrypted_ogg, tmp_dir):
        """When encryption key not set, .encrypted file is served as FileResponse (no key = no decrypt)."""
        svc = self._make_storage(tmp_dir, enabled=False)

        with patch("app.api.voice.storage_service", svc):
            from app.api.voice import _stream_audio_file
            response = await _stream_audio_file(encrypted_ogg)

        # encryption_enabled is False → fallback to FileResponse
        from fastapi.responses import FileResponse
        assert isinstance(response, FileResponse)

    @pytest.mark.asyncio
    async def test_webm_extension_returns_correct_mime(self, tmp_dir):
        """audio/webm MIME for .webm files."""
        path = os.path.join(tmp_dir, "public", "voice.webm")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        Path(path).write_bytes(b"webm bytes")
        svc = self._make_storage(tmp_dir, enabled=False)

        with patch("app.api.voice.storage_service", svc):
            from app.api.voice import _stream_audio_file
            response = await _stream_audio_file(path)

        assert response.media_type == "audio/webm"

    @pytest.mark.asyncio
    async def test_mp3_extension_returns_correct_mime(self, tmp_dir):
        """audio/mpeg MIME for .mp3 files."""
        path = os.path.join(tmp_dir, "public", "voice.mp3")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        Path(path).write_bytes(b"mp3 bytes")
        svc = self._make_storage(tmp_dir, enabled=False)

        with patch("app.api.voice.storage_service", svc):
            from app.api.voice import _stream_audio_file
            response = await _stream_audio_file(path)

        assert response.media_type == "audio/mpeg"

    @pytest.mark.asyncio
    async def test_encrypted_ogg_extension_stripped_correctly(self, tmp_dir):
        """.ogg.encrypted → real ext is .ogg → audio/ogg not audio/encrypted."""
        conf_dir = os.path.join(tmp_dir, "confidential")
        os.makedirs(conf_dir, exist_ok=True)
        enc_path = os.path.join(conf_dir, "20260413_abc.ogg.encrypted")
        fernet = make_fernet()
        Path(enc_path).write_bytes(fernet.encrypt(b"ogg content"))
        svc = self._make_storage(tmp_dir, enabled=True)

        with patch("app.api.voice.storage_service", svc):
            from app.api.voice import _stream_audio_file
            response = await _stream_audio_file(enc_path)

        assert response.media_type == "audio/ogg", (
            f"Got '{response.media_type}'. Extension strip logic is broken: "
            "os.path.splitext('.ogg.encrypted') returns '.encrypted', not '.ogg'."
        )


# ---------------------------------------------------------------------------
# 3. voice_tasks.py — decrypts before whisper
# ---------------------------------------------------------------------------

def _call_task(audio_file_path: str, document_id: str, *, mock_storage=None,
               mock_loop=None) -> dict:
    """Call transcribe_voice_note's logic with controlled mocks.

    Patches:
      - storage_service at the services level (local import inside the task)
      - asyncio.new_event_loop so whisper is never actually called
      - app.database.SessionLocal so no real DB is touched
    """
    loop = mock_loop or MagicMock(
        **{"run_until_complete.return_value": {"transcript": "test transcript"}}
    )
    storage = mock_storage or MagicMock(**{"get_file.return_value": FAKE_OGG_BYTES})

    db_ctx = MagicMock()
    db_ctx.__enter__ = MagicMock(return_value=MagicMock())
    db_ctx.__exit__ = MagicMock(return_value=False)

    with patch("app.services.storage_service.storage_service", storage), \
         patch("asyncio.new_event_loop", return_value=loop), \
         patch("app.database.SessionLocal", return_value=db_ctx):
        from app.tasks.voice_tasks import transcribe_voice_note
        # .run() is the bound method — Celery handles injecting `self`
        return transcribe_voice_note.run(
            audio_file_path=audio_file_path,
            document_id=document_id,
        )


class TestVoiceTaskDecryption:
    """transcribe_voice_note must decrypt encrypted files before calling whisper."""

    @pytest.fixture
    def tmp_dir(self):
        d = tempfile.mkdtemp()
        yield d
        shutil.rmtree(d)

    def test_missing_file_returns_error_dict(self):
        """Non-existent audio file → returns dict with 'error', does not raise."""
        result = _call_task(
            audio_file_path="/nonexistent/voice.ogg",
            document_id=str(uuid.uuid4()),
        )
        assert "error" in result, f"Expected error dict, got: {result}"
        assert "not found" in result["error"].lower()

    def test_encrypted_file_triggers_storage_decrypt(self, tmp_dir):
        """Encrypted .ogg.encrypted path → storage_service.get_file called with decrypt=True."""
        enc_path = os.path.join(tmp_dir, "confidential", "voice.ogg.encrypted")
        os.makedirs(os.path.dirname(enc_path))
        Path(enc_path).write_bytes(b"any bytes - will be replaced by mock")

        decrypt_kwargs: list[dict] = []

        def capture_get_file(filename, bucket, **kwargs):
            decrypt_kwargs.append(kwargs)
            return FAKE_OGG_BYTES

        mock_storage = MagicMock()
        mock_storage.get_file.side_effect = capture_get_file

        result = _call_task(
            audio_file_path=enc_path,
            document_id=str(uuid.uuid4()),
            mock_storage=mock_storage,
        )

        assert mock_storage.get_file.called, (
            "storage_service.get_file was never called. Decryption path not triggered."
        )
        assert any(kw.get("decrypt") is True for kw in decrypt_kwargs), (
            f"decrypt=True was not passed to storage_service.get_file. Calls: {decrypt_kwargs}. "
            "Whisper would have received encrypted bytes."
        )

    def test_plain_file_does_not_call_storage_service(self, tmp_dir):
        """Unencrypted .ogg → storage_service.get_file must NOT be called (no decryption needed)."""
        ogg_path = os.path.join(tmp_dir, "voice.ogg")
        Path(ogg_path).write_bytes(FAKE_OGG_BYTES)

        mock_storage = MagicMock()

        result = _call_task(
            audio_file_path=ogg_path,
            document_id=str(uuid.uuid4()),
            mock_storage=mock_storage,
        )

        mock_storage.get_file.assert_not_called()

    def test_tmp_decrypted_file_cleaned_up(self, tmp_dir):
        """Temp plaintext file written for whisper must be deleted after transcription."""
        enc_path = os.path.join(tmp_dir, "confidential", "voice.ogg.encrypted")
        os.makedirs(os.path.dirname(enc_path))
        Path(enc_path).write_bytes(b"some encrypted bytes")

        created_tmp: list[str] = []
        real_named_temp = tempfile.NamedTemporaryFile

        def tracking_named_temp(suffix="", delete=True, **kwargs):
            tmp = real_named_temp(suffix=suffix, delete=delete, **kwargs)
            created_tmp.append(tmp.name)
            return tmp

        mock_storage = MagicMock(**{"get_file.return_value": FAKE_OGG_BYTES})

        with patch("app.tasks.voice_tasks.tempfile.NamedTemporaryFile", side_effect=tracking_named_temp):
            _call_task(
                audio_file_path=enc_path,
                document_id=str(uuid.uuid4()),
                mock_storage=mock_storage,
            )

        for tmp_path in created_tmp:
            assert not os.path.exists(tmp_path), (
                f"Temp decrypted file was NOT deleted: {tmp_path}. "
                "Plaintext audio leaks to disk — security violation."
            )


# ---------------------------------------------------------------------------
# 4. is_audio equivalence — MIME types that must render the audio player
# ---------------------------------------------------------------------------

class TestIsAudioMimeTypes:
    """These MIME types must all be considered audio in the frontend isAudio() check.

    The function is: mimeType.startsWith('audio/') || mimeType === 'application/ogg'
    These tests document the contract so a future refactor doesn't break it.
    """

    MUST_BE_AUDIO = [
        "audio/ogg",
        "audio/webm",
        "audio/mpeg",
        "audio/wav",
        "audio/mp4",
        "audio/flac",
        "audio/aac",
        "application/ogg",  # Telegram OGG Opus detected by python-magic (legacy data)
    ]

    MUST_NOT_BE_AUDIO = [
        "application/pdf",
        "image/jpeg",
        "text/plain",
        "application/octet-stream",
        "video/mp4",
    ]

    @staticmethod
    def is_audio(mime_type: str) -> bool:
        """Python mirror of the frontend isAudio() function in journal/page.tsx."""
        return mime_type.startswith("audio/") or mime_type == "application/ogg"

    def test_all_audio_mimes_recognized(self):
        for mime in self.MUST_BE_AUDIO:
            assert self.is_audio(mime), (
                f"'{mime}' was not recognized as audio. "
                "Frontend will not render the <audio> element for this MIME type."
            )

    def test_non_audio_mimes_rejected(self):
        for mime in self.MUST_NOT_BE_AUDIO:
            assert not self.is_audio(mime), (
                f"'{mime}' was incorrectly recognized as audio."
            )


# ---------------------------------------------------------------------------
# 5. stream_audio endpoint — integration-level checks (all dependencies mocked)
# ---------------------------------------------------------------------------

class TestStreamAudioEndpoint:
    """stream_audio endpoint must return 200 for audio docs regardless of MIME variant."""

    def _make_doc(self, *, mime_type: str, file_path: str, bucket: str = "confidential",
                  audio_file_path: str | None = None):
        doc = MagicMock()
        doc.id = uuid.uuid4()
        doc.mime_type = mime_type
        doc.file_path = file_path
        doc.audio_file_path = audio_file_path
        doc.bucket = MagicMock()
        doc.bucket.value = bucket
        return doc

    def _make_user(self, role: str = "admin"):
        user = MagicMock()
        user.role = MagicMock()
        user.role.value = role
        return user

    @pytest.mark.asyncio
    async def test_application_ogg_mime_resolves_audio_path(self, tmp_path):
        """Document with mime_type=application/ogg must have audio_path resolved."""
        ogg_file = tmp_path / "voice.ogg"
        ogg_file.write_bytes(FAKE_OGG_BYTES)

        doc = self._make_doc(mime_type="application/ogg", file_path=str(ogg_file), bucket="public")

        mock_db = AsyncMock()
        mock_db.execute.return_value.scalar_one_or_none = MagicMock(return_value=doc)

        mock_storage = MagicMock()
        mock_storage.encryption_enabled = False

        mock_request = MagicMock()
        mock_request.headers.get.return_value = ""

        with patch("app.api.voice.storage_service", mock_storage):
            from app.api.voice import stream_audio
            response = await stream_audio(
                audio_id=str(doc.id),
                request=mock_request,
                current_user=self._make_user("admin"),
                db=mock_db,
            )

        from fastapi.responses import FileResponse
        assert isinstance(response, FileResponse), (
            "Expected FileResponse for application/ogg mime_type document. "
            "The is_audio_mime check is rejecting application/ogg."
        )

    @pytest.mark.asyncio
    async def test_confidential_encrypted_ogg_decrypted(self, tmp_path):
        """Encrypted .ogg.encrypted in confidential bucket → decrypted StreamingResponse."""
        conf_dir = tmp_path / "confidential"
        conf_dir.mkdir()
        enc_file = conf_dir / "voice.ogg.encrypted"
        enc_file.write_bytes(encrypt_bytes(FAKE_OGG_BYTES))

        doc = self._make_doc(
            mime_type="audio/ogg",
            file_path=str(enc_file),
            bucket="confidential",
        )

        mock_db = AsyncMock()
        mock_db.execute.return_value.scalar_one_or_none = MagicMock(return_value=doc)

        # Build a real storage service pointing at tmp_path
        with patch("app.services.storage_service.StorageService._ensure_directories"):
            from app.services.storage_service import StorageService
            svc = StorageService()
            svc.confidential_path = conf_dir
            svc.public_path = tmp_path / "public"
            svc._fernet = make_fernet()

        mock_request = MagicMock()
        mock_request.headers.get.return_value = ""

        with patch("app.api.voice.storage_service", svc):
            from app.api.voice import stream_audio
            response = await stream_audio(
                audio_id=str(doc.id),
                request=mock_request,
                current_user=self._make_user("admin"),
                db=mock_db,
            )

        from fastapi.responses import StreamingResponse
        assert isinstance(response, StreamingResponse), (
            "Expected StreamingResponse for encrypted .ogg.encrypted file. "
            "FileResponse would serve encrypted bytes; browsers cannot play them."
        )

        # body_iterator may be async — collect properly
        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)
        body = b"".join(chunks)
        assert body == FAKE_OGG_BYTES

    @pytest.mark.asyncio
    async def test_regular_user_forbidden_from_confidential_audio(self, tmp_path):
        """Regular users must get 403 for confidential audio docs."""
        ogg_file = tmp_path / "voice.ogg"
        ogg_file.write_bytes(FAKE_OGG_BYTES)

        doc = self._make_doc(mime_type="audio/ogg", file_path=str(ogg_file), bucket="confidential")

        mock_db = AsyncMock()
        mock_db.execute.return_value.scalar_one_or_none = MagicMock(return_value=doc)

        mock_request = MagicMock()
        mock_request.headers.get.return_value = ""

        from app.api.voice import stream_audio
        with pytest.raises(HTTPException) as exc_info:
            await stream_audio(
                audio_id=str(doc.id),
                request=mock_request,
                current_user=self._make_user("user"),
                db=mock_db,
            )

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_invalid_uuid_returns_404(self):
        """Non-UUID audio_id must return 404 not 500."""
        mock_db = AsyncMock()
        mock_request = MagicMock()
        mock_request.headers.get.return_value = ""

        from app.api.voice import stream_audio
        with pytest.raises(HTTPException) as exc_info:
            await stream_audio(
                audio_id="not-a-uuid",
                request=mock_request,
                current_user=self._make_user(),
                db=mock_db,
            )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_file_not_on_disk_returns_404(self, tmp_path):
        """If file_path no longer exists on disk → 404, not 500."""
        doc = self._make_doc(
            mime_type="audio/ogg",
            file_path=str(tmp_path / "missing.ogg"),
            bucket="public",
        )

        mock_db = AsyncMock()
        mock_db.execute.return_value.scalar_one_or_none = MagicMock(return_value=doc)
        mock_storage = MagicMock()
        mock_storage.encryption_enabled = False

        mock_request = MagicMock()
        mock_request.headers.get.return_value = ""

        with patch("app.api.voice.storage_service", mock_storage):
            from app.api.voice import stream_audio
            with pytest.raises(HTTPException) as exc_info:
                await stream_audio(
                    audio_id=str(doc.id),
                    request=mock_request,
                    current_user=self._make_user("admin"),
                    db=mock_db,
                )

        assert exc_info.value.status_code == 404
