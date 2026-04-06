"""
Pipeline stage tasks for guaranteed document processing.

Each stage is a Celery task that calls update_stage() before/after the work
function, then either:
  - returns document_id on success
  - retries with exponential backoff if attempts remain
  - raises Reject(requeue=False) when max_attempts is exhausted

All DB interactions use the synchronous SessionLocal (Celery workers have no
async event loop at task execution time).
"""

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone

from celery.exceptions import Reject

from app.celery_app import celery_app
from app.models.pipeline import STAGE_RETRY_CONFIG, PipelineStage, StageEnum, StageStatus

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Core helper: update_stage
# ---------------------------------------------------------------------------


def update_stage(
    document_id: str,
    stage: StageEnum,
    status: StageStatus,
    error: str | None = None,
    worker_id: str | None = None,
    db=None,
) -> PipelineStage:
    """
    Get-or-create a PipelineStage row and update it according to *status*.

    If *db* is None a fresh SessionLocal session is created and closed here.
    Pass an open session when you need to batch several stage updates in one
    transaction.
    """
    from app.database import SessionLocal
    from app.models.pipeline import PipelineStage, StageEnum, StageStatus

    _own_session = db is None
    if _own_session:
        db = SessionLocal()

    try:
        doc_uuid = uuid.UUID(document_id) if isinstance(document_id, str) else document_id

        # Retry config tells us how many attempts are allowed
        retry_cfg = STAGE_RETRY_CONFIG.get(stage, {})
        max_attempts = retry_cfg.get("max_attempts", 3)

        # Get or create the stage row
        row = (
            db.query(PipelineStage)
            .filter(
                PipelineStage.document_id == doc_uuid,
                PipelineStage.stage == stage,
            )
            .first()
        )

        if row is None:
            row = PipelineStage(
                document_id=doc_uuid,
                stage=stage,
                status=StageStatus.PENDING,
                attempt=0,
                max_attempts=max_attempts,
            )
            db.add(row)

        # Apply the status-specific mutations
        row.status = status

        if status == StageStatus.RUNNING:
            row.attempt = (row.attempt or 0) + 1
            row.started_at = datetime.now(timezone.utc)
            row.error_message = None  # clear previous error on retry

        elif status == StageStatus.COMPLETED:
            row.completed_at = datetime.now(timezone.utc)

        elif status == StageStatus.FAILED:
            if error:
                row.error_message = error

        if worker_id is not None:
            row.worker_id = worker_id

        db.commit()
        db.refresh(row)
        return row

    finally:
        if _own_session:
            db.close()


# ---------------------------------------------------------------------------
# Generic stage runner
# ---------------------------------------------------------------------------


def _stage_task(self, document_id: str, stage: StageEnum, work_fn) -> str:
    """
    Generic pipeline stage runner.

    Marks the stage RUNNING, calls work_fn(document_id), then either marks it
    COMPLETED and returns document_id, or handles retries/rejection on failure.
    """
    worker_id = self.request.id  # Celery task ID

    update_stage(document_id, stage, StageStatus.RUNNING, worker_id=worker_id)

    try:
        work_fn(document_id)
    except Exception as exc:
        logger.exception("Stage %s failed for doc %s: %s", stage, document_id, exc)

        # Check how many attempts have been made
        from app.database import SessionLocal
        doc_uuid = uuid.UUID(document_id) if isinstance(document_id, str) else document_id
        db = SessionLocal()
        try:
            row = (
                db.query(PipelineStage)
                .filter(
                    PipelineStage.document_id == doc_uuid,
                    PipelineStage.stage == stage,
                )
                .first()
            )
            attempts = row.attempt if row else 1
        finally:
            db.close()

        retry_cfg = STAGE_RETRY_CONFIG.get(stage, {})
        max_attempts = retry_cfg.get("max_attempts", 3)
        backoff_list = retry_cfg.get("backoff", [30, 60, 120])

        if attempts >= max_attempts:
            update_stage(document_id, stage, StageStatus.FAILED, error=str(exc))
            logger.error(
                "Stage %s exhausted %d attempts for doc %s — rejecting task",
                stage,
                max_attempts,
                document_id,
            )
            raise Reject(str(exc), requeue=False)

        # Determine backoff countdown (use list index, capped at last value)
        backoff_idx = min(attempts - 1, len(backoff_list) - 1)
        countdown = backoff_list[backoff_idx]
        raise self.retry(exc=exc, countdown=countdown)

    update_stage(document_id, stage, StageStatus.COMPLETED)
    return document_id


# ---------------------------------------------------------------------------
# Work functions
# ---------------------------------------------------------------------------


