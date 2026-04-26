"""
Recover documents whose entity stage failed (mostly OOM/crashes before fixes).

Resets the 'entities' pipeline stage from FAILED → PENDING and re-dispatches
from StageEnum.ENTITIES so the celery-entities worker can reprocess them.

Run inside the backend container:
    python /app/scripts/recover_failed_entities.py [--dry-run]
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal
from app.models.document import Document
from app.models.pipeline import PipelineStage, StageEnum, StageStatus
from app.tasks.pipeline_orchestrator import dispatch_document


def recover(dry_run: bool = True):
    db = SessionLocal()
    try:
        failed_rows = (
            db.query(PipelineStage)
            .filter(
                PipelineStage.stage == StageEnum.ENTITIES,
                PipelineStage.status == StageStatus.FAILED,
            )
            .all()
        )

        print(f"Found {len(failed_rows)} failed entity stages")
        if not failed_rows:
            print("Nothing to recover.")
            return

        # Show breakdown by error message
        error_counts = {}
        for row in failed_rows:
            msg = (row.error_message or "(no error)").split("\n")[0][:80]
            error_counts[msg] = error_counts.get(msg, 0) + 1

        print("\nError breakdown:")
        for msg, cnt in sorted(error_counts.items(), key=lambda x: -x[1]):
            print(f"  {cnt}: {msg}")

        if dry_run:
            print("\nDry run — no changes made. Re-run without --dry-run to execute.")
            return

        doc_ids = []
        for row in failed_rows:
            doc_id = str(row.document_id)
            doc_ids.append(doc_id)

            # Reset stage row
            row.status = StageStatus.PENDING
            row.attempt = 0
            row.error_message = None
            row.started_at = None
            row.completed_at = None
            row.worker_id = None

            # Clean Document-level error flags
            doc = db.query(Document).filter(Document.id == row.document_id).first()
            if doc:
                doc.pipeline_error = None
                if doc.document_metadata and isinstance(doc.document_metadata, dict):
                    doc.document_metadata.pop("processing_error", None)
                    doc.document_metadata.pop("last_error_at", None)

        db.commit()
        print(f"\nReset {len(doc_ids)} entity stages to PENDING")

        # Re-dispatch from ENTITIES stage
        dispatched = 0
        backpressured = 0
        for doc_id in doc_ids:
            result = dispatch_document(doc_id, from_stage=StageEnum.ENTITIES)
            if result.startswith("backpressure"):
                backpressured += 1
                print(f"  BACKPRESSURE for {doc_id}")
            else:
                dispatched += 1

        print(f"\nDispatched {dispatched} documents, backpressured {backpressured}")

    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Recover failed entity stages")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Preview changes without applying")
    parser.add_argument("--no-dry-run", action="store_false", dest="dry_run", help="Apply changes")
    args = parser.parse_args()
    recover(dry_run=args.dry_run)
