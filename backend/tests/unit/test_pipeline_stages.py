"""
Unit tests for pipeline_tasks.py

All DB interactions are mocked — no real database is needed.
celery_app import is avoided at module level by using unittest.mock.patch.
"""
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, call, patch

import pytest

from app.models.pipeline import PipelineStage, StageEnum, StageStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_stage_row(stage=StageEnum.OCR, status=StageStatus.PENDING, attempt=0, max_attempts=3):
    row = MagicMock(spec=PipelineStage)
    row.stage = stage
    row.status = status
    row.attempt = attempt
    row.max_attempts = max_attempts
    row.started_at = None
    row.completed_at = None
    row.error_message = None
    row.worker_id = None
    return row


# ---------------------------------------------------------------------------
# update_stage()
# ---------------------------------------------------------------------------


class TestUpdateStage:
    """Test update_stage helper with mocked SessionLocal."""

    def test_creates_new_row_when_none_exists(self):
        """When no PipelineStage row exists, one is created and added to the session."""
        from app.tasks.pipeline_tasks import update_stage

        mock_db = MagicMock()
        mock_query = MagicMock()
        # Simulate db.query(...).filter(...).first() returning None
        mock_db.query.return_value.filter.return_value.first.return_value = None

        result = update_stage(
            document_id=str(uuid.uuid4()),
            stage=StageEnum.OCR,
            status=StageStatus.RUNNING,
            db=mock_db,
        )

        # db.add should have been called with a new PipelineStage instance
        mock_db.add.assert_called_once()
        added_obj = mock_db.add.call_args[0][0]
        assert isinstance(added_obj, PipelineStage)
        mock_db.commit.assert_called_once()

    def test_updates_existing_row(self):
        """When a PipelineStage row already exists, it is updated in place."""
        from app.tasks.pipeline_tasks import update_stage

        existing = _make_stage_row(stage=StageEnum.OCR, attempt=0)

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = existing

        update_stage(
            document_id=str(uuid.uuid4()),
            stage=StageEnum.OCR,
            status=StageStatus.RUNNING,
            db=mock_db,
        )

        # Should NOT add a new row — existing was found
        mock_db.add.assert_not_called()
        # attempt should be incremented
        assert existing.attempt == 1
        mock_db.commit.assert_called_once()

    def test_running_clears_error_and_increments_attempt(self):
        """RUNNING status increments attempt, sets started_at, clears error_message."""
        from app.tasks.pipeline_tasks import update_stage

        existing = _make_stage_row(attempt=1)
        existing.error_message = "previous error"

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = existing

        update_stage(
            document_id=str(uuid.uuid4()),
            stage=StageEnum.OCR,
            status=StageStatus.RUNNING,
            db=mock_db,
        )

        assert existing.status == StageStatus.RUNNING
        assert existing.attempt == 2
        assert existing.error_message is None
        assert existing.started_at is not None

    def test_completed_sets_completed_at(self):
        """COMPLETED status sets completed_at."""
        from app.tasks.pipeline_tasks import update_stage

        existing = _make_stage_row(status=StageStatus.RUNNING, attempt=1)

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = existing

        update_stage(
            document_id=str(uuid.uuid4()),
            stage=StageEnum.OCR,
            status=StageStatus.COMPLETED,
            db=mock_db,
        )

        assert existing.status == StageStatus.COMPLETED
        assert existing.completed_at is not None

    def test_failed_sets_error_message(self):
        """FAILED status records the error_message."""
        from app.tasks.pipeline_tasks import update_stage

        existing = _make_stage_row(status=StageStatus.RUNNING, attempt=1)

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = existing

        update_stage(
            document_id=str(uuid.uuid4()),
            stage=StageEnum.OCR,
            status=StageStatus.FAILED,
            error="OCR exploded",
            db=mock_db,
        )

        assert existing.status == StageStatus.FAILED
        assert existing.error_message == "OCR exploded"

    def test_worker_id_is_recorded(self):
        """worker_id is stored on the row when provided."""
        from app.tasks.pipeline_tasks import update_stage

        existing = _make_stage_row()
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = existing

        update_stage(
            document_id=str(uuid.uuid4()),
            stage=StageEnum.OCR,
            status=StageStatus.RUNNING,
            worker_id="celery-worker-42",
            db=mock_db,
        )

        assert existing.worker_id == "celery-worker-42"

    def test_creates_own_session_when_db_is_none(self):
        """When db=None, update_stage creates and closes its own session.

        update_stage does `from app.database import SessionLocal` inside the
        function body, so we patch `app.database.SessionLocal` — the place the
        name is actually looked up at call time.
        """
        from app.tasks.pipeline_tasks import update_stage

        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = None

        mock_session_factory = MagicMock(return_value=mock_session)

        with patch("app.database.SessionLocal", mock_session_factory):
            update_stage(
                document_id=str(uuid.uuid4()),
                stage=StageEnum.OCR,
                status=StageStatus.RUNNING,
                db=None,
            )

        mock_session.close.assert_called_once()


# ---------------------------------------------------------------------------
# ocr_stage task
# ---------------------------------------------------------------------------


