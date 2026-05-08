#!/usr/bin/env python3
"""
Pipeline recovery script — fixes corrupted documents, stale pipeline_stage values,
and re-dispatches stalled work.

Run inside the backend container:
    docker exec -it sowknow4-backend python /app/scripts/fix_pipeline.py

Or from the project root (if backend code is importable):
    cd backend && python scripts/fix_pipeline.py
"""

import os
import sys
import uuid

# Ensure backend is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal
from app.models.document import Document, DocumentChunk, DocumentStatus
from app.models.pipeline import PipelineStage, StageEnum, StageStatus
from app.tasks.pipeline_orchestrator import dispatch_document


def _fix_stale_pipeline_stages() -> int:
    """Sync Document.pipeline_stage with the latest completed pipeline stage."""
    db = SessionLocal()
    fixed = 0
    try:
        # Find docs whose pipeline_stage doesn't match their furthest completed stage
        stages = list(StageEnum)
        for doc in db.query(Document).all():
            rows = (
                db.query(PipelineStage)
                .filter(PipelineStage.document_id == doc.id)
                .order_by(PipelineStage.updated_at.desc())
                .all()
            )
            if not rows:
                continue

            # Find the most advanced completed stage
            target_stage = None
            for s in reversed(stages):
                for r in rows:
                    if r.stage == s and r.status == StageStatus.COMPLETED:
                        target_stage = s.value
                        break
                if target_stage:
                    break

            if target_stage and doc.pipeline_stage != target_stage:
                if doc.status == DocumentStatus.ERROR:
                    # Don't overwrite failed docs
                    continue
                doc.pipeline_stage = target_stage
                fixed += 1

        db.commit()
        print(f"  Fixed {fixed} stale pipeline_stage values")
        return fixed
    finally:
        db.close()


def _fix_corrupted_document(doc_id: str) -> bool:
    """
    Reset a corrupted document (e.g. chunk_count > 0 but 0 actual chunks,
    or all stages completed except one with impossible error).
    Deletes pipeline stages, resets status, removes sidecar, re-dispatches.
    """
    db = SessionLocal()
    try:
        doc_uuid = uuid.UUID(doc_id) if isinstance(doc_id, str) else doc_id
        doc = db.query(Document).filter(Document.id == doc_uuid).first()
        if not doc:
            print(f"  Document {doc_id} not found")
            return False

        print(f"  Fixing corrupted document: {doc.original_filename} ({doc_id})")
        print(f"    Current: chunk_count={doc.chunk_count}, status={doc.status}")

        # Delete all pipeline stages for this doc
        deleted = (
            db.query(PipelineStage)
            .filter(PipelineStage.document_id == doc_uuid)
            .delete(synchronize_session=False)
        )
        print(f"    Deleted {deleted} pipeline stage rows")

        # Delete actual chunks if any exist
        chunk_deleted = (
            db.query(DocumentChunk)
            .filter(DocumentChunk.document_id == doc_uuid)
            .delete(synchronize_session=False)
        )
        print(f"    Deleted {chunk_deleted} chunk rows")

        # Reset document state
        doc.status = DocumentStatus.PENDING
        doc.pipeline_stage = "uploaded"
        doc.chunk_count = 0
        doc.embedding_generated = False
        doc.articles_generated = False
        doc.article_count = 0
        doc.pipeline_error = None
        meta = doc.document_metadata or {}
        meta.pop("processing_error", None)
        meta.pop("last_error_at", None)
        doc.document_metadata = meta
        db.commit()

        # Remove sidecar to force fresh text extraction
        sidecar = doc.file_path + ".txt"
        if os.path.exists(sidecar):
            os.remove(sidecar)
            print(f"    Removed sidecar: {sidecar}")
        else:
            print(f"    No sidecar found at: {sidecar}")

        # Re-dispatch
        result = dispatch_document(str(doc.id), from_stage=StageEnum.OCR)
        print(f"    Re-dispatch result: {result}")
        return result == "dispatched"
    except Exception as e:
        db.rollback()
        print(f"    ERROR fixing document {doc_id}: {e}")
        return False
    finally:
        db.close()


def _reset_failed_stage(doc_id: str, stage: StageEnum) -> bool:
    """Reset a single failed stage to PENDING and re-dispatch from there."""
    db = SessionLocal()
    try:
        doc_uuid = uuid.UUID(doc_id) if isinstance(doc_id, str) else doc_id
        row = (
            db.query(PipelineStage)
            .filter(
                PipelineStage.document_id == doc_uuid,
                PipelineStage.stage == stage,
            )
            .first()
        )
        if not row:
            return False

        row.status = StageStatus.PENDING
        row.attempt = 0
        row.error_message = None
        row.started_at = None
        row.completed_at = None
        db.commit()

        result = dispatch_document(str(doc_uuid), from_stage=stage)
        print(f"  Reset {stage.value} for {doc_id} → {result}")
        return result == "dispatched"
    except Exception as e:
        db.rollback()
        print(f"  ERROR resetting {stage.value} for {doc_id}: {e}")
        return False
    finally:
        db.close()


def _dispatch_stalled() -> int:
    """Dispatch documents stalled between stages."""
    db = SessionLocal()
    dispatched = 0
    try:
        stages = list(StageEnum)
        for i, completed_stage in enumerate(stages[:-1]):
            next_stage = stages[i + 1]
            if next_stage == StageEnum.UPLOADED:
                continue

            stalled = (
                db.query(PipelineStage)
                .filter(
                    PipelineStage.stage == next_stage,
                    PipelineStage.status == StageStatus.PENDING,
                    PipelineStage.document_id.in_(
                        db.query(PipelineStage.document_id).filter(
                            PipelineStage.stage == completed_stage,
                            PipelineStage.status == StageStatus.COMPLETED,
                        )
                    ),
                )
                .all()
            )
            for ps in stalled:
                doc = db.query(Document).filter(Document.id == ps.document_id).first()
                if doc and doc.status == DocumentStatus.ERROR:
                    continue
                result = dispatch_document(str(ps.document_id), from_stage=next_stage)
                if result == "dispatched":
                    dispatched += 1
        print(f"  Dispatched {dispatched} stalled documents")
        return dispatched
    finally:
        db.close()


def main():
    print("=== SOWKNOW Pipeline Recovery ===\n")

    # 1. Fix stale pipeline_stage values
    print("[1] Fixing stale pipeline_stage values...")
    _fix_stale_pipeline_stages()

    # 2. Fix the corrupted document (Portefeuille General 06 2016.xlsx)
    print("\n[2] Fixing corrupted document 63c57a15-b1d2-4e9d-9b2f-3062557858ab...")
    _fix_corrupted_document("63c57a15-b1d2-4e9d-9b2f-3062557858ab")

    # 3. Reset failed embedded stage if it's a transient-looking error
    #    (The other 2 chunked failures are permanent — too many chunks / no text)
    print("\n[3] Resetting failed embedded stage...")
    _reset_failed_stage("63c57a15-b1d2-4e9d-9b2f-3062557858ab", StageEnum.EMBEDDED)

    # 4. Dispatch any stalled documents
    print("\n[4] Dispatching stalled documents...")
    _dispatch_stalled()

    print("\n=== Recovery complete ===")


if __name__ == "__main__":
    main()
