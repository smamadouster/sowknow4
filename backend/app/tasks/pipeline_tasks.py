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
import time
import uuid
from datetime import UTC, datetime

from celery.exceptions import Reject

from app.celery_app import celery_app
from app.models.pipeline import STAGE_RETRY_CONFIG, PipelineStage, StageEnum, StageStatus

logger = logging.getLogger(__name__)


class _EmbedContinue(Exception):
    """Raised by _run_embed when more chunks remain and the task was re-queued."""

    def __init__(self, remaining: int):
        self.remaining = remaining


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
    from app.models.pipeline import PipelineStage, StageStatus

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
            row.started_at = datetime.now(UTC)
            row.error_message = None  # clear previous error on retry

        elif status == StageStatus.COMPLETED:
            row.completed_at = datetime.now(UTC)

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
    except _EmbedContinue as cont:
        # Partial embed — retry this chain link so the next stage does NOT
        # run until all chunks are fully embedded.  The retry countdown
        # gives other documents a turn between windows.
        logger.info(
            "Stage %s partial for doc %s — %d chunks remaining, retrying chain link",
            stage, document_id, cont.remaining,
        )
        raise self.retry(countdown=10)
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
            error_text = str(exc)
            update_stage(document_id, stage, StageStatus.FAILED, error=error_text)

            # Also write to Document so the status API can surface the error
            # without needing to query PipelineStage.
            from app.database import SessionLocal
            from app.models.document import Document

            db = SessionLocal()
            try:
                doc_uuid = uuid.UUID(document_id) if isinstance(document_id, str) else document_id
                doc = db.query(Document).filter(Document.id == doc_uuid).first()
                if doc:
                    doc.pipeline_error = error_text[:500]
                    meta = doc.document_metadata or {}
                    meta["processing_error"] = error_text[:500]
                    meta["last_error_at"] = datetime.now(UTC).isoformat()
                    doc.document_metadata = meta
                    db.commit()
            finally:
                db.close()

            logger.error(
                "Stage %s exhausted %d attempts for doc %s — rejecting task",
                stage,
                max_attempts,
                document_id,
            )

            # Write to Dead Letter Queue for observability
            try:
                import traceback as _tb
                from app.services.dlq_service import DeadLetterQueueService

                DeadLetterQueueService.store_failed_task(
                    task_name=self.name,
                    task_id=self.request.id or "unknown",
                    args=(document_id,),
                    kwargs={},
                    exception=exc,
                    traceback_str=_tb.format_exc(),
                    retry_count=attempts,
                    extra_metadata={"document_id": document_id, "stage": stage.value},
                )
            except Exception:
                logger.exception("DLQ write failed for doc %s stage %s", document_id, stage)

            raise Reject(error_text, requeue=False)

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

            if doc.mime_type == "application/pdf":
                import os as _os
                import tempfile

                images = asyncio.run(text_extractor.extract_images_from_pdf(file_path))
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
                ocr_result = asyncio.run(ocr_service._extract_full(file_path))
                extracted_text = ocr_result.get("text", "")

            doc.ocr_processed = True

        # Write sidecar .txt file — but preserve existing content if extraction
        # returns empty (prevents destroying previously-extracted text on reprocess).
        txt_path = file_path + ".txt"
        existing_text = ""
        if os.path.exists(txt_path):
            try:
                with open(txt_path, encoding="utf-8") as fh:
                    existing_text = fh.read()
            except Exception:
                pass

        if extracted_text or not existing_text:
            with open(txt_path, "w", encoding="utf-8") as fh:
                fh.write(extracted_text or "")
        else:
            logger.warning(
                "OCR returned empty for doc %s but sidecar %.0f bytes exists — preserving",
                document_id, len(existing_text)
            )

        if not extracted_text:
            logger.warning(
                "No text extracted for doc %s (%s). Document will proceed but may produce 0 chunks.",
                document_id,
                doc.mime_type,
            )
            meta = doc.document_metadata or {}
            meta["extraction_empty"] = True
            doc.document_metadata = meta

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

        with open(txt_path, encoding="utf-8") as fh:
            text = fh.read()

        if not text.strip():
            logger.warning("Document %s has no text content — skipping chunking", document_id)
            doc.chunk_count = 0
            db.commit()
            return

        # Detect language for full-text search configuration
        search_lang = detect_text_language(text)

        chunks = chunking_service.chunk_document(text, document_id=document_id)

        if len(chunks) > CHUNK_COUNT_MAX:
            error_msg = f"Too many chunks ({len(chunks)} > {CHUNK_COUNT_MAX}) — document rejected to prevent queue starvation"
            logger.error("Doc %s: %s", document_id, error_msg)
            from app.models.document import DocumentStatus

            doc.status = DocumentStatus.ERROR
            doc.pipeline_error = error_msg
            meta = doc.document_metadata or {}
            meta["processing_error"] = error_msg
            meta["last_error_at"] = datetime.now(UTC).isoformat()
            doc.document_metadata = meta
            db.commit()
            raise RuntimeError(error_msg)

        # Delete existing chunks to allow re-runs
        db.query(DocumentChunk).filter(DocumentChunk.document_id == doc_uuid).delete()

        for chunk_data in chunks:
            # Defensive: strip NUL bytes that PostgreSQL rejects
            clean_text = chunk_data["text"].replace("\x00", "")
            chunk = DocumentChunk(
                document_id=doc_uuid,
                chunk_index=chunk_data["index"],
                chunk_text=clean_text,
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


EMBED_CHUNK_CAP = int(os.getenv("EMBED_CHUNK_CAP", "64"))
GRAPH_CHUNK_CAP = int(os.getenv("GRAPH_CHUNK_CAP", "20"))
CHUNK_COUNT_MAX = int(os.getenv("CHUNK_COUNT_MAX", "5000"))


def _run_embed(document_id: str) -> None:
    """Load chunks, generate embeddings in batches of 32, capped at EMBED_CHUNK_CAP per pass.

    For large documents the work is committed in windows of EMBED_CHUNK_CAP chunks so
    that each embed task finishes quickly and doesn't starve the queue.
    """
    from app.database import SessionLocal
    from app.models.document import Document, DocumentChunk
    from app.services.embed_client import embedding_service

    db = SessionLocal()
    try:
        doc_uuid = uuid.UUID(document_id) if isinstance(document_id, str) else document_id
        doc = db.query(Document).filter(Document.id == doc_uuid).first()
        if doc is None:
            raise ValueError(f"Document {document_id} not found")

        # Preflight: fail fast if embed-server is unreachable so we retry
        # instead of silently poisoning chunks with zero vectors.
        # Retry a few times to survive the ~5s uvicorn worker restart window.
        _embed_ready = False
        for _attempt in range(1, 3):
            if embedding_service.can_embed:
                _embed_ready = True
                break
            time.sleep(3.0)
        if not _embed_ready:
            raise RuntimeError("Embed server is not healthy after 2 attempts")

        # Only fetch chunks that still need embeddings
        chunks = (
            db.query(DocumentChunk)
            .filter(
                DocumentChunk.document_id == doc_uuid,
                DocumentChunk.embedding_vector.is_(None),
            )
            .order_by(DocumentChunk.chunk_index)
            .limit(EMBED_CHUNK_CAP)
            .all()
        )

        if not chunks:
            # All chunks already embedded (or none exist)
            total = (
                db.query(DocumentChunk)
                .filter(DocumentChunk.document_id == doc_uuid)
                .count()
            )
            if total == 0:
                logger.warning("No chunks for doc %s — skipping embedding", document_id)
                doc.embedding_generated = False
            else:
                doc.embedding_generated = True
            db.commit()
            return

        batch_size = 8
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i : i + batch_size]
            texts = [c.chunk_text for c in batch]
            vectors = embedding_service.encode(texts=texts, batch_size=batch_size)
            for chunk, vec in zip(batch, vectors, strict=False):
                chunk.embedding_vector = vec

        db.commit()
        logger.info("Embedded %d chunks for doc %s", len(chunks), document_id)

        # Check if more un-embedded chunks remain
        remaining = (
            db.query(DocumentChunk)
            .filter(
                DocumentChunk.document_id == doc_uuid,
                DocumentChunk.embedding_vector.is_(None),
            )
            .count()
        )
        if remaining > 0:
            logger.info(
                "Doc %s has %d more chunks to embed — retrying chain link", document_id, remaining
            )
            # Signal _stage_task to retry this chain link so the next stage
            # (index_stage) does NOT run until all chunks are embedded.
            raise _EmbedContinue(remaining)

        doc.embedding_generated = True
        db.commit()
        logger.info("All chunks embedded for doc %s", document_id)

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
            error_msg = "No chunks generated — document may have no extractable text"
            doc.status = DocumentStatus.ERROR
            doc.pipeline_error = error_msg
            doc.document_metadata = {
                **(doc.document_metadata or {}),
                "processing_error": error_msg,
            }

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
    """Extract entities from document for knowledge graph.

    Uses sync SessionLocal for all DB operations (safe in Celery workers)
    and only runs the LLM call via asyncio.run() to avoid event-loop conflicts
    with the module-level async engine/connection pool.

    Also runs the new graph extraction pipeline (asyncpg, separate pool) which
    populates graph_nodes / graph_edges / entity_synonyms via spaCy NER +
    financial rules + LLM relationship inference.
    """
    from app.database import SessionLocal
    from app.models.document import Document, DocumentChunk
    from app.services.entity_extraction_service import entity_extraction_service

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

        # Step 1: LLM-based entity extraction (sync DB, async LLM call only)
        entity_extraction_service.extract_entities_from_document_sync(doc, chunks, db)

        # Step 2: Graph extraction — capped to GRAPH_CHUNK_CAP chunks to keep
        # task runtime reasonable. Large documents can generate thousands of
        # edges and starve the queue.
        bucket = doc.bucket.value if hasattr(doc.bucket, "value") else str(doc.bucket)
        graph_chunks = chunks[:GRAPH_CHUNK_CAP]
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(
                    asyncio.wait_for(
                        _graph_extract_document(document_id, graph_chunks, bucket),
                        timeout=120,  # cap graph extraction to prevent 391s tasks
                    )
                )
            finally:
                loop.close()
        except asyncio.TimeoutError:
            logger.warning("Graph extraction timed out for doc %s (cap=120s); skipping", document_id)
        except Exception as e:
            logger.warning("Graph extraction failed for doc %s: %s", document_id, e)

    finally:
        db.close()

    # Force garbage collection after heavy NLP + graph work to release memory
    # in Celery prefork workers before the next task.
    import gc
    gc.collect()

    logger.info("Entities extracted for doc %s", document_id)


