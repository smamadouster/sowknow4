"""
Backfill tasks for recovering from pipeline failures.

These tasks are designed to be run manually (via celery call or admin API)
to fix batches of documents that missed processing stages.
"""

import logging
from datetime import datetime, timezone

from celery import shared_task

logger = logging.getLogger(__name__)


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
