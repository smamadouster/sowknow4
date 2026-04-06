"""Unified pipeline sweeper — finds stuck documents and resumes or parks them."""
import logging
from datetime import datetime, timedelta, timezone

from app.celery_app import celery_app
from app.models.pipeline import STAGE_RETRY_CONFIG, PipelineStage, StageEnum, StageStatus

logger = logging.getLogger(__name__)


@celery_app.task(name="pipeline.sweeper")
def pipeline_sweeper() -> dict:
    """Find documents stuck at any stage and resume or park them.

    Runs every 5 minutes via Celery Beat.

    1. STUCK RUNNING: stage RUNNING for > 2x its hard_timeout
       - attempts < max: reset to PENDING, re-dispatch chain
       - attempts >= max: mark FAILED

    2. BACKPRESSURED: documents with UPLOADED completed but no OCR stage started
       - Check queue depths, dispatch if capacity available
    """
    from app.database import SessionLocal
    from app.tasks.pipeline_orchestrator import dispatch_document

    db = SessionLocal()
    stuck_resumed = 0
    stuck_failed = 0
    backpressure_dispatched = 0

    try:
        now = datetime.now(timezone.utc)

        # 1. Find stages stuck in RUNNING state
        for stage in StageEnum:
            config = STAGE_RETRY_CONFIG.get(stage)
            if not config:
                continue

            stuck_threshold = now - timedelta(seconds=config["hard_timeout"] * 2)

            stuck_stages = (
                db.query(PipelineStage)
                .filter(
                    PipelineStage.stage == stage,
                    PipelineStage.status == StageStatus.RUNNING,
                    PipelineStage.started_at < stuck_threshold,
                )
                .all()
            )

            for ps in stuck_stages:
                if ps.attempt >= ps.max_attempts:
                    ps.status = StageStatus.FAILED
                    ps.error_message = f"Sweeper: stuck in RUNNING after {ps.attempt} attempts"
                    db.commit()
                    stuck_failed += 1
                    logger.error(f"Sweeper: permanently failed doc={ps.document_id} stage={stage.name}")
                else:
                    ps.status = StageStatus.PENDING
                    ps.error_message = f"Sweeper: reset from stuck RUNNING (attempt {ps.attempt})"
                    db.commit()

                    result = dispatch_document(str(ps.document_id))
                    if result == "dispatched":
                        stuck_resumed += 1
                    # else: deferred, sweeper picks up next run

        # 2. Find documents with UPLOADED completed but no chain dispatched
        uploaded_completed = (
            db.query(PipelineStage)
            .filter(
                PipelineStage.stage == StageEnum.UPLOADED,
                PipelineStage.status == StageStatus.COMPLETED,
            )
            .all()
        )

        for ps in uploaded_completed:
            ocr_stage = (
                db.query(PipelineStage)
                .filter(
                    PipelineStage.document_id == ps.document_id,
                    PipelineStage.stage == StageEnum.OCR,
                )
                .first()
            )

            if ocr_stage is None or ocr_stage.status == StageStatus.PENDING:
                result = dispatch_document(str(ps.document_id))
                if result == "dispatched":
                    backpressure_dispatched += 1

        return {
            "timestamp": now.isoformat(),
            "stuck_resumed": stuck_resumed,
            "stuck_failed": stuck_failed,
            "backpressure_dispatched": backpressure_dispatched,
        }

    except Exception as e:
        logger.error(f"Sweeper error: {e}")
        raise
    finally:
        db.close()
