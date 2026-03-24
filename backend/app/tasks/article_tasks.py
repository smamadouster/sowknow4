"""
Celery tasks for article generation and embedding.

Tasks:
  1. generate_articles_for_document — extract articles from chunks via LLM
  2. generate_article_embeddings — embed articles for semantic search
  3. backfill_articles — generate articles for all indexed documents
"""

import asyncio
import logging
import uuid
from datetime import datetime

from celery import shared_task

from app.tasks.base import log_task_memory

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    name="app.tasks.article_tasks.generate_articles_for_document",
    autoretry_for=(Exception,),
    max_retries=2,
    retry_backoff=True,
    soft_time_limit=600,
    time_limit=720,
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

        # Select LLM based on document bucket
        is_confidential = document.bucket == DocumentBucket.CONFIDENTIAL
        llm_service, provider_name = _get_llm_service(is_confidential)

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
    """
    from app.database import SessionLocal
    from app.models.document import Document, DocumentStatus

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

        queued = 0
        for doc in documents:
            generate_articles_for_document.delay(str(doc.id))
            queued += 1

        logger.info(f"Backfill: queued article generation for {queued} documents")
        return {"status": "success", "queued": queued}

    finally:
        db.close()


def _get_llm_service(is_confidential: bool):
    """Get the appropriate LLM service based on confidentiality."""
    if is_confidential:
        try:
            from app.services.ollama_service import ollama_service
            return ollama_service, "ollama"
        except Exception:
            logger.error("Ollama unavailable for confidential article generation")
            raise RuntimeError("Ollama required for confidential documents but unavailable")

    # Public docs: MiniMax 2.7 → mistral-small-2603 (OpenRouter) → Ollama
    try:
        from app.services.minimax_service import minimax_service
        if getattr(minimax_service, "api_key", None):
            return minimax_service, "minimax"
    except Exception:
        pass

    try:
        from app.services.openrouter_service import openrouter_service
        if getattr(openrouter_service, "api_key", None):
            return openrouter_service, "openrouter"
    except Exception:
        pass

    try:
        from app.services.ollama_service import ollama_service
        return ollama_service, "ollama"
    except Exception:
        pass

    raise RuntimeError("No LLM service available for article generation")
