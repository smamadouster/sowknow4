"""Tests for LLM request metrics."""
from app.services.prometheus_metrics import (
    Counter,
    Histogram,
    get_metrics,
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
        assert isinstance(llm_request_duration, Histogram)

    def test_llm_request_total_metric_exists(self):
        """LLM request count metric should be defined."""
        assert llm_request_total is not None
        assert llm_request_total.name == "sowknow_llm_requests_total"
        assert isinstance(llm_request_total, Counter)

    def test_llm_retry_total_metric_exists(self):
        """LLM retry count metric should be defined."""
        assert llm_retry_total is not None
        assert llm_retry_total.name == "sowknow_llm_retries_total"
        assert isinstance(llm_retry_total, Counter)

    def test_can_record_request_duration(self):
        """Should record duration by provider."""
        llm_request_duration.observe(1.5, labels={"provider": "openrouter", "model": "mistral-small"})
        assert 1.5 in llm_request_duration._observations[("openrouter", "mistral-small")]

    def test_can_increment_request_count(self):
        """Should count requests by provider and status."""
        # Reset to avoid cross-test pollution
        llm_request_total._values[("test-minimax", "success")] = 0
        llm_request_total.inc(labels={"provider": "test-minimax", "status": "success"})
        llm_request_total.inc(labels={"provider": "test-minimax", "status": "success"})
        assert llm_request_total._values[("test-minimax", "success")] == 2.0

    def test_can_increment_retry_count(self):
        """Should count retries by provider."""
        llm_retry_total.inc(labels={"provider": "test-ollama"})
        assert llm_retry_total._values[("test-ollama",)] >= 1.0

    def test_metrics_in_registry_export(self):
        """LLM metrics must appear in the /metrics export."""
        export = get_metrics().export()
        assert "sowknow_llm_request_duration_seconds" in export
        assert "sowknow_llm_requests_total" in export
        assert "sowknow_llm_retries_total" in export
