"""
Celery tasks for article generation and embedding.

Tasks:
  1. generate_articles_for_document — extract articles from chunks via LLM
  2. generate_article_embeddings — embed articles for semantic search
  3. backfill_articles — generate articles for all indexed documents
"""

import asyncio
import logging
import time
import uuid
from datetime import datetime

import httpx
from celery import shared_task

from app.tasks.base import log_task_memory

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Ollama circuit breaker -- prevents hammering an overloaded/dead service
# ---------------------------------------------------------------------------

class OllamaCircuitBreaker:
    """Simple circuit breaker for Ollama.

    States:
      CLOSED  — normal, requests go through
      OPEN    — Ollama is down/overloaded, reject immediately
      HALF    — allow one probe request to check recovery

    Opens after `failure_threshold` consecutive failures.
    Stays open for `recovery_timeout` seconds before probing.
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(self, failure_threshold: int = 3, recovery_timeout: int = 120):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.state = self.CLOSED
        self.failures = 0
        self.last_failure_time = 0.0

    def record_success(self):
        self.failures = 0
        self.state = self.CLOSED

    def record_failure(self):
        self.failures += 1
        self.last_failure_time = time.monotonic()
        if self.failures >= self.failure_threshold:
            self.state = self.OPEN
            logger.warning(
                "Ollama circuit breaker OPEN after %d failures — "
                "blocking requests for %ds",
                self.failures, self.recovery_timeout,
            )

    def allow_request(self) -> bool:
        if self.state == self.CLOSED:
            return True
        if self.state == self.OPEN:
            elapsed = time.monotonic() - self.last_failure_time
            if elapsed >= self.recovery_timeout:
                self.state = self.HALF_OPEN
                logger.info("Ollama circuit breaker HALF_OPEN — probing")
                return True
            return False
        # HALF_OPEN: allow one probe
        return True


_ollama_breaker = OllamaCircuitBreaker()


def _check_ollama_health() -> bool:
    """Synchronous Ollama health probe (used inside Celery tasks)."""
    from app.services.ollama_service import OLLAMA_BASE_URL

    if not _ollama_breaker.allow_request():
        logger.info("Ollama circuit breaker is OPEN — skipping health check")
        return False

    try:
        resp = httpx.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=10.0)
        resp.raise_for_status()
        _ollama_breaker.record_success()
        return True
    except Exception as e:
        _ollama_breaker.record_failure()
        logger.warning("Ollama health check failed: %s", e)
        return False


class OllamaUnavailableError(Exception):
    """Raised when Ollama is down and the circuit breaker is open."""


@shared_task(
    bind=True,
    name="app.tasks.article_tasks.generate_articles_for_document",
    autoretry_for=(httpx.TimeoutException, httpx.ConnectError),
    max_retries=5,
    retry_backoff=True,
    retry_backoff_max=300,
    soft_time_limit=600,
    time_limit=660,
)
def generate_articles_for_document(self, document_id: str, force: bool = False) -> dict:
    """
    Generate articles for a single document using LLM.

    Args:
        document_id: UUID of the document
        force: If True, delete existing articles and regenerate

    Returns:
        dict with generation results
    """
    from app.database import SessionLocal
    from app.models.article import Article, ArticleStatus
    from app.models.document import Document, DocumentBucket, DocumentChunk, DocumentStatus

    db = SessionLocal()
    try:
        document = db.query(Document).filter(Document.id == uuid.UUID(document_id)).first()
        if not document:
            return {"status": "error", "message": "Document not found"}

        if document.status != DocumentStatus.INDEXED:
            return {"status": "skipped", "message": f"Document not indexed (status: {document.status.value})"}

        if document.articles_generated and not force:
            return {"status": "skipped", "message": f"Articles already generated ({document.article_count})"}

        # Delete existing articles if forcing regeneration
        if force and document.articles_generated:
            db.query(Article).filter(Article.document_id == document.id).delete()
            db.commit()
            logger.info(f"Deleted existing articles for document {document_id}")

        # Load chunks
        chunks = (
            db.query(DocumentChunk)
            .filter(DocumentChunk.document_id == document.id)
            .order_by(DocumentChunk.chunk_index)
            .all()
        )

        if not chunks:
            document.articles_generated = True
            document.article_count = 0
            db.commit()
            return {"status": "success", "message": "No chunks to process", "article_count": 0}

        # Prepare chunk data for the service
        chunk_data = [
            {"id": str(c.id), "index": c.chunk_index, "text": c.chunk_text}
            for c in chunks
        ]

        # Determine language
        language = document.language.value if document.language else "french"
        language_map = {"fr": "french", "en": "english", "multi": "french", "unknown": "french"}
        language = language_map.get(language, language)

        llm_service, provider_name = _get_llm_service()

        log_task_memory("generate_articles", "before_llm")

        # Generate articles
        from app.services.article_generation_service import article_generation_service

        articles_data = asyncio.run(
            article_generation_service.generate_articles_for_document(
                document_id=document_id,
                chunks=chunk_data,
                filename=document.original_filename,
                language=language,
                bucket=document.bucket.value,
                llm_service=llm_service,
                provider_name=provider_name,
            )
        )

        log_task_memory("generate_articles", "after_llm")

        # Store articles in DB
        article_ids = []
        for art_data in articles_data:
            article = Article(
                document_id=document.id,
                title=art_data["title"],
                summary=art_data["summary"],
                body=art_data["body"],
                bucket=document.bucket,
                status=ArticleStatus.PENDING,
                language=art_data.get("language", language),
                search_language=art_data.get("language", language),
                source_chunk_ids=art_data.get("source_chunk_ids", []),
                tags=art_data.get("tags", []),
                categories=art_data.get("categories", []),
                entities=art_data.get("entities", []),
                confidence=art_data.get("confidence", 0),
                llm_provider=art_data.get("llm_provider"),
                content_hash=art_data.get("content_hash"),
            )
            db.add(article)
            db.flush()
            article_ids.append(str(article.id))

        # Update document
        document.articles_generated = True
        document.article_count = len(article_ids)
        db.commit()

        logger.info(f"Generated {len(article_ids)} articles for document {document_id}")

        # Dispatch embedding generation
        if article_ids:
            generate_article_embeddings.delay(article_ids)

        return {
            "status": "success",
            "document_id": document_id,
            "article_count": len(article_ids),
            "message": f"Generated {len(article_ids)} articles",
        }

    except Exception as e:
        db.rollback()
        logger.error(f"Article generation failed for {document_id}: {e}")
        raise

    finally:
        db.close()


@shared_task(
    bind=True,
    name="app.tasks.article_tasks.generate_article_embeddings",
    autoretry_for=(Exception,),
    max_retries=3,
    retry_backoff=True,
    soft_time_limit=1800,
    time_limit=2000,
)
def generate_article_embeddings(self, article_ids: list[str]) -> dict:
    """
    Generate embeddings for articles and mark them as indexed.

    Args:
        article_ids: List of article UUID strings

    Returns:
        dict with embedding results
    """
    from app.database import SessionLocal
    from app.models.article import Article, ArticleStatus
    from app.services.embedding_service import embedding_service

    db = SessionLocal()
    try:
        articles = (
            db.query(Article)
            .filter(Article.id.in_([uuid.UUID(aid) for aid in article_ids]))
            .all()
        )

        if not articles:
            return {"status": "success", "updated": 0, "failed": 0}

        updated = 0
        failed = 0
        batch_size = 16

        for i in range(0, len(articles), batch_size):
            batch = articles[i : i + batch_size]
            # Embed: title + summary + body concatenated
            texts = [
                f"{a.title}\n{a.summary}\n{a.body}" for a in batch
            ]

            try:
                embeddings = embedding_service.encode(texts=texts, batch_size=batch_size)
                for j, article in enumerate(batch):
                    if j < len(embeddings):
                        article.embedding_vector = embeddings[j]
                        article.status = ArticleStatus.INDEXED
                        updated += 1
                db.commit()
            except Exception as batch_err:
                db.rollback()
                logger.error(f"Article embedding batch {i} failed: {batch_err}")
                failed += len(batch)

        logger.info(f"Article embeddings: {updated} updated, {failed} failed")
        return {"status": "success", "updated": updated, "failed": failed}

    except Exception as e:
        db.rollback()
        logger.error(f"Article embedding generation failed: {e}")
        raise

    finally:
        db.close()


@shared_task(name="app.tasks.article_tasks.backfill_articles")
def backfill_articles() -> dict:
    """
    Generate articles for all indexed documents that don't have them yet.
    Admin-triggerable maintenance task.

    Dispatches in batches of 10, staggered 60s apart.
    Public documents are prioritised first (fast cloud APIs),
    then confidential documents (slower Ollama).
    """
    from app.database import SessionLocal
    from app.models.document import Document, DocumentBucket, DocumentStatus

    BATCH_SIZE = 40
    BATCH_INTERVAL_SECONDS = 20

    db = SessionLocal()
    try:
        documents = (
            db.query(Document)
            .filter(
                Document.status == DocumentStatus.INDEXED,
                Document.articles_generated == False,  # noqa: E712
                Document.chunk_count > 0,
            )
            .all()
        )

        # Split into public-first, then confidential
        public_docs = [d for d in documents if d.bucket != DocumentBucket.CONFIDENTIAL]
        confidential_docs = [d for d in documents if d.bucket == DocumentBucket.CONFIDENTIAL]
        ordered_docs = public_docs + confidential_docs

        queued_public = 0
        queued_confidential = 0

        for batch_index, offset in enumerate(range(0, len(ordered_docs), BATCH_SIZE)):
            batch = ordered_docs[offset : offset + BATCH_SIZE]
            countdown = batch_index * BATCH_INTERVAL_SECONDS

            for doc in batch:
                generate_articles_for_document.apply_async(
                    args=[str(doc.id)],
                    countdown=countdown,
                )
                if doc.bucket == DocumentBucket.CONFIDENTIAL:
                    queued_confidential += 1
                else:
                    queued_public += 1

        total = queued_public + queued_confidential
        logger.info(
            "Backfill: queued %d documents (public=%d, confidential=%d) "
            "in %d batches of %d, %ds apart",
            total,
            queued_public,
            queued_confidential,
            (total + BATCH_SIZE - 1) // BATCH_SIZE if total else 0,
            BATCH_SIZE,
            BATCH_INTERVAL_SECONDS,
        )
        return {
            "status": "success",
            "queued": total,
            "queued_public": queued_public,
            "queued_confidential": queued_confidential,
        }

    finally:
        db.close()


def _get_llm_service():
    """Get LLM service for article generation.

    All documents (public + confidential) route through cloud APIs for
    reliability and speed.  Preference: OpenRouter → MiniMax → Ollama fallback.
    """
    try:
        from app.services.openrouter_service import openrouter_service
        if getattr(openrouter_service, "api_key", None):
            return openrouter_service, "openrouter"
    except Exception:
        pass

    try:
        from app.services.minimax_service import minimax_service
        if getattr(minimax_service, "api_key", None):
            return minimax_service, "minimax"
    except Exception:
        pass

    try:
        from app.services.ollama_service import ollama_service
        return ollama_service, "ollama"
    except Exception:
        pass

    raise RuntimeError("No LLM service available for article generation")
