"""
Dedicated Celery tasks for embedding generation and model management.

Three tasks are provided:
  1. generate_embeddings_batch  — embed a list of chunk IDs (max 100)
  2. recompute_embeddings_for_document — re-embed all chunks for one document
  3. upgrade_embeddings_model   — bulk migrate embeddings to a new model version
"""

import logging
import time
import uuid

from app.celery_app import celery_app
from app.tasks.base import store_dlq_on_max_retries

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Task 1: generate_embeddings_batch
# ---------------------------------------------------------------------------


@celery_app.task(
    bind=True,
    name="app.tasks.embedding_tasks.generate_embeddings_batch",
    queue="document_processing",
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 3},
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
)
def generate_embeddings_batch(
    self,
    chunk_ids: list[str],
    model_name: str = "default",
) -> dict:
    """
    Generate embeddings for multiple document chunks in one batch.

    Args:
        chunk_ids:  List of DocumentChunk UUID strings (max 100).
        model_name: Embedding model to use ("default" → multilingual-e5-large).

    Returns:
        {
            "status": "completed",
            "total": int,
            "successful": int,
            "failed": int,
            "errors": [{"chunk_id": str, "error": str}, ...]
        }
    """
    if len(chunk_ids) > 100:
        raise ValueError(f"generate_embeddings_batch: max 100 chunk_ids, got {len(chunk_ids)}")

    from app.database import SessionLocal
    from app.models.document import DocumentChunk
    from app.services.embedding_service import embedding_service

    db = SessionLocal()
    try:
        chunk_uuids = [uuid.UUID(c) if isinstance(c, str) else c for c in chunk_ids]
        chunks = db.query(DocumentChunk).filter(DocumentChunk.id.in_(chunk_uuids)).all()

        if not chunks:
            return {
                "status": "completed",
                "total": 0,
                "successful": 0,
                "failed": 0,
                "errors": [],
            }

        texts = [c.chunk_text for c in chunks]
        embeddings = embedding_service.encode(texts=texts, batch_size=32)

        success_count = 0
        failed_count = 0
        errors: list = []

        for i, chunk in enumerate(chunks):
            try:
                chunk.embedding_vector = embeddings[i]
                meta = chunk.document_metadata or {}
                meta["embedding"] = embeddings[i]
                chunk.document_metadata = meta
                success_count += 1
            except Exception as err:
                failed_count += 1
                errors.append({"chunk_id": str(chunk.id), "error": str(err)})

        db.commit()
        logger.info(f"generate_embeddings_batch: {success_count} ok, {failed_count} failed")
        return {
            "status": "completed",
            "total": len(chunks),
            "successful": success_count,
            "failed": failed_count,
            "errors": errors,
        }

    except Exception as exc:
        db.rollback()
        logger.error(f"generate_embeddings_batch error: {exc}")
        store_dlq_on_max_retries(self, exc, extra_metadata={"chunk_ids": chunk_ids[:10]})
        raise

    finally:
        db.close()


# ---------------------------------------------------------------------------
# Task 2: recompute_embeddings_for_document
# ---------------------------------------------------------------------------


@celery_app.task(
    bind=True,
    name="app.tasks.embedding_tasks.recompute_embeddings_for_document",
    queue="document_processing",
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 2},
    retry_backoff=True,
)
def recompute_embeddings_for_document(self, document_id: str) -> dict:
    """
    Recompute all embeddings for every chunk of a single document.

    Useful after a model upgrade or when embeddings were missing.

    Args:
        document_id: Document UUID string.

    Returns:
        {
            "document_id": str,
            "chunks_updated": int,
            "chunks_failed": int,
            "duration_seconds": float
        }
    """
    from app.database import SessionLocal
    from app.models.document import Document, DocumentChunk
    from app.services.embedding_service import embedding_service

    start = time.time()
    db = SessionLocal()
    try:
        doc_uuid = uuid.UUID(document_id)
        document = db.query(Document).filter(Document.id == doc_uuid).first()
        if not document:
            raise ValueError(f"Document {document_id} not found")

        chunks = (
            db.query(DocumentChunk)
            .filter(DocumentChunk.document_id == doc_uuid)
            .order_by(DocumentChunk.chunk_index)
            .all()
        )

        if not chunks:
            return {
                "document_id": document_id,
                "chunks_updated": 0,
                "chunks_failed": 0,
                "duration_seconds": round(time.time() - start, 2),
            }

        # Process in batches of 100
        batch_size = 100
        updated = 0
        failed = 0

        for batch_start in range(0, len(chunks), batch_size):
            batch = chunks[batch_start : batch_start + batch_size]
            texts = [c.chunk_text for c in batch]
            try:
                embeddings = embedding_service.encode(texts=texts, batch_size=32)
                for i, chunk in enumerate(batch):
                    chunk.embedding_vector = embeddings[i]
                    meta = chunk.document_metadata or {}
                    meta["embedding"] = embeddings[i]
                    chunk.document_metadata = meta
                    updated += 1
                db.commit()
            except Exception as batch_err:
                db.rollback()
                logger.error(
                    f"recompute batch {batch_start}-{batch_start + batch_size} "
                    f"failed for doc {document_id}: {batch_err}"
                )
                failed += len(batch)

        # Update document flag
        document.embedding_generated = updated > 0
        db.commit()

        duration = round(time.time() - start, 2)
        logger.info(f"recompute_embeddings_for_document {document_id}: {updated} updated, {failed} failed, {duration}s")
        return {
            "document_id": document_id,
            "chunks_updated": updated,
            "chunks_failed": failed,
            "duration_seconds": duration,
        }

    except Exception as exc:
        db.rollback()
        logger.error(f"recompute_embeddings_for_document error: {exc}")
        store_dlq_on_max_retries(self, exc, extra_metadata={"document_id": document_id})
        raise

    finally:
        db.close()


