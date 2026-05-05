"""Pipeline observability endpoint for admin dashboard."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_superuser_or_admin
from app.database import get_db
from app.models.pipeline import PipelineStage, StageEnum, StageStatus

router = APIRouter(prefix="/admin/pipeline", tags=["admin-pipeline"])


@router.get("/status", dependencies=[Depends(require_superuser_or_admin)])
async def pipeline_status(db: AsyncSession = Depends(get_db)) -> dict:
    """Get pipeline status overview — stage counts, queue depths, worker status."""
    # Stage counts
    stages = {}
    for stage in StageEnum:
        result = await db.execute(
            select(PipelineStage.status, func.count())
            .where(PipelineStage.stage == stage)
            .group_by(PipelineStage.status)
        )
        counts = {row[0].value: row[1] for row in result.all()}
        stages[stage.value] = {
            "pending": counts.get("pending", 0),
            "running": counts.get("running", 0),
            "completed": counts.get("completed", 0),
            "failed": counts.get("failed", 0),
            "skipped": counts.get("skipped", 0),
        }

    # Queue depths from Redis
    queues = {}
    try:
        import redis

        from app.core.redis_url import safe_redis_url
        from app.tasks.pipeline_orchestrator import MAX_QUEUE_DEPTH

        r = redis.from_url(safe_redis_url())
        for queue_name in ["pipeline.ocr", "pipeline.chunk", "pipeline.embed",
                           "pipeline.index", "pipeline.articles", "pipeline.entities"]:
            depth = r.llen(queue_name)
            queues[queue_name] = {
                "depth": depth,
                "max": MAX_QUEUE_DEPTH.get(queue_name),
            }
    except Exception:
        queues = {"error": "Could not connect to Redis"}

    # Worker status
    workers = {}
    try:
        from app.celery_app import celery_app
        inspect = celery_app.control.inspect(timeout=5.0)
        stats = inspect.stats() or {}
        for worker_name, worker_stats in stats.items():
            workers[worker_name] = {
                "status": "ok",
                "pool": worker_stats.get("pool", {}).get("implementation", "unknown"),
            }
    except Exception:
        workers = {"error": "Could not inspect workers"}

    return {"stages": stages, "queues": queues, "workers": workers}


@router.post("/retry-failed", dependencies=[Depends(require_superuser_or_admin)])
async def retry_failed_pipeline_stages(
    stage: str | None = Query(None, description="Stage name to retry (e.g. 'ocr', 'chunked'). If omitted, retries all failed stages."),
    limit: int = Query(100, ge=1, le=500, description="Maximum number of failed stages to retry"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Bulk-retry permanently failed pipeline stages.

    Resets FAILED rows to PENDING and re-dispatches their document chains.
    Use this after fixing a root cause (e.g. restarted embed server,
    corrected OCR config) to recover the backlog.
    """
    from app.tasks.pipeline_orchestrator import dispatch_document

    stmt = select(PipelineStage).where(PipelineStage.status == StageStatus.FAILED)
    if stage:
        try:
            stage_enum = StageEnum(stage)
            stmt = stmt.where(PipelineStage.stage == stage_enum)
        except ValueError:
            return {"error": f"Invalid stage '{stage}'. Valid: {[s.value for s in StageEnum]}"}

    stmt = stmt.order_by(PipelineStage.updated_at.desc()).limit(limit)
    result = await db.execute(stmt)
    rows = result.scalars().all()

    import asyncio

    retried = 0
    skipped = 0
    for ps in rows:
        # Only retry if the document itself is not in permanent ERROR
        from app.models.document import Document, DocumentStatus
        doc_result = await db.execute(
            select(Document.status).where(Document.id == ps.document_id)
        )
        doc_status = doc_result.scalar_one_or_none()
        if doc_status == DocumentStatus.ERROR:
            skipped += 1
            continue

        ps.status = StageStatus.PENDING
        ps.attempt = 0
        ps.error_message = None
        ps.started_at = None
        ps.completed_at = None
        await db.commit()

        # Run sync dispatch in threadpool so we don't block the event loop
        dispatch_result = await asyncio.to_thread(
            dispatch_document, str(ps.document_id), from_stage=ps.stage
        )
        if dispatch_result == "dispatched":
            retried += 1
        else:
            skipped += 1

    return {
        "retried": retried,
        "skipped": skipped,
        "stage_filter": stage,
        "limit": limit,
    }
