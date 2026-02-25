"""
Celery tasks for document processing

Status values used in this module:
  document.status = "failed" / "indexed" / "error" / "pending" (via DocumentStatus enum)
  processing_task.status = "failed" / "indexed" / "completed" (via TaskStatus enum)
"""

from celery import shared_task
from app.celery_app import celery_app
import logging
from typing import Optional
import uuid
from datetime import datetime

logger = logging.getLogger(__name__)


@shared_task(bind=True, name="app.tasks.document_tasks.process_document")
def process_document(self, document_id: str, task_type: str = "full_pipeline"):
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
    from app.models.processing import ProcessingQueue, TaskType, TaskStatus

    db = SessionLocal()
    processing_task = None  # Initialize to prevent UnboundLocalError
    try:
        # Get document
        document = (
            db.query(Document).filter(Document.id == uuid.UUID(document_id)).first()
        )
        if not document:
            logger.error(f"Document {document_id} not found")
            return {"status": "error", "message": "Document not found"}

        # Check if document is already being processed (prevent duplicate processing)
        if document.status == DocumentStatus.PROCESSING and document.document_metadata:
            existing_task_id = document.document_metadata.get("celery_task_id")
            if existing_task_id and existing_task_id != self.request.id:
                logger.warning(
                    f"Document {document_id} is already being processed by task {existing_task_id}"
                )
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
        document.document_metadata["processing_started_at"] = (
            datetime.utcnow().isoformat()
        )
        document.document_metadata["celery_task_id"] = self.request.id
        db.commit()

        logger.info(f"Processing document {document_id}: {document.filename}")

        # Step 1: OCR / Text Extraction
        if task_type in ["ocr", "full_pipeline"]:
            self.update_state(state="PROGRESS", meta={"step": "ocr", "progress": 10})

            import asyncio
            from app.services.text_extractor import text_extractor
            from app.services.ocr_service import ocr_service

            # Extract text based on file type (run async code in event loop)
            extraction_result = asyncio.run(
                text_extractor.extract_text(
                    file_path=document.file_path, filename=document.original_filename
                )
            )

            extracted_text = extraction_result.get("text", "")
            document.page_count = extraction_result.get("pages", 0)

            # If no text extracted and it's an image-based PDF, try OCR
            if not extracted_text.strip() and document.mime_type == "application/pdf":
                self.update_state(
                    state="PROGRESS", meta={"step": "ocr_images", "progress": 20}
                )
                # Extract images and run OCR
                images = asyncio.run(
                    text_extractor.extract_images_from_pdf(document.file_path)
                )
                ocr_texts = []
                for i, image_bytes in enumerate(images):
                    ocr_result = asyncio.run(ocr_service.extract_text(image_bytes))
                    if ocr_result.get("text"):
                        ocr_texts.append(f"[Image Page {i + 1}] {ocr_result['text']}")
                extracted_text = "\n\n".join(ocr_texts)

            # For image files, run OCR directly
            elif document.mime_type.startswith("image/"):
                with open(document.file_path, "rb") as f:
                    image_bytes = f.read()
                ocr_result = asyncio.run(ocr_service.extract_text(image_bytes))
                extracted_text = ocr_result.get("text", "")

            if extracted_text:
                document.ocr_processed = True
                # Save extracted text to a file for later chunking
                text_file_path = f"{document.file_path}.txt"
                with open(text_file_path, "w", encoding="utf-8") as f:
                    f.write(extracted_text)

            logger.info(f"OCR/Text extraction completed for {document_id}")

        # Step 2: Chunking
        chunks = []
        if task_type in ["chunking", "full_pipeline"]:
            self.update_state(
                state="PROGRESS", meta={"step": "chunking", "progress": 40}
            )

            from app.services.embedding_service import chunking_service

            # Read extracted text from file
            text_file_path = f"{document.file_path}.txt"
            extracted_text = ""
            try:
                with open(text_file_path, "r", encoding="utf-8") as f:
                    extracted_text = f.read()
            except FileNotFoundError:
                logger.warning(
                    f"No extracted text file found for document {document_id}"
                )

            if extracted_text:
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
                        )
                        db.add(chunk)

                    document.chunk_count = len(chunks)
                    processing_task.progress_percentage = 50
                    db.commit()
                    logger.info(
                        f"Successfully stored {len(chunks)} chunks for document {document_id}"
                    )
                except Exception as chunk_error:
                    db.rollback()
                    logger.error(
                        f"Failed to store chunks for document {document_id}: {chunk_error}"
                    )
                    metadata = document.document_metadata or {}
                    metadata["chunk_storage_error"] = str(chunk_error)
                    document.document_metadata = metadata
                    db.commit()
                    raise chunk_error
            else:
                logger.warning(f"No text to chunk for document {document_id}")

        # Step 3: Embedding Generation
        if task_type in ["embedding", "full_pipeline"] and chunks:
            self.update_state(
                state="PROGRESS", meta={"step": "embedding", "progress": 70}
            )

            from app.services.embedding_service import embedding_service
            from app.models.document import DocumentChunk

            # Get chunks from database
            db_chunks = (
                db.query(DocumentChunk)
                .filter(DocumentChunk.document_id == document.id)
                .order_by(DocumentChunk.chunk_index)
                .all()
            )

            if db_chunks:
                # Generate embeddings for all chunks
                chunk_texts = [chunk.chunk_text for chunk in db_chunks]

                embedding_success = False
                try:
                    embeddings = embedding_service.encode(
                        texts=chunk_texts, batch_size=32, show_progress=False
                    )

                    # Store embeddings in the dedicated vector column
                    for i, chunk in enumerate(db_chunks):
                        if i < len(embeddings):
                            # Store embedding in vector column (pgvector)
                            chunk.embedding_vector = embeddings[i]
                            # Also keep in metadata for backward compatibility during transition
                            metadata = chunk.document_metadata or {}
                            metadata["embedding"] = embeddings[i]
                            chunk.document_metadata = metadata

                    document.embedding_generated = True
                    processing_task.progress_percentage = 90
                    db.commit()

                    logger.info(
                        f"Generated {len(embeddings)} embeddings for document {document_id}"
                    )
                    embedding_success = True

                except Exception as embed_error:
                    logger.error(
                        f"Error generating embeddings for document {document_id}: {embed_error}"
                    )
                    # Mark embedding as failed in metadata but continue with text indexing
                    doc_metadata = document.document_metadata or {}
                    doc_metadata["embedding_error"] = str(embed_error)
                    doc_metadata["embedding_failed_at"] = datetime.utcnow().isoformat()
                    document.document_metadata = doc_metadata
                    processing_task.error_message = (
                        f"Embedding failed: {str(embed_error)[:400]}"
                    )
                    db.commit()
                    # Document can still be searched via text, so we continue
                finally:
                    # Ensure progress is updated even on partial failure
                    if not embedding_success:
                        logger.warning(
                            f"Embedding generation incomplete for document {document_id}, "
                            "document will be searchable via text only"
                        )
            else:
                logger.warning(
                    f"No chunks found for embedding generation (document {document_id})"
                )

        # Step 4: Update document status
        document.status = DocumentStatus.INDEXED
        processing_task.status = TaskStatus.COMPLETED
        processing_task.progress_percentage = 100
        db.commit()

        logger.info(f"Document {document_id} processed successfully")

        return {
            "status": "success",
            "document_id": str(document.id),
            "filename": document.filename,
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
                logger.error(
                    f"Document {document_id} failed permanently after {current_retry} retries: {str(e)}"
                )
            else:
                document.status = DocumentStatus.PENDING
                logger.warning(
                    f"Document {document_id} will be retried ({current_retry}/2)"
                )
            db.commit()

        # Retry with fixed 30s delay (max 2 retries = 3 total attempts)
        raise self.retry(exc=e, countdown=30, max_retries=2)

    finally:
        db.close()


@shared_task(name="app.tasks.document_tasks.process_batch_documents")
def process_batch_documents(document_ids: list):
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
            results.append(
                {"document_id": doc_id, "task_id": result.id, "status": "queued"}
            )
        except Exception as e:
            logger.error(f"Failed to queue document {doc_id}: {str(e)}")
            results.append(
                {"document_id": doc_id, "status": "error", "message": str(e)}
            )

    return {
        "total": len(document_ids),
        "queued": sum(1 for r in results if r["status"] == "queued"),
        "errors": sum(1 for r in results if r["status"] == "error"),
        "results": results,
    }


@shared_task(name="app.tasks.document_tasks.generate_embeddings")
def generate_embeddings(chunk_ids: list):
    """
    Generate embeddings for document chunks

    Args:
        chunk_ids: List of chunk UUIDs to generate embeddings for

    Returns:
        dict with embedding generation results
    """
    from app.database import SessionLocal
    from app.models.document import DocumentChunk

    db = SessionLocal()
    try:
        chunks = db.query(DocumentChunk).filter(DocumentChunk.id.in_(chunk_ids)).all()
        logger.info(f"Generating embeddings for {len(chunks)} chunks")

        # Embedding generation will be implemented in embedding service
        # For now, return placeholder
        return {
            "status": "success",
            "processed": len(chunks),
            "message": "Embeddings generated successfully",
        }

    except Exception as e:
        logger.error(f"Error generating embeddings: {str(e)}")
        raise

    finally:
        db.close()


@shared_task(name="app.tasks.document_tasks.cleanup_old_tasks")
def cleanup_old_tasks(days: int = 7):
    """
    Clean up old completed tasks from the processing queue

    Args:
        days: Number of days after which to remove completed tasks

    Returns:
        dict with cleanup results
    """
    from app.database import SessionLocal
    from app.models.processing import ProcessingQueue, TaskStatus
    from datetime import datetime, timedelta

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
def recover_stuck_documents(stuck_threshold_minutes: int = 60):
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
    from app.database import SessionLocal
    from app.models.document import Document, DocumentStatus
    from app.models.processing import ProcessingQueue, TaskStatus
    from datetime import datetime, timedelta

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
                doc = (
                    db.query(Document)
                    .filter(Document.id == task.document_id)
                    .first()
                )
                if not doc:
                    continue

                logger.warning(
                    f"Stuck document detected: doc_id={doc.id}, "
                    f"started_at={task.started_at}, requeuing…"
                )

                # Reset processing queue entry so it can be retried
                task.status = TaskStatus.FAILED
                task.error_message = (
                    f"Stuck processing recovered at {datetime.utcnow().isoformat()}"
                )
                db.commit()

                # Reset document to PENDING so it gets requeued
                doc.status = DocumentStatus.PENDING
                db.commit()

                # Re-dispatch the processing task
                process_document.delay(str(doc.id))
                requeued += 1

            except Exception as inner_e:
                logger.error(
                    f"Error recovering stuck document {task.document_id}: {inner_e}"
                )
                errors += 1

        logger.info(
            f"Stuck-document recovery complete: "
            f"found={len(stuck_tasks)}, requeued={requeued}, errors={errors}"
        )

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
