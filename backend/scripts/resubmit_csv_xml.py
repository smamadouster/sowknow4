"""
One-off script: Reset ERROR CSV/XML documents to PENDING and trigger reprocessing.
Run inside backend container: docker exec -it sowknow4-backend python scripts/resubmit_csv_xml.py
"""

import sys
sys.path.insert(0, "/app")

from app.database import SessionLocal
from app.models.document import Document, DocumentStatus


def main():
    db = SessionLocal()
    try:
        # Find all ERROR documents with .csv or .xml extensions
        error_docs = (
            db.query(Document)
            .filter(
                Document.status == DocumentStatus.ERROR,
                (Document.filename.ilike("%.csv")) | (Document.filename.ilike("%.xml")),
            )
            .all()
        )

        count = len(error_docs)
        print(f"Found {count} ERROR CSV/XML documents to resubmit.")

        if count == 0:
            print("Nothing to do.")
            return

        # Reset status to PENDING
        doc_ids = []
        for doc in error_docs:
            doc.status = DocumentStatus.PENDING
            # Clear previous error metadata
            meta = doc.document_metadata or {}
            meta.pop("processing_error", None)
            meta.pop("failure_reason", None)
            meta["reprocess_reason"] = "CSV/XML support added"
            doc.document_metadata = meta
            doc_ids.append(str(doc.id))

        db.commit()
        print(f"Reset {count} documents to PENDING.")

        # Trigger staggered reprocessing via Celery task
        from app.tasks.document_tasks import reprocess_pending_documents

        result = reprocess_pending_documents.delay()
        print(f"Queued reprocessing task: {result.id}")
        print("Documents will be processed in batches of 40, 30s apart.")

    finally:
        db.close()


if __name__ == "__main__":
    main()
