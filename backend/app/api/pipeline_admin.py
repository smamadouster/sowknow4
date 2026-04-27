"""Pipeline observability endpoint for admin dashboard."""
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_superuser_or_admin
from app.database import get_db
from app.models.pipeline import PipelineStage, StageEnum

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
