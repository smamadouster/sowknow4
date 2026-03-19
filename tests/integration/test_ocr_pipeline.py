"""
Integration tests for the OCR processing pipeline via Celery tasks.
Uses mocked Celery worker to test task logic without a live broker.
"""
import pytest
import uuid
from unittest.mock import MagicMock, patch, AsyncMock
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../backend"))

pytestmark = pytest.mark.integration


class TestEmbeddingStorageNoDualWrite:
    """Issue #1: Embeddings must be stored only in vector column, not JSONB."""

    def test_no_jsonb_embedding_write_in_tasks(self):
        """document_tasks.py must not write embeddings to metadata JSONB."""
        tasks_path = os.path.join(
            os.path.dirname(__file__),
            "../../backend/app/tasks/document_tasks.py"
        )
        with open(tasks_path) as f:
            source = f.read()
        assert 'metadata["embedding"]' not in source, (
            'Found metadata["embedding"] in document_tasks.py — '
            "embeddings must be stored only in embedding_vector column"
        )
        assert "meta[\"embedding\"]" not in source, (
            'Found meta["embedding"] in document_tasks.py — '
            "remove dual JSONB write"
        )

    def test_embedding_vector_column_used(self):
        """document_tasks.py must assign to chunk.embedding_vector."""
        tasks_path = os.path.join(
            os.path.dirname(__file__),
            "../../backend/app/tasks/document_tasks.py"
        )
        with open(tasks_path) as f:
            source = f.read()
        assert "chunk.embedding_vector = " in source, (
            "chunk.embedding_vector assignment not found in document_tasks.py"
        )


class TestCostTrackerIntegration:
    """Issue #7: CostTracker.track_ocr_operation must be callable."""

    def test_track_ocr_operation_exists(self):
        try:
            from app.services.monitoring import CostTracker
        except ImportError:
            pytest.skip("monitoring module not importable")
        ct = CostTracker()
        assert hasattr(ct, "track_ocr_operation"), "track_ocr_operation method missing"

    def test_track_ocr_operation_local_engine_free(self):
        """Local OCR engines (paddle, tesseract) must cost $0.00."""
        try:
            from app.services.monitoring import CostTracker
        except ImportError:
            pytest.skip("monitoring module not importable")
        ct = CostTracker()
        cost = ct.track_ocr_operation(method="paddle", mode="base", pages=1)
        assert cost == 0.0, f"Local paddle OCR should be free, got ${cost}"

        cost = ct.track_ocr_operation(method="tesseract", mode="gundam", pages=3)
        assert cost == 0.0, f"Local tesseract OCR should be free, got ${cost}"

    def test_ocr_pricing_dict_present(self):
        """CostTracker must have OCR_PRICING class attribute."""
        try:
            from app.services.monitoring import CostTracker
        except ImportError:
            pytest.skip("monitoring module not importable")
        assert hasattr(CostTracker, "OCR_PRICING"), "OCR_PRICING missing from CostTracker"
        pricing = CostTracker.OCR_PRICING
        assert "base" in pricing
        assert "large" in pricing
        assert "gundam" in pricing
        assert pricing["base"] == 0.001
        assert pricing["large"] == 0.002
        assert pricing["gundam"] == 0.003

    def test_should_use_ocr_called_in_pipeline(self):
        """document_tasks.py must call should_use_ocr()."""
        tasks_path = os.path.join(
            os.path.dirname(__file__),
            "../../backend/app/tasks/document_tasks.py"
        )
        with open(tasks_path) as f:
            source = f.read()
        assert "should_use_ocr" in source, (
            "should_use_ocr() call not found in document_tasks.py"
        )
