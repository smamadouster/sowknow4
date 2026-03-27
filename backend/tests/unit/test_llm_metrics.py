"""Tests for LLM request metrics."""
import pytest
from app.services.prometheus_metrics import (
    llm_request_duration,
    llm_request_total,
    llm_retry_total,
)


class TestLLMMetrics:
    """Verify LLM metrics are defined and functional."""

    def test_llm_request_duration_metric_exists(self):
        """LLM request duration metric should be defined."""
        assert llm_request_duration is not None
        assert llm_request_duration.name == "sowknow_llm_request_duration_seconds"

    def test_llm_request_total_metric_exists(self):
        """LLM request count metric should be defined."""
        assert llm_request_total is not None
        assert llm_request_total.name == "sowknow_llm_requests_total"

    def test_llm_retry_total_metric_exists(self):
        """LLM retry count metric should be defined."""
        assert llm_retry_total is not None
        assert llm_retry_total.name == "sowknow_llm_retries_total"

    def test_can_record_request_duration(self):
        """Should record duration by provider."""
        llm_request_duration.observe(1.5, labels={"provider": "openrouter", "model": "mistral-small"})
        assert llm_request_duration._values[("openrouter", "mistral-small")] == 1.5

    def test_can_increment_request_count(self):
        """Should count requests by provider and status."""
        llm_request_total.inc(labels={"provider": "minimax", "status": "success"})
        llm_request_total.inc(labels={"provider": "minimax", "status": "success"})
        assert llm_request_total._values[("minimax", "success")] == 2.0

    def test_can_increment_retry_count(self):
        """Should count retries by provider."""
        llm_retry_total.inc(labels={"provider": "ollama"})
        assert llm_retry_total._values[("ollama",)] == 1.0