async def _graph_extract_document(document_id: str, chunks, bucket: str) -> None:
    """Run the knowledge-graph extraction pipeline over all chunks of a document.

    Uses a dedicated asyncpg pool (separate from the SQLAlchemy pool) so it
    is safe to call via asyncio.run() from a Celery task.
    """
    from app.services.embed_client import embedding_service
    from app.services.knowledge_graph.extraction import EntityExtractor
    from app.services.knowledge_graph.pool import get_graph_pool, close_graph_pool

    pool = await get_graph_pool()

    async def embedding_fn(text: str) -> list[float]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, embedding_service.encode_single, text)

    extractor = EntityExtractor(
        pool=pool,
        embedding_fn=embedding_fn,
        llm_fn=None,  # LLM relationship extraction is opt-in — enable once spaCy NER is validated
    )

    total = {"nodes_created": 0, "edges_created": 0, "nodes_merged": 0}
    try:
        for chunk in chunks:
            stats = await extractor.process_chunk(
                chunk_text=chunk.chunk_text,
                document_id=document_id,
                chunk_id=str(chunk.id),
                bucket=bucket,
            )
            for k in total:
                total[k] += stats.get(k, 0)
    finally:
        # Explicitly drop the extractor reference so spaCy docs/tensors can be GC'd
        del extractor
        # Close the dedicated asyncpg pool to release DB connections per-task
        await close_graph_pool()

    logger.info(
        "Graph extraction done for doc %s — nodes_created=%d merged=%d edges=%d",
        document_id, total["nodes_created"], total["nodes_merged"], total["edges_created"],
    )


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
    max_retries=None,
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


def _run_finalize(document_id: str) -> None:
    """Mark document as fully enriched — terminal stage work function."""
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


@celery_app.task(
    bind=True,
    name="pipeline.finalize_stage",
    max_retries=3,
    acks_late=True,
    soft_time_limit=120,
    time_limit=180,
)
def finalize_stage(self, document_id: str) -> str:
    """Mark document as fully enriched — terminal stage with retries."""
    return _stage_task(self, document_id, StageEnum.ENRICHED, _run_finalize)
