"""
Celery tasks for document processing

Status values used in this module:
  document.status = "failed" / "indexed" / "error" / "pending" (via DocumentStatus enum)
  processing_task.status = "failed" / "indexed" / "completed" (via TaskStatus enum)
"""

import logging
import uuid
from datetime import datetime

from celery import shared_task

from app.tasks.base import base_task_failure_handler, log_task_memory

logger = logging.getLogger(__name__)

# langdetect is an optional dependency — import gracefully
try:
    from langdetect import LangDetectException
    from langdetect import detect as _ld_detect  # type: ignore[import]
except ImportError:
    _ld_detect = None  # type: ignore[assignment]

    class LangDetectException(Exception):  # type: ignore[no-redef]
        pass


# PostgreSQL text-search configuration names supported by this system
_LANG_MAP = {
    "fr": "french",
    "en": "english",
    "de": "german",
    "es": "spanish",
    "it": "italian",
    "pt": "portuguese",
    "nl": "dutch",
    "sv": "swedish",
    "no": "norwegian",
    "da": "danish",
    "fi": "finnish",
    "ru": "russian",
    "tr": "turkish",
    "ar": "arabic",
}


def detect_text_language(text: str, fallback: str = "french") -> str:
    """
    Detect the primary language of *text* and return the corresponding
    PostgreSQL text-search configuration name (e.g. 'french', 'english').

    Uses the first 1 000 characters as a sample. Falls back to *fallback*
    (default: 'french') when the text is too short, langdetect is not
    installed, or detection fails for any reason.
    """
    try:
        from langdetect import LangDetectException, detect  # type: ignore[import]

        sample = text[:1000].strip()
        if len(sample) < 50:
            return fallback

        try:
            detected = detect(sample)
            return _LANG_MAP.get(detected, fallback)
        except LangDetectException:
            return fallback

    except Exception:  # ImportError or any other runtime error
        return fallback