def _run_ocr(document_id: str) -> None:
    """Extract text via OCR or native parser; write .txt sidecar file."""
    from app.database import SessionLocal
    from app.models.document import Document
    from app.services.ocr_service import ocr_service
    from app.services.text_extractor import text_extractor

    db = SessionLocal()
    try:
        doc_uuid = uuid.UUID(document_id) if isinstance(document_id, str) else document_id
        doc = db.query(Document).filter(Document.id == doc_uuid).first()
        if doc is None:
            raise ValueError(f"Document {document_id} not found")

        file_path = doc.file_path
        filename = doc.original_filename or doc.filename

        # Try native text extraction first
        result = asyncio.run(text_extractor.extract_text(file_path, filename))
        extracted_text = result.get("text", "")
        page_count = result.get("pages", 0)

        # If OCR is needed (image files, PDFs without text layer, etc.)
        should_ocr, reason = ocr_service.should_use_ocr(
            mime_type=doc.mime_type,
            extracted_text=extracted_text or None,
            file_path=file_path,
        )

        if should_ocr:
            logger.info("OCR needed for doc %s: %s", document_id, reason)
            ocr_result = asyncio.run(ocr_service._extract_full(file_path))
            extracted_text = ocr_result.get("text", "")
            doc.ocr_processed = True

        # Write sidecar .txt file
        txt_path = file_path + ".txt"
        with open(txt_path, "w", encoding="utf-8") as fh:
            fh.write(extracted_text or "")

        doc.page_count = page_count or 1
        db.commit()

    finally:
        db.close()


def _run_chunk(document_id: str) -> None:
    """Read .txt sidecar, chunk text, persist DocumentChunk rows."""
    from app.database import SessionLocal
    from app.models.document import Document, DocumentChunk
    from app.services.chunking_service import chunking_service
    from app.tasks.document_tasks import detect_text_language

    db = SessionLocal()
    try:
        doc_uuid = uuid.UUID(document_id) if isinstance(document_id, str) else document_id
        doc = db.query(Document).filter(Document.id == doc_uuid).first()
        if doc is None:
            raise ValueError(f"Document {document_id} not found")

        txt_path = doc.file_path + ".txt"
        if not os.path.exists(txt_path):
            raise FileNotFoundError(f"Sidecar text file not found: {txt_path}")

        with open(txt_path, "r", encoding="utf-8") as fh:
            text = fh.read()

        if not text.strip():
            logger.warning("Document %s has no text content — skipping chunking", document_id)
            doc.chunk_count = 0
            db.commit()
            return

        # Detect language for full-text search configuration
        search_lang = detect_text_language(text)

        chunks = chunking_service.chunk_document(text, document_id=document_id)

        # Delete existing chunks to allow re-runs
        db.query(DocumentChunk).filter(DocumentChunk.document_id == doc_uuid).delete()

        for chunk_data in chunks:
            chunk = DocumentChunk(
                document_id=doc_uuid,
                chunk_index=chunk_data["index"],
                chunk_text=chunk_data["text"],
                token_count=chunk_data.get("token_count"),
                search_language=search_lang,
                document_metadata=chunk_data.get("metadata", {}),
            )
            db.add(chunk)

        doc.chunk_count = len(chunks)
        db.commit()
        logger.info("Chunked doc %s into %d chunks", document_id, len(chunks))

    finally:
        db.close()


def _run_embed(document_id: str) -> None:
    """Load chunks, generate embeddings in batches of 32, update rows."""
    from app.database import SessionLocal
    from app.models.document import Document, DocumentChunk
    from app.services.embedding_service import embedding_service

    db = SessionLocal()
    try:
        doc_uuid = uuid.UUID(document_id) if isinstance(document_id, str) else document_id
        doc = db.query(Document).filter(Document.id == doc_uuid).first()
        if doc is None:
            raise ValueError(f"Document {document_id} not found")

        chunks = (
            db.query(DocumentChunk)
            .filter(DocumentChunk.document_id == doc_uuid)
            .order_by(DocumentChunk.chunk_index)
            .all()
        )

        if not chunks:
            logger.warning("No chunks for doc %s — skipping embedding", document_id)
            doc.embedding_generated = False
            db.commit()
            return

        batch_size = 32
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i : i + batch_size]
            texts = [c.chunk_text for c in batch]
            vectors = embedding_service.encode(texts=texts, batch_size=batch_size)
            for chunk, vec in zip(batch, vectors):
                chunk.embedding_vector = vec

        doc.embedding_generated = True
        db.commit()
        logger.info("Embedded %d chunks for doc %s", len(chunks), document_id)

    finally:
        db.close()


