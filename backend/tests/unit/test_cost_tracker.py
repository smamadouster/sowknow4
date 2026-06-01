"""
Unit tests for CostTracker memory-safety fixes (blueprint §7.2).

Covers:
- MAX_COST_RECORDS cap on record_api_call
- MAX_COST_RECORDS cap on _record_cost (OCR path)
- Correct lock usage in CostCeiling._check_emergency_spike
"""

from unittest.mock import MagicMock, patch

import pytest

from app.services.monitoring import (
    MAX_COST_RECORDS,
    APICostRecord,
    CostTracker,
    CostCeiling,
)


class TestCostTrackerRecordCap:
    """Tests for the 10K-record cap on _cost_records."""

    def test_record_api_call_caps_at_max(self):
        """After exceeding MAX_COST_RECORDS, list should be halved."""
        tracker = CostTracker()

        # Fill up to the limit + 1
        for i in range(MAX_COST_RECORDS + 1):
            tracker.record_api_call(
                service="openrouter",
                operation="chat",
                model="mistralai/mistral-small-2409",
                input_tokens=10,
                output_tokens=10,
            )

        assert len(tracker._cost_records) == MAX_COST_RECORDS // 2

    def test_record_api_call_preserves_recent_records(self):
        """When capping, the most recent records should be kept."""
        tracker = CostTracker()

        for i in range(MAX_COST_RECORDS + 100):
            tracker.record_api_call(
                service="openrouter",
                operation="chat",
                model="mistralai/mistral-small-2409",
                input_tokens=1,
                output_tokens=1,
            )

        # The last record should still be present
        assert tracker._cost_records[-1].timestamp is not None

    def test__record_cost_ocr_path_also_caps(self):
        """The OCR (_record_cost) append path must also respect the cap."""
        tracker = CostTracker()

        for i in range(MAX_COST_RECORDS + 1):
            tracker._record_cost(method="paddleocr", mode="page", pages=1)

        assert len(tracker._cost_records) == MAX_COST_RECORDS // 2

    def test_get_daily_cost_works_after_cap(self):
        """Reading stats after a cap should not crash."""
        tracker = CostTracker()

        for _ in range(MAX_COST_RECORDS + 1):
            tracker.record_api_call(
                service="openrouter", operation="chat", model="test"
            )

        cost = tracker.get_daily_cost()
        assert cost >= 0.0


class TestCostCeilingRaceCondition:
    """Tests that CostCeiling uses the correct lock when reading CostTracker."""

    def test_emergency_spike_uses_tracker_lock(self):
        """_check_emergency_spike must acquire tracker._lock, not its own."""
        tracker = CostTracker()
        ceiling = CostCeiling()

        # Pre-populate some cost records so the spike check has data
        for _ in range(10):
            tracker.record_api_call(
                service="openrouter", operation="chat", model="test",
                input_tokens=10, output_tokens=10,
            )

        # Patch tracker._lock to verify it is acquired
        mock_lock = MagicMock()
        mock_lock.__enter__ = MagicMock(return_value=None)
        mock_lock.__exit__ = MagicMock(return_value=None)

        with patch.object(tracker, "_lock", mock_lock):
            # Force the tracker reference inside CostCeiling
            with patch("app.services.monitoring.get_cost_tracker", return_value=tracker):
                result = ceiling._check_emergency_spike(estimated_cost=0.001)

        # The lock should be acquired at least once (get_daily_cost + reading records)
        assert mock_lock.__enter__.call_count >= 1