@shared_task(bind=True, name="app.tasks.document_tasks.process_document")
def process_document(self, document_id: str, task_type: str = "full_pipeline") -> dict:
    """
    Process a document through the full pipeline:
    1. OCR / Text extraction
    2. Chunking
    3. Embedding generation
    4. Indexing

    Args:
        document_id: UUID of the document to process
        task_type: Type of processing ("ocr", "chunking", "embedding", "full_pipeline")

    Returns:
        dict with processing results
    """
    from app.database import SessionLocal
    from app.models.document import Document, DocumentStatus
    from app.models.processing import ProcessingQueue, TaskStatus, TaskType

    db = SessionLocal()
    processing_task = None  # Initialize to prevent UnboundLocalError
    detected_language = "french"  # default; updated by chunking step if text is present
    try:
        # Get document
        document = db.query(Document).filter(Document.id == uuid.UUID(document_id)).first()
        if not document:
            logger.error(f"Document {document_id} not found")
            return {"status": "error", "message": "Document not found"}

        # Check if document is already being processed (prevent duplicate processing)
        if document.status == DocumentStatus.PROCESSING and document.document_metadata:
            existing_task_id = document.document_metadata.get("celery_task_id")
            if existing_task_id and existing_task_id != self.request.id:
                logger.warning(f"Document {document_id} is already being processed by task {existing_task_id}")
                # Don't fail, just return - the other task is handling it
                return {
                    "status": "skipped",
                    "message": "Document already being processed",
                }

        # Create or update processing queue entry
        processing_task = (
            db.query(ProcessingQueue)
            .filter(
                ProcessingQueue.document_id == document.id,
                ProcessingQueue.task_type == TaskType.OCR_PROCESSING,
            )
            .first()
        )

        if not processing_task:
            processing_task = ProcessingQueue(
                document_id=document.id,
                task_type=TaskType.OCR_PROCESSING,
                status=TaskStatus.PENDING,
            )
            db.add(processing_task)
            db.commit()

        # Update task status
        processing_task.status = TaskStatus.IN_PROGRESS
        processing_task.celery_task_id = self.request.id
        # Track start time for timeout detection
        processing_task.started_at = datetime.utcnow()
        db.commit()

        # Add processing metadata to document
        document.document_metadata = document.document_metadata or {}
        document.document_metadata["processing_started_at"] = datetime.utcnow().isoformat()
        document.document_metadata["celery_task_id"] = self.request.id
        db.commit()

        logger.info(f"Processing document {document_id}: {document.filename}")
        log_task_memory("process_document", "start")

        # Step 1: OCR / Text Extraction
        if task_type in ["ocr", "full_pipeline"]:
            self.update_state(state="PROGRESS", meta={"step": "ocr", "progress": 10})

            import asyncio

            from app.services.ocr_service import ocr_service
            from app.services.text_extractor import text_extractor

            # Extract text based on file type (run async code in event loop)
            extraction_result = asyncio.run(
                text_extractor.extract_text(file_path=document.file_path, filename=document.original_filename)
            )

            extracted_text = extraction_result.get("text", "")
            document.page_count = extraction_result.get("pages", 0)

            if not extraction_result.get("success", True) or extraction_result.get("error"):
                err_msg = extraction_result.get("error", "Unknown extraction error")
                logger.warning(f"Text extraction issue for {document_id}: {err_msg}")
                metadata = document.document_metadata or {}
                metadata["extraction_warning"] = err_msg
                document.document_metadata = metadata
                db.commit()

            should_ocr, ocr_reason = ocr_service.should_use_ocr(
                mime_type=document.mime_type,
                extracted_text=extracted_text,
            )

            if should_ocr:
                logger.info(f"OCR triggered for {document_id}: {ocr_reason}")
                self.update_state(state="PROGRESS", meta={"step": "ocr_images", "progress": 20})

                if document.mime_type.startswith("image/"):
                    ocr_result = asyncio.run(ocr_service._extract_full(document.file_path))
                    extracted_text = ocr_result.get("text", "")
                elif document.mime_type == "application/pdf":
                    import os as _os
                    import tempfile

                    images = asyncio.run(text_extractor.extract_images_from_pdf(document.file_path))
                    ocr_texts = []
                    for i, page_bytes in enumerate(images):
                        tmp_path = None
                        try:
                            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                                tmp.write(page_bytes)
                                tmp_path = tmp.name
                            ocr_result = asyncio.run(ocr_service._extract_full(tmp_path))
                        finally:
                            if tmp_path and _os.path.exists(tmp_path):
                                _os.unlink(tmp_path)
                        if ocr_result.get("text"):
                            ocr_texts.append(f"[Image Page {i + 1}] {ocr_result['text']}")
                    extracted_text = "\n\n".join(ocr_texts)
            else:
                logger.debug(f"OCR skipped for {document_id}: {ocr_reason}")

            if extracted_text:
                document.ocr_processed = True
                # Save extracted text to a file for later chunking
                text_file_path = f"{document.file_path}.txt"
                with open(text_file_path, "w", encoding="utf-8") as f:
                    f.write(extracted_text)
            else:
                logger.warning(
                    f"No text extracted for {document_id} ({document.mime_type}). "
                    "Document will proceed but may produce 0 chunks."
                )
                metadata = document.document_metadata or {}
                metadata["extraction_empty"] = True
                document.document_metadata = metadata
                db.commit()

            logger.info(f"OCR/Text extraction completed for {document_id}")
            log_task_memory("process_document", "after_ocr")

        # Step 2: Chunking
        chunks = []
        if task_type in ["chunking", "full_pipeline"]:
            self.update_state(state="PROGRESS", meta={"step": "chunking", "progress": 40})

            from app.services.chunking_service import chunking_service

            # Read extracted text from file
            text_file_path = f"{document.file_path}.txt"
            extracted_text = ""
            try:
                with open(text_file_path, encoding="utf-8") as f:
                    extracted_text = f.read()
            except FileNotFoundError:
                logger.warning(f"No extracted text file found for document {document_id}")

            if extracted_text:
                # Detect language for full-text search stemming
                detected_language = detect_text_language(extracted_text)
                logger.info(f"Detected language for document {document_id}: {detected_language}")

                # Chunk the text
                chunks = chunking_service.chunk_document(
                    text=extracted_text,
                    document_id=str(document.id),
                    metadata={
                        "filename": document.filename,
                        "bucket": document.bucket.value,
                        "mime_type": document.mime_type,
                    },
                )
                logger.info(f"Created {len(chunks)} chunks for document {document_id}")

                # Store chunks in database with proper transaction handling
                from app.models.document import DocumentChunk

                try:
                    for chunk_data in chunks:
                        chunk = DocumentChunk(
                            document_id=document.id,
                            chunk_index=chunk_data["index"],
                            chunk_text=chunk_data["text"],
                            token_count=chunk_data["token_count"],
                            search_language=detected_language,
                        )
                        db.add(chunk)

                    document.chunk_count = len(chunks)
                    processing_task.progress_percentage = 50
                    db.commit()
                    logger.info(f"Successfully stored {len(chunks)} chunks for document {document_id}")
                except Exception as chunk_error:
                    db.rollback()
                    logger.error(f"Failed to store chunks for document {document_id}: {chunk_error}")
                    metadata = document.document_metadata or {}
                    metadata["chunk_storage_error"] = str(chunk_error)
                    document.document_metadata = metadata
                    db.commit()
                    raise chunk_error
            else:
                logger.warning(f"No text to chunk for document {document_id}")

        # Step 3: Embedding Generation — dispatched as separate task to avoid OOM
        # The embedding model (~1.3GB) + encoding large docs exceeds memory in fork workers.
        # Dispatch to recompute_embeddings_for_document which handles batching safely.
        if task_type in ["embedding", "full_pipeline"] and chunks:
            try:
                from app.tasks.embedding_tasks import recompute_embeddings_for_document

                recompute_embeddings_for_document.delay(str(document.id))
                logger.info(f"Embedding generation dispatched for document {document_id}")
            except Exception as embed_err:
                logger.warning(f"Failed to queue embedding for {document_id}: {embed_err}")

        log_task_memory("process_document", "after_chunking")

        # Step 4: Update document status
        if document.chunk_count and document.chunk_count > 0:
            document.status = DocumentStatus.INDEXED
            processing_task.status = TaskStatus.COMPLETED
            processing_task.progress_percentage = 100
        else:
            document.status = DocumentStatus.ERROR
            processing_task.status = TaskStatus.FAILED
            processing_task.error_message = "No chunks generated — text extraction or chunking failed"
            logger.error(f"Document {document_id} produced 0 chunks, marking as ERROR")
        db.commit()

        # Step 5: Queue article generation (async, non-blocking)
        if document.status == DocumentStatus.INDEXED:
            try:
                from app.tasks.article_tasks import generate_articles_for_document as gen_articles

                gen_articles.delay(str(document.id))
                logger.info(f"Article generation queued for document {document_id}")
            except Exception as article_err:
                logger.warning(f"Failed to queue article generation for {document_id}: {article_err}")

        log_task_memory("process_document", "end")
        logger.info(f"Document {document_id} processed successfully")

        return {
            "status": "success",
            "document_id": str(document.id),
            "filename": document.filename,
            "language": detected_language,
            "message": "Document processed successfully",
        }

    except Exception as e:
        logger.error(f"Error processing document {document_id}: {str(e)}")

        # Safely handle the error - ensure processing_task is defined
        if "processing_task" in locals() and processing_task:
            processing_task.status = TaskStatus.FAILED
            processing_task.error_message = str(e)[:500]  # Limit error message length
            # Increment retry count (default to 0 if not set)
            processing_task.retry_count = (processing_task.retry_count or 0) + 1
            current_retry = processing_task.retry_count
            db.commit()
        else:
            current_retry = 1  # Default retry count if processing_task not available

        # CRITICAL: Update document status too (not just ProcessingQueue)
        if "document" in locals() and document:
            # Update document metadata with error info
            metadata = document.document_metadata or {}
            metadata["processing_error"] = str(e)[:500]
            metadata["retry_count"] = current_retry
            metadata["last_error_at"] = datetime.utcnow().isoformat()
            document.document_metadata = metadata

            if current_retry >= 3:
                document.status = DocumentStatus.ERROR
                logger.error(f"Document {document_id} failed permanently after {current_retry} retries: {str(e)}")
                db.commit()
                # Store in Dead Letter Queue for admin inspection
                try:
                    import traceback as _tb

                    from app.services.dlq_service import DeadLetterQueueService

                    DeadLetterQueueService.store_failed_task(
                        task_name="app.tasks.document_tasks.process_document",
                        task_id=self.request.id or "unknown",
                        args=(document_id,),
                        kwargs={"task_type": task_type},
                        exception=e,
                        traceback_str=_tb.format_exc(),
                        retry_count=current_retry,
                        extra_metadata={"document_id": document_id},
                    )
                except Exception as dlq_err:
                    logger.error(f"DLQ storage failed for {document_id}: {dlq_err}")
            else:
                document.status = DocumentStatus.PENDING
                logger.warning(f"Document {document_id} will be retried ({current_retry}/2)")
                db.commit()

        # Retry with fixed 30s delay (max 2 retries = 3 total attempts)
        raise self.retry(exc=e, countdown=30, max_retries=2)

    finally:
        db.close()


