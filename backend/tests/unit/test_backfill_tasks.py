"""
Unit tests for backfill tasks.
"""

import uuid
from datetime import UTC, datetime, timedelta, timezone
from unittest.mock import Mock, patch

import pytest
from sqlalchemy.orm import Session

from app.models.document import Document, DocumentBucket, DocumentStatus


def _make_indexed_doc(db: Session, embedding_generated: bool = False, articles_generated: bool = False, chunk_count: int = 10) -> Document:
    doc = Document(
        id=uuid.uuid4(),
        filename="backfill_test.pdf",
        original_filename="backfill_test.pdf",
        file_path="/data/public/backfill_test.pdf",
        mime_type="application/pdf",
        size=1024,
        bucket=DocumentBucket.PUBLIC,
        status=DocumentStatus.INDEXED,
        created_at=datetime.now(UTC) - timedelta(days=3),
        updated_at=datetime.now(UTC) - timedelta(days=3),
        ocr_processed=True,
        embedding_generated=embedding_generated,
        articles_generated=articles_generated,
        chunk_count=chunk_count,
        document_metadata={},
    )
    db.add(doc)
    db.commit()
    return doc


def _make_error_doc(db: Session, created_at: datetime = None) -> Document:
    doc = Document(
        id=uuid.uuid4(),
        filename="failed_doc.pdf",
        original_filename="failed_doc.pdf",
        file_path="/data/public/failed_doc.pdf",
        mime_type="application/pdf",
        size=2048,
        bucket=DocumentBucket.PUBLIC,
        status=DocumentStatus.ERROR,
        created_at=created_at or datetime(2026, 4, 3, tzinfo=UTC),
        updated_at=datetime.now(UTC),
        document_metadata={
            "processing_error": "Permanently failed: stuck in processing after 4 recovery attempts",
            "recovery_count": 5,
        },
    )
    db.add(doc)
    db.commit()
    return doc


class TestReprocessFailedDocuments:
    def test_resets_error_docs_to_pending(self, db: Session):
        from app.tasks.backfill_tasks import reprocess_failed_documents

        doc = _make_error_doc(db, created_at=datetime(2026, 4, 3, tzinfo=UTC))

        mock_pd = Mock()
        mock_task = Mock()
        mock_task.id = "new-task-id"
        mock_pd.apply_async = Mock(return_value=mock_task)

        with patch("app.database.SessionLocal", return_value=db), \
             patch("app.tasks.document_tasks.process_document", mock_pd):
            original_close = db.close
            db.close = Mock()
            try:
                result = reprocess_failed_documents("2026-04-02", "2026-04-05", batch_size=100, delay_seconds=0)
            finally:
                db.close = original_close

        assert result["total_reset"] == 1
        db.refresh(doc)
        assert doc.status == DocumentStatus.PENDING
        assert doc.document_metadata.get("recovery_count") == 0


class TestBackfillMissingEmbeddings:
    def test_queues_embedding_tasks_for_indexed_docs(self, db: Session):
        from app.tasks.backfill_tasks import backfill_missing_embeddings

        doc = _make_indexed_doc(db, embedding_generated=False, articles_generated=True)

        mock_embed = Mock()
        mock_embed.apply_async = Mock(return_value=Mock(id="embed-task-id"))

        with patch("app.database.SessionLocal", return_value=db), \
             patch("app.tasks.embedding_tasks.recompute_embeddings_for_document", mock_embed):
            original_close = db.close
            db.close = Mock()
            try:
                result = backfill_missing_embeddings(batch_size=100, delay_seconds=0)
            finally:
                db.close = original_close

        assert result["total_queued"] == 1
        mock_embed.apply_async.assert_called_once()


class TestBackfillMissingArticles:
    def test_queues_article_tasks_for_indexed_docs(self, db: Session):
        from app.tasks.backfill_tasks import backfill_missing_articles

        doc = _make_indexed_doc(db, embedding_generated=True, articles_generated=False, chunk_count=5)

        mock_gen = Mock()
        mock_gen.apply_async = Mock(return_value=Mock(id="article-task-id"))

        with patch("app.database.SessionLocal", return_value=db), \
             patch("app.tasks.article_tasks.generate_articles_for_document", mock_gen):
            original_close = db.close
            db.close = Mock()
            try:
                result = backfill_missing_articles(batch_size=100, delay_seconds=0)
            finally:
                db.close = original_close

        assert result["total_queued"] == 1
        mock_gen.apply_async.assert_called_once()
