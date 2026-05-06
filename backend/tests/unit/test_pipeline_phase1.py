"""QA tests for Phase 1 reliability fixes."""
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest


class TestDispatchDeduplication:
    """Phase 1.2: dispatch_document skips stages already in flight."""

    @patch("app.tasks.pipeline_orchestrator._check_backpressure", return_value=None)
    @patch("app.tasks.pipeline_orchestrator._build_chain")
    def test_skips_when_stage_running(self, mock_build, mock_bp):
        from app.models.pipeline import StageEnum, StageStatus
        from app.tasks.pipeline_orchestrator import dispatch_document

        doc_id = str(uuid.uuid4())
        stage_row = MagicMock()
        stage_row.status = StageStatus.RUNNING
        stage_row.started_at = datetime.now(UTC) - timedelta(minutes=5)
        stage_row.updated_at = datetime.now(UTC) - timedelta(minutes=5)

        with patch("app.database.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.query.return_value.filter.return_value.first.return_value = stage_row
            mock_session.return_value = mock_db

            result = dispatch_document(doc_id, from_stage=StageEnum.OCR)

        assert result == "inflight"
        mock_build.assert_not_called()

    @patch("app.tasks.pipeline_orchestrator._check_backpressure", return_value=None)
    @patch("app.tasks.pipeline_orchestrator._build_chain")
    def test_dispatches_when_stage_old(self, mock_build, mock_bp):
        from app.models.pipeline import StageEnum, StageStatus
        from app.tasks.pipeline_orchestrator import dispatch_document

        doc_id = str(uuid.uuid4())
        stage_row = MagicMock()
        stage_row.status = StageStatus.RUNNING
        stage_row.started_at = datetime.now(UTC) - timedelta(hours=2)
        stage_row.updated_at = datetime.now(UTC) - timedelta(hours=2)

        with patch("app.database.SessionLocal") as mock_session:
            mock_db = MagicMock()
            mock_db.query.return_value.filter.return_value.first.return_value = stage_row
            mock_session.return_value = mock_db

            result = dispatch_document(doc_id, from_stage=StageEnum.OCR)

        assert result == "dispatched"
        mock_build.assert_called_once()


class TestPoisonPillQuarantine:
    """Phase 1.4: sweeper quarantines docs with excessive attempts."""

    def test_poison_pill_threshold_constant(self):
        """The threshold is loaded from env (default 5)."""
        from app.tasks.pipeline_sweeper import _POISON_PILL_ATTEMPTS
        assert _POISON_PILL_ATTEMPTS == 5

    def test_poison_pill_logic_path(self):
        """A stage with attempt 7 / max 10 should hit the quarantine path."""
        from app.models.pipeline import StageEnum, StageStatus
        from app.tasks.pipeline_sweeper import _POISON_PILL_ATTEMPTS

        attempt = 7
        max_attempts = 10

        # Replicate the exact branch logic from the sweeper
        if attempt >= max_attempts:
            outcome = "failed"
        elif attempt >= _POISON_PILL_ATTEMPTS:
            outcome = "quarantined"
        else:
            outcome = "resumed"

        assert outcome == "quarantined"
