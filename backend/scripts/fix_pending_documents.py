#!/usr/bin/env python3
"""
One-time fix for 121 PENDING documents with failed pipeline stages.

Breakdown (from production DB query 2026-05-04):
  - 37 lost files: old storage/documents/... paths that no longer exist
  - 77 image files: .jpg/.png that were incorrectly rejected by fail-fast
                  (text_extractor returned "Unsupported file format" before
                   OCR logic could run). After the code fix these are recoverable.
  - 5 audio/video: .ogg files — permanently unprocessable, should be ERROR.
  - 2 embedded-failed: DB disconnect / embed-server unreachable — transient,
                       reset to PENDING and retry.

Actions:
  1. Mark 42 permanently-failed docs (37 lost + 5 audio/video) as ERROR.
  2. Reset 77 image docs: set OCR stage back to PENDING (attempt=0) so the
     fixed code can OCR them.
  3. Reset 2 embedded-failed docs: set EMBEDDED stage to PENDING (attempt=0)
     and dispatch.
"""

import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

# Add /app to path so 'app' imports work when script runs inside container
SCRIPT_DIR = Path(__file__).resolve().parent
APP_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(APP_DIR))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def main():
    from app.database import SessionLocal
    from app.models.document import Document, DocumentStatus
    from app.models.pipeline import PipelineStage, StageEnum, StageStatus
    from app.tasks.pipeline_orchestrator import dispatch_document

    db = SessionLocal()
    try:
        pending = (
            db.query(Document)
            .filter(Document.status == DocumentStatus.PENDING)
            .all()
        )
        logger.info(f"Total PENDING documents: {len(pending)}")

        marked_error = 0
        reset_image = 0
        reset_embedded = 0
        dispatch_errors = 0

        for doc in pending:
            fp = doc.file_path or ""
            mime = doc.mime_type or ""
            exists = Path(fp).exists() if fp else False

            stages = {
                s.stage: s
                for s in db.query(PipelineStage)
                .filter(PipelineStage.document_id == doc.id)
                .all()
            }

            # ── Category 1: Permanently lost files ──
            if not exists and fp.startswith("storage/"):
                doc.status = DocumentStatus.ERROR
                error_msg = f"File not found: {fp}"
                doc.pipeline_error = error_msg[:500]
                meta = doc.document_metadata or {}
                meta["processing_error"] = error_msg[:500]
                meta["last_error_at"] = datetime.now(UTC).isoformat()
                meta["orphan_fix"] = "marked_error_due_to_missing_file"
                doc.document_metadata = meta
                marked_error += 1
                logger.warning(f"ERROR lost-file   doc={doc.id} fp={fp}")
                continue

            # ── Category 2: Permanently unprocessable audio/video ──
            if mime.startswith("audio/") or mime.startswith("video/"):
                doc.status = DocumentStatus.ERROR
                error_msg = f"Unsupported file format: {mime} — audio/video files cannot be processed as text documents"
                doc.pipeline_error = error_msg[:500]
                meta = doc.document_metadata or {}
                meta["processing_error"] = error_msg[:500]
                meta["last_error_at"] = datetime.now(UTC).isoformat()
                meta["orphan_fix"] = "marked_error_unprocessable_format"
                doc.document_metadata = meta
                marked_error += 1
                logger.warning(f"ERROR unprocessable doc={doc.id} mime={mime}")
                continue

            # ── Category 3: Image files — reset OCR to PENDING ──
            if mime.startswith("image/"):
                ocr_stage = stages.get(StageEnum.OCR)
                if ocr_stage:
                    ocr_stage.status = StageStatus.PENDING
                    ocr_stage.attempt = 0
                    ocr_stage.error_message = None
                    ocr_stage.started_at = None
                doc.pipeline_stage = "ocr"
                reset_image += 1
                logger.info(f"RESET image       doc={doc.id} mime={mime}")
                continue

            # ── Category 4: Embedded-failed — reset and retry ──
            if StageEnum.EMBEDDED in stages and stages[StageEnum.EMBEDDED].status == StageStatus.FAILED:
                emb_stage = stages[StageEnum.EMBEDDED]
                emb_stage.status = StageStatus.PENDING
                emb_stage.attempt = 0
                emb_stage.error_message = None
                emb_stage.started_at = None
                doc.pipeline_stage = "embedded"
                reset_embedded += 1
                logger.info(f"RESET embedded    doc={doc.id}")
                continue

            # Fallback — anything else we didn't categorise
            logger.warning(f"UNKNOWN state     doc={doc.id} mime={mime} fp={fp}")

        db.commit()
        logger.info(
            f"Committed: {marked_error} marked ERROR, {reset_image} images reset, "
            f"{reset_embedded} embedded reset"
        )

        # ── Dispatch reset documents ──
        for doc in pending:
            if doc.status == DocumentStatus.ERROR:
                continue
            try:
                # Determine starting stage
                stages = {
                    s.stage: s
                    for s in db.query(PipelineStage)
                    .filter(PipelineStage.document_id == doc.id)
                    .all()
                }
                from_stage = None
                for stage in StageEnum:
                    if stage in stages and stages[stage].status == StageStatus.PENDING:
                        from_stage = stage
                        break

                if from_stage:
                    result = dispatch_document(str(doc.id), from_stage=from_stage)
                    if result == "dispatched":
                        logger.info(f"DISPATCHED doc={doc.id} from={from_stage.value}")
                    else:
                        logger.warning(f"BACKPRESSURE doc={doc.id}: {result}")
                else:
                    logger.warning(f"NO_PENDING_STAGE doc={doc.id}")
            except Exception as exc:
                dispatch_errors += 1
                logger.error(f"DISPATCH FAILED doc={doc.id}: {exc}")

        logger.info(
            f"Summary: marked_error={marked_error}, reset_image={reset_image}, "
            f"reset_embedded={reset_embedded}, dispatch_errors={dispatch_errors}"
        )

    finally:
        db.close()


if __name__ == "__main__":
    main()
