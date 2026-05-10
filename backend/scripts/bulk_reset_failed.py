#!/usr/bin/env python3
"""Bulk reset all documents with failed pipeline stages."""
import asyncio
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

sys.path.insert(0, "/app")
os.chdir("/app")

from app.database import AsyncSessionLocal
from app.models.document import Document, DocumentChunk, DocumentStatus
from app.models.pipeline import PipelineStage, StageStatus, StageEnum
from sqlalchemy import select, update, delete
from sqlalchemy.orm import selectinload

from app.tasks.pipeline_orchestrator import dispatch_document
from app.tasks.pipeline_tasks import update_stage


async def reset_doc(db, document_id: str) -> bool:
    """Hard-reset a document: wipe stages, chunks, and re-dispatch."""
    result = await db.execute(
        select(Document).where(Document.id == document_id)
    )
    document = result.scalar_one_or_none()
    if not document:
        return False

    # 1. Delete all pipeline stages
    await db.execute(
        delete(PipelineStage).where(PipelineStage.document_id == document_id)
    )

    # 2. Delete all chunks
    await db.execute(
        delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
    )

    # 3. Delete sidecar .txt if it exists
    if document.file_path:
        txt_path = document.file_path + ".txt"
        try:
            if os.path.exists(txt_path):
                os.remove(txt_path)
        except Exception:
            pass

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
    meta["bulk_reset_at"] = datetime.now(timezone.utc).isoformat()
    meta.pop("processing_error", None)
    meta.pop("extraction_empty", None)
    document.document_metadata = meta
    await db.commit()

    # 5. Re-create UPLOADED stage and dispatch
    try:
        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=1) as pool:
            await loop.run_in_executor(
                pool, update_stage, str(document.id), StageEnum.UPLOADED, StageStatus.COMPLETED
            )
            dispatch_result = await loop.run_in_executor(
                pool, dispatch_document, str(document.id)
            )

        if dispatch_result == "dispatched":
            document.status = DocumentStatus.PROCESSING
            document.pipeline_stage = "ocr"
        else:
            document.status = DocumentStatus.PENDING
            meta = document.document_metadata or {}
            meta["backpressure"] = dispatch_result
            document.document_metadata = meta
        await db.commit()

        print(f"  OK: {document.filename} -> {document.status.value} ({dispatch_result})")
        return True
    except Exception as e:
        print(f"  DISPATCH ERROR: {document.filename} -> {e}")
        # Even if dispatch fails, the doc is reset and will be picked up by sweeper
        return True


async def main():
    async with AsyncSessionLocal() as db:
        # Find all unique docs with any failed stage
        result = await db.execute(
            select(Document.id, Document.filename)
            .join(PipelineStage, PipelineStage.document_id == Document.id)
            .where(PipelineStage.status == StageStatus.FAILED)
            .distinct()
        )
        failed_docs = result.all()
        print(f"Found {len(failed_docs)} documents with failed stages")

        success = 0
        for doc_id, filename in failed_docs:
            print(f"Resetting {doc_id} ({filename})...")
            try:
                ok = await reset_doc(db, str(doc_id))
                if ok:
                    success += 1
            except Exception as e:
                print(f"  FAILED: {e}")

        print(f"\nDone. Reset {success}/{len(failed_docs)} documents.")


if __name__ == "__main__":
    asyncio.run(main())
