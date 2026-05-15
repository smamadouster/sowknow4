#!/usr/bin/env python3
"""Bulk reprocess all .xls files stuck due to the xlrd bug."""
import sys
sys.path.insert(0, "/app")

from app.database import SessionLocal
from app.models.document import Document, DocumentStatus
from app.models.pipeline import PipelineStage, StageEnum, StageStatus
from app.tasks.pipeline_orchestrator import dispatch_document
from app.tasks.pipeline_tasks import update_stage
from sqlalchemy import text
import os

# Errors that are likely recoverable now that xlrd is installed
RECOVERABLE_ERRORS = [
    "No chunks generated",
    "No text content extracted",
    "Embed server unreachable",
]

# Errors that will NOT recover (permanent)
SKIP_ERRORS = [
    "Too many chunks",
    "video and audio files cannot be processed",
    "unsupported file format",
]

db = SessionLocal()
dispatched = 0
skipped = 0
failed = 0
try:
    rows = db.execute(text("""
        SELECT id::text as doc_id, original_filename, file_path, pipeline_error
        FROM sowknow.documents
        WHERE filename ~* '\.(xls|xlt)$'
          AND status = 'error'
        ORDER BY created_at DESC
    """))
    docs = list(rows.mappings())

    for d in docs:
        err = d["pipeline_error"] or ""

        # Skip permanently oversized files
        if any(se in err for se in SKIP_ERRORS):
            print(f"SKIP (permanent)  | {d['original_filename']:50} | {err}")
            skipped += 1
            continue

        # Only recover files with known recoverable errors
        if not any(re in err for re in RECOVERABLE_ERRORS):
            print(f"SKIP (unknown)    | {d['original_filename']:50} | {err}")
            skipped += 1
            continue

        doc_id = d["doc_id"]
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if not doc:
            continue

        # Remove empty sidecar if present
        txt_path = doc.file_path + ".txt" if doc.file_path else None
        if txt_path and os.path.exists(txt_path):
            try:
                os.remove(txt_path)
            except Exception:
                pass

        # Reset document
        doc.status = DocumentStatus.PENDING
        doc.pipeline_stage = "uploaded"
        doc.pipeline_error = None
        doc.pipeline_retry_count = 0
        meta = doc.document_metadata or {}
        meta.pop("processing_error", None)
        meta.pop("extraction_empty", None)
        doc.document_metadata = meta
        db.commit()

        # Clear downstream pipeline stages
        for stage in StageEnum:
            if stage == StageEnum.UPLOADED:
                continue
            row = (
                db.query(PipelineStage)
                .filter(
                    PipelineStage.document_id == doc_id,
                    PipelineStage.stage == stage,
                )
                .first()
            )
            if row:
                db.delete(row)
        db.commit()

        # Dispatch
        update_stage(doc_id, StageEnum.UPLOADED, StageStatus.COMPLETED)
        result = dispatch_document(doc_id, from_stage=StageEnum.OCR)

        if result == "dispatched":
            doc.status = DocumentStatus.PROCESSING
            doc.pipeline_stage = "ocr"
            db.commit()
            print(f"DISPATCHED        | {d['original_filename']:50}")
            dispatched += 1
        elif result.startswith("backpressure"):
            print(f"BACKPRESSURE      | {d['original_filename']:50} | {result}")
            skipped += 1
            break  # Stop when backpressure kicks in
        else:
            print(f"FAILED            | {d['original_filename']:50} | {result}")
            failed += 1

    print(f"\n=== Summary ===")
    print(f"Dispatched: {dispatched}")
    print(f"Skipped:    {skipped}")
    print(f"Failed:     {failed}")

finally:
    db.close()
