"""
Recover documents poisoned with zero-vector embeddings.

This script finds all chunks whose embedding_vector is exactly zero,
nulls them out, resets the pipeline stage to PENDING, and re-dispatches
from the EMBEDDED stage so the embed-server will regenerate real vectors.

Run inside the backend container:
    python /app/scripts/recover_zero_vectors.py [--dry-run]
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text

from app.database import SessionLocal
from app.models.document import Document
from app.models.pipeline import PipelineStage, StageEnum, StageStatus
from app.tasks.pipeline_orchestrator import dispatch_document


def recover(dry_run: bool = True):
    db = SessionLocal()
    try:
        # 1. Find all documents with zero-vector chunks
        # pgvector stores vectors like [0.0,0.0,...] without spaces
        zero_docs = db.execute(
            text("""
                SELECT DISTINCT document_id
                FROM document_chunks
                WHERE embedding_vector IS NOT NULL
                  AND embedding_vector::text LIKE '[0,0,0,0,0,0,0,0,0,0%'
            """)
        ).fetchall()

        doc_ids = [str(row.document_id) for row in zero_docs]
        print(f"Found {len(doc_ids)} documents with zero-vector chunks")

        if not doc_ids:
            print("Nothing to recover.")
            return

        # 2. Also include the 2 genuinely failed embedding docs
        failed_rows = db.execute(
            text("""
                SELECT document_id
                FROM pipeline_stages
                WHERE stage = 'embedded' AND status = 'failed'
            """)
        ).fetchall()
        for row in failed_rows:
            sid = str(row.document_id)
            if sid not in doc_ids:
                doc_ids.append(sid)
                print(f"Including failed doc {sid}")

        # 3. Per-document stats before recovery
        print("\nDocuments to recover (top 20 by zero chunks):")
        stats = db.execute(
            text("""
                SELECT
                    d.id,
                    d.filename,
                    d.chunk_count,
                    COUNT(dc.id) AS zero_chunks
                FROM documents d
                JOIN document_chunks dc ON d.id = dc.document_id
                WHERE dc.embedding_vector IS NOT NULL
                  AND dc.embedding_vector::text LIKE '[0,0,0,0,0,0,0,0,0,0%'
                GROUP BY d.id, d.filename, d.chunk_count
                ORDER BY zero_chunks DESC
                LIMIT 20
            """)
        ).fetchall()

        for row in stats:
            pct = row.zero_chunks / row.chunk_count * 100 if row.chunk_count else 0
            print(f"  {row.id}: {row.filename or '(no name)'} — {row.zero_chunks}/{row.chunk_count} zero chunks ({pct:.0f}%)")
        if len(doc_ids) > 20:
            print(f"  ... and {len(doc_ids) - 20} more")

        if dry_run:
            print("\nDry run — no changes made. Re-run without --dry-run to execute.")
            return

        # 4. Null out zero vectors
        result = db.execute(
            text("""
                UPDATE document_chunks
                SET embedding_vector = NULL
                WHERE embedding_vector IS NOT NULL
                  AND embedding_vector::text LIKE '[0,0,0,0,0,0,0,0,0,0%'
            """)
        )
        db.commit()
        print(f"\nNulled out {result.rowcount} zero-vector chunks")

        # 5. Reset pipeline_stages for affected docs
        for doc_id in doc_ids:
            stage_row = (
                db.query(PipelineStage)
                .filter(
                    PipelineStage.document_id == doc_id,
                    PipelineStage.stage == StageEnum.EMBEDDED,
                )
                .first()
            )
            if stage_row:
                stage_row.status = StageStatus.PENDING
                stage_row.attempt = 0
                stage_row.error_message = None
                stage_row.started_at = None
                stage_row.completed_at = None
                stage_row.worker_id = None
            else:
                # Create a PENDING row if missing
                db.add(
                    PipelineStage(
                        document_id=doc_id,
                        stage=StageEnum.EMBEDDED,
                        status=StageStatus.PENDING,
                        attempt=0,
                        max_attempts=3,
                    )
                )

            # Also fix Document-level flags
            doc = db.query(Document).filter(Document.id == doc_id).first()
            if doc:
                doc.embedding_generated = False
                doc.pipeline_error = None
                if doc.document_metadata and isinstance(doc.document_metadata, dict):
                    doc.document_metadata.pop("processing_error", None)
                    doc.document_metadata.pop("last_error_at", None)

        db.commit()
        print(f"Reset pipeline stage for {len(doc_ids)} documents")

        # 6. Re-dispatch from EMBEDDED stage
        dispatched = 0
        backpressured = 0
        for doc_id in doc_ids:
            result = dispatch_document(doc_id, from_stage=StageEnum.EMBEDDED)
            if result.startswith("backpressure"):
                backpressured += 1
                print(f"  BACKPRESSURE for {doc_id}")
            else:
                dispatched += 1

        print(f"\nDispatched {dispatched} documents, backpressured {backpressured}")

    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Recover zero-vector embeddings")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Preview changes without applying")
    parser.add_argument("--no-dry-run", action="store_false", dest="dry_run", help="Apply changes")
    args = parser.parse_args()
    recover(dry_run=args.dry_run)
