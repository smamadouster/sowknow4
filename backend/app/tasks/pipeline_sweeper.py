"""Unified pipeline sweeper — finds stuck documents and resumes or parks them."""
import logging
import os
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, exists, func
from sqlalchemy.orm import aliased

from app.celery_app import celery_app
from app.models.pipeline import STAGE_RETRY_CONFIG, PipelineStage, StageEnum, StageStatus

logger = logging.getLogger(__name__)

# Stages that have a corresponding Celery task (UPLOADED is just a marker)
_DISPATCHABLE_STAGES = [s for s in StageEnum if s != StageEnum.UPLOADED]

# Safety cap: maximum total dispatches per sweeper run to prevent queue flooding
# when a large backlog exists (e.g., after an outage or batch upload).
_MAX_DISPATCHES_PER_RUN = int(os.getenv("SWEEPER_MAX_DISPATCH", "1000"))

# Queue depth thresholds for embed server protection.
# If embed queue exceeds this, skip stalled/missing dispatches that would land there.
_EMBED_QUEUE_SOFT_LIMIT = int(os.getenv("SWEEPER_EMBED_QUEUE_LIMIT", "250"))

# Poison-pill threshold: if a stage has been attempted this many times,
# mark it permanently failed instead of re-dispatching.
_POISON_PILL_ATTEMPTS = int(os.getenv("SWEEPER_POISON_PILL_ATTEMPTS", "5"))

# Permanent error patterns — these should NEVER be retried because they will
# always fail with the same error.
_PERMANENT_ERROR_PATTERNS = [
    "too many chunks",
    "document has",
    "chunks (limit",
    "unsupported file format",
    "no text content extracted",
    "video and audio files cannot be processed",
    "quarantined to prevent embed queue starvation",
    "quarantined poison pill",
    "no chunks exist for embedding",
    "no chunks generated",
]

# Queue depth alert thresholds — if any queue exceeds these for multiple
# consecutive sweeper runs, something is wrong (workers down, backpressure, etc.)
_QUEUE_ALERT_THRESHOLDS = {
    "pipeline.ocr": 50,
    "pipeline.chunk": 50,
    "pipeline.embed": 100,
    "pipeline.index": 50,
    "pipeline.articles": 50,
    "pipeline.entities": 50,
}

