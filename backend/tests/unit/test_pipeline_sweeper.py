"""Unit tests for pipeline_sweeper — unified recovery task."""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch


def _make_stage(
    stage_enum,
    status_enum,
    attempt=1,
    max_attempts=3,
    started_at=None,
    document_id=None,
):
    """Helper to build a mock PipelineStage."""
    ps = MagicMock()
    ps.document_id = document_id or uuid.uuid4()
    ps.stage = stage_enum
    ps.status = status_enum
    ps.attempt = attempt
    ps.max_attempts = max_attempts
    ps.started_at = started_at or (datetime.now(timezone.utc) - timedelta(hours=2))
    ps.error_message = None
    return ps


class TestResumesStuckRunningStages:
    """Stage RUNNING for > 2x hard_timeout with attempt < max_attempts → reset to PENDING + re-dispatch."""

    @patch("app.database.SessionLocal")
    @patch("app.tasks.pipeline_orchestrator.dispatch_document")
    def test_resumes_stuck_running_stages(self, mock_dispatch, mock_session_local):
        from app.models.pipeline import StageEnum, StageStatus
        from app.tasks.pipeline_sweeper import pipeline_sweeper

        mock_dispatch.return_value = "dispatched"

        doc_id = uuid.uuid4()
        stuck_stage = _make_stage(
            StageEnum.OCR,
            StageStatus.RUNNING,
            attempt=1,
            max_attempts=3,
            document_id=doc_id,
        )

        db = MagicMock()
        mock_session_local.return_value = db

        # Query returning stuck stage only for the first stage (OCR), empty for others
        ocr_stuck_query = MagicMock()
        ocr_stuck_query.filter.return_value = ocr_stuck_query
        ocr_stuck_query.all.return_value = [stuck_stage]

        empty_query = MagicMock()
        empty_query.filter.return_value = empty_query
        empty_query.all.return_value = []

        call_count = [0]

        def query_side_effect(model):
            call_count[0] += 1
            if call_count[0] == 1:  # first stage query (OCR) returns stuck stage
                return ocr_stuck_query
            return empty_query

        db.query.side_effect = query_side_effect

        result = pipeline_sweeper()

        assert result["stuck_resumed"] == 1
        assert result["stuck_failed"] == 0
        assert stuck_stage.status == StageStatus.PENDING
        mock_dispatch.assert_called_once_with(str(doc_id), from_stage=StageEnum.OCR)


class TestMarksExhaustedStagesAsFailed:
    """Stage RUNNING for > 2x hard_timeout with attempt >= max_attempts → mark FAILED."""

    @patch("app.database.SessionLocal")
    @patch("app.tasks.pipeline_orchestrator.dispatch_document")
    def test_marks_exhausted_stages_as_failed(self, mock_dispatch, mock_session_local):
        from app.models.pipeline import StageEnum, StageStatus
        from app.tasks.pipeline_sweeper import pipeline_sweeper

        doc_id = uuid.uuid4()
        exhausted_stage = _make_stage(
            StageEnum.OCR,
            StageStatus.RUNNING,
            attempt=3,
            max_attempts=3,
            document_id=doc_id,
        )

        db = MagicMock()
        mock_session_local.return_value = db

        # Return exhausted stage only for first stage (OCR), empty for all others
        ocr_stuck_query = MagicMock()
        ocr_stuck_query.filter.return_value = ocr_stuck_query
        ocr_stuck_query.all.return_value = [exhausted_stage]

        empty_query = MagicMock()
        empty_query.filter.return_value = empty_query
        empty_query.all.return_value = []

        call_count = [0]

        def query_side_effect(model):
            call_count[0] += 1
            if call_count[0] == 1:  # first stage query (OCR) returns exhausted stage
                return ocr_stuck_query
            return empty_query

        db.query.side_effect = query_side_effect

        result = pipeline_sweeper()

        assert result["stuck_failed"] == 1
        assert result["stuck_resumed"] == 0
        assert exhausted_stage.status == StageStatus.FAILED
        assert "Sweeper: stuck in RUNNING" in exhausted_stage.error_message
        mock_dispatch.assert_not_called()


