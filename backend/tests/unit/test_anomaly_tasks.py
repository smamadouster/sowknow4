"""
Unit tests for anomaly recovery tasks.
"""

import uuid
from datetime import datetime, timedelta, timezone
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
        created_at=datetime.now(timezone.utc) - timedelta(minutes=created_minutes_ago),
        updated_at=datetime.now(timezone.utc) - timedelta(minutes=created_minutes_ago),
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
