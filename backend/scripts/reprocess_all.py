"""
Reprocess all documents that need attention:
  - Documents not in 'indexed' status
  - Documents in 'indexed' status but with 0 chunks
  - Documents with chunks but no embeddings (embedding-only backfill)

Run inside the backend container:
    python /app/scripts/reprocess_all.py
    python /app/scripts/reprocess_all.py --embeddings-only   # just backfill embeddings
"""
import argparse

from app.database import SessionLocal
from app.models.document import Document, DocumentChunk, DocumentStatus


def backfill_embeddings(db):
    """Generate embeddings for chunks that have none."""
    from app.services.embedding_service import embedding_service

    docs = (
        db.query(Document)
        .filter(Document.status == DocumentStatus.INDEXED, Document.chunk_count > 0)
        .all()
    )

    total_updated = 0
    for doc in docs:
        chunks = (
            db.query(DocumentChunk)
            .filter(
                DocumentChunk.document_id == doc.id,
                DocumentChunk.embedding_vector.is_(None),
            )
            .order_by(DocumentChunk.chunk_index)
            .all()
        )

        if not chunks:
            continue

        print(f"  Embedding {len(chunks)} chunks for: {doc.original_filename[:60]}")
        texts = [c.chunk_text for c in chunks]

        try:
            # Process in batches of 32
            batch_size = 32
            for i in range(0, len(texts), batch_size):
                batch_texts = texts[i : i + batch_size]
                batch_chunks = chunks[i : i + batch_size]
                embeddings = embedding_service.encode(
                    texts=batch_texts, batch_size=batch_size, show_progress=False
                )
                for j, chunk in enumerate(batch_chunks):
                    if j < len(embeddings):
                        chunk.embedding_vector = embeddings[j]
                db.commit()
                total_updated += len(batch_texts)
                print(f"    Batch {i // batch_size + 1}: {len(batch_texts)} chunks embedded")

            doc.embedding_generated = True
            db.commit()

        except Exception as e:
            db.rollback()
            print(f"    ERROR embedding {doc.original_filename}: {e}")

    return total_updated


def main():
    parser = argparse.ArgumentParser(description="Reprocess documents and backfill embeddings")
    parser.add_argument(
        "--embeddings-only",
        action="store_true",
        help="Only backfill embeddings for already-chunked documents",
    )
    args = parser.parse_args()

    db = SessionLocal()

    try:
        # 1. Show current state
        print("=== DOCUMENT STATUS ===")
        docs = db.query(Document).order_by(Document.created_at.desc()).all()
        status_counts = {}
        for d in docs:
            s = d.status.value
            status_counts[s] = status_counts.get(s, 0) + 1
        for s, c in status_counts.items():
            print(f"  {s}: {c}")
        print(f"  TOTAL: {len(docs)}")

        # 2. Count chunks
        total_chunks = db.query(DocumentChunk).count()
        print(f"\n=== CHUNKS: {total_chunks} total ===")

        # 3. Count chunks without embeddings
        no_embedding = (
            db.query(DocumentChunk)
            .filter(DocumentChunk.embedding_vector.is_(None))
            .count()
        )
        print(f"=== CHUNKS WITHOUT EMBEDDINGS: {no_embedding} ===")

        if args.embeddings_only:
            print("\n=== BACKFILLING EMBEDDINGS ONLY ===")
            updated = backfill_embeddings(db)
            print(f"\nDone! Updated {updated} chunks with embeddings.")
            return

        # 4. Find documents needing reprocessing
        not_indexed = [d for d in docs if d.status != DocumentStatus.INDEXED]
        no_chunks = []
        for d in docs:
            if d.status == DocumentStatus.INDEXED:
                c = db.query(DocumentChunk).filter(DocumentChunk.document_id == d.id).count()
                if c == 0:
                    no_chunks.append(d)

        to_reprocess = not_indexed + no_chunks
        print(f"\n=== NEED REPROCESSING: {len(to_reprocess)} ===")
        for d in to_reprocess:
            print(f"  {d.original_filename[:60]} | {d.status.value}")

        # 5. Queue them for reprocessing
        if to_reprocess:
            from app.tasks.document_tasks import process_document

            print(f"\n=== QUEUING {len(to_reprocess)} DOCUMENTS ===")
            for d in to_reprocess:
                d.status = DocumentStatus.PENDING
                db.commit()
                result = process_document.delay(str(d.id))
                print(f"  Queued: {d.original_filename[:50]} -> task {result.id}")
            print("\nDone! Monitor with: docker logs -f sowknow4-celery-worker")
        else:
            print("\nAll documents are indexed with chunks.")

        # 6. Backfill embeddings for indexed docs
        if no_embedding > 0:
            print(f"\n=== BACKFILLING EMBEDDINGS FOR {no_embedding} CHUNKS ===")
            updated = backfill_embeddings(db)
            print(f"\nDone! Updated {updated} chunks with embeddings.")
        else:
            print("\nAll chunks have embeddings.")

    finally:
        db.close()


if __name__ == "__main__":
    main()
