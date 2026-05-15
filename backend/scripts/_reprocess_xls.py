#!/usr/bin/env python3
import sys
sys.path.insert(0, "/app")

from app.database import SessionLocal
from app.models.document import Document, DocumentStatus
from app.models.pipeline import PipelineStage, StageEnum, StageStatus
from app.tasks.pipeline_orchestrator import dispatch_document
from app.tasks.pipeline_tasks import update_stage
import os

db = SessionLocal()
try:
    doc_id = "47cbb5ad-3c7c-4e13-99f4-f76d166c22a7"
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        print("Document not found")
        sys.exit(1)

    print(f"Found: {doc.original_filename} (status={doc.status}, stage={doc.pipeline_stage})")

    # Remove empty sidecar if it exists
    txt_path = doc.file_path + ".txt" if doc.file_path else None
    if txt_path and os.path.exists(txt_path):
        os.remove(txt_path)
        print(f"Removed empty sidecar: {txt_path}")

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
    print("Reset document status to PENDING")

    # Clear all downstream pipeline stages
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
    print("Cleared downstream pipeline stages")

    # Set uploaded completed and dispatch from OCR
    update_stage(doc_id, StageEnum.UPLOADED, StageStatus.COMPLETED)
    result = dispatch_document(doc_id, from_stage=StageEnum.OCR)
    print(f"Dispatch result: {result}")

    if result == "dispatched":
        doc.status = DocumentStatus.PROCESSING
        doc.pipeline_stage = "ocr"
        db.commit()
        print("SUCCESS: Document re-queued for processing")
    else:
        print(f"WARNING: Dispatch returned '{result}'")

finally:
    db.close()
