#!/usr/bin/env python3
"""
Flush permanently stuck and missing files.

Uses PostgreSQL CASCADE delete — document_chunks, pipeline_stages, etc.
all have ON DELETE CASCADE, so deleting the document row is sufficient.
"""
import asyncio
import os
import sys

sys.path.insert(0, "/app")
os.chdir("/app")

from app.database import AsyncSessionLocal
from app.models.document import Document, DocumentStatus
from sqlalchemy import select, delete, text

PERMANENT_FILES = [
    "Doctrine fiscale 2012.pdf",
    "Doctrine fiscale 2010.pdf",
    "cgi2013[1].pdf",
    "ANALYSE CA ET TVA 2012.xls",
    "RAPPROCHEMENTS BANKS 2013 bis (2).xlsx",
    "etat de stock modele Filiales.xls",
    "Flash clients 30MAR13.xls",
]

MISSING_FILES = [
    "Recherche écart CA.xls",
    "Template MatRégions.xls",
    "liste des factures validées.xlsx",
]


async def find_doc(filename: str):
    async with AsyncSessionLocal() as db:
        rows = await db.execute(
            select(Document)
            .where(
                (Document.original_filename == filename)
                | (Document.filename == filename)
            )
            .order_by(Document.created_at.desc())
        )
        docs = rows.scalars().all()
        for doc in docs:
            if doc.status != DocumentStatus.INDEXED:
                return doc
        return None


async def flush_document(doc: Document) -> bool:
    async with AsyncSessionLocal() as db:
        doc_id = str(doc.id)
        file_path = doc.file_path

        try:
            # PostgreSQL CASCADE handles all related rows
            await db.execute(
                text("DELETE FROM sowknow.documents WHERE id = :doc_id"),
                {"doc_id": doc_id},
            )
            await db.commit()

            # Delete physical file and sidecar
            if file_path:
                for path in [file_path, file_path + ".txt"]:
                    try:
                        if os.path.exists(path):
                            os.remove(path)
                    except Exception as e:
                        print(f"    Warning: could not delete {path}: {e}")

            return True
        except Exception as e:
            print(f"    ERROR during flush: {e}")
            try:
                await db.rollback()
            except Exception:
                pass
            return False


async def main():
    print("=== FLUSHING PERMANENTLY STUCK FILES ===\n")

    flushed = 0
    skipped = 0
    not_found = 0

    for filename in PERMANENT_FILES:
        doc = await find_doc(filename)
        if doc is None:
            print(f"  [NOT FOUND/INDEXED] {filename}")
            not_found += 1
            continue

        if doc.status == DocumentStatus.INDEXED:
            print(f"  [SKIP INDEXED] {filename} → {doc.id}")
            skipped += 1
            continue

        print(f"  [FLUSH] {filename} → {doc.id} (status={doc.status.value}, chunks={doc.chunk_count or 0})")
        ok = await flush_document(doc)
        if ok:
            print(f"    → deleted")
            flushed += 1

    print(f"\n=== PERMANENT STUCK SUMMARY ===")
    print(f"  Flushed: {flushed}")
    print(f"  Skipped (indexed): {skipped}")
    print(f"  Not found: {not_found}")

    print(f"\n=== MISSING FILES (nothing to flush) ===")
    for filename in MISSING_FILES:
        print(f"  [NOT IN DB] {filename}")

    print(f"\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
