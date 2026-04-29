"""Unified pipeline sweeper — finds stuck documents and resumes or parks them."""
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_
from sqlalchemy.orm import aliased

from app.celery_app import celery_app
from app.models.pipeline import STAGE_RETRY_CONFIG, PipelineStage, StageEnum, StageStatus

logger = logging.getLogger(__name__)

# Stages that have a corresponding Celery task (UPLOADED is just a marker)
_DISPATCHABLE_STAGES = [s for s in StageEnum if s != StageEnum.UPLOADED]


@celery_app.task(name="pipeline.sweeper")
def pipeline_sweeper() -> dict:
    """Find documents stuck at any stage and resume or park them.

    Runs every 5 minutes via Celery Beat.

    1. STUCK RUNNING: stage RUNNING for > 2x its hard_timeout
       - attempts < max: reset to PENDING, re-dispatch chain
       - attempts >= max: mark FAILED

    2. STALLED MID-PIPELINE: stage N completed but stage N+1 is pending
       with no running task — re-dispatch from stage N+1.

    3. BACKPRESSURED NEW: UPLOADED completed but OCR not started.
    """
    from app.database import SessionLocal
    from app.tasks.pipeline_orchestrator import dispatch_document

    db = SessionLocal()
    stuck_resumed = 0
    stuck_failed = 0
    stalled_dispatched = 0

    try:
        now = datetime.now(UTC)

        # ── 1. Find stages stuck in RUNNING state ──
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

                    # Mirror the error to Document so the status API can see it
                    from app.models.document import Document

                    doc = db.query(Document).filter(Document.id == ps.document_id).first()
                    if doc:
                        error_text = ps.error_message
                        doc.pipeline_error = error_text[:500]
                        meta = doc.document_metadata or {}
                        meta["processing_error"] = error_text[:500]
                        meta["last_error_at"] = datetime.now(UTC).isoformat()
                        doc.document_metadata = meta
                        db.commit()
                else:
                    ps.status = StageStatus.PENDING
                    ps.error_message = f"Sweeper: reset from stuck RUNNING (attempt {ps.attempt})"
                    db.commit()

                    result = dispatch_document(str(ps.document_id), from_stage=stage)
                    if result == "dispatched":
                        stuck_resumed += 1

        # ── 2. Find documents stalled between stages ──
        # For each pair (stage_N completed, stage_N+1 pending), dispatch from N+1.
        # This catches broken chains, lost tasks, and backfill gaps.
        stages = list(StageEnum)
        for i, completed_stage in enumerate(stages[:-1]):
            next_stage = stages[i + 1]
            if next_stage not in _DISPATCHABLE_STAGES:
                continue

            # Subquery: docs where completed_stage is COMPLETED
            # and next_stage is PENDING (not running/failed/completed)
            stalled = (
                db.query(PipelineStage)
                .filter(
                    PipelineStage.stage == next_stage,
                    PipelineStage.status == StageStatus.PENDING,
                    PipelineStage.document_id.in_(
                        db.query(PipelineStage.document_id).filter(
                            and_(
                                PipelineStage.stage == completed_stage,
                                PipelineStage.status == StageStatus.COMPLETED,
                            )
                        )
                    ),
                )
                .limit(500)  # temporarily raised for backlog catchup
                .all()
            )

            for ps in stalled:
                result = dispatch_document(str(ps.document_id), from_stage=next_stage)
                if result == "dispatched":
                    stalled_dispatched += 1
                elif result.startswith("backpressure"):
                    # Stop dispatching this stage pair — queue is full
                    break

        # ── 2.5 Missing intermediate rows: completed stage N but no row at all for stage N+1 ──
        missing_intermediate_dispatched = 0
        stages = list(StageEnum)
        for i, completed_stage in enumerate(stages[:-1]):
            next_stage = stages[i + 1]
            if next_stage not in _DISPATCHABLE_STAGES:
                continue

            NextAlias = aliased(PipelineStage)
            missing_rows = (
                db.query(PipelineStage.document_id)
                .filter(
                    PipelineStage.stage == completed_stage,
                    PipelineStage.status == StageStatus.COMPLETED,
                )
                .filter(
                    ~exists().where(
                        and_(
                            NextAlias.stage == next_stage,
                            NextAlias.document_id == PipelineStage.document_id,
                        )
                    ).correlate(PipelineStage)
                )
                .limit(500)
                .all()
            )

            for (doc_id,) in missing_rows:
                row = PipelineStage(
                    document_id=doc_id,
                    stage=next_stage,
                    status=StageStatus.PENDING,
                    attempt=0,
                    max_attempts=STAGE_RETRY_CONFIG.get(next_stage, {}).get("max_attempts", 3),
                )
                db.add(row)
                db.commit()

                result = dispatch_document(str(doc_id), from_stage=next_stage)
                if result == "dispatched":
                    missing_intermediate_dispatched += 1
                elif result.startswith("backpressure"):
                    break

        # ── 3. Clean up premature ENRICHED rows (entities not done yet) ──
        premature_deleted = 0
        premature_enriched = (
            db.query(PipelineStage)
            .filter(
                PipelineStage.stage == StageEnum.ENRICHED,
                PipelineStage.status == StageStatus.PENDING,
            )
            .all()
        )
        for ps in premature_enriched:
            entity_row = (
                db.query(PipelineStage)
                .filter(
                    PipelineStage.document_id == ps.document_id,
                    PipelineStage.stage == StageEnum.ENTITIES,
                )
                .first()
            )
            if not entity_row or entity_row.status != StageStatus.COMPLETED:
                db.delete(ps)
                premature_deleted += 1
        if premature_deleted:
            db.commit()
            logger.info(f"Sweeper deleted {premature_deleted} premature ENRICHED rows")

        # ── 4. Missing terminal rows: ENTITIES completed but no ENRICHED row ──
        missing_enriched_dispatched = 0
        from sqlalchemy import exists
        from sqlalchemy.orm import aliased

        EnrichedAlias = aliased(PipelineStage)
        missing_enriched = (
            db.query(PipelineStage.document_id)
            .filter(
                PipelineStage.stage == StageEnum.ENTITIES,
                PipelineStage.status == StageStatus.COMPLETED,
            )
            .filter(
                ~exists().where(
                    and_(
                        EnrichedAlias.stage == StageEnum.ENRICHED,
                        EnrichedAlias.document_id == PipelineStage.document_id,
                    )
                ).correlate(PipelineStage)
            )
            .limit(500)
            .all()
        )

        for (doc_id,) in missing_enriched:
            # Create the missing row so the dashboard tracks it
            row = PipelineStage(
                document_id=doc_id,
                stage=StageEnum.ENRICHED,
                status=StageStatus.PENDING,
                attempt=0,
                max_attempts=3,
            )
            db.add(row)
            db.commit()

            result = dispatch_document(str(doc_id), from_stage=StageEnum.ENRICHED)
            if result == "dispatched":
                missing_enriched_dispatched += 1
            elif result.startswith("backpressure"):
                break

        # ── 4. Backpressured new uploads: UPLOADED completed but OCR not started ──
        backpressure_dispatched = 0
        uploaded_done = (
            db.query(PipelineStage)
            .filter(
                PipelineStage.stage == StageEnum.UPLOADED,
                PipelineStage.status == StageStatus.COMPLETED,
            )
            .all()
        )

        for ps in uploaded_done:
            ocr_exists = (
                db.query(PipelineStage)
                .filter(
                    PipelineStage.document_id == ps.document_id,
                    PipelineStage.stage == StageEnum.OCR,
                )
                .first()
            )
            if ocr_exists is None:
                result = dispatch_document(str(ps.document_id))
                if result == "dispatched":
                    backpressure_dispatched += 1
                elif result.startswith("backpressure"):
                    break

        metrics = {
            "timestamp": now.isoformat(),
            "stuck_resumed": stuck_resumed,
            "stuck_failed": stuck_failed,
            "stalled_dispatched": stalled_dispatched,
            "missing_intermediate_dispatched": missing_intermediate_dispatched,
            "premature_deleted": premature_deleted,
            "missing_enriched_dispatched": missing_enriched_dispatched,
            "backpressure_dispatched": backpressure_dispatched,
        }
        logger.info(f"Sweeper completed: {metrics}")
        return metrics

    except Exception as e:
        logger.error(f"Sweeper error: {e}")
        raise
    finally:
        db.close()
