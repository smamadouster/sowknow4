"""Pipeline orchestrator — builds and dispatches Celery chains with backpressure."""
import logging

import redis
from celery import chain

from app.tasks.pipeline_tasks import (
    article_stage, chunk_stage, embed_stage, entity_stage,
    finalize_stage, index_stage, ocr_stage,
)

logger = logging.getLogger(__name__)

MAX_QUEUE_DEPTH = {
    "pipeline.embed": 20,
    "pipeline.ocr": 40,
    "pipeline.articles": 30,
}

# Redis client for queue depth checks
try:
    from app.core.redis_url import safe_redis_url
    redis_client = redis.from_url(safe_redis_url())
except Exception:
    redis_client = None


def _check_backpressure() -> str | None:
    """Check all queue depths. Returns queue name if over limit, None if OK."""
    if redis_client is None:
        return None
    for queue_name, max_depth in MAX_QUEUE_DEPTH.items():
        depth = redis_client.llen(queue_name)
        if depth > max_depth:
            logger.warning(f"Backpressure on {queue_name}: depth={depth} max={max_depth}")
            return queue_name
    return None


def dispatch_document(document_id: str) -> str:
    """Build and dispatch the processing chain for a document.
    Returns 'dispatched' on success, 'backpressure:<queue>' if queues are full.
    """
    blocked_queue = _check_backpressure()
    if blocked_queue:
        return f"backpressure:{blocked_queue}"

    pipeline = chain(
        ocr_stage.s(document_id),
        chunk_stage.s(),
        embed_stage.s(),
        index_stage.s(),
        article_stage.s(),
        entity_stage.s(),
        finalize_stage.s(),
    )
    pipeline.apply_async()
    logger.info(f"Pipeline chain dispatched for document {document_id}")
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
