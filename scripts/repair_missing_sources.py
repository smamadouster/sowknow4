#!/usr/bin/env python3
"""
Repair documents whose source binary is missing (source_file_available=false).

Reads a CSV mapping document_id -> replacement source file and re-stores the
file in the correct bucket, updating file_path / filename and flipping
source_file_available back to true. Idempotent: re-running with the same CSV
skips documents that are already available.

CSV format (header required):
    document_id,source_path
    <uuid>,/data/repair/5-Year-Projection-Template.xltx
    ...

Run INSIDE the backend container (has /data mounts + DB access):
    docker cp scripts/repair_missing_sources.py sowknow-backend:/tmp/
    docker cp mapping.csv sowknow-backend:/tmp/repair.csv
    docker exec sowknow-backend python /tmp/repair_missing_sources.py /tmp/repair.csv
"""

import csv
import logging
import sys
from pathlib import Path
from uuid import UUID

# Add /app to path so 'app' imports work inside the container
APP_DIR = Path(__file__).resolve().parent.parent / "app"
if APP_DIR.exists():
    sys.path.insert(0, str(APP_DIR.parent))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    if len(sys.argv) != 2:
        logger.error("Usage: repair_missing_sources.py <mapping.csv>")
        sys.exit(2)

    from app.database import SessionLocal
    from app.models.document import Document
    from app.services.storage_service import storage_service

    mapping_path = Path(sys.argv[1])
    if not mapping_path.exists():
        logger.error("Mapping file not found: %s", mapping_path)
        sys.exit(2)

    db = SessionLocal()
    repaired = 0
    skipped_available = 0
    missing_doc = 0
    missing_source = 0
    errors = 0

    try:
        with open(mapping_path, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            if "document_id" not in (reader.fieldnames or []):
                logger.error("CSV must have a 'document_id' column")
                sys.exit(2)

            for row in reader:
                doc_id = (row.get("document_id") or "").strip()
                source = (row.get("source_path") or "").strip()
                if not doc_id or not source:
                    continue

                try:
                    uuid = UUID(doc_id)
                except ValueError:
                    logger.warning("Skipping invalid document_id: %r", doc_id)
                    continue

                doc = db.get(Document, uuid)
                if doc is None:
                    logger.warning("Document not found: %s", doc_id)
                    missing_doc += 1
                    continue

                if doc.source_file_available:
                    skipped_available += 1
                    continue

                src_path = Path(source)
                if not src_path.is_file():
                    logger.warning("Source file missing: %s", source)
                    missing_source += 1
                    continue

                try:
                    content = src_path.read_bytes()
                    bucket = doc.bucket.value
                    original = doc.original_filename or src_path.name
                    result = storage_service.save_file(
                        file_content=content,
                        original_filename=original,
                        bucket=bucket,
                    )
                    doc.filename = result["filename"]
                    doc.file_path = result["file_path"]
                    doc.source_file_available = True
                    db.commit()
                    repaired += 1
                    logger.info(
                        "REPAIRED doc=%s bucket=%s -> %s",
                        doc_id,
                        bucket,
                        result["filename"],
                    )
                except Exception as exc:
                    db.rollback()
                    errors += 1
                    logger.error("FAILED doc=%s: %s", doc_id, exc)

    finally:
        db.close()

    logger.info(
        "Summary: repaired=%d skipped_available=%d missing_doc=%d "
        "missing_source=%d errors=%d",
        repaired,
        skipped_available,
        missing_doc,
        missing_source,
        errors,
    )


if __name__ == "__main__":
    main()
