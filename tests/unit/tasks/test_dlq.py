"""
Unit tests for the Dead Letter Queue (DLQ) service.

Tests DLQ insertion and retrieval using a fully mocked database session
so no real PostgreSQL/pgvector connection is required.
"""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

# Ensure backend/ is on sys.path (also done by conftest.py, belt-and-suspenders)
_BACKEND = str(Path(__file__).parent.parent.parent.parent / "backend")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("APP_ENV", "test")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_session():
    """Return a MagicMock that behaves like an SQLAlchemy Session."""
    session = MagicMock()
    session.add = MagicMock()
    session.commit = MagicMock()
    session.refresh = MagicMock()
    session.rollback = MagicMock()
    session.close = MagicMock()
    # query().filter().count() → 0, query().filter().all() → []
    mock_query = MagicMock()
    mock_query.filter.return_value = mock_query
    mock_query.order_by.return_value = mock_query
    mock_query.offset.return_value = mock_query
    mock_query.limit.return_value = mock_query
    mock_query.count.return_value = 0
    mock_query.all.return_value = []
    session.query.return_value = mock_query
    return session


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_store_failed_task_inserts_record():
    """
    DeadLetterQueueService.store_failed_task should create a FailedCeleryTask
    record, add it to the session, and commit.
    """
    mock_session = _make_mock_session()
    mock_record = MagicMock()
    mock_record.id = str(uuid.uuid4())

    with (
        patch("app.database.SessionLocal", return_value=mock_session),
        patch("app.models.failed_task.FailedCeleryTask", return_value=mock_record),
        patch("app.services.alert_service.alert_service"),
    ):
        from app.services.dlq_service import DeadLetterQueueService

        result = DeadLetterQueueService.store_failed_task(
            task_name="app.tasks.document_tasks.process_document",
            task_id="task-unit-test-001",
            args=("doc-uuid-abc",),
            kwargs={"task_type": "full_pipeline"},
            exception=ValueError("test error — disk full"),
            traceback_str="Traceback (most recent call last):\n  File ...\nValueError: test error",
            retry_count=3,
            extra_metadata={"document_id": "doc-uuid-abc"},
        )

    # session.add should have been called exactly once with our mock record
    mock_session.add.assert_called_once_with(mock_record)
    mock_session.commit.assert_called_once()
    mock_session.close.assert_called_once()


def test_store_failed_task_handles_db_error_gracefully():
    """
    If the database operation raises an exception, store_failed_task should
    swallow it and return None (DLQ must never crash the caller).
    """
    mock_session = _make_mock_session()
    mock_session.add.side_effect = Exception("simulated DB failure")

    with (
        patch("app.database.SessionLocal", return_value=mock_session),
        patch("app.services.alert_service.alert_service"),
    ):
        from app.services.dlq_service import DeadLetterQueueService

        result = DeadLetterQueueService.store_failed_task(
            task_name="app.tasks.document_tasks.generate_embeddings",
            task_id="task-unit-test-002",
            args=(["chunk-1", "chunk-2"],),
            kwargs={},
            exception=RuntimeError("embedding model OOM"),
            retry_count=2,
        )

    # Must not raise; must return None
    assert result is None
    mock_session.rollback.assert_called_once()
    mock_session.close.assert_called_once()


def test_list_failed_tasks_returns_paginated_structure():
    """
    DeadLetterQueueService.list_failed_tasks should return a dict with
    'items', 'total', 'page', and 'page_size' keys.
    """
    mock_session = _make_mock_session()
    # Simulate 0 records in the table
    mock_session.query.return_value.filter.return_value.count.return_value = 0
    mock_session.query.return_value.filter.return_value.order_by.return_value\
        .offset.return_value.limit.return_value.all.return_value = []
    mock_session.query.return_value.count.return_value = 0
    mock_session.query.return_value.order_by.return_value\
        .offset.return_value.limit.return_value.all.return_value = []

    with patch("app.database.SessionLocal", return_value=mock_session):
        from app.services.dlq_service import DeadLetterQueueService

        result = DeadLetterQueueService.list_failed_tasks(page=1, page_size=10)

    assert "items" in result
    assert "total" in result
    assert "page" in result
    assert "page_size" in result
    assert result["page"] == 1
    assert result["page_size"] == 10