# How many consecutive sweeper runs a queue must be over threshold before
# we raise a critical alert.
_QUEUE_ALERT_CONSECUTIVE = int(os.getenv("SWEEPER_QUEUE_ALERT_CONSECUTIVE", "3"))


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

    # Distributed lock: prevent concurrent sweeper runs (e.g. manual trigger
    # overlapping with Celery Beat, or multiple beat instances after a deploy).
    _redis = None
    try:
        from app.core.redis_url import safe_redis_url
        import redis
        _redis = redis.from_url(safe_redis_url())
        lock_acquired = _redis.set(
            "pipeline:sweeper:lock",
            datetime.now(UTC).isoformat(),
            nx=True,
            ex=300,  # 5 minutes — longer than any sweeper run should take
        )
        if not lock_acquired:
            logger.info("Sweeper lock already held — skipping this run")
            return {"status": "skipped", "reason": "lock_already_held"}
    except Exception:
        # If Redis is unreachable, continue anyway — better to risk a double-run
        # than to stop recovery entirely.
        pass

    db = SessionLocal()
    stuck_resumed = 0
    stuck_failed = 0
    stalled_dispatched = 0
    total_dispatched = 0

    # Quick queue-depth check for embed-server protection
    embed_queue_depth = 0
    try:
        if _redis is None:
            from app.core.redis_url import safe_redis_url
            import redis
            _redis = redis.from_url(safe_redis_url())
        embed_queue_depth = _redis.llen("pipeline.embed")
    except Exception:
        pass

    embed_backpressure = embed_queue_depth > _EMBED_QUEUE_SOFT_LIMIT
    if embed_backpressure:
        logger.warning(
            "Sweeper embed backpressure active: pipeline.embed depth=%d > limit=%d",
            embed_queue_depth, _EMBED_QUEUE_SOFT_LIMIT,
        )

    try:
        now = datetime.now(UTC)

        # Helper: skip documents that are permanently in ERROR — no point
        # resuming a broken pipeline for a doc that already failed.
        def _skip_if_error(doc_id) -> bool:
            from app.models.document import Document, DocumentStatus
            doc = db.query(Document).filter(Document.id == doc_id).first()
            return doc is not None and doc.status == DocumentStatus.ERROR

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
                .limit(500)
                .all()
            )

            for ps in stuck_stages:
                if stage == StageEnum.EMBEDDED:
                    # Embed limits scale with chunk count
                    # (pipeline_orchestrator._get_embed_time_limits) — re-check
                    # per document so a large, healthy embed is not reset mid-run.
                    from app.models.document import Document as _Doc
                    from app.tasks.pipeline_orchestrator import _get_embed_time_limits

                    _doc = db.query(_Doc).filter(_Doc.id == ps.document_id).first()
                    _chunks = (_doc.chunk_count or 0) if _doc else 0
                    _, _dyn_hard = _get_embed_time_limits(_chunks)
                    if ps.started_at is not None and (
                        now - ps.started_at
                    ).total_seconds() < _dyn_hard * 2:
                        continue
                if _skip_if_error(ps.document_id):
                    continue
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
                        doc.pipeline_stage = "failed"
                        meta = doc.document_metadata or {}
                        meta["processing_error"] = error_text[:500]
                        meta["last_error_at"] = datetime.now(UTC).isoformat()
                        doc.document_metadata = meta
                        db.commit()
                elif ps.attempt >= _POISON_PILL_ATTEMPTS:
                    # Poison-pill quarantine: a stage that has been retried many
                    # times but is still stuck is unlikely to succeed.  Park it
                    # permanently to prevent queue flooding.
                    ps.status = StageStatus.FAILED
                    ps.error_message = (
                        f"Sweeper: quarantined poison pill (attempt {ps.attempt} >= {_POISON_PILL_ATTEMPTS})"
                    )
                    db.commit()
                    stuck_failed += 1
                    logger.error(
                        "Sweeper: quarantined poison-pill doc=%s stage=%s attempts=%d",
                        ps.document_id, stage.name, ps.attempt,
                    )

                    from app.models.document import Document, DocumentStatus

                    doc = db.query(Document).filter(Document.id == ps.document_id).first()
                    if doc:
                        doc.status = DocumentStatus.ERROR
                        doc.pipeline_stage = "failed"
                        doc.pipeline_error = ps.error_message[:500]
                        meta = doc.document_metadata or {}
                        meta["processing_error"] = ps.error_message[:500]
                        meta["last_error_at"] = datetime.now(UTC).isoformat()
                        doc.document_metadata = meta
                        db.commit()
                else:
                    # CRITICAL: do NOT redispatch stuck embed stages when the embed
                    # queue is already backlogged — that creates a cascading flood.
                    if embed_backpressure and stage == StageEnum.EMBEDDED:
                        logger.info(
                            "Sweeper skipping stuck EMBEDDED stage doc=%s due to embed backpressure (depth=%d)",
                            ps.document_id, embed_queue_depth,
                        )
                        continue

                    ps.status = StageStatus.PENDING
                    ps.error_message = f"Sweeper: reset from stuck RUNNING (attempt {ps.attempt})"
                    db.commit()

                    # Mirror the reset to Document.status so the UI and reprocess
                    # endpoint don't disagree about whether the doc is active.
                    from app.models.document import Document, DocumentStatus

                    doc = db.query(Document).filter(Document.id == ps.document_id).first()
                    if doc and doc.status == DocumentStatus.PROCESSING:
                        doc.status = DocumentStatus.PENDING
                        db.commit()

                    result = dispatch_document(str(ps.document_id), from_stage=stage, force=True)
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

            # Skip dispatches that would land on embed queue if it's already high
            if embed_backpressure and next_stage in (StageEnum.CHUNKED, StageEnum.EMBEDDED):
                logger.info("Sweeper skipping stalled %s dispatches due to embed backpressure", next_stage.name)
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
                .limit(500)
                .all()
            )

            for ps in stalled:
                if total_dispatched >= _MAX_DISPATCHES_PER_RUN:
                    logger.warning("Sweeper reached MAX_DISPATCHES_PER_RUN=%d — stopping", _MAX_DISPATCHES_PER_RUN)
                    break
                if _skip_if_error(ps.document_id):
                    continue
                result = dispatch_document(str(ps.document_id), from_stage=next_stage, force=True)
                if result == "dispatched":
                    stalled_dispatched += 1
                    total_dispatched += 1
                elif result.startswith("backpressure"):
                    # Stop dispatching this stage pair — queue is full
                    break
            if total_dispatched >= _MAX_DISPATCHES_PER_RUN:
                break

        # ── 2.5 Missing intermediate rows: completed stage N but no row at all for stage N+1 ──
        missing_intermediate_dispatched = 0
        stages = list(StageEnum)
        for i, completed_stage in enumerate(stages[:-1]):
            next_stage = stages[i + 1]
            if next_stage not in _DISPATCHABLE_STAGES:
                continue

            # CRITICAL: skip missing-row creation for embed/chunk when embed
            # backpressure is active.  Creating the row and then failing to
            # dispatch leaves a PENDING row that the next sweeper run will
            # treat as "stalled" and re-dispatch, causing an infinite loop.
            if embed_backpressure and next_stage in (StageEnum.CHUNKED, StageEnum.EMBEDDED):
                logger.info(
                    "Sweeper skipping missing-intermediate %s creation due to embed backpressure",
                    next_stage.name,
                )
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
                if total_dispatched >= _MAX_DISPATCHES_PER_RUN:
                    logger.warning("Sweeper reached MAX_DISPATCHES_PER_RUN=%d — stopping", _MAX_DISPATCHES_PER_RUN)
                    break
                if _skip_if_error(doc_id):
                    continue
                row = PipelineStage(
                    document_id=doc_id,
                    stage=next_stage,
                    status=StageStatus.PENDING,
                    attempt=0,
                    max_attempts=STAGE_RETRY_CONFIG.get(next_stage, {}).get("max_attempts", 3),
                )
                db.add(row)
                db.commit()

                result = dispatch_document(str(doc_id), from_stage=next_stage, force=True)
                if result == "dispatched":
                    missing_intermediate_dispatched += 1
                    total_dispatched += 1
                elif result.startswith("backpressure"):
                    break
            if total_dispatched >= _MAX_DISPATCHES_PER_RUN:
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
            if _skip_if_error(ps.document_id):
                continue
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
            if total_dispatched >= _MAX_DISPATCHES_PER_RUN:
                logger.warning("Sweeper reached MAX_DISPATCHES_PER_RUN=%d — stopping", _MAX_DISPATCHES_PER_RUN)
                break
            if _skip_if_error(doc_id):
                continue
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

            result = dispatch_document(str(doc_id), from_stage=StageEnum.ENRICHED, force=True)
            if result == "dispatched":
                missing_enriched_dispatched += 1
                total_dispatched += 1
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
            .limit(500)
            .all()
        )

        for ps in uploaded_done:
            if total_dispatched >= _MAX_DISPATCHES_PER_RUN:
                logger.warning("Sweeper reached MAX_DISPATCHES_PER_RUN=%d — stopping", _MAX_DISPATCHES_PER_RUN)
                break
            if _skip_if_error(ps.document_id):
                continue
            ocr_exists = (
                db.query(PipelineStage)
                .filter(
                    PipelineStage.document_id == ps.document_id,
                    PipelineStage.stage == StageEnum.OCR,
                )
                .first()
            )
            if ocr_exists is None:
                result = dispatch_document(str(ps.document_id), force=True)
                if result == "dispatched":
                    backpressure_dispatched += 1
                    total_dispatched += 1
                elif result.startswith("backpressure"):
                    break

        # ── 5. Auto-retry FAILED stages that may have failed transiently ──
        # Some failures are transient (missing dependency, temporary network
        # error, worker crash). If attempt < max_attempts and the error does
        # NOT match a known permanent pattern, reset to PENDING and re-dispatch.
        failed_retried = 0
        failed_permanent = 0
        failed_stages = (
            db.query(PipelineStage)
            .filter(PipelineStage.status == StageStatus.FAILED)
            .limit(500)
            .all()
        )

        for ps in failed_stages:
            if _skip_if_error(ps.document_id):
                continue
            if ps.attempt >= ps.max_attempts:
                failed_permanent += 1
                continue

            error_lower = (ps.error_message or "").lower()
            is_permanent = any(p in error_lower for p in _PERMANENT_ERROR_PATTERNS)
            if is_permanent:
                failed_permanent += 1
                continue

            # Transient failure — retry with backoff based on attempt count
            # Wait at least 5 minutes × attempt before retrying
            min_age = timedelta(minutes=5 * (ps.attempt + 1))
            if ps.updated_at and (now - ps.updated_at) < min_age:
                continue

            # Skip embed retries during backpressure
            if embed_backpressure and ps.stage == StageEnum.EMBEDDED:
                continue

            ps.status = StageStatus.PENDING
            ps.error_message = f"Sweeper: auto-retrying after transient failure (attempt {ps.attempt})"
            db.commit()

            result = dispatch_document(str(ps.document_id), from_stage=ps.stage, force=True)
            if result == "dispatched":
                failed_retried += 1
                total_dispatched += 1
                logger.info(
                    "Sweeper auto-retried doc=%s stage=%s attempt=%d",
                    ps.document_id, ps.stage.name, ps.attempt,
                )
            elif result.startswith("backpressure"):
                break

        if failed_retried:
            logger.info("Sweeper auto-retried %d failed stages", failed_retried)

        # Collect depths for all pipeline queues (needed for alerting + metrics)
        queue_depths = {}
        if _redis is not None:
            for q in [
                "pipeline.ocr", "pipeline.chunk", "pipeline.embed",
                "pipeline.index", "pipeline.articles", "pipeline.entities",
                "celery", "scheduled",
            ]:
                try:
                    queue_depths[q] = _redis.llen(q)
                except Exception:
                    queue_depths[q] = -1

        # ── 6. Queue depth alerting ──
        if _redis is not None:
            for q, threshold in _QUEUE_ALERT_THRESHOLDS.items():
                depth = queue_depths.get(q, 0)
                if depth > threshold:
                    alert_key = f"pipeline:alert:queue_depth:{q}"
                    try:
                        consecutive = int(_redis.get(alert_key) or 0)
                    except Exception:
                        consecutive = 0
                    consecutive += 1
                    try:
                        _redis.setex(alert_key, 900, str(consecutive))
                    except Exception:
                        pass
                    if consecutive >= _QUEUE_ALERT_CONSECUTIVE:
                        logger.error(
                            "CRITICAL: Queue %s depth=%d exceeds threshold=%d for %d consecutive sweeper runs. "
                            "Workers may be down or overwhelmed.",
                            q, depth, threshold, consecutive,
                        )
                else:
                    alert_key = f"pipeline:alert:queue_depth:{q}"
                    try:
                        _redis.delete(alert_key)
                    except Exception:
                        pass

        # ── 7. Corrupted pipeline data: upstream stages completed but 0 chunks ──
        # This catches backfilled/migrated documents that have fake COMPLETED
        # pipeline rows without actual chunk data, or documents that failed
        # permanently but never had their status updated.
        corrupted_fixed = 0
        try:
            from app.models.document import Document, DocumentChunk, DocumentStatus

            corrupted = (
                db.query(Document)
                .outerjoin(DocumentChunk, DocumentChunk.document_id == Document.id)
                .filter(
                    Document.status.in_([DocumentStatus.PENDING, DocumentStatus.PROCESSING]),
                )
                .group_by(Document.id)
                .having(
                    func.count(DocumentChunk.id) == 0,
                )
                .limit(500)
                .all()
            )

            for doc in corrupted:
                # Verify that at least one upstream stage claims to be completed
                has_completed_upstream = (
                    db.query(PipelineStage)
                    .filter(
                        PipelineStage.document_id == doc.id,
                        PipelineStage.stage.in_([StageEnum.OCR, StageEnum.CHUNKED]),
                        PipelineStage.status == StageStatus.COMPLETED,
                    )
                    .first()
                )
                if has_completed_upstream:
                    doc.status = DocumentStatus.ERROR
                    error_msg = "No chunks generated — document has no extractable text"
                    doc.pipeline_error = error_msg
                    meta = doc.document_metadata or {}
                    meta["processing_error"] = error_msg
                    meta["last_error_at"] = datetime.now(UTC).isoformat()
                    doc.document_metadata = meta
                    db.commit()
                    corrupted_fixed += 1
                    logger.info(
                        "Sweeper fixed corrupted doc %s — 0 chunks but upstream stages completed",
                        doc.id,
                    )
        except Exception:
            logger.exception("Sweeper corrupted-data check failed")

        metrics = {
            "timestamp": now.isoformat(),
            "stuck_resumed": stuck_resumed,
            "stuck_failed": stuck_failed,
            "stalled_dispatched": stalled_dispatched,
            "missing_intermediate_dispatched": missing_intermediate_dispatched,
            "premature_deleted": premature_deleted,
            "missing_enriched_dispatched": missing_enriched_dispatched,
            "backpressure_dispatched": backpressure_dispatched,
            "failed_retried": failed_retried,
            "failed_permanent": failed_permanent,
            "corrupted_fixed": corrupted_fixed,
            "total_dispatched": total_dispatched,
            "embed_queue_depth": embed_queue_depth,
            "embed_backpressure": embed_backpressure,
            "max_dispatches_per_run": _MAX_DISPATCHES_PER_RUN,
            "queue_depths": queue_depths,
        }
        logger.info(f"Sweeper completed: {metrics}")
        return metrics

    except Exception as e:
        logger.error(f"Sweeper error: {e}")
        raise
    finally:
        db.close()
        # Release the distributed lock so the next scheduled run can proceed.
        try:
            if _redis is not None:
                _redis.delete("pipeline:sweeper:lock")
        except Exception:
            pass
