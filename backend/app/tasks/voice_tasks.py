import logging
import os
import tempfile

from app.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.voice_tasks.transcribe_voice_note", bind=True, max_retries=1)
def transcribe_voice_note(self, audio_file_path: str, document_id: str) -> dict:
    """Transcribe an audio file using whisper.cpp synchronously (Celery task).

    Updates the document's extracted_text and detected_language after transcription.
    Confidential files are stored Fernet-encrypted (.ogg.encrypted); we decrypt
    to a temp file before passing to whisper.cpp and clean up immediately after.
    """
    import asyncio

    from app.services.whisper_service import whisper_service

    logger.info(f"Transcribing voice note: doc={document_id}, file={audio_file_path}")

    if not os.path.exists(audio_file_path):
        logger.error(f"Audio file not found: {audio_file_path}")
        return {"error": "Audio file not found", "document_id": document_id}

    # Decrypt Fernet-encrypted files to a temp path before handing to whisper.
    # Whisper needs a real unencrypted audio file; encrypted bytes are not valid audio.
    whisper_path = audio_file_path
    tmp_decrypted = None
    if audio_file_path.endswith(".encrypted"):
        try:
            from app.services.storage_service import storage_service
            bucket = "confidential" if "/confidential/" in audio_file_path else "public"
            filename = os.path.basename(audio_file_path)
            decrypted = storage_service.get_file(filename, bucket, decrypt=True)
            if not decrypted:
                logger.error(f"Decryption returned empty bytes for: {audio_file_path}")
                return {"error": "Failed to decrypt audio file", "document_id": document_id}
            # Real extension is everything before .encrypted (e.g. .ogg from .ogg.encrypted)
            base_name = audio_file_path[: -len(".encrypted")]
            real_ext = os.path.splitext(base_name)[1] or ".ogg"
            with tempfile.NamedTemporaryFile(suffix=real_ext, delete=False) as tmp:
                tmp.write(decrypted)
                tmp_decrypted = tmp.name
            whisper_path = tmp_decrypted
            logger.info(f"Decrypted audio to tmp: {tmp_decrypted} ({len(decrypted)} bytes)")
        except Exception as e:
            logger.error(f"Failed to decrypt audio for transcription: {e}")
            return {"error": str(e), "document_id": document_id}

    try:
        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(whisper_service.transcribe(whisper_path))
        loop.close()
    except RuntimeError as e:
        logger.error(f"Whisper transcription failed: {e}")
        return {"error": str(e), "document_id": document_id}
    finally:
        if tmp_decrypted and os.path.exists(tmp_decrypted):
            os.unlink(tmp_decrypted)
            logger.debug(f"Cleaned up tmp decrypted file: {tmp_decrypted}")

    # Update document with transcript using the shared sync SessionLocal
    from sqlalchemy import text

    from app.database import SessionLocal

    with SessionLocal() as db:
        db.execute(
            text("""
                UPDATE sowknow.documents
                SET metadata = jsonb_set(COALESCE(metadata, '{}'), '{extracted_text}', to_jsonb(CAST(:transcript AS text))),
                    detected_language = :lang
                WHERE id = CAST(:doc_id AS uuid)
            """),
            {"transcript": result["transcript"], "lang": "auto", "doc_id": document_id},
        )
        db.commit()

    logger.info(f"Voice note transcribed: doc={document_id}, chars={len(result['transcript'])}")
    return {"transcript": result["transcript"], "document_id": document_id}
