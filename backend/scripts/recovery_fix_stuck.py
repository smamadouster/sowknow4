#!/usr/bin/env python3
"""
Emergency recovery script:
1. Force-reset 4 stuck embedding docs (phantom RUNNING with empty queue)
2. Bulk force-reset all FAILED stage docs (chunked + embedded + ocr)
"""
import asyncio
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

sys.path.insert(0, "/app")
os.chdir("/app")

from app.database import AsyncSessionLocal
from app.models.document import Document, DocumentChunk, DocumentStatus
from app.models.pipeline import PipelineStage, StageStatus
from app.models.user import User
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

# Sync helpers
from app.tasks.pipeline_orchestrator import dispatch_document
from app.tasks.pipeline_tasks import update_stage
from app.models.pipeline import StageEnum


async def force_reset_doc(db, document_id: str, reset_by: str = "recovery_script"):
    """Hard-reset a single document (mirrors admin.py force-reset logic)."""
    result = await db.execute(select(Document).where(Document.id == document_id))
    document = result.scalar_one_or_none()
    if not document:
        print(f"  SKIP: Document {document_id} not found")
        return False

    # 1. Delete all pipeline stage rows
    await db.execute(
        PipelineStage.__table__.delete().where(PipelineStage.document_id == document_id)
    )

    # 2. Delete all chunks
    await db.execute(
        DocumentChunk.__table__.delete().where(DocumentChunk.document_id == document_id)
    )

    # 3. Delete sidecar .txt if it exists
    txt_path = None
    if document.file_path:
        txt_path = document.file_path + ".txt"
        try:
            if os.path.exists(txt_path):
                os.remove(txt_path)
                print(f"  Removed sidecar {txt_path}")
        except Exception as e:
            print(f"  Could not remove sidecar {txt_path}: {e}")

    # 4. Reset document fields
    document.status = DocumentStatus.PENDING
    document.pipeline_stage = "uploaded"
    document.pipeline_error = None
    document.pipeline_retry_count = 0
    document.pipeline_last_attempt = None
    document.chunk_count = 0
    document.embedding_generated = False
    document.ocr_processed = False
    meta = document.document_metadata or {}
    meta["force_reset_at"] = datetime.now(timezone.utc).isoformat()
    meta["force_reset_by"] = reset_by
    meta.pop("processing_error", None)
    meta.pop("extraction_empty", None)
    document.document_metadata = meta
    await db.commit()

    # 5. Re-create UPLOADED stage and dispatch
    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor(max_workers=1) as pool:
        await loop.run_in_executor(
            pool, update_stage, str(document.id), StageEnum.UPLOADED, StageStatus.COMPLETED
        )
        dispatch_result = await loop.run_in_executor(pool, dispatch_document, str(document.id))

    if dispatch_result == "dispatched":
        document.status = DocumentStatus.PROCESSING
        document.pipeline_stage = "ocr"
    else:
        document.status = DocumentStatus.PENDING
        meta = document.document_metadata or {}
        meta["backpressure"] = dispatch_result
        document.document_metadata = meta
    await db.commit()

    print(f"  -> {document.filename}: {document.status.value} ({dispatch_result})")
    return True


async def main():
    async with AsyncSessionLocal() as db:
        # --- Part 1: Stuck embedding docs ---
        print("=== Part 1: Resetting 4 stuck embedding docs ===")
        result = await db.execute(
            select(Document.id, Document.filename)
            .join(PipelineStage, PipelineStage.document_id == Document.id)
            .where(PipelineStage.status == StageStatus.RUNNING)
            .where(PipelineStage.stage == "embedded")
        )
        stuck_docs = result.all()
        print(f"Found {len(stuck_docs)} stuck embedding docs")

        for doc_id, filename in stuck_docs:
            print(f"Resetting {doc_id} ({filename})...")
            await force_reset_doc(db, str(doc_id))

        # --- Part 2: Failed stages ---
        print("\n=== Part 2: Bulk resetting FAILED stage docs ===")
        result = await db.execute(
            select(Document.id, Document.filename, PipelineStage.stage, PipelineStage.error_message)
            .join(PipelineStage, PipelineStage.document_id == Document.id)
            .where(PipelineStage.status == StageStatus.FAILED)
            .order_by(Document.created_at.asc())
        )
        failed_rows = result.all()

        # Group by document (a doc may have multiple failed stages)
        failed_docs = {}
        for doc_id, filename, stage, err in failed_rows:
            if doc_id not in failed_docs:
                failed_docs[doc_id] = {"filename": filename, "stages": []}
            failed_docs[doc_id]["stages"].append((stage, err))

        print(f"Found {len(failed_docs)} documents with failed stages ({len(failed_rows)} total failed stages)")

        reset_count = 0
        skip_count = 0
        for doc_id, info in failed_docs.items():
            stages_str = ", ".join([s[0] for s in info["stages"]])
            print(f"Resetting {doc_id} ({info['filename']}) — stages: {stages_str}")
            try:
                ok = await force_reset_doc(db, str(doc_id))
                if ok:
                    reset_count += 1
                else:
                    skip_count += 1
            except Exception as e:
                print(f"  ERROR: {e}")
                skip_count += 1

        print(f"\nDone. Reset {reset_count} docs, skipped {skip_count}.")


if __name__ == "__main__":
    asyncio.run(main())
