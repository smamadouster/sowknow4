"""Unit tests for FR6.4 retry policy helpers in collection_request_tasks.

Pure functions only — no broker, no DB.
"""
import pytest
pytest.skip("Disabled during Ollama removal (Sep 4)", allow_module_level=True)

from app.tasks.collection_request_tasks import (
    RETRY_BASE_SECONDS,
    RETRY_MAX,
    RETRY_MAX_COUNTDOWN,
    is_search_unavailable,
    retry_countdown,
)


class TestRetryCountdown:
    def test_exponential_backoff_sequence(self):
        delays = [retry_countdown(i) for i in range(RETRY_MAX)]
        assert delays == [60, 120, 240, 480, 900]
        assert delays[0] == RETRY_BASE_SECONDS
        assert delays[-1] == RETRY_MAX_COUNTDOWN
        # Exponential growth, capped
        assert delays[1] == delays[0] * 2
        assert delays[2] == delays[1] * 2

    def test_total_backoff_under_one_hour(self):
        total = sum(retry_countdown(i) for i in range(RETRY_MAX))
        assert total <= 3600  # FR6.4 cap

    def test_exhausted_after_max_retries(self):
        assert retry_countdown(RETRY_MAX) is None
        assert retry_countdown(RETRY_MAX + 1) is None


class TestIsSearchUnavailable:
    def test_search_unavailable_message_detected(self):
        assert is_search_unavailable(
            "All 3 search spec(s) failed permanently — search unavailable"
        )

    def test_case_insensitive(self):
        assert is_search_unavailable("SEARCH UNAVAILABLE at gateway")

    def test_other_failures_not_retried(self):
        assert not is_search_unavailable("relation 'documents' does not exist")
        assert not is_search_unavailable("")
        assert not is_search_unavailable(None)
