"""
Unit tests for anomaly recovery tasks.
"""

import uuid
from datetime import UTC, datetime, timedelta, timezone
from unittest.mock import Mock, patch

import pytest
from sqlalchemy.orm import Session

from app.models.document import Document, DocumentBucket, DocumentStatus
from app.tasks.anomaly_tasks import recover_pending_documents


def _make_pending_doc(db: Session, created_minutes_ago: int = 10) -> Document:
    """Create a PENDING document older than the recovery threshold."""
    doc = Document(
        id=uuid.uuid4(),
        filename="test_pending.pdf",
        original_filename="test_pending.pdf",
        file_path="/data/public/test_pending.pdf",
        size=1024,
        mime_type="application/pdf",
        bucket=DocumentBucket.PUBLIC,
        status=DocumentStatus.PENDING,
        created_at=datetime.now(UTC) - timedelta(minutes=created_minutes_ago),
        updated_at=datetime.now(UTC) - timedelta(minutes=created_minutes_ago),
        document_metadata={},
    )
    db.add(doc)
    db.commit()
    return doc


def _run_pending_recovery(db: Session, threshold: int = 5) -> dict:
    """Run recover_pending_documents with the test db session."""
    mock_pd = Mock()
    mock_task = Mock()
    mock_task.id = "fake-celery-task-id"
    mock_pd.delay = Mock(return_value=mock_task)

    with patch("app.database.SessionLocal", return_value=db), \
         patch("app.tasks.document_tasks.process_document", mock_pd):
        original_close = db.close
        db.close = Mock()
        try:
            result = recover_pending_documents(pending_threshold_minutes=threshold)
        finally:
            db.close = original_close

    return result


class TestRecoverPendingDocuments:
    def test_does_not_crash_with_name_error(self, db: Session):
        """The critical bug: already_queued was undefined, causing NameError."""
        doc = _make_pending_doc(db, created_minutes_ago=10)
        # This must not raise NameError
        result = _run_pending_recovery(db)
        assert "recovered" in result
        assert "already_queued" in result
        assert "failed" in result

    def test_recovers_old_pending_document(self, db: Session):
        """A PENDING document older than threshold should be re-queued."""
        doc = _make_pending_doc(db, created_minutes_ago=10)
        result = _run_pending_recovery(db, threshold=5)
        assert len(result["recovered"]) == 1
        assert result["recovered"][0]["document_id"] == str(doc.id)

    def test_ignores_recent_pending_document(self, db: Session):
        """A PENDING document within threshold should NOT be re-queued."""
        doc = _make_pending_doc(db, created_minutes_ago=2)
        result = _run_pending_recovery(db, threshold=5)
        assert len(result["recovered"]) == 0


from app.tasks.anomaly_tasks import recover_stuck_documents


def _make_processing_doc(db: Session, updated_minutes_ago: int = 30, recovery_count: int = 4) -> Document:
    """Create a PROCESSING document that has exceeded max recovery attempts."""
    doc = Document(
        id=uuid.uuid4(),
        filename="stuck_doc.pdf",
        original_filename="stuck_doc.pdf",
        file_path="/data/public/stuck_doc.pdf",
        size=1024,
        mime_type="application/pdf",
        bucket=DocumentBucket.PUBLIC,
        status=DocumentStatus.PROCESSING,
        created_at=datetime.utcnow() - timedelta(hours=2),
        updated_at=datetime.utcnow() - timedelta(minutes=updated_minutes_ago),
        document_metadata={"recovery_count": recovery_count, "celery_task_id": "old-task-id"},
    )
    db.add(doc)
    db.commit()
    return doc


def _run_stuck_recovery(db: Session, max_minutes: int = 5) -> dict:
    """Run recover_stuck_documents with the test db session.

    SQLite returns timezone-naive datetimes, but the production code uses
    ``datetime.now(timezone.utc)`` which is timezone-aware.  We patch the
    ``datetime`` class inside anomaly_tasks so that ``.now()`` always returns
    a naive UTC datetime, avoiding the "can't subtract offset-naive and
    offset-aware datetimes" error that only appears in the SQLite test env.
    """
    mock_pd = Mock()
    mock_pd.delay = Mock(return_value=None)

    # Build a thin datetime wrapper that forces .now() to return naive UTC
    import app.tasks.anomaly_tasks as _mod

    _real_datetime = datetime

    class _NaiveDatetime(_real_datetime):
        @classmethod
        def now(cls, tz=None):
            return _real_datetime.utcnow()

    with patch("app.database.SessionLocal", return_value=db), \
         patch("app.tasks.document_tasks.process_document", mock_pd), \
         patch.object(_mod, "datetime", _NaiveDatetime):
        original_close = db.close
        db.close = Mock()
        try:
            result = recover_stuck_documents(max_processing_minutes=max_minutes)
        finally:
            db.close = original_close

    return result


class TestRecoverStuckDocumentsErrorCapture:
    def test_permanently_failed_doc_captures_celery_traceback(self, db: Session):
        """When marking a doc as permanently failed, attempt to capture Celery task traceback."""
        doc = _make_processing_doc(db, updated_minutes_ago=30, recovery_count=4)

        mock_async_result = Mock()
        mock_async_result.traceback = "Traceback: OOM killed during OCR"

        with patch("celery.result.AsyncResult", return_value=mock_async_result):
            result = _run_stuck_recovery(db, max_minutes=5)

        db.refresh(doc)
        assert doc.status == DocumentStatus.ERROR
        meta = doc.document_metadata
        assert "actual_error" in meta
        assert "OOM killed" in meta["actual_error"]
