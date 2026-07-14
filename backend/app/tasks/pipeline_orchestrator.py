"""Pipeline orchestrator — builds and dispatches Celery chains with backpressure."""
import logging
import uuid

import redis
from celery import chain

from app.models.pipeline import StageEnum
from app.tasks.pipeline_tasks import (
    article_stage,
    chunk_stage,
    embed_stage,
    entity_stage,
    finalize_stage,
    index_stage,
    ocr_stage,
)

logger = logging.getLogger(__name__)

MAX_QUEUE_DEPTH = {
    "pipeline.embed": 300,
    "pipeline.ocr": 500,
    "pipeline.articles": 300,
    "pipeline.entities": 200,
    "pipeline.chunk": 300,
    "pipeline.index": 300,
}

# Global safety limit: if total pipeline queue depth exceeds this, stop all dispatching.
# Prevents system-wide queue flooding during batch uploads or recovery from outage.
MAX_TOTAL_QUEUE_DEPTH = 1000

_PIPELINE_QUEUES = ["pipeline.embed", "pipeline.ocr", "pipeline.chunk", "pipeline.index",
                    "pipeline.articles", "pipeline.entities"]

# Mapping from StageEnum to Celery task (for building partial chains)
_STAGE_TASKS = {
    StageEnum.OCR: ocr_stage,
    StageEnum.CHUNKED: chunk_stage,
    StageEnum.EMBEDDED: embed_stage,
    StageEnum.INDEXED: index_stage,
    StageEnum.ARTICLES: article_stage,
    StageEnum.ENTITIES: entity_stage,
    StageEnum.ENRICHED: finalize_stage,
}

# Redis client for queue depth checks
try:
    from app.core.redis_url import safe_redis_url
    redis_client = redis.from_url(safe_redis_url())
except Exception:
    redis_client = None


# Map from StageEnum to the Redis queue name the task lands on
_STAGE_QUEUE = {
    StageEnum.OCR: "pipeline.ocr",
    StageEnum.CHUNKED: "pipeline.chunk",
    StageEnum.EMBEDDED: "pipeline.embed",
    StageEnum.INDEXED: "pipeline.index",
    StageEnum.ARTICLES: "pipeline.articles",
    StageEnum.ENTITIES: "pipeline.entities",
}


def _total_queue_depth() -> int:
    """Sum the depths of all pipeline queues."""
    if redis_client is None:
        return 0
    total = 0
    for q in _PIPELINE_QUEUES:
        try:
            total += redis_client.llen(q)
        except Exception:
            pass
    return total


def _check_backpressure(from_stage: StageEnum = StageEnum.OCR) -> str | None:
    """Check the entry queue depth for the given stage AND global queue depth.

    Blocks dispatch if either the entry queue or the total pipeline queue depth
    exceeds its limit.  Downstream queues are not checked — tasks will naturally
    queue up as upstream stages complete.
    """
    if redis_client is None:
        return None

    # Global backpressure first
    total_depth = _total_queue_depth()
    if total_depth > MAX_TOTAL_QUEUE_DEPTH:
        logger.warning(
            "Global backpressure: total pipeline queue depth=%d > max=%d",
            total_depth, MAX_TOTAL_QUEUE_DEPTH,
        )
        return "global"

    queue_name = _STAGE_QUEUE.get(from_stage)
    if queue_name is None:
        return None
    max_depth = MAX_QUEUE_DEPTH.get(queue_name)
    if max_depth is None:
        return None
    depth = redis_client.llen(queue_name)
    if depth > max_depth:
        logger.warning(f"Backpressure on {queue_name}: depth={depth} max={max_depth}")
        return queue_name
    return None