class TestDispatchesBackpressuredDocuments:
    """Documents with UPLOADED completed but no OCR stage → dispatch."""

    @patch("app.database.SessionLocal")
    @patch("app.tasks.pipeline_orchestrator.dispatch_document")
    def test_dispatches_backpressured_documents(self, mock_dispatch, mock_session_local):
        from app.models.pipeline import StageEnum, StageStatus
        from app.tasks.pipeline_sweeper import pipeline_sweeper

        mock_dispatch.return_value = "dispatched"

        doc_id = uuid.uuid4()
        uploaded_stage = _make_stage(
            StageEnum.UPLOADED,
            StageStatus.COMPLETED,
            document_id=doc_id,
        )

        db = MagicMock()
        mock_session_local.return_value = db

        # Queries for stuck stages return empty
        stuck_query = MagicMock()
        stuck_query.filter.return_value = stuck_query
        stuck_query.all.return_value = []

        # Query for UPLOADED completed returns one document
        uploaded_query = MagicMock()
        uploaded_query.filter.return_value = uploaded_query
        uploaded_query.all.return_value = [uploaded_stage]

        # Query for OCR stage returns None (not started)
        ocr_check_query = MagicMock()
        ocr_check_query.filter.return_value = ocr_check_query
        ocr_check_query.first.return_value = None

        call_count = [0]

        def query_side_effect(model):
            call_count[0] += 1
            # Step 1: 6 stuck-stage queries; Step 2: 7 pairs × 2 queries = 14
            # Total before step 3: 20 queries
            if call_count[0] <= 20:
                return stuck_query
            if call_count[0] == 21:
                return uploaded_query
            return ocr_check_query

        db.query.side_effect = query_side_effect

        result = pipeline_sweeper()

        assert result["backpressure_dispatched"] == 1
        assert result["stuck_resumed"] == 0
        assert result["stuck_failed"] == 0
        mock_dispatch.assert_called_once_with(str(doc_id))

    @patch("app.database.SessionLocal")
    @patch("app.tasks.pipeline_orchestrator.dispatch_document")
    def test_skips_documents_with_ocr_already_running(self, mock_dispatch, mock_session_local):
        from app.models.pipeline import StageEnum, StageStatus
        from app.tasks.pipeline_sweeper import pipeline_sweeper

        doc_id = uuid.uuid4()
        uploaded_stage = _make_stage(
            StageEnum.UPLOADED,
            StageStatus.COMPLETED,
            document_id=doc_id,
        )

        existing_ocr = MagicMock()
        existing_ocr.status = StageStatus.RUNNING

        db = MagicMock()
        mock_session_local.return_value = db

        stuck_query = MagicMock()
        stuck_query.filter.return_value = stuck_query
        stuck_query.all.return_value = []

        uploaded_query = MagicMock()
        uploaded_query.filter.return_value = uploaded_query
        uploaded_query.all.return_value = [uploaded_stage]

        ocr_check_query = MagicMock()
        ocr_check_query.filter.return_value = ocr_check_query
        ocr_check_query.first.return_value = existing_ocr

        call_count = [0]

        def query_side_effect(model):
            call_count[0] += 1
            # Step 1: 6 queries; Step 2: 14 queries; Step 3 starts at 21
            if call_count[0] <= 20:
                return stuck_query
            if call_count[0] == 21:
                return uploaded_query
            return ocr_check_query

        db.query.side_effect = query_side_effect

        result = pipeline_sweeper()

        assert result["backpressure_dispatched"] == 0
        mock_dispatch.assert_not_called()


class TestReturnsResultDict:
    """Result dict has all expected keys."""

    @patch("app.database.SessionLocal")
    @patch("app.tasks.pipeline_orchestrator.dispatch_document")
    def test_returns_result_dict(self, mock_dispatch, mock_session_local):
        from app.tasks.pipeline_sweeper import pipeline_sweeper

        db = MagicMock()
        mock_session_local.return_value = db

        empty_query = MagicMock()
        empty_query.filter.return_value = empty_query
        empty_query.all.return_value = []
        db.query.return_value = empty_query

        result = pipeline_sweeper()

        assert isinstance(result, dict)
        assert "timestamp" in result
        assert "stuck_resumed" in result
        assert "stuck_failed" in result
        assert "backpressure_dispatched" in result
        assert result["stuck_resumed"] == 0
        assert result["stuck_failed"] == 0
        assert result["backpressure_dispatched"] == 0
        # timestamp is valid ISO format
        datetime.fromisoformat(result["timestamp"])

    @patch("app.database.SessionLocal")
    @patch("app.tasks.pipeline_orchestrator.dispatch_document")
    def test_closes_db_session_on_success(self, mock_dispatch, mock_session_local):
        from app.tasks.pipeline_sweeper import pipeline_sweeper

        db = MagicMock()
        mock_session_local.return_value = db

        empty_query = MagicMock()
        empty_query.filter.return_value = empty_query
        empty_query.all.return_value = []
        db.query.return_value = empty_query

        pipeline_sweeper()

        db.close.assert_called_once()

    @patch("app.database.SessionLocal")
    @patch("app.tasks.pipeline_orchestrator.dispatch_document")
    def test_closes_db_session_on_error(self, mock_dispatch, mock_session_local):
        from app.tasks.pipeline_sweeper import pipeline_sweeper

        db = MagicMock()
        mock_session_local.return_value = db
        db.query.side_effect = RuntimeError("DB exploded")

        try:
            pipeline_sweeper()
        except RuntimeError:
            pass

        db.close.assert_called_once()
