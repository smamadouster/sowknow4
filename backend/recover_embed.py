import os
os.chdir('/app')

from app.database import SessionLocal
from app.models.pipeline import PipelineStage, StageEnum, StageStatus
from app.tasks.pipeline_orchestrator import dispatch_document
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

db = SessionLocal()
try:
    # 1. Find docs with chunked completed but no embedded row
    chunked_ids = {
        r[0] for r in db.query(PipelineStage.document_id).filter(
            PipelineStage.stage == StageEnum.CHUNKED,
            PipelineStage.status == StageStatus.COMPLETED,
        ).all()
    }
    embedded_ids = {
        r[0] for r in db.query(PipelineStage.document_id).filter(
            PipelineStage.stage == StageEnum.EMBEDDED,
        ).all()
    }
    missing_ids = chunked_ids - embedded_ids
    
    created = 0
    for doc_id in missing_ids:
        row = PipelineStage(
            document_id=doc_id,
            stage=StageEnum.EMBEDDED,
            status=StageStatus.PENDING,
            attempt=0,
            max_attempts=3,
        )
        db.add(row)
        created += 1
    db.commit()
    logger.info(f"Created {created} missing embedded rows")

    # 2. Reset failed embedded rows to PENDING
    failed_embedded = db.query(PipelineStage).filter(
        PipelineStage.stage == StageEnum.EMBEDDED,
        PipelineStage.status == StageStatus.FAILED,
    ).all()
    
    reset_embed = 0
    for ps in failed_embedded:
        ps.status = StageStatus.PENDING
        ps.attempt = 0
        ps.error_message = None
        reset_embed += 1
    db.commit()
    logger.info(f"Reset {reset_embed} failed embedded rows to PENDING")

    # 3. Reset failed entity rows to PENDING
    failed_entities = db.query(PipelineStage).filter(
        PipelineStage.stage == StageEnum.ENTITIES,
        PipelineStage.status == StageStatus.FAILED,
    ).all()
    
    reset_entity = 0
    for ps in failed_entities:
        ps.status = StageStatus.PENDING
        ps.attempt = 0
        ps.error_message = None
        reset_entity += 1
    db.commit()
    logger.info(f"Reset {reset_entity} failed entity rows to PENDING")

    # 4. Dispatch all pending embedded stages
    pending_embedded = db.query(PipelineStage).filter(
        PipelineStage.stage == StageEnum.EMBEDDED,
        PipelineStage.status == StageStatus.PENDING,
    ).all()
    
    dispatched_embed = 0
    backpressure_embed = 0
    for ps in pending_embedded:
        result = dispatch_document(str(ps.document_id), from_stage=StageEnum.EMBEDDED)
        if result == "dispatched":
            dispatched_embed += 1
        elif result.startswith("backpressure"):
            backpressure_embed += 1
            logger.warning(f"Backpressure on embed queue, stopped dispatching")
            break
    logger.info(f"Dispatched {dispatched_embed} embedded tasks (backpressure: {backpressure_embed})")

    # 5. Dispatch all pending entity stages
    pending_entities = db.query(PipelineStage).filter(
        PipelineStage.stage == StageEnum.ENTITIES,
        PipelineStage.status == StageStatus.PENDING,
    ).all()
    
    dispatched_entity = 0
    for ps in pending_entities:
        result = dispatch_document(str(ps.document_id), from_stage=StageEnum.ENTITIES)
        if result == "dispatched":
            dispatched_entity += 1
        elif result.startswith("backpressure"):
            logger.warning(f"Backpressure on entity queue, stopped dispatching")
            break
    logger.info(f"Dispatched {dispatched_entity} entity tasks")

finally:
    db.close()
