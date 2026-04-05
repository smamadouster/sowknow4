import logging
import os

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

    # Update document with transcript using the shared sync SessionLocal
    from sqlalchemy import text

    from app.database import SessionLocal

    with SessionLocal() as db:
        db.execute(
            text("""
                UPDATE sowknow.documents
                SET metadata = jsonb_set(COALESCE(metadata, '{}'), '{extracted_text}', to_jsonb(:transcript::text)),
                    detected_language = :lang
                WHERE id = :doc_id::uuid
            """),
            {"transcript": result["transcript"], "lang": "auto", "doc_id": document_id},
        )
        db.commit()

    logger.info(f"Voice note transcribed: doc={document_id}, chars={len(result['transcript'])}")
    return {"transcript": result["transcript"], "document_id": document_id}
