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
        document.pipeline_last_attempt = datetime.utcnow()
        db.commit()

        logger.info(f"Processing document {document_id}: {document.filename}")
        log_task_memory("process_document", "start")

        # Step 1: OCR / Text Extraction
        if task_type in ["ocr", "full_pipeline"]:
            document.pipeline_stage = "ocr_pending"
            db.commit()
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
                # Sanitize NUL bytes — OCR/text extraction can produce \x00
                # which PostgreSQL rejects in text columns
                extracted_text = extracted_text.replace("\x00", "")
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

            document.pipeline_stage = "ocr_complete"
            db.commit()
            logger.info(f"OCR/Text extraction completed for {document_id}")
            log_task_memory("process_document", "after_ocr")

        # Step 2: Chunking
        chunks = []
        if task_type in ["chunking", "full_pipeline"]:
            document.pipeline_stage = "chunking"
            db.commit()
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
                # Sanitize NUL bytes from text files that may have been
                # written before the extraction-stage sanitization was added
                extracted_text = extracted_text.replace("\x00", "")

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
                    document.pipeline_stage = "chunked"
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

                document.pipeline_stage = "embedding"
                db.commit()
                recompute_embeddings_for_document.delay(str(document.id))
                logger.info(f"Embedding generation dispatched for document {document_id}")
            except Exception as embed_err:
                logger.warning(f"Failed to queue embedding for {document_id}: {embed_err}")

        log_task_memory("process_document", "after_chunking")

        # Step 4: Update document status
        if document.chunk_count and document.chunk_count > 0:
            document.status = DocumentStatus.INDEXED
            document.pipeline_stage = "indexed"
            document.pipeline_error = None
            document.pipeline_retry_count = 0
            processing_task.status = TaskStatus.COMPLETED
            processing_task.progress_percentage = 100
        else:
            document.status = DocumentStatus.ERROR
            document.pipeline_stage = "failed"
            document.pipeline_error = "No chunks generated — text extraction or chunking failed"
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

        # Step 6: Queue entity extraction for knowledge graph (async, non-blocking)
        if document.status == DocumentStatus.INDEXED:
            try:
                extract_entities_for_document.delay(str(document.id))
                logger.info(f"Entity extraction queued for document {document_id}")
            except Exception as entity_err:
                logger.warning(f"Failed to queue entity extraction for {document_id}: {entity_err}")

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

            # Track pipeline failure at current stage
            document.pipeline_error = str(e)[:500]
            document.pipeline_retry_count = (document.pipeline_retry_count or 0) + 1

            if current_retry >= 3:
                document.status = DocumentStatus.ERROR
                document.pipeline_stage = "failed"
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
    from app.services.embed_client import embedding_service

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
                doc.pipeline_error = str(exc)[:500]
                doc.document_metadata = {
                    **(doc.document_metadata or {}),
                    "processing_error": str(exc)[:500],
                }
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


@shared_task(
    bind=True,
    name="app.tasks.document_tasks.extract_entities_for_document",
    autoretry_for=(Exception,),
    max_retries=2,
    retry_backoff=True,
    retry_backoff_max=120,
    soft_time_limit=600,
    time_limit=660,
    rate_limit="1/m",
)
def extract_entities_for_document(self, document_id: str) -> dict:
    """
    Extract entities and relationships from a document for the knowledge graph.

    Runs after embedding generation. Uses entity_extraction_service to analyze
    document chunks and populate the knowledge graph with people, organizations,
    locations, concepts, and their relationships.

    Args:
        document_id: UUID of the document to extract entities from.

    Returns:
        dict with extraction results.
    """
    import asyncio

    async def _inner():
        from app.database import AsyncSessionLocal
        from app.models.document import Document, DocumentChunk
        from app.services.entity_extraction_service import entity_extraction_service

        async with AsyncSessionLocal() as db:
            from sqlalchemy import select

            result = await db.execute(
                select(Document).where(Document.id == uuid.UUID(document_id))
            )
            document = result.scalar_one_or_none()
            if not document:
                return {"status": "error", "message": f"Document {document_id} not found"}

            chunk_result = await db.execute(
                select(DocumentChunk)
                .where(DocumentChunk.document_id == document.id)
                .order_by(DocumentChunk.chunk_index)
            )
            chunks = chunk_result.scalars().all()
            if not chunks:
                return {"status": "skipped", "message": "No chunks to extract entities from"}

            extraction_result = await entity_extraction_service.extract_entities_from_document(
                document=document, chunks=chunks, db=db
            )

            entity_count = extraction_result.get("entities_count", 0) if isinstance(extraction_result, dict) else 0
            relationship_count = extraction_result.get("relationships_count", 0) if isinstance(extraction_result, dict) else 0

            logger.info(
                f"Entity extraction completed for document {document_id}: "
                f"{entity_count} entities, {relationship_count} relationships"
            )

            # Invalidate the context block cache so it picks up new entity data
            try:
                from app.services.context_block_service import invalidate_context_block

                invalidate_context_block()
            except Exception:
                pass  # context_block_service may not exist yet

            return {
                "status": "success",
                "document_id": document_id,
                "entities_count": entity_count,
                "relationships_count": relationship_count,
            }

    try:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_inner())
        finally:
            loop.close()
    except Exception as e:
        logger.error(f"Entity extraction error for {document_id}: {e}")
        raise


