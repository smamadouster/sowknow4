"""Pipeline orchestrator — builds and dispatches Celery chains with backpressure."""
import logging

import redis
from celery import chain

from app.models.pipeline import StageEnum
from app.tasks.pipeline_tasks import (
    article_stage, chunk_stage, embed_stage, entity_stage,
    finalize_stage, index_stage, ocr_stage,
)

logger = logging.getLogger(__name__)

MAX_QUEUE_DEPTH = {
    "pipeline.embed": 300,
    "pipeline.ocr": 500,
    "pipeline.articles": 300,
}

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
    StageEnum.EMBEDDED: "pipeline.embed",
    StageEnum.ARTICLES: "pipeline.articles",
}


def _check_backpressure(from_stage: StageEnum = StageEnum.OCR) -> str | None:
    """Check the entry queue depth for the given stage.

    Only blocks dispatch if the queue that the *first* task in the chain
    lands on is over its limit.  Downstream queues are not checked —
    tasks will naturally queue up as upstream stages complete.
    """
    if redis_client is None:
        return None
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


def _build_chain(document_id: str, from_stage: StageEnum = StageEnum.OCR):
    """Build a Celery chain starting from the given stage.

    The first task in the chain receives document_id as an argument.
    Subsequent tasks receive it as the return value of the previous task.
    """
    stages = list(StageEnum)
    start_idx = stages.index(from_stage)
    task_stages = [s for s in stages[start_idx:] if s in _STAGE_TASKS]

    if not task_stages:
        return None

    # First task gets document_id explicitly, rest get it from chain
    tasks = [_STAGE_TASKS[task_stages[0]].s(document_id)]
    for s in task_stages[1:]:
        tasks.append(_STAGE_TASKS[s].s())

    return chain(*tasks)


def dispatch_document(document_id: str, from_stage: StageEnum = StageEnum.OCR) -> str:
    """Build and dispatch the processing chain for a document.

    Args:
        document_id: UUID of the document to process.
        from_stage: Stage to start the chain from (default: OCR for new documents).

    Returns:
        'dispatched' on success, 'backpressure:<queue>' if queues are full.
    """
    blocked_queue = _check_backpressure(from_stage)
    if blocked_queue:
        return f"backpressure:{blocked_queue}"

    pipeline = _build_chain(document_id, from_stage)
    if pipeline is None:
        logger.warning(f"No tasks to dispatch for document {document_id} from stage {from_stage}")
        return "dispatched"

    pipeline.apply_async()
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