def _run_index(document_id: str) -> None:
    """Mark document as INDEXED when chunks exist, ERROR otherwise."""
    from app.database import SessionLocal
    from app.models.document import Document, DocumentChunk, DocumentStatus

    db = SessionLocal()
    try:
        doc_uuid = uuid.UUID(document_id) if isinstance(document_id, str) else document_id
        doc = db.query(Document).filter(Document.id == doc_uuid).first()
        if doc is None:
            raise ValueError(f"Document {document_id} not found")

        chunk_count = (
            db.query(DocumentChunk)
            .filter(DocumentChunk.document_id == doc_uuid)
            .count()
        )

        if chunk_count > 0:
            doc.status = DocumentStatus.INDEXED
        else:
            doc.status = DocumentStatus.ERROR
            doc.pipeline_error = "No chunks generated — document may have no extractable text"

        db.commit()
        logger.info("Indexed doc %s (chunks=%d)", document_id, chunk_count)

    finally:
        db.close()


def _run_articles(document_id: str) -> None:
    """Generate knowledge articles from document chunks.

    Delegates to the fully-featured generate_articles_for_document task which
    handles DB loading, LLM routing, article storage, and embedding dispatch.
    """
    from app.tasks.article_tasks import generate_articles_for_document

    # Call the task synchronously — __call__ handles bind=True self injection
    result = generate_articles_for_document(document_id)
    logger.info("Articles generated for doc %s: %s", document_id, result.get("status", "unknown"))


def _run_entities(document_id: str) -> None:
    """Extract entities from document for knowledge graph."""
    from sqlalchemy import select

    from app.database import AsyncSessionLocal
    from app.models.document import Document, DocumentChunk
    from app.services.entity_extraction_service import entity_extraction_service

    async def _extract():
        async with AsyncSessionLocal() as db:
            doc_uuid = uuid.UUID(document_id) if isinstance(document_id, str) else document_id
            result = await db.execute(
                select(Document).where(Document.id == doc_uuid)
            )
            doc = result.scalar_one_or_none()
            if not doc:
                raise ValueError(f"Document {document_id} not found")

            chunk_result = await db.execute(
                select(DocumentChunk)
                .where(DocumentChunk.document_id == doc_uuid)
                .order_by(DocumentChunk.chunk_index)
            )
            chunks = chunk_result.scalars().all()

            await entity_extraction_service.extract_entities_from_document(doc, chunks, db)

    asyncio.run(_extract())
    logger.info("Entities extracted for doc %s", document_id)


# ---------------------------------------------------------------------------
# Celery task definitions
# ---------------------------------------------------------------------------


@celery_app.task(
    bind=True,
    name="pipeline.ocr_stage",
    max_retries=3,
    acks_late=True,
    soft_time_limit=300,
    time_limit=360,
)
def ocr_stage(self, document_id: str) -> str:
    return _stage_task(self, document_id, StageEnum.OCR, _run_ocr)


@celery_app.task(
    bind=True,
    name="pipeline.chunk_stage",
    max_retries=2,
    acks_late=True,
    soft_time_limit=120,
    time_limit=180,
)
def chunk_stage(self, document_id: str) -> str:
    return _stage_task(self, document_id, StageEnum.CHUNKED, _run_chunk)


@celery_app.task(
    bind=True,
    name="pipeline.embed_stage",
    max_retries=3,
    acks_late=True,
    soft_time_limit=1800,
    time_limit=1980,
)
def embed_stage(self, document_id: str) -> str:
    return _stage_task(self, document_id, StageEnum.EMBEDDED, _run_embed)


@celery_app.task(
    bind=True,
    name="pipeline.index_stage",
    max_retries=2,
    acks_late=True,
    soft_time_limit=120,
    time_limit=180,
)
def index_stage(self, document_id: str) -> str:
    return _stage_task(self, document_id, StageEnum.INDEXED, _run_index)


@celery_app.task(
    bind=True,
    name="pipeline.article_stage",
    max_retries=3,
    acks_late=True,
    soft_time_limit=600,
    time_limit=720,
)
def article_stage(self, document_id: str) -> str:
    return _stage_task(self, document_id, StageEnum.ARTICLES, _run_articles)


@celery_app.task(
    bind=True,
    name="pipeline.entity_stage",
    max_retries=3,
    acks_late=True,
    soft_time_limit=600,
    time_limit=720,
)
def entity_stage(self, document_id: str) -> str:
    return _stage_task(self, document_id, StageEnum.ENTITIES, _run_entities)


@celery_app.task(name="pipeline.finalize_stage", acks_late=True)
def finalize_stage(document_id: str) -> str:
    """Mark document as fully enriched — terminal stage, no retries."""
    update_stage(document_id, StageEnum.ENRICHED, StageStatus.COMPLETED)

    from app.database import SessionLocal
    from app.models.document import Document

    db = SessionLocal()
    try:
        doc_uuid = uuid.UUID(document_id) if isinstance(document_id, str) else document_id
        doc = db.query(Document).filter(Document.id == doc_uuid).first()
        if doc:
            doc.pipeline_stage = "enriched"
            db.commit()
    finally:
        db.close()

    return document_id