@shared_task(name="app.tasks.document_tasks.batch_extract_entities")
def batch_extract_entities(batch_size: int = 20, batch_interval: int = 60) -> dict:
    """
    Queue entity extraction for all indexed documents that don't have entities yet.
    Staggers work to avoid overwhelming the worker.

    Args:
        batch_size: Documents per batch (default 20)
        batch_interval: Seconds between batches (default 60)
    """
    from sqlalchemy import text as sa_text

    from app.database import SessionLocal

    db = SessionLocal()
    try:
        # Find indexed documents without entity mentions
        result = db.execute(
            sa_text(
                "SELECT d.id FROM sowknow.documents d "
                "WHERE d.status = 'indexed' "
                "AND d.id NOT IN (SELECT DISTINCT document_id FROM sowknow.entity_mentions) "
                "ORDER BY d.created_at DESC"
            )
        )
        doc_ids = [str(row[0]) for row in result.all()]

        queued = 0
        for batch_index, offset in enumerate(range(0, len(doc_ids), batch_size)):
            batch = doc_ids[offset : offset + batch_size]
            countdown = batch_index * batch_interval
            for doc_id in batch:
                extract_entities_for_document.apply_async(
                    args=[doc_id], countdown=countdown
                )
                queued += 1

        logger.info(
            "batch_extract_entities: queued %d documents in %d batches, %ds apart",
            queued,
            (queued + batch_size - 1) // batch_size if queued else 0,
            batch_interval,
        )
        return {"status": "success", "queued": queued, "total_docs": len(doc_ids)}

    except Exception as e:
        logger.error(f"batch_extract_entities error: {e}")
        return {"status": "error", "message": str(e)}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Smart Collection async build task
# ---------------------------------------------------------------------------


def _run_build_pipeline(collection_id: str, user_id: str) -> None:
    """
    Sync wrapper that runs the async collection build pipeline.
    Called by the Celery task. Uses a fresh async DB session.
    """
    import asyncio
    from uuid import UUID

    from app.services.collection_service import collection_service

    async def _inner():
        from app.database import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            try:
                await collection_service.build_collection_pipeline(
                    collection_id=UUID(collection_id),
                    user_id=UUID(user_id),
                    db=session,
                )
            except Exception:
                # Pipeline already sets status=FAILED and commits.
                # If that commit also failed (broken session), rollback and retry.
                try:
                    await session.rollback()
                except Exception:
                    pass
                raise

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_inner())
    finally:
        loop.close()


@shared_task(
    bind=True,
    name="build_smart_collection",
    max_retries=1,
    soft_time_limit=240,
    time_limit=300,
)
def build_smart_collection(self, collection_id: str, user_id: str) -> dict:
    """
    Celery task: build a Smart Collection asynchronously.
    Runs intent parsing -> hybrid search -> AI summary -> DB update.
    On failure, the collection is set to FAILED status by the pipeline.
    """
    logger.info(f"Starting build_smart_collection for collection={collection_id}")
    try:
        _run_build_pipeline(collection_id, user_id)
        return {"status": "ready", "collection_id": collection_id}
    except Exception as exc:
        logger.error(f"build_smart_collection failed: {exc}", exc_info=True)
        return {"status": "failed", "collection_id": collection_id, "error": str(exc)[:500]}


@shared_task(name="app.tasks.document_tasks.reprocess_pending_documents")
def reprocess_pending_documents() -> dict:
    """Dispatch processing for all pending documents in staggered batches."""
    from app.database import SessionLocal
    from app.models.document import Document, DocumentStatus

    BATCH_SIZE = 40
    BATCH_INTERVAL_SECONDS = 30

    db = SessionLocal()
    try:
        docs = (
            db.query(Document)
            .filter(Document.status == DocumentStatus.PENDING)
            .order_by(Document.created_at)
            .all()
        )

        queued = 0
        for batch_index, offset in enumerate(range(0, len(docs), BATCH_SIZE)):
            batch = docs[offset : offset + BATCH_SIZE]
            countdown = batch_index * BATCH_INTERVAL_SECONDS
            for doc in batch:
                process_document.apply_async(
                    args=[str(doc.id)],
                    countdown=countdown,
                )
                queued += 1

        logger.info(
            "Reprocess: queued %d pending documents in %d batches of %d, %ds apart",
            queued,
            (queued + BATCH_SIZE - 1) // BATCH_SIZE if queued else 0,
            BATCH_SIZE,
            BATCH_INTERVAL_SECONDS,
        )
        return {"status": "success", "queued": queued}

    finally:
        db.close()