@shared_task(name="app.tasks.document_tasks.process_batch_documents")
def process_batch_documents(document_ids: list) -> dict:
    """
    Process multiple documents in batch

    Args:
        document_ids: List of document UUIDs to process

    Returns:
        dict with batch processing results
    """
    results = []
    for doc_id in document_ids:
        try:
            result = process_document.delay(str(doc_id))
            results.append({"document_id": doc_id, "task_id": result.id, "status": "queued"})
        except Exception as e:
            logger.error(f"Failed to queue document {doc_id}: {str(e)}")
            results.append({"document_id": doc_id, "status": "error", "message": str(e)})

    return {
        "total": len(document_ids),
        "queued": sum(1 for r in results if r["status"] == "queued"),
        "errors": sum(1 for r in results if r["status"] == "error"),
        "results": results,
    }


@shared_task(
    bind=True,
    name="app.tasks.document_tasks.generate_embeddings",
    autoretry_for=(Exception,),
    max_retries=3,
    retry_kwargs={"max_retries": 3},
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
)
def generate_embeddings(self, chunk_ids: list) -> dict:
    """
    Generate and store embeddings for a list of DocumentChunk IDs.

    Args:
        chunk_ids: List of chunk UUIDs (strings) to generate embeddings for.
                   Maximum 100 chunks per call.

    Returns:
        dict with embedding generation results
    """
    if len(chunk_ids) > 100:
        return {
            "status": "error",
            "message": "Maximum 100 chunk_ids per call",
            "total": len(chunk_ids),
        }

    from app.database import SessionLocal
    from app.models.document import DocumentChunk
    from app.services.embedding_service import embedding_service

    db = SessionLocal()
    try:
        chunks = (
            db.query(DocumentChunk)
            .filter(DocumentChunk.id.in_([uuid.UUID(c) if isinstance(c, str) else c for c in chunk_ids]))
            .all()
        )
        logger.info(f"Generating embeddings for {len(chunks)} chunks")

        if not chunks:
            return {"status": "success", "total": 0, "successful": 0, "failed": 0}

        chunk_texts = [chunk.chunk_text for chunk in chunks]

        embeddings = embedding_service.encode(
            texts=chunk_texts,
            batch_size=32,
            show_progress=False,
        )

        success_count = 0
        failed_count = 0
        errors = []

        for i, chunk in enumerate(chunks):
            try:
                if i < len(embeddings):
                    chunk.embedding_vector = embeddings[i]
                    success_count += 1
            except Exception as chunk_err:
                failed_count += 1
                errors.append({"chunk_id": str(chunk.id), "error": str(chunk_err)})

        db.commit()
        logger.info(f"Embeddings generated: {success_count} success, {failed_count} failed")

        return {
            "status": "completed",
            "total": len(chunks),
            "successful": success_count,
            "failed": failed_count,
            "errors": errors,
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Error generating embeddings: {str(e)}")
        # If all retries exhausted, store in DLQ

        if self.request.retries >= self.max_retries:
            try:
                import traceback as _tb

                from app.services.dlq_service import DeadLetterQueueService

                DeadLetterQueueService.store_failed_task(
                    task_name="app.tasks.document_tasks.generate_embeddings",
                    task_id=self.request.id or "unknown",
                    args=(chunk_ids,),
                    kwargs={},
                    exception=e,
                    traceback_str=_tb.format_exc(),
                    retry_count=self.request.retries,
                )
            except Exception as dlq_err:
                logger.error(f"DLQ storage failed for generate_embeddings: {dlq_err}")
        raise

    finally:
        db.close()


@shared_task(name="app.tasks.document_tasks.cleanup_old_tasks")
def cleanup_old_tasks(days: int = 7) -> dict:
    """
    Clean up old completed tasks from the processing queue

    Args:
        days: Number of days after which to remove completed tasks

    Returns:
        dict with cleanup results
    """
    from datetime import datetime, timedelta

    from app.database import SessionLocal
    from app.models.processing import ProcessingQueue, TaskStatus

    db = SessionLocal()
    try:
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        old_tasks = (
            db.query(ProcessingQueue)
            .filter(
                ProcessingQueue.status == TaskStatus.COMPLETED,
                ProcessingQueue.completed_at < cutoff_date,
            )
            .all()
        )

        count = len(old_tasks)
        for task in old_tasks:
            db.delete(task)

        db.commit()
        logger.info(f"Cleaned up {count} old tasks")

        return {
            "status": "success",
            "cleaned": count,
            "cutoff_date": cutoff_date.isoformat(),
        }

    except Exception as e:
        logger.error(f"Error cleaning up old tasks: {str(e)}")
        db.rollback()
        raise

    finally:
        db.close()


@shared_task(name="app.tasks.document_tasks.recover_stuck_documents")
def recover_stuck_documents(stuck_threshold_minutes: int = 60) -> dict:
    """
    Periodic beat task: detect and requeue stuck documents.

    A document is considered stuck if it has been in PROCESSING status for
    longer than `stuck_threshold_minutes` without completing.  This task is
    scheduled by Celery Beat to run every 30 minutes as a safety net for
    documents whose worker process was killed (OOM, container restart, etc.).

    Recovery strategy:
      - status='failed' (processing_task) → mark as "failed" for auditing
      - status='indexed' is set by the main pipeline on success
      - Documents reset to PENDING are requeued automatically by process_document

    Args:
        stuck_threshold_minutes: Minutes before a PROCESSING doc is considered stuck.

    Returns:
        dict with recovery results (stuck_found, requeued, errors).
    """
    from datetime import datetime, timedelta

    from app.database import SessionLocal
    from app.models.document import Document, DocumentStatus
    from app.models.processing import ProcessingQueue, TaskStatus

    db = SessionLocal()
    try:
        cutoff = datetime.utcnow() - timedelta(minutes=stuck_threshold_minutes)

        # Find documents stuck in PROCESSING with an overdue started_at
        stuck_tasks = (
            db.query(ProcessingQueue)
            .filter(
                ProcessingQueue.status == TaskStatus.IN_PROGRESS,
                ProcessingQueue.started_at < cutoff,
            )
            .all()
        )

        requeued = 0
        errors = 0

        for task in stuck_tasks:
            try:
                doc = db.query(Document).filter(Document.id == task.document_id).first()
                if not doc:
                    continue

                logger.warning(f"Stuck document detected: doc_id={doc.id}, started_at={task.started_at}, requeuing…")

                # Reset processing queue entry so it can be retried
                task.status = TaskStatus.FAILED
                task.error_message = f"Stuck processing recovered at {datetime.utcnow().isoformat()}"
                db.commit()

                # Reset document to PENDING so it gets requeued
                doc.status = DocumentStatus.PENDING
                db.commit()

                # Re-dispatch the processing task
                process_document.delay(str(doc.id))
                requeued += 1

            except Exception as inner_e:
                logger.error(f"Error recovering stuck document {task.document_id}: {inner_e}")
                errors += 1

        logger.info(f"Stuck-document recovery complete: found={len(stuck_tasks)}, requeued={requeued}, errors={errors}")

        return {
            "status": "success",
            "stuck_found": len(stuck_tasks),
            "requeued": requeued,
            "errors": errors,
        }

    except Exception as e:
        logger.error(f"Error in recover_stuck_documents: {e}")
        db.rollback()
        raise

    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────────────────
# on_failure callbacks — called by Celery after all retries are exhausted
# ─────────────────────────────────────────────────────────────────────────────


def on_process_document_failure(self, exc, task_id, args, kwargs, einfo) -> None:
    """on_failure callback for the process_document task."""
    logger.error(f"on_process_document_failure: task_id={task_id} exc={exc!r}")
    doc_id = args[0] if args else None
    # Update document status and attach failure_reason metadata
    try:
        from app.database import SessionLocal
        from app.models.document import Document, DocumentStatus

        db = SessionLocal()
        try:
            doc = db.query(Document).filter(Document.id == doc_id).first()
            if doc:
                doc.status = DocumentStatus.ERROR
                doc.metadata = {**(doc.metadata or {}), "failure_reason": str(exc)}
                db.commit()
        finally:
            db.close()
    except Exception as meta_err:
        logger.warning(f"Could not update doc metadata on failure: {meta_err}")
    # Increment prometheus metrics — task_failures counter
    try:
        from app.services.prometheus_metrics import metrics

        metrics.task_failures.labels(task_name="process_document").inc()
    except Exception:
        pass
    base_task_failure_handler(
        task_self=self,
        exception=exc,
        task_id=task_id,
        args=args,
        kwargs=kwargs,
        traceback=einfo,
        is_critical=True,
        extra_metadata={"document_id": doc_id, "failure_reason": str(exc)},
    )


def on_generate_embeddings_failure(self, exc, task_id, args, kwargs, einfo) -> None:
    """on_failure callback for the generate_embeddings task."""
    logger.error(f"on_generate_embeddings_failure: task_id={task_id} exc={exc!r}")
    base_task_failure_handler(
        task_self=self,
        exception=exc,
        task_id=task_id,
        args=args,
        kwargs=kwargs,
        traceback=einfo,
        is_critical=False,
    )
