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


class _PermanentPipelineError(Exception):
    """Raised by work functions when a failure is permanent (unsupported format,
    empty text, zero chunks, etc.).  The stage is marked FAILED immediately
    without retries and the document is parked in ERROR status."""


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

        # Capture pre-mutation state before we overwrite status
        was_running = row.status == StageStatus.RUNNING

        # Apply the status-specific mutations
        row.status = status

        if status == StageStatus.RUNNING:
            same_worker = (
                worker_id is not None
                and row.worker_id == worker_id
            )
            if same_worker:
                # Same Celery task retrying (e.g. _EmbedContinue or self.retry()).
                # Don't burn an attempt — it's continuation, not a new try.
                row.started_at = datetime.now(UTC)
                row.error_message = None
            else:
                # New worker picking up this stage.
                # Don't increment for rapid re-dispatches (<45 s) of a healthy
                # running stage — prevents double-count when a chain link or
                # sweeper re-dispatches quickly.
                already_running = (
                    was_running
                    and row.error_message is None
                    and row.started_at is not None
                )
                recent = (
                    row.started_at is not None
                    and (datetime.now(UTC) - row.started_at).total_seconds() < 45
                )
                if not (already_running and recent):
                    row.attempt = (row.attempt or 0) + 1
                row.started_at = datetime.now(UTC)
                row.error_message = None
                row.worker_id = worker_id

        elif status == StageStatus.COMPLETED:
            row.completed_at = datetime.now(UTC)

        elif status == StageStatus.FAILED:
            if error:
                row.error_message = error

        # For non-RUNNING statuses, still record the worker if provided.
        if status != StageStatus.RUNNING and worker_id is not None:
            row.worker_id = worker_id

        db.commit()
        db.refresh(row)
        return row

    finally:
        if _own_session:
            db.close()


def _sync_document_stage(document_id: str, stage_value: str) -> None:
    """Mirror the current pipeline stage into Document.pipeline_stage."""
    from app.database import SessionLocal
    from app.models.document import Document

    db = SessionLocal()
    try:
        doc_uuid = uuid.UUID(document_id) if isinstance(document_id, str) else document_id
        doc = db.query(Document).filter(Document.id == doc_uuid).first()
        if doc and doc.pipeline_stage != stage_value:
            doc.pipeline_stage = stage_value
            db.commit()
    except Exception:
        logger.exception("Failed to sync pipeline_stage for doc %s", document_id)
    finally:
        db.close()


def _clear_document_error(document_id: str) -> None:
    """If a document was previously marked ERROR but a stage now succeeded, clear it."""
    from app.database import SessionLocal
    from app.models.document import Document, DocumentStatus

    db = SessionLocal()
    try:
        doc_uuid = uuid.UUID(document_id) if isinstance(document_id, str) else document_id
        doc = db.query(Document).filter(Document.id == doc_uuid).first()
        if doc and doc.status == DocumentStatus.ERROR:
            doc.status = DocumentStatus.PROCESSING
            doc.pipeline_error = None
            db.commit()
    except Exception:
        logger.exception("Failed to clear error status for doc %s", document_id)
    finally:
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
    except _PermanentPipelineError as exc:
        error_text = str(exc)
        update_stage(document_id, stage, StageStatus.FAILED, error=error_text)

        # Mirror error to Document so the status API can surface it
        from app.database import SessionLocal
        from app.models.document import Document, DocumentStatus

        doc_uuid = uuid.UUID(document_id) if isinstance(document_id, str) else document_id
        db_err = SessionLocal()
        try:
            doc = db_err.query(Document).filter(Document.id == doc_uuid).first()
            if doc:
                doc.status = DocumentStatus.ERROR
                doc.pipeline_error = error_text[:500]
                meta = doc.document_metadata or {}
                meta["processing_error"] = error_text[:500]
                meta["last_error_at"] = datetime.now(UTC).isoformat()
                doc.document_metadata = meta
                db_err.commit()
        finally:
            db_err.close()

        # Write to DLQ for observability
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
                retry_count=0,
                extra_metadata={"document_id": document_id, "stage": stage.value},
            )
        except Exception:
            logger.exception("DLQ write failed for doc %s stage %s", document_id, stage)

        logger.error(
            "Stage %s permanently failed for doc %s — %s",
            stage, document_id, error_text,
        )
        raise Reject(error_text, requeue=False)
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
            from app.models.document import Document, DocumentStatus

            db = SessionLocal()
            try:
                doc_uuid = uuid.UUID(document_id) if isinstance(document_id, str) else document_id
                doc = db.query(Document).filter(Document.id == doc_uuid).first()
                if doc:
                    doc.status = DocumentStatus.ERROR
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
    _sync_document_stage(document_id, stage.value)
    _clear_document_error(document_id)
    return document_id


