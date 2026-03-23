"""
Deep integration test for the article generation pipeline.

Tests the full flow:
  1. Reset all documents to PENDING (delete chunks, articles, embeddings)
  2. Reprocess all 3 documents through the full pipeline
  3. Wait for processing to complete
  4. Verify chunks, embeddings, and articles were created
  5. Verify search integration (articles appear in search results)

Run inside the celery worker container:
    docker exec sowknow4-celery-worker python /app/scripts/test_article_pipeline.py
"""

import sys
import time
import uuid

from app.database import SessionLocal
from app.models.article import Article, ArticleStatus
from app.models.document import Document, DocumentChunk, DocumentStatus


def step(msg):
    print(f"\n{'='*60}")
    print(f"  {msg}")
    print(f"{'='*60}")


def check(condition, msg):
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {msg}")
    return condition


def main():
    db = SessionLocal()
    failures = 0

    try:
        # ─── STEP 1: Show current state ───────────────────────────
        step("STEP 1: Current state before reset")

        docs = db.query(Document).order_by(Document.created_at).all()
        print(f"  Documents: {len(docs)}")
        for d in docs:
            chunk_count = db.query(DocumentChunk).filter(DocumentChunk.document_id == d.id).count()
            article_count = db.query(Article).filter(Article.document_id == d.id).count()
            print(f"    {d.original_filename[:50]}")
            print(f"      status={d.status.value}, chunks={chunk_count}, articles={article_count}")

        # ─── STEP 2: Reset documents ──────────────────────────────
        step("STEP 2: Resetting all documents (delete articles, chunks, reset status)")

        for d in docs:
            # Delete articles
            db.query(Article).filter(Article.document_id == d.id).delete()
            # Delete chunks
            db.query(DocumentChunk).filter(DocumentChunk.document_id == d.id).delete()
            # Reset document state
            d.status = DocumentStatus.PENDING
            d.chunk_count = 0
            d.article_count = 0
            d.articles_generated = False
            d.embedding_generated = False
            d.ocr_processed = False
            print(f"    Reset: {d.original_filename[:50]}")

        db.commit()

        remaining_articles = db.query(Article).count()
        remaining_chunks = db.query(DocumentChunk).count()
        if not check(remaining_articles == 0, f"All articles deleted (got {remaining_articles})"):
            failures += 1
        if not check(remaining_chunks == 0, f"All chunks deleted (got {remaining_chunks})"):
            failures += 1

        # ─── STEP 3: Queue reprocessing ───────────────────────────
        step("STEP 3: Queuing all documents for full reprocessing")

        from app.tasks.document_tasks import process_document

        task_ids = {}
        for d in docs:
            d.status = DocumentStatus.PENDING
            db.commit()
            result = process_document.delay(str(d.id))
            task_ids[d.original_filename] = result.id
            print(f"    Queued: {d.original_filename[:50]} -> task {result.id}")

        # ─── STEP 4: Wait for processing ──────────────────────────
        step("STEP 4: Waiting for document processing (OCR + chunking + embedding)")

        max_wait = 900  # 15 minutes max
        poll_interval = 15
        elapsed = 0

        while elapsed < max_wait:
            time.sleep(poll_interval)
            elapsed += poll_interval

            db.expire_all()
            docs = db.query(Document).order_by(Document.created_at).all()
            statuses = {d.original_filename: d.status.value for d in docs}

            all_done = all(s in ("indexed", "error") for s in statuses.values())
            print(f"    [{elapsed}s] Statuses: {statuses}")

            if all_done:
                print(f"    All documents processed in {elapsed}s")
                break
        else:
            print(f"    TIMEOUT after {max_wait}s — some documents still processing")

        # ─── STEP 5: Verify document processing ──────────────────
        step("STEP 5: Verifying document processing results")

        db.expire_all()
        docs = db.query(Document).order_by(Document.created_at).all()

        total_chunks = 0
        total_with_embeddings = 0
        indexed_docs = 0

        for d in docs:
            chunks = db.query(DocumentChunk).filter(DocumentChunk.document_id == d.id).all()
            chunk_count = len(chunks)
            embed_count = sum(1 for c in chunks if c.embedding_vector is not None)

            total_chunks += chunk_count
            total_with_embeddings += embed_count

            if d.status == DocumentStatus.INDEXED:
                indexed_docs += 1

            print(f"    {d.original_filename[:50]}")
            print(f"      status={d.status.value}, chunks={chunk_count}, embeddings={embed_count}")

            # Validate individual doc
            if d.original_filename == "acte-uniforme-revise-portant-droit-commercial-general-2010_1.pdf":
                # This doc has extraction issues — should be ERROR
                if not check(d.status == DocumentStatus.ERROR, f"acte-uniforme: expected ERROR status"):
                    failures += 1
            else:
                if not check(d.status == DocumentStatus.INDEXED, f"{d.original_filename[:30]}: expected INDEXED"):
                    failures += 1
                if not check(chunk_count > 0, f"{d.original_filename[:30]}: expected chunks > 0 (got {chunk_count})"):
                    failures += 1

        if not check(indexed_docs >= 2, f"At least 2 docs indexed (got {indexed_docs})"):
            failures += 1
        if not check(total_chunks > 0, f"Total chunks > 0 (got {total_chunks})"):
            failures += 1

        # ─── STEP 6: Wait for article generation ─────────────────
        step("STEP 6: Waiting for article generation (LLM calls + embedding)")

        # Articles are generated async after INDEXED status
        max_wait = 600  # 10 minutes
        elapsed = 0

        while elapsed < max_wait:
            time.sleep(poll_interval)
            elapsed += poll_interval

            db.expire_all()
            docs = db.query(Document).order_by(Document.created_at).all()

            indexed_docs_with_articles = [
                d for d in docs
                if d.status == DocumentStatus.INDEXED and d.articles_generated
            ]
            total_indexed = sum(1 for d in docs if d.status == DocumentStatus.INDEXED)

            article_count = db.query(Article).count()
            indexed_articles = db.query(Article).filter(Article.status == ArticleStatus.INDEXED).count()

            print(f"    [{elapsed}s] Articles: {article_count} total, {indexed_articles} indexed | "
                  f"Docs with articles: {len(indexed_docs_with_articles)}/{total_indexed}")

            if len(indexed_docs_with_articles) >= total_indexed and indexed_articles == article_count and article_count > 0:
                print(f"    All articles generated and embedded in {elapsed}s")
                break
        else:
            print(f"    TIMEOUT after {max_wait}s — articles may still be generating")

        # ─── STEP 7: Final validation ─────────────────────────────
        step("STEP 7: Final validation — articles created and searchable")

        db.expire_all()
        docs = db.query(Document).order_by(Document.created_at).all()

        total_articles = 0
        total_indexed_articles = 0
        total_embedded_articles = 0

        for d in docs:
            articles = db.query(Article).filter(Article.document_id == d.id).all()
            art_count = len(articles)
            indexed_count = sum(1 for a in articles if a.status == ArticleStatus.INDEXED)
            embed_count = sum(1 for a in articles if a.embedding_vector is not None)
            has_search = sum(1 for a in articles if a.search_vector is not None)

            total_articles += art_count
            total_indexed_articles += indexed_count
            total_embedded_articles += embed_count

            print(f"    {d.original_filename[:50]}")
            print(f"      articles={art_count}, indexed={indexed_count}, "
                  f"embeddings={embed_count}, search_vectors={has_search}")

            if d.status == DocumentStatus.INDEXED:
                if not check(art_count > 0, f"{d.original_filename[:30]}: expected articles > 0"):
                    failures += 1
                if not check(indexed_count == art_count, f"{d.original_filename[:30]}: all articles indexed"):
                    failures += 1
                if not check(embed_count == art_count, f"{d.original_filename[:30]}: all articles have embeddings"):
                    failures += 1
                if not check(has_search == art_count, f"{d.original_filename[:30]}: all articles have search_vector"):
                    failures += 1

        # Check article quality
        step("STEP 8: Article quality check")

        sample_articles = db.query(Article).filter(Article.status == ArticleStatus.INDEXED).limit(5).all()
        for a in sample_articles:
            title_ok = len(a.title) > 5
            summary_ok = len(a.summary) > 10
            body_ok = len(a.body) > 50
            tags_ok = isinstance(a.tags, list) and len(a.tags) > 0
            confidence_ok = 0 < a.confidence <= 100

            if not check(title_ok, f"Title length > 5: '{a.title[:60]}'"):
                failures += 1
            if not check(summary_ok, f"Summary length > 10"):
                failures += 1
            if not check(body_ok, f"Body length > 50 (got {len(a.body)})"):
                failures += 1
            if not check(tags_ok, f"Has tags: {a.tags}"):
                failures += 1
            if not check(confidence_ok, f"Confidence 1-100: {a.confidence}"):
                failures += 1

        # ─── SUMMARY ─────────────────────────────────────────────
        step("TEST SUMMARY")

        db.expire_all()
        final_docs = db.query(Document).count()
        final_chunks = db.query(DocumentChunk).count()
        final_articles = db.query(Article).count()
        final_indexed_articles = db.query(Article).filter(Article.status == ArticleStatus.INDEXED).count()
        final_embedded_articles = db.query(Article).filter(Article.embedding_vector.isnot(None)).count()

        print(f"  Documents:           {final_docs}")
        print(f"  Total chunks:        {final_chunks}")
        print(f"  Total articles:      {final_articles}")
        print(f"  Indexed articles:    {final_indexed_articles}")
        print(f"  Embedded articles:   {final_embedded_articles}")
        print(f"  Failures:            {failures}")
        print()

        if failures == 0:
            print("  *** ALL TESTS PASSED ***")
        else:
            print(f"  *** {failures} TESTS FAILED ***")

        return failures

    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
