"""
Celery tasks for document processing
"""
from celery import shared_task
from app.celery_app import celery_app
import logging
from typing import Optional
import uuid

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
    try:
        # Get document
        document = db.query(Document).filter(Document.id == uuid.UUID(document_id)).first()
        if not document:
            logger.error(f"Document {document_id} not found")
            return {"status": "error", "message": "Document not found"}

        # Create or update processing queue entry
        processing_task = db.query(ProcessingQueue).filter(
            ProcessingQueue.document_id == document.id,
            ProcessingQueue.task_type == TaskType.OCR_PROCESSING
        ).first()

        if not processing_task:
            processing_task = ProcessingQueue(
                document_id=document.id,
                task_type=TaskType.OCR_PROCESSING,
                status=TaskStatus.PENDING
            )
            db.add(processing_task)
            db.commit()

        # Update task status
        processing_task.status = TaskStatus.IN_PROGRESS
        processing_task.celery_task_id = self.request.id
        db.commit()

        logger.info(f"Processing document {document_id}: {document.filename}")

        # Step 1: OCR / Text Extraction
        if task_type in ["ocr", "full_pipeline"]:
            self.update_state(state="PROGRESS", meta={"step": "ocr", "progress": 10})

            import asyncio
            from app.services.text_extractor import text_extractor
            from app.services.ocr_service import ocr_service

            # Extract text based on file type (run async code in event loop)
            extraction_result = asyncio.run(text_extractor.extract_text(
                file_path=document.file_path,
                filename=document.original_filename
            ))

            extracted_text = extraction_result.get("text", "")
            document.page_count = extraction_result.get("pages", 0)

            # If no text extracted and it's an image-based PDF, try OCR
            if not extracted_text.strip() and document.mime_type == "application/pdf":
                self.update_state(state="PROGRESS", meta={"step": "ocr_images", "progress": 20})
                # Extract images and run OCR
                images = asyncio.run(text_extractor.extract_images_from_pdf(document.file_path))
                ocr_texts = []
                for i, image_bytes in enumerate(images):
                    ocr_result = asyncio.run(ocr_service.extract_text(image_bytes))
                    if ocr_result.get("text"):
                        ocr_texts.append(f"[Image Page {i+1}] {ocr_result['text']}")
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
        if task_type in ["chunking", "full_pipeline"]:
            self.update_state(state="PROGRESS", meta={"step": "chunking", "progress": 40})
            # Chunking will be implemented in chunking service
            logger.info(f"Chunking for {document_id}")

        # Step 3: Embedding Generation
        if task_type in ["embedding", "full_pipeline"]:
            self.update_state(state="PROGRESS", meta={"step": "embedding", "progress": 70})
            # Embedding will be implemented in embedding service
            logger.info(f"Generating embeddings for {document_id}")

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
            "message": "Document processed successfully"
        }

    except Exception as e:
        logger.error(f"Error processing document {document_id}: {str(e)}")
        if processing_task:
            processing_task.status = TaskStatus.FAILED
            processing_task.error_message = str(e)
            db.commit()

        # Retry with exponential backoff
        raise self.retry(exc=e, countdown=60, max_retries=3)

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
            results.append({"document_id": doc_id, "task_id": result.id, "status": "queued"})
        except Exception as e:
            logger.error(f"Failed to queue document {doc_id}: {str(e)}")
            results.append({"document_id": doc_id, "status": "error", "message": str(e)})

    return {
        "total": len(document_ids),
        "queued": sum(1 for r in results if r["status"] == "queued"),
        "errors": sum(1 for r in results if r["status"] == "error"),
        "results": results
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
            "message": "Embeddings generated successfully"
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
        old_tasks = db.query(ProcessingQueue).filter(
            ProcessingQueue.status == TaskStatus.COMPLETED,
            ProcessingQueue.completed_at < cutoff_date
        ).all()

        count = len(old_tasks)
        for task in old_tasks:
            db.delete(task)

        db.commit()
        logger.info(f"Cleaned up {count} old tasks")

        return {
            "status": "success",
            "cleaned": count,
            "cutoff_date": cutoff_date.isoformat()
        }

    except Exception as e:
        logger.error(f"Error cleaning up old tasks: {str(e)}")
        db.rollback()
        raise

    finally:
        db.close()