class TestOcrStage:
    """Tests for the ocr_stage Celery task."""

    def test_returns_document_id_on_success(self):
        """ocr_stage returns document_id when work succeeds."""
        doc_id = str(uuid.uuid4())

        with (
            patch("app.tasks.pipeline_tasks.update_stage") as mock_update,
            patch("app.tasks.pipeline_tasks._run_ocr") as mock_run,
        ):
            mock_run.return_value = None

            from app.tasks.pipeline_tasks import ocr_stage

            # Build a minimal fake Celery task context
            task = ocr_stage
            mock_self = MagicMock()
            mock_self.request.id = "fake-task-id"

            result = task.run.__func__(mock_self, doc_id)

        # Verify result
        assert result == doc_id

    def test_update_stage_called_twice(self):
        """update_stage is called with RUNNING then COMPLETED on success."""
        doc_id = str(uuid.uuid4())

        with (
            patch("app.tasks.pipeline_tasks.update_stage") as mock_update,
            patch("app.tasks.pipeline_tasks._run_ocr"),
        ):
            from app.tasks.pipeline_tasks import _stage_task

            mock_self = MagicMock()
            mock_self.request.id = "fake-task-id"

            _stage_task(mock_self, doc_id, StageEnum.OCR, lambda _: None)

            assert mock_update.call_count == 2
            calls = mock_update.call_args_list
            # First call: RUNNING
            assert calls[0] == call(doc_id, StageEnum.OCR, StageStatus.RUNNING, worker_id="fake-task-id")
            # Second call: COMPLETED
            assert calls[1] == call(doc_id, StageEnum.OCR, StageStatus.COMPLETED)

    def test_rejects_when_max_attempts_exhausted(self):
        """Raises Reject when attempt count >= max_attempts."""
        from celery.exceptions import Reject

        from app.tasks.pipeline_tasks import _stage_task

        doc_id = str(uuid.uuid4())
        existing = _make_stage_row(stage=StageEnum.OCR, attempt=3, max_attempts=3)

        mock_self = MagicMock()
        mock_self.request.id = "fake-task-id"

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = existing

        def exploding_work(_):
            raise RuntimeError("OCR failed")

        with (
            patch("app.tasks.pipeline_tasks.update_stage"),
            patch("app.database.SessionLocal", return_value=mock_db),
        ):
            with pytest.raises(Reject):
                _stage_task(mock_self, doc_id, StageEnum.OCR, exploding_work)

    def test_retries_when_attempts_remain(self):
        """Calls self.retry when attempts < max_attempts."""
        from app.tasks.pipeline_tasks import _stage_task

        doc_id = str(uuid.uuid4())
        existing = _make_stage_row(stage=StageEnum.OCR, attempt=1, max_attempts=3)

        mock_self = MagicMock()
        mock_self.request.id = "fake-task-id"
        mock_self.retry.side_effect = Exception("retry raised")

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = existing

        def exploding_work(_):
            raise RuntimeError("transient error")

        with (
            patch("app.tasks.pipeline_tasks.update_stage"),
            patch("app.database.SessionLocal", return_value=mock_db),
        ):
            with pytest.raises(Exception, match="retry raised"):
                _stage_task(mock_self, doc_id, StageEnum.OCR, exploding_work)

        mock_self.retry.assert_called_once()


# ---------------------------------------------------------------------------
# embed_stage task
# ---------------------------------------------------------------------------


class TestEmbedStage:
    def test_returns_document_id_on_success(self):
        """embed_stage returns document_id on success."""
        doc_id = str(uuid.uuid4())

        with (
            patch("app.tasks.pipeline_tasks.update_stage"),
            patch("app.tasks.pipeline_tasks._run_embed"),
        ):
            from app.tasks.pipeline_tasks import _stage_task

            mock_self = MagicMock()
            mock_self.request.id = "fake-task-id"

            result = _stage_task(mock_self, doc_id, StageEnum.EMBEDDED, lambda _: None)

        assert result == doc_id


# ---------------------------------------------------------------------------
# finalize_stage task
# ---------------------------------------------------------------------------


class TestFinalizeStage:
    def test_marks_document_pipeline_stage_as_enriched(self):
        """finalize_stage sets doc.pipeline_stage = 'enriched'."""
        doc_id = str(uuid.uuid4())
        doc_uuid = uuid.UUID(doc_id)

        mock_doc = MagicMock()
        mock_doc.id = doc_uuid

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_doc

        mock_session_factory = MagicMock(return_value=mock_db)

        with (
            patch("app.tasks.pipeline_tasks.update_stage") as mock_update,
            patch("app.database.SessionLocal", mock_session_factory),
        ):
            from app.tasks.pipeline_tasks import finalize_stage

            result = finalize_stage(doc_id)

        assert result == doc_id
        assert mock_doc.pipeline_stage == "enriched"
        mock_db.commit.assert_called_once()
        mock_db.close.assert_called_once()

        # update_stage called with ENRICHED / COMPLETED
        mock_update.assert_called_once_with(doc_id, StageEnum.ENRICHED, StageStatus.COMPLETED)

    def test_handles_missing_document_gracefully(self):
        """finalize_stage does not raise if document row is not found."""
        doc_id = str(uuid.uuid4())

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        mock_session_factory = MagicMock(return_value=mock_db)

        with (
            patch("app.tasks.pipeline_tasks.update_stage"),
            patch("app.database.SessionLocal", mock_session_factory),
        ):
            from app.tasks.pipeline_tasks import finalize_stage

            result = finalize_stage(doc_id)

        assert result == doc_id
        mock_db.commit.assert_not_called()
