#!/usr/bin/env python3
"""
Targeted reset for the specific stuck files reported by user.

Categories:
  - RECOVERABLE: Reset pipeline stages, clear ERROR status, and re-dispatch.
  - PERMANENT: "Too many chunks" — these exceed CHUNK_COUNT_MAX and cannot
    be processed without raising the system limit.
  - MISSING: Not found in DB — may need to be uploaded.

Run inside backend container:
    docker exec -i sowknow4-backend python /app/scripts/reset_specific_stuck.py
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
from app.models.pipeline import PipelineStage, StageStatus, StageEnum
from sqlalchemy import select, delete, text

from app.tasks.pipeline_orchestrator import dispatch_document
from app.tasks.pipeline_tasks import update_stage


# Files reported as stuck by user
STUCK_FILENAMES = [
    "CSI Matforce template.Finance.Aout2013.ppt",
    "NORMES_IAS_IFRS_2008[1].pdf",
    "Recherche écart CA.xls",
    "etatdereponses2012.pdf",
    "Doctrine fiscale 2012.pdf",
    "Doctrine fiscale 2010.pdf",
    "circulaire_tva_ndeg_153_du_11.05[1] suspension tva.pdf",
    "cgi2013[1].pdf",
    "ANALYSE CA ET TVA 2012.xls",
    "Liasse Fiscale GUINEE 2012.xlsx",
    "FACT N°F10410412120058 GUINEE.docx",
    "Balance 2012 excel.xls",
    "Budget Filiales 2014 - NOTES.xlsx",
    "Template MatRégions.xls",
    "SITUATION DE LA FACTURATION 071113 - Fichier Khadija.xlsx",
    "Rattrapage Facturation PDG.xlsx",
    "liste des factures validées.xlsx",
    "FACTURES 2012.xlsx",
    "Facturation en chantier.xlsx",
    "bl en suspens.xlsx",
    "RAPPROCHEMENTS BANKS 2013 bis (2).xlsx",
    "etat de stock modele Filiales.xls",
    "Flash clients 30MAR13.xls",
]

# Error substrings that mean the file is permanently unprocessable at current settings
PERMANENT_ERRORS = [
    "too many chunks",
    "chunks (limit",
    "unsupported file format",
    "video and audio files cannot be processed",
]


async def find_documents(db):
    """Find all documents matching the stuck filenames."""
    found = {}
    missing = []

    for filename in STUCK_FILENAMES:
        rows = await db.execute(
            select(Document)
            .where(
                (Document.original_filename == filename)
                | (Document.filename == filename)
                | (Document.original_filename.ilike(f"%{filename}%"))
            )
            .order_by(Document.created_at.desc())
        )
        docs = rows.scalars().all()
        if docs:
            # If multiple matches, take the most recent non-indexed one, or most recent overall
            target = None
            for d in docs:
                if d.status != DocumentStatus.INDEXED:
                    target = d
                    break
            if target is None:
                target = docs[0]
            found[filename] = target
        else:
            missing.append(filename)

    return found, missing


async def reset_and_dispatch(db, document: Document) -> str:
    """Hard-reset a document and re-dispatch it."""
    doc_id = str(document.id)

    # 1. Delete all pipeline stages
    await db.execute(
        delete(PipelineStage).where(PipelineStage.document_id == doc_id)
    )

    # 2. Delete all chunks
    await db.execute(
        delete(DocumentChunk).where(DocumentChunk.document_id == doc_id)
    )

    # 3. Delete sidecar .txt if present
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
    meta["bulk_reset_reason"] = "user_reported_stuck"
    meta.pop("processing_error", None)
    meta.pop("extraction_empty", None)
    document.document_metadata = meta
    await db.commit()

    # 5. Re-create UPLOADED stage and dispatch
    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor(max_workers=1) as pool:
        await loop.run_in_executor(
            pool, update_stage, doc_id, StageEnum.UPLOADED, StageStatus.COMPLETED
        )
        dispatch_result = await loop.run_in_executor(
            pool, dispatch_document, doc_id
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

    return dispatch_result


async def main():
    async with AsyncSessionLocal() as db:
        found, missing = await find_documents(db)

        print(f"=== Found {len(found)} documents, {len(missing)} missing ===\n")

        recoverable = []
        permanent = []
        already_ok = []

        for filename, doc in found.items():
            err = (doc.pipeline_error or "").lower()
            is_permanent = any(p.lower() in err for p in PERMANENT_ERRORS)

            if doc.status == DocumentStatus.INDEXED:
                already_ok.append((filename, doc))
            elif is_permanent:
                permanent.append((filename, doc))
            else:
                recoverable.append((filename, doc))

        # Report already-OK files
        if already_ok:
            print("=== ALREADY INDEXED (no action needed) ===")
            for filename, doc in already_ok:
                print(f"  [OK] {filename} — status={doc.status.value}, stage={doc.pipeline_stage}")
            print()

        # Report permanently stuck files
        if permanent:
            print("=== PERMANENTLY STUCK (Too many chunks — cannot process without raising CHUNK_COUNT_MAX) ===")
            for filename, doc in permanent:
                print(f"  [SKIP] {filename}")
                print(f"         status={doc.status.value}, stage={doc.pipeline_stage}")
                print(f"         error={doc.pipeline_error}")
            print()

        # Report missing files
        if missing:
            print("=== MISSING FROM DATABASE (need upload or filename mismatch) ===")
            for filename in missing:
                print(f"  [MISSING] {filename}")
            print()

        # Reset and dispatch recoverable files
        if recoverable:
            print(f"=== RESETTING {len(recoverable)} RECOVERABLE FILES ===")
            success = 0
            failed = 0
            for filename, doc in recoverable:
                print(f"  Resetting {filename} ...", end=" ", flush=True)
                try:
                    result = await reset_and_dispatch(db, doc)
                    print(f"→ {doc.status.value} ({result})")
                    success += 1
                except Exception as e:
                    print(f"→ FAILED: {e}")
                    failed += 1

            print(f"\n=== Recoverable reset complete: {success} dispatched, {failed} failed ===")
        else:
            print("=== No recoverable files to reset ===")

        # Final summary
        print(f"\n=== SUMMARY ===")
        print(f"  Total requested:     {len(STUCK_FILENAMES)}")
        print(f"  Already indexed:     {len(already_ok)}")
        print(f"  Permanently stuck:   {len(permanent)}")
        print(f"  Missing from DB:     {len(missing)}")
        print(f"  Reset & dispatched:  {len(recoverable)}")


if __name__ == "__main__":
    asyncio.run(main())