# ---------------------------------------------------------------------------
# Work functions
# ---------------------------------------------------------------------------


# Formats that are uploaded but fundamentally unprocessable as text documents
_UNPROCESSABLE_EXTENSIONS = {
    ".mp4", ".avi", ".mov", ".mkv", ".webm",
    ".mp3", ".wav", ".ogg", ".flac", ".aac", ".wma", ".m4a",
}


def _run_ocr(document_id: str) -> None:
    """Extract text via OCR or native parser; write .txt sidecar file."""
    from app.database import SessionLocal
    from app.models.document import Document, DocumentStatus
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
        file_ext = (filename or "").lower().rsplit(".", 1)[-1]
        file_ext = f".{file_ext}" if file_ext else ""

        # Fail fast for known unprocessable formats (video, audio, etc.)
        if file_ext in _UNPROCESSABLE_EXTENSIONS:
            raise _PermanentPipelineError(
                f"Unsupported file format: {file_ext} — video and audio files cannot be processed as text documents"
            )

        # Image files have no native text layer — skip text extractor and go
        # straight to OCR.  Otherwise text_extractor returns "Unsupported file
        # format" which our fail-fast incorrectly treats as permanent.
        is_image = doc.mime_type and doc.mime_type.startswith("image/")
        if is_image:
            extracted_text = ""
            page_count = 0
            extraction_error = ""
        else:
            # Try native text extraction first
            result = asyncio.run(text_extractor.extract_text(file_path, filename))
            extracted_text = result.get("text", "")
            page_count = result.get("pages", 0)
            extraction_error = result.get("error", "")

            # Fail fast when text extractor reports an unsupported format
            if extraction_error and "Unsupported file format" in extraction_error:
                raise _PermanentPipelineError(extraction_error)

            # For office documents (xls, xlt, xlsx, doc, docx, ppt, etc.) OCR is
            # never attempted — a native extraction error is therefore permanent.
            if extraction_error and doc.mime_type and not doc.mime_type.startswith(("image/", "application/pdf")):
                raise _PermanentPipelineError(f"Text extraction failed: {extraction_error}")

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
            logger.warning("Document %s has no text content — failing pipeline", document_id)
            raise _PermanentPipelineError(
                "No text content extracted — document has no extractable text"
            )

        # Detect language for full-text search configuration
        search_lang = detect_text_language(text)

        chunks = chunking_service.chunk_document(text, document_id=document_id)

        if len(chunks) == 0:
            raise _PermanentPipelineError(
                "No chunks generated — chunking produced zero segments"
            )

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
            raise _PermanentPipelineError(error_msg)

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


EMBED_CHUNK_CAP = int(os.getenv("EMBED_CHUNK_CAP", "512"))
GRAPH_CHUNK_CAP = int(os.getenv("GRAPH_CHUNK_CAP", "5"))
CHUNK_COUNT_MAX = int(os.getenv("CHUNK_COUNT_MAX", "75000"))