# ---------------------------------------------------------------------------
# Task 3: upgrade_embeddings_model
# ---------------------------------------------------------------------------


@celery_app.task(
    bind=True,
    name="app.tasks.embedding_tasks.upgrade_embeddings_model",
    queue="document_processing",
    # Long-running — do NOT autoretry; it must be run during maintenance window
    time_limit=7200,  # 2 hours hard limit
    soft_time_limit=6600,
)
def upgrade_embeddings_model(
    self,
    from_model: str,
    to_model: str,
    batch_size: int = 100,
) -> dict:
    """
    Migrate all document embeddings from one model version to another.

    This is a long-running, maintenance-window task.  It processes all
    documents whose chunks do not yet have embeddings generated by *to_model*,
    in batches of *batch_size* chunks.

    Args:
        from_model: Previous model name (informational, used for logging).
        to_model:   New model name to use for encoding.
        batch_size: Number of chunks to process per iteration (max 100).

    Returns:
        {
            "status": "completed" | "partial",
            "from_model": str,
            "to_model": str,
            "total_chunks": int,
            "chunks_updated": int,
            "chunks_failed": int,
            "duration_seconds": float
        }
    """
    from app.database import SessionLocal
    from app.models.document import DocumentChunk

    start = time.time()

    # Load the target model on-demand (may differ from the singleton)
    try:
        from sentence_transformers import SentenceTransformer

        target_model = SentenceTransformer(to_model, device="cpu")
    except Exception as load_err:
        raise RuntimeError(f"Cannot load target model '{to_model}': {load_err}") from load_err

    db = SessionLocal()
    total_chunks = 0
    updated = 0
    failed = 0

    try:
        all_chunks = db.query(DocumentChunk).order_by(DocumentChunk.document_id, DocumentChunk.chunk_index).all()
        total_chunks = len(all_chunks)
        logger.info(f"upgrade_embeddings_model: migrating {total_chunks} chunks from '{from_model}' → '{to_model}'")

        for batch_start in range(0, total_chunks, batch_size):
            batch = all_chunks[batch_start : batch_start + batch_size]
            texts = [f"passage: {c.chunk_text}" for c in batch]
            try:
                embeddings = target_model.encode(
                    texts,
                    batch_size=32,
                    show_progress_bar=False,
                    convert_to_numpy=True,
                    normalize_embeddings=True,
                ).tolist()

                for i, chunk in enumerate(batch):
                    chunk.embedding_vector = embeddings[i]
                    meta = chunk.document_metadata or {}
                    meta["embedding"] = embeddings[i]
                    meta["embedding_model"] = to_model
                    chunk.document_metadata = meta
                    updated += 1

                db.commit()
                logger.debug(f"upgrade_embeddings_model: committed batch {batch_start}–{batch_start + len(batch)}")
            except Exception as batch_err:
                db.rollback()
                logger.error(f"upgrade_embeddings_model batch {batch_start} failed: {batch_err}")
                failed += len(batch)

    except Exception as exc:
        db.rollback()
        logger.error(f"upgrade_embeddings_model fatal error: {exc}")
        # upgrade_embeddings_model has no autoretry — store unconditionally
        store_dlq_on_max_retries(
            self,
            exc,
            extra_metadata={"from_model": from_model, "to_model": to_model},
        )
        raise

    finally:
        db.close()

    duration = round(time.time() - start, 2)
    status = "completed" if failed == 0 else "partial"
    logger.info(f"upgrade_embeddings_model done: {updated} updated, {failed} failed, {duration}s ({status})")
    return {
        "status": status,
        "from_model": from_model,
        "to_model": to_model,
        "total_chunks": total_chunks,
        "chunks_updated": updated,
        "chunks_failed": failed,
        "duration_seconds": duration,
    }
