#!/usr/bin/env python3
"""
Inject a manual text description into a failed image document and re-queue it.

Usage (inside backend container):
    python /app/scripts/inject_image_description.py <document_id> "<description text>"

Example:
    python /app/scripts/inject_image_description.py \
        3acce116-d78f-4444-8400-7f013d6acbbe \
        "ID photo of employee John Doe, badge number 12345"
"""
import sys
import uuid

sys.path.insert(0, "/app")


def main() -> int:
    if len(sys.argv) < 3:
        print("Usage: inject_image_description.py <document_id> '<description text>'")
        return 1

    document_id = sys.argv[1]
    description = sys.argv[2]

    from app.database import SessionLocal
    from app.models.document import Document, DocumentStatus
    from app.models.pipeline import PipelineStage, StageEnum, StageStatus
    from app.tasks.pipeline_orchestrator import dispatch_document
    from app.tasks.pipeline_tasks import update_stage

    db = SessionLocal()
    try:
        doc_uuid = uuid.UUID(document_id)
        doc = db.query(Document).filter(Document.id == doc_uuid).first()
        if doc is None:
            print(f"ERROR: Document {document_id} not found")
            return 1

        # 1. Write the .txt sidecar
        txt_path = doc.file_path + ".txt"
        with open(txt_path, "w", encoding="utf-8") as fh:
            fh.write(description)
        print(f"Wrote {len(description)} chars to {txt_path}")

        # 2. Reset document status
        doc.status = DocumentStatus.PENDING
        doc.pipeline_stage = "uploaded"
        doc.pipeline_error = None
        doc.pipeline_retry_count = 0
        meta = doc.document_metadata or {}
        meta.pop("processing_error", None)
        meta.pop("extraction_empty", None)
        meta["manual_description_injected"] = True
        meta["injected_at"] = doc.updated_at.isoformat() if doc.updated_at else None
        doc.document_metadata = meta
        db.commit()
        print(f"Reset document {document_id} status to PENDING")

        # 3. Reset pipeline stages for this document
        for stage in StageEnum:
            if stage == StageEnum.UPLOADED:
                continue
            row = (
                db.query(PipelineStage)
                .filter(
                    PipelineStage.document_id == doc_uuid,
                    PipelineStage.stage == stage,
                )
                .first()
            )
            if row:
                db.delete(row)
        db.commit()
        print(f"Cleared downstream pipeline stages for {document_id}")

        # 4. Set UPLOADED to COMPLETED and dispatch from OCR
        update_stage(str(document_id), StageEnum.UPLOADED, StageStatus.COMPLETED)
        result = dispatch_document(str(document_id), from_stage=StageEnum.OCR)
        print(f"Dispatch result: {result}")

        if result == "dispatched":
            doc.status = DocumentStatus.PROCESSING
            doc.pipeline_stage = "ocr"
            db.commit()
            print(f"SUCCESS: Document {document_id} re-queued for processing")
            return 0
        else:
            print(f"WARNING: Dispatch returned '{result}' — document may need manual retry")
            return 2

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
