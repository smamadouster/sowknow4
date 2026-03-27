"""Tests for DLQ service — verify sync/async boundary is clean."""
import sys
from unittest.mock import MagicMock


def _make_db_mock():
    """Return a fresh MagicMock that behaves like a SQLAlchemy session."""
    mock_db = MagicMock()
    # refresh() should return the record that was added
    mock_db.refresh.side_effect = lambda obj: obj
    return mock_db


def _load_dlq_service_with_mocks(mock_db):
    """
    Inject lightweight stubs for heavy modules, then import DeadLetterQueueService.

    Because dlq_service.py uses deferred imports (inside method bodies),
    we inject via sys.modules so those local `from app.X import Y` calls
    resolve to our stubs instead of the real modules.
    """
    fake_database = MagicMock()
    fake_database.SessionLocal.return_value = mock_db

    fake_model_instance = MagicMock()
    fake_failed_task_cls = MagicMock(return_value=fake_model_instance)
    fake_models = MagicMock()
    fake_models.FailedCeleryTask = fake_failed_task_cls

    # Ensure a clean import each call
    sys.modules.pop("app.services.dlq_service", None)

    sys.modules["app.database"] = fake_database
    sys.modules["app.models.failed_task"] = fake_models

    from app.services.dlq_service import DeadLetterQueueService
    return DeadLetterQueueService, fake_database, fake_models


class TestDLQStoreFailedTask:
    """Test store_failed_task handles DB and alerts correctly."""

    def test_store_failed_task_commits_to_db(self):
        """Verify failed task is stored via sync DB session."""
        mock_db = _make_db_mock()
        DeadLetterQueueService, _, _ = _load_dlq_service_with_mocks(mock_db)

        result = DeadLetterQueueService.store_failed_task(
            task_name="test.task",
            task_id="abc-123",
            args=("arg1",),
            kwargs={"key": "val"},
            exception=ValueError("test error"),
            traceback_str="Traceback ...",
        )

        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()
        mock_db.close.assert_called_once()
        assert result is not None

    def test_store_failed_task_rolls_back_on_error(self):
        """Verify rollback on DB error."""
        mock_db = _make_db_mock()
        mock_db.commit.side_effect = Exception("DB error")
        DeadLetterQueueService, _, _ = _load_dlq_service_with_mocks(mock_db)

        result = DeadLetterQueueService.store_failed_task(
            task_name="test.task",
            task_id="abc-123",
            args=(),
            kwargs={},
            exception=ValueError("test"),
        )

        mock_db.rollback.assert_called_once()
        mock_db.close.assert_called_once()
        assert result is None