def _get_embed_time_limits(chunk_count: int) -> tuple[int, int]:
    """Calculate Celery time limits for the embed stage based on chunk count.

    Base: 33 min hard / 30 min soft for <= 1000 chunks.
    Additional 10 min hard / 9 min soft per 1000 chunks beyond that.
    Cap at 2 hours to prevent runaway tasks.
    """
    base_hard = 1980  # 33 minutes
    base_soft = 1800  # 30 minutes
    extra = max(0, chunk_count - 1000)
    extra_minutes = (extra // 1000) + (1 if extra % 1000 else 0)
    hard = min(base_hard + extra_minutes * 600, 7200)  # cap at 2h
    soft = min(base_soft + extra_minutes * 540, 6600)  # cap at 1h50m
    return soft, hard


def _build_chain(document_id: str, from_stage: StageEnum = StageEnum.OCR):
    """Build a Celery chain starting from the given stage.

    The first task in the chain receives document_id as an argument.
    Subsequent tasks receive it as the return value of the previous task.

    For large documents starting at the EMBEDDED stage, the embed task gets
    a dynamically-calculated longer timeout so it is not killed mid-flight.
    """
    stages = list(StageEnum)
    start_idx = stages.index(from_stage)
    task_stages = [s for s in stages[start_idx:] if s in _STAGE_TASKS]

    if not task_stages:
        return None

    first_stage = task_stages[0]
    first_task = _STAGE_TASKS[first_stage].s(document_id)

    # Dynamic timeout for large documents at embed stage
    if first_stage == StageEnum.EMBEDDED:
        from app.database import SessionLocal
        from app.models.document import Document

        db = SessionLocal()
        try:
            doc = db.query(Document).filter(Document.id == document_id).first()
            if doc and doc.chunk_count and doc.chunk_count > 1000:
                soft, hard = _get_embed_time_limits(doc.chunk_count)
                first_task = first_task.set(
                    soft_time_limit=soft,
                    time_limit=hard,
                )
                logger.info(
                    "Doc %s has %d chunks — embed timeout extended to %ds",
                    document_id, doc.chunk_count, hard,
                )
        except Exception:
            logger.exception("Failed to calculate embed timeout for doc %s", document_id)
        finally:
            db.close()

    tasks = [first_task]
    for s in task_stages[1:]:
        tasks.append(_STAGE_TASKS[s].s())

    return chain(*tasks)


def _is_stage_inflight(document_id: str, stage: StageEnum) -> bool:
    """Check if a stage already has an active task in flight.

    Uses the PipelineStage row: RUNNING with a recent started_at means a worker
    is currently processing it (or will retry shortly).  PENDING with a very
    recent updated_at means it was just queued.
    """
    from app.database import SessionLocal
    from app.models.pipeline import PipelineStage, StageStatus
    from datetime import UTC, datetime, timedelta

    db = SessionLocal()
    try:
        row = (
            db.query(PipelineStage)
            .filter(
                PipelineStage.document_id == document_id,
                PipelineStage.stage == stage,
            )
            .first()
        )
        if row is None:
            return False

        now = datetime.now(UTC)

        # RUNNING + started_at within hard_timeout → worker is alive or retry imminent
        if row.status == StageStatus.RUNNING and row.started_at is not None:
            from app.models.pipeline import STAGE_RETRY_CONFIG
            cfg = STAGE_RETRY_CONFIG.get(stage, {})
            hard_timeout = cfg.get("hard_timeout", 600)
            if (now - row.started_at).total_seconds() < hard_timeout:
                return True

        # PENDING + updated_at within 60s → just queued by sweeper or upload
        if row.status == StageStatus.PENDING and row.updated_at is not None:
            if (now - row.updated_at).total_seconds() < 60:
                return True

        return False
    except Exception:
        # SECURITY: fail closed. If we cannot verify the stage is not already
        # in flight, do not dispatch another task.
        logger.exception("Error checking inflight status for doc %s stage %s", document_id, stage)
        return True
    finally:
        db.close()


def dispatch_document(document_id: str, from_stage: StageEnum = StageEnum.OCR) -> str:
    """Build and dispatch the processing chain for a document.

    Args:
        document_id: UUID of the document to process.
        from_stage: Stage to start the chain from (default: OCR for new documents).

    Returns:
        'dispatched' on success, 'backpressure:<queue>' if queues are full,
        'inflight' if the stage is already active.
    """
    blocked_queue = _check_backpressure(from_stage)
    if blocked_queue:
        return f"backpressure:{blocked_queue}"

    if _is_stage_inflight(document_id, from_stage):
        logger.info(
            "Skipping dispatch for document %s stage %s — already inflight",
            document_id, from_stage.name,
        )
        return "inflight"

    # Don't dispatch a document that is globally in ERROR unless someone
    # explicitly cleared its pipeline stages (indicating a manual retry).
    try:
        from app.database import SessionLocal
        from app.models.document import Document, DocumentStatus

        db_check = SessionLocal()
        try:
            doc_uuid = uuid.UUID(document_id) if isinstance(document_id, str) else document_id
            doc = db_check.query(Document).filter(Document.id == doc_uuid).first()
            if doc and doc.status == DocumentStatus.ERROR:
                logger.warning(
                    "Refusing to dispatch document %s — status is ERROR. "
                    "Clear status manually before retrying.",
                    document_id,
                )
                return "error: document status is ERROR"
        finally:
            db_check.close()
    except Exception:
        # SECURITY: fail closed. If we cannot verify the document status,
        # do not dispatch the pipeline.
        logger.exception("Error checking document status for dispatch %s", document_id)
        return "error: could not verify document status"

    pipeline = _build_chain(document_id, from_stage)
    if pipeline is None:
        logger.warning(f"No tasks to dispatch for document {document_id} from stage {from_stage}")
        return "dispatched"

    # Size-based routing: warn when large documents enter the pipeline
    if from_stage in (StageEnum.OCR, StageEnum.CHUNKED, StageEnum.EMBEDDED):
        from app.database import SessionLocal
        from app.models.document import Document

        db = SessionLocal()
        try:
            doc = db.query(Document).filter(Document.id == document_id).first()
            if doc and doc.chunk_count and doc.chunk_count > 1000:
                logger.warning(
                    "Large document %s (%d chunks) entering pipeline at stage %s",
                    document_id, doc.chunk_count, from_stage.name,
                )
        except Exception:
            pass
        finally:
            db.close()

    pipeline.apply_async()

    # Keep Document.pipeline_stage in sync so the UI and status API don't lie
    try:
        from app.database import SessionLocal
        from app.models.document import Document

        db_sync = SessionLocal()
        try:
            doc_uuid = uuid.UUID(document_id) if isinstance(document_id, str) else document_id
            doc = db_sync.query(Document).filter(Document.id == doc_uuid).first()
            if doc and doc.pipeline_stage != from_stage.value:
                doc.pipeline_stage = from_stage.value
                db_sync.commit()
        finally:
            db_sync.close()
    except Exception:
        logger.exception("Failed to sync pipeline_stage in dispatch for doc %s", document_id)

    logger.info(f"Pipeline chain dispatched for document {document_id} from stage {from_stage.name}")
    return "dispatched"


def dispatch_batch(document_ids: list[str]) -> dict:
    """Dispatch multiple documents, stopping on backpressure."""
    dispatched = 0
    for i, doc_id in enumerate(document_ids):
        result = dispatch_document(doc_id)
        if result.startswith("backpressure"):
            remaining = len(document_ids) - i
            return {"dispatched": dispatched, "backpressured": remaining}
        dispatched += 1
    return {"dispatched": dispatched, "backpressured": 0}