def _run_embed(document_id: str) -> None:
    """Load chunks and generate embeddings until ALL chunks are embedded.

    Opens a DB session only around active DB work, never during the slow
    HTTP calls to the embed-server.  This prevents exhausting the sync
    connection pool when multiple large-document embed tasks run concurrently.
    """
    from app.database import SessionLocal
    from app.models.document import Document, DocumentChunk
    from app.services.embed_client import embedding_service

    doc_uuid = uuid.UUID(document_id) if isinstance(document_id, str) else document_id

    # Preflight: fail fast if embed-server is unreachable so we retry
    # instead of silently poisoning chunks with zero vectors.
    _embed_ready = False
    for _attempt in range(1, 3):
        if embedding_service.can_embed:
            _embed_ready = True
            break
        time.sleep(3.0)
    if not _embed_ready:
        raise RuntimeError("Embed server is not healthy after 2 attempts")

    # --- One-shot read: document metadata and chunk count ---
    db = SessionLocal()
    try:
        doc = db.query(Document).filter(Document.id == doc_uuid).first()
        if doc is None:
            raise ValueError(f"Document {document_id} not found")

        total_chunks = (
            db.query(DocumentChunk)
            .filter(DocumentChunk.document_id == doc_uuid)
            .count()
        )
        if total_chunks == 0:
            raise _PermanentPipelineError(
                "No chunks exist for embedding — document has no extractable text"
            )

        if total_chunks > CHUNK_COUNT_MAX:
            raise _PermanentPipelineError(
                f"Document has {total_chunks} chunks (limit {CHUNK_COUNT_MAX}) — "
                "quarantined to prevent embed queue starvation"
            )
    finally:
        db.close()

    batch_size = int(os.getenv("EMBED_BATCH_SIZE", "32"))
    total_embedded = 0

    while True:
        # --- Per-window session: fetch, embed, write, commit ---
        db = SessionLocal()
        try:
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
                break  # All chunks embedded

            # Sort by ascending text length so short chunks are batched together.
            # Prevents a single long chunk from padding an entire batch to max
            # sequence length, which multiplies CPU time by 10-50x on the embed
            # server (sentence-transformers pads every text in a batch to the
            # longest token count).
            chunks_sorted = sorted(chunks, key=lambda c: len(c.chunk_text or ""))

            for i in range(0, len(chunks_sorted), batch_size):
                batch = chunks_sorted[i : i + batch_size]
                texts = [c.chunk_text for c in batch]
                # HTTP call happens HERE — DB connection is NOT held
                vectors = embedding_service.encode(texts=texts, batch_size=batch_size)
                for chunk, vec in zip(batch, vectors, strict=False):
                    chunk.embedding_vector = vec

            db.commit()
            total_embedded += len(chunks)
            logger.info(
                "Embedded %d/%d chunks for doc %s (window=%d)",
                total_embedded,
                total_chunks,
                document_id,
                len(chunks),
            )
        finally:
            db.close()

    # --- Finalize: mark document as embedded ---
    db = SessionLocal()
    try:
        doc = db.query(Document).filter(Document.id == doc_uuid).first()
        if doc:
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
            raise _PermanentPipelineError(
                "No chunks generated — document may have no extractable text"
            )

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

    async def embedding_fn(texts: str | list[str]) -> list[float] | list[list[float]]:
        loop = asyncio.get_running_loop()
        if isinstance(texts, list):
            if not texts:
                return []
            return await loop.run_in_executor(
                None, lambda: embedding_service.encode(texts=texts, batch_size=32)
            )
        return await loop.run_in_executor(None, embedding_service.encode_single, texts)

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
    soft_time_limit=600,
    time_limit=900,
)
def ocr_stage(self, document_id: str) -> str:
    return _stage_task(self, document_id, StageEnum.OCR, _run_ocr)


@celery_app.task(
    bind=True,
    name="pipeline.chunk_stage",
    max_retries=2,
    acks_late=True,
    soft_time_limit=600,
    time_limit=900,
)
def chunk_stage(self, document_id: str) -> str:
    return _stage_task(self, document_id, StageEnum.CHUNKED, _run_chunk)


@celery_app.task(
    bind=True,
    name="pipeline.embed_stage",
    max_retries=5,
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
    max_retries=5,
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
    from app.models.document import Document, DocumentStatus

    db = SessionLocal()
    try:
        doc_uuid = uuid.UUID(document_id) if isinstance(document_id, str) else document_id
        doc = db.query(Document).filter(Document.id == doc_uuid).first()
        if doc:
            doc.pipeline_stage = "enriched"
            # Ensure terminal status is consistent — if indexing succeeded the
            # document should be INDEXED, not left in PROCESSING or PENDING.
            if doc.status not in (DocumentStatus.INDEXED, DocumentStatus.ERROR):
                doc.status = DocumentStatus.INDEXED
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
