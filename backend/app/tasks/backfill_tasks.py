"""
Backfill tasks for recovering from pipeline failures.

These tasks are designed to be run manually (via celery call or admin API)
to fix batches of documents that missed processing stages.
"""

import logging
from datetime import datetime, timezone

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="app.tasks.backfill_tasks.classify_and_recover_errors")
def classify_and_recover_errors(
    batch_size: int = 50,
    delay_seconds: int = 10,
    dry_run: bool = True,
) -> dict:
    """
    Classify all ERROR documents by what work was already completed,
    then recover them with the minimum work needed.

    Phase A: Fix status-only (have chunks+embeddings, just stuck in error)
    Phase B: Queue embedding-only (have chunks, missing embeddings)
    Phase C: Queue full reprocessing (no progress at all)

    Args:
        batch_size: Max documents to process per phase
        delay_seconds: Stagger delay between queued tasks
        dry_run: If True, only classify — don't actually recover
    """
    from app.database import SessionLocal
    from app.models.document import Document, DocumentChunk, DocumentStatus

    db = SessionLocal()
    try:
        # Classify all error documents
        error_docs = (
            db.query(Document)
            .filter(Document.status == DocumentStatus.ERROR)
            .all()
        )

        # Classification buckets
        status_fix_only = []  # Have chunks with embeddings — just fix status
        embed_only = []       # Have chunks, missing embeddings
        full_reprocess = []   # No progress at all

        for doc in error_docs:
            chunk_count = (
                db.query(DocumentChunk)
                .filter(DocumentChunk.document_id == doc.id)
                .count()
            )
            if chunk_count > 0:
                # Check if embeddings exist
                embedded_count = (
                    db.query(DocumentChunk)
                    .filter(
                        DocumentChunk.document_id == doc.id,
                        DocumentChunk.embedding_vector != None,  # noqa: E711
                    )
                    .count()
                )
                if embedded_count > 0:
                    status_fix_only.append(doc)
                else:
                    embed_only.append(doc)
            else:
                full_reprocess.append(doc)

        classification = {
            "total_errors": len(error_docs),
            "status_fix_only": len(status_fix_only),
            "embed_only": len(embed_only),
            "full_reprocess": len(full_reprocess),
        }
        logger.info(f"Error classification: {classification}")

        if dry_run:
            return {"status": "dry_run", "classification": classification}

        # Phase A: Fix status-only documents immediately
        fixed = 0
        for doc in status_fix_only[:batch_size]:
            doc.status = DocumentStatus.INDEXED
            doc.pipeline_stage = "indexed"
            doc.pipeline_error = None
            meta = doc.document_metadata or {}
            meta["auto_recovered_at"] = datetime.now(timezone.utc).isoformat()
            meta["recovery_type"] = "status_fix"
            doc.document_metadata = meta
            fixed += 1
        db.commit()

        # Phase B: Queue embedding-only recovery
        embed_queued = 0
        from app.tasks.embedding_tasks import recompute_embeddings_for_document

        for i, doc in enumerate(embed_only[:batch_size]):
            doc.status = DocumentStatus.INDEXED
            doc.pipeline_stage = "embedding"
            meta = doc.document_metadata or {}
            meta["recovery_type"] = "embed_only"
            doc.document_metadata = meta
            db.commit()
            recompute_embeddings_for_document.apply_async(
                args=(str(doc.id),),
                countdown=i * delay_seconds,
            )
            embed_queued += 1

        # Phase C: Queue full reprocessing (smallest batches, highest cost)
        reprocess_queued = 0
        from app.tasks.document_tasks import process_document

        reprocess_batch = min(batch_size // 2, 25)  # Smaller batches for full reprocess
        for i, doc in enumerate(full_reprocess[:reprocess_batch]):
            doc.status = DocumentStatus.PENDING
            doc.pipeline_stage = "uploaded"
            doc.pipeline_error = None
            doc.pipeline_retry_count = 0
            meta = doc.document_metadata or {}
            meta["recovery_type"] = "full_reprocess"
            meta["backfill_reset_at"] = datetime.now(timezone.utc).isoformat()
            meta["original_error"] = meta.get("processing_error", "unknown")
            doc.document_metadata = meta
            db.commit()
            process_document.apply_async(
                args=(str(doc.id),),
                countdown=i * delay_seconds * 2,  # Double stagger for full pipeline
            )
            reprocess_queued += 1

        return {
            "status": "success",
            "classification": classification,
            "actions": {
                "status_fixed": fixed,
                "embed_queued": embed_queued,
                "reprocess_queued": reprocess_queued,
            },
        }

    except Exception as e:
        logger.error(f"Error in classify_and_recover_errors: {e}")
        db.rollback()
        raise

    finally:
        db.close()


@shared_task(name="app.tasks.backfill_tasks.reprocess_failed_documents")
def reprocess_failed_documents(
    date_from: str,
    date_to: str,
    batch_size: int = 200,
    delay_seconds: int = 5,
) -> dict:
    """
    Reset ERROR documents back to PENDING for reprocessing.

    Args:
        date_from: ISO date string (inclusive), e.g. "2026-04-02"
        date_to: ISO date string (exclusive), e.g. "2026-04-05"
        batch_size: Max documents to reset per invocation
        delay_seconds: Stagger delay between queued tasks
    """
    from app.database import SessionLocal
    from app.models.document import Document, DocumentStatus
    from app.tasks.document_tasks import process_document

    db = SessionLocal()
    try:
        from_dt = datetime.fromisoformat(date_from).replace(tzinfo=timezone.utc)
        to_dt = datetime.fromisoformat(date_to).replace(tzinfo=timezone.utc)

        docs = (
            db.query(Document)
            .filter(
                Document.status == DocumentStatus.ERROR,
                Document.created_at >= from_dt,
                Document.created_at < to_dt,
            )
            .limit(batch_size)
            .all()
        )

        logger.info(f"Reprocess backfill: found {len(docs)} ERROR documents in [{date_from}, {date_to})")

        reset_count = 0
        for i, doc in enumerate(docs):
            meta = doc.document_metadata or {}
            doc.status = DocumentStatus.PENDING
            doc.document_metadata = {
                **meta,
                "recovery_count": 0,
                "pending_recovery_count": 0,
                "backfill_reset_at": datetime.now(timezone.utc).isoformat(),
                "original_error": meta.get("processing_error", "unknown"),
            }
            db.commit()

            process_document.apply_async(
                args=(str(doc.id),),
                countdown=i * delay_seconds,
            )
            reset_count += 1

        logger.info(f"Reprocess backfill: reset {reset_count} documents, stagger={delay_seconds}s")

        return {
            "status": "success",
            "date_from": date_from,
            "date_to": date_to,
            "total_reset": reset_count,
            "batch_size": batch_size,
        }

    except Exception as e:
        logger.error(f"Error in reprocess_failed_documents: {e}")
        db.rollback()
        raise

    finally:
        db.close()


@shared_task(name="app.tasks.backfill_tasks.backfill_missing_embeddings")
def backfill_missing_embeddings(
    batch_size: int = 10,
    delay_seconds: int = 30,
) -> dict:
    """
    Queue embedding generation for indexed documents that are missing embeddings.

    Args:
        batch_size: Max documents to process per invocation
        delay_seconds: Stagger delay between queued tasks (embeddings are CPU-heavy)
    """
    from app.database import SessionLocal
    from app.models.document import Document, DocumentStatus
    from app.tasks.embedding_tasks import recompute_embeddings_for_document

    db = SessionLocal()
    try:
        docs = (
            db.query(Document)
            .filter(
                Document.status == DocumentStatus.INDEXED,
                Document.embedding_generated == False,  # noqa: E712
            )
            .limit(batch_size)
            .all()
        )

        logger.info(f"Embedding backfill: found {len(docs)} indexed documents without embeddings")

        queued = 0
        for i, doc in enumerate(docs):
            recompute_embeddings_for_document.apply_async(
                args=(str(doc.id),),
                countdown=i * delay_seconds,
            )
            queued += 1

        return {
            "status": "success",
            "total_queued": queued,
            "batch_size": batch_size,
            "delay_seconds": delay_seconds,
        }

    finally:
        db.close()


@shared_task(name="app.tasks.backfill_tasks.backfill_missing_articles")
def backfill_missing_articles(
    batch_size: int = 20,
    delay_seconds: int = 60,
) -> dict:
    """
    Queue article generation for indexed documents that are missing articles.

    Args:
        batch_size: Max documents to process per invocation
        delay_seconds: Stagger delay (article gen calls external LLM APIs)
    """
    from app.database import SessionLocal
    from app.models.document import Document, DocumentStatus
    from app.tasks.article_tasks import generate_articles_for_document

    db = SessionLocal()
    try:
        docs = (
            db.query(Document)
            .filter(
                Document.status == DocumentStatus.INDEXED,
                Document.articles_generated == False,  # noqa: E712
                Document.chunk_count > 0,
            )
            .limit(batch_size)
            .all()
        )

        logger.info(f"Article backfill: found {len(docs)} indexed documents without articles")

        queued = 0
        for i, doc in enumerate(docs):
            generate_articles_for_document.apply_async(
                args=(str(doc.id),),
                countdown=i * delay_seconds,
            )
            queued += 1

        return {
            "status": "success",
            "total_queued": queued,
            "batch_size": batch_size,
            "delay_seconds": delay_seconds,
        }

    finally:
        db.close()


@shared_task(name="app.tasks.backfill_tasks.backfill_article_embeddings")
def backfill_article_embeddings(
    batch_size: int = 50,
    delay_seconds: int = 10,
) -> dict:
    """
    Queue embedding generation for articles stuck in PENDING status.

    Args:
        batch_size: Max articles to process per invocation
        delay_seconds: Stagger delay between batches
    """
    from app.database import SessionLocal
    from app.models.article import Article, ArticleStatus
    from app.tasks.article_tasks import generate_article_embeddings

    db = SessionLocal()
    try:
        articles = (
            db.query(Article)
            .filter(
                Article.status == ArticleStatus.PENDING,
                Article.embedding_vector == None,  # noqa: E711
            )
            .limit(batch_size)
            .all()
        )

        logger.info(f"Article embedding backfill: found {len(articles)} pending articles")

        if not articles:
            return {"status": "success", "total_queued": 0}

        article_ids = [str(a.id) for a in articles]
        generate_article_embeddings.apply_async(
            args=(article_ids,),
            countdown=delay_seconds,
        )

        return {
            "status": "success",
            "total_queued": len(article_ids),
            "batch_size": batch_size,
        }

    finally:
        db.close()
