"""
Recover all ERROR documents in batches.

Strategy:
  - If .txt sidecar exists and has content → re-chunk, mark INDEXED, queue embedding
  - If .txt is missing or empty      → reset to PENDING, dispatch full pipeline from OCR

Run inside the backend container:
    python /app/scripts/recover_error_documents.py [--batch-size N] [--dry-run]
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal
from app.models.document import Document, DocumentChunk, DocumentStatus
from app.models.pipeline import PipelineStage, StageEnum, StageStatus
from app.services.chunking_service import chunking_service
from app.tasks.pipeline_orchestrator import dispatch_document


def recover(batch_size: int = 50, limit: int = 0, dry_run: bool = True):
    db = SessionLocal()
    try:
        query = (
            db.query(Document)
            .filter(Document.status == DocumentStatus.ERROR)
            .order_by(Document.updated_at.asc())
        )
        if limit > 0:
            query = query.limit(limit)
        error_docs = query.all()

        print(f"Total ERROR documents: {len(error_docs)}")

        fixed = 0
        requeued = 0
        skipped = 0

        for doc in error_docs:
            txt_path = f"{doc.file_path}.txt" if doc.file_path else None
            txt_exists = txt_path and os.path.exists(txt_path)
            txt_size = os.path.getsize(txt_path) if txt_exists else 0

            if dry_run:
                action = "RECHUNK" if txt_size > 0 else "REPROCESS"
                print(f"  [{action}] {doc.id} | {doc.original_filename or doc.filename} | txt={txt_size}b | chunks_col={doc.chunk_count}")
                continue

            # ── Case A: sidecar has content → re-chunk directly ──
            if txt_size > 0:
                # Skip massive sidecars that would OOM the chunker
                MAX_TXT_SIZE = 5 * 1024 * 1024  # 5 MB
                if txt_size > MAX_TXT_SIZE:
                    print(f"  SKIP (large txt {txt_size:,}b): {doc.id}")
                    skipped += 1
                    continue
                try:
                    with open(txt_path, encoding="utf-8") as fh:
                        text = fh.read()

                    if not text.strip():
                        raise ValueError("Empty text after read")

                    # Delete stale chunks (if any)
                    db.query(DocumentChunk).filter(
                        DocumentChunk.document_id == doc.id
                    ).delete(synchronize_session=False)

                    # Re-chunk
                    chunks = chunking_service.chunk_document(
                        text=text,
                        document_id=str(doc.id),
                        metadata={
                            "filename": doc.original_filename or doc.filename,
                            "bucket": str(doc.bucket),
                            "mime_type": doc.mime_type,
                        },
                    )

                    for chunk_data in chunks:
                        chunk = DocumentChunk(
                            document_id=doc.id,
                            chunk_index=chunk_data["index"],
                            chunk_text=chunk_data["text"].replace("\x00", ""),
                            token_count=chunk_data.get("token_count"),
                            search_language=doc.language,
                        )
                        db.add(chunk)

                    doc.chunk_count = len(chunks)
                    doc.status = DocumentStatus.INDEXED
                    doc.pipeline_stage = "indexed"
                    doc.pipeline_error = None
                    doc.embedding_generated = False
                    meta = doc.document_metadata or {}
                    meta.pop("processing_error", None)
                    meta.pop("last_error_at", None)
                    meta["auto_recovered_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    meta["recovery_type"] = "rechunk_from_sidecar"
                    doc.document_metadata = meta
                    db.commit()

                    # Queue embedding
                    from app.tasks.embedding_tasks import recompute_embeddings_for_document

                    recompute_embeddings_for_document.apply_async(args=(str(doc.id),))

                    fixed += 1
                    if fixed % 10 == 0:
                        print(f"  ... fixed {fixed} docs so far")
                except Exception as e:
                    db.rollback()
                    print(f"  FAILED to rechunk {doc.id}: {e}")
                    skipped += 1
                continue

            # ── Case B: no sidecar / empty → full reprocess from OCR ──
            try:
                doc.status = DocumentStatus.PENDING
                doc.pipeline_stage = "uploaded"
                doc.pipeline_error = None
                doc.chunk_count = 0
                meta = doc.document_metadata or {}
                meta.pop("processing_error", None)
                meta.pop("last_error_at", None)
                meta["auto_recovered_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                meta["recovery_type"] = "full_reprocess"
                doc.document_metadata = meta
                db.commit()

                # Ensure UPLOADED stage row exists
                uploaded_row = (
                    db.query(PipelineStage)
                    .filter(
                        PipelineStage.document_id == doc.id,
                        PipelineStage.stage == StageEnum.UPLOADED,
                    )
                    .first()
                )
                if not uploaded_row:
                    db.add(
                        PipelineStage(
                            document_id=doc.id,
                            stage=StageEnum.UPLOADED,
                            status=StageStatus.COMPLETED,
                            attempt=1,
                            max_attempts=3,
                        )
                    )
                    db.commit()

                # Dispatch from OCR
                result = dispatch_document(str(doc.id), from_stage=StageEnum.OCR)
                time.sleep(0.5)
                if result.startswith("backpressure"):
                    print(f"  BACKPRESSURE for {doc.id} — stopping batch")
                    break

                requeued += 1
                if requeued % 10 == 0:
                    print(f"  ... requeued {requeued} docs so far")
            except Exception as e:
                db.rollback()
                print(f"  FAILED to requeue {doc.id}: {e}")
                skipped += 1

        print(f"\nDone! fixed={fixed}, requeued={requeued}, skipped={skipped}")

    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Recover ERROR documents")
    parser.add_argument("--batch-size", type=int, default=50, help="Unused — processes all")
    parser.add_argument("--limit", type=int, default=0, help="Max docs to process (0 = all)")
    parser.add_argument("--dry-run", action="store_true", default=False, help="Preview only")
    args = parser.parse_args()
    recover(batch_size=args.batch_size, limit=args.limit, dry_run=args.dry_run)
