"""
Unit tests for OpenRouterThrottle — provider-aware dynamic throttling with
adaptive backoff (blueprint §2.3 Tier C).
"""
import time

import pytest

from app.services.openrouter_throttle import (
    ADAPTIVE_BACKOFF_FACTOR,
    ADAPTIVE_BACKOFF_TTL_SECONDS,
    OPENROUTER_RATE_LIMITS,
    OpenRouterThrottle,
    _detect_tier,
)


class FakeRedis:
    """In-memory Redis mock for unit tests."""

    def __init__(self):
        self._data = {}
        self._ttls = {}

    def get(self, key):
        return self._data.get(key)

    def set(self, key, value):
        self._data[key] = str(value)

    def setex(self, key, seconds, value):
        self._data[key] = str(value)
        self._ttls[key] = seconds

    def incr(self, key):
        val = int(self._data.get(key, 0))
        self._data[key] = str(val + 1)
        return val + 1

    def expire(self, key, seconds):
        self._ttls[key] = seconds

    def exists(self, key):
        return 1 if key in self._data else 0

    def delete(self, key):
        self._data.pop(key, None)
        self._ttls.pop(key, None)

    def pipeline(self):
        return FakePipeline(self)


class FakePipeline:
    def __init__(self, redis):
        self._redis = redis
        self._ops = []

    def incr(self, key):
        self._ops.append(("incr", key))
        return self

    def expire(self, key, seconds):
        self._ops.append(("expire", key, seconds))
        return self

    def execute(self):
        results = []
        for op in self._ops:
            if op[0] == "incr":
                results.append(self._redis.incr(op[1]))
            elif op[0] == "expire":
                results.append(self._redis.expire(op[1], op[2]))
        self._ops = []
        return results


@pytest.fixture
def throttle():
    return OpenRouterThrottle(redis_client=FakeRedis())


class TestTierDetection:
    """Model-to-tier mapping must match the blueprint."""

    def test_free_suffix_detected(self):
        assert _detect_tier("meta-llama/llama-3.3-70b-instruct:free") == "free"
        assert _detect_tier("qwen/qwen3-235b-a22b:free") == "free"

    def test_pro_models_detected(self):
        assert _detect_tier("anthropic/claude-3.5-sonnet") == "pro"
        assert _detect_tier("deepseek/deepseek-v4-pro") == "pro"
        assert _detect_tier("moonshotai/kimi-k2.6") == "pro"

    def test_standard_models_detected(self):
        assert _detect_tier("mistralai/mistral-small-2409") == "standard"
        assert _detect_tier("google/gemini-2.0-flash-001") == "standard"
        assert _detect_tier("qwen/qwen3.5-plus-20260420") == "standard"


class TestCheckAllowed:
    """Pre-flight rate-limit checks."""

    def test_allowed_when_no_redis(self):
        throttle = OpenRouterThrottle(redis_client=None)
        assert throttle.check_allowed("mistralai/mistral-small-2409") is True

    def test_allowed_under_limits(self, throttle):
        assert throttle.check_allowed("mistralai/mistral-small-2409") is True

    def test_blocked_when_rpm_exceeded(self, throttle):
        model = "mistralai/mistral-small-2409"
        limit = OPENROUTER_RATE_LIMITS["standard"]["rpm"]
        # Exhaust the RPM bucket
        for _ in range(limit):
            throttle.record_request(model)
        assert throttle.check_allowed(model) is False

    def test_blocked_when_rpd_exceeded(self, throttle):
        model = "mistralai/mistral-small-2409"
        limit = OPENROUTER_RATE_LIMITS["standard"]["rpd"]
        # Exhaust the RPD bucket by simulating high count
        key = throttle._rpd_key("standard", throttle._current_buckets()[1])
        throttle._get_redis()._data[key] = str(limit)
        assert throttle.check_allowed(model) is False

    def test_free_tier_stricter_limits(self, throttle):
        model = "meta-llama/llama-3.3-70b-instruct:free"
        limit = OPENROUTER_RATE_LIMITS["free"]["rpm"]
        for _ in range(limit):
            throttle.record_request(model)
        assert throttle.check_allowed(model) is False

    def test_pro_tier_higher_limits(self, throttle):
        model = "anthropic/claude-3.5-sonnet"
        limit = OPENROUTER_RATE_LIMITS["pro"]["rpm"]
        # Pro tier has 500 RPM — we won't exhaust it, just verify it's allowed
        for _ in range(10):
            throttle.record_request(model)
        assert throttle.check_allowed(model) is True


class TestRecordRequest:
    """Request counting increments RPM and RPD counters."""

    def test_increments_counters(self, throttle):
        model = "mistralai/mistral-small-2409"
        throttle.record_request(model)

        minute_bucket, day_bucket = throttle._current_buckets()
        rpm_key = throttle._rpm_key("standard", minute_bucket)
        rpd_key = throttle._rpd_key("standard", day_bucket)

        assert int(throttle._get_redis().get(rpm_key)) == 1
        assert int(throttle._get_redis().get(rpd_key)) == 1

    def test_multiple_requests_accumulate(self, throttle):
        model = "mistralai/mistral-small-2409"
        for _ in range(5):
            throttle.record_request(model)

        minute_bucket, _ = throttle._current_buckets()
        rpm_key = throttle._rpm_key("standard", minute_bucket)
        assert int(throttle._get_redis().get(rpm_key)) == 5


class TestAdaptiveBackoff:
    """429 responses trigger 50% RPM reduction for 2 minutes."""

    def test_backoff_reduces_rpm_limit(self, throttle):
        model = "mistralai/mistral-small-2409"
        base_rpm = OPENROUTER_RATE_LIMITS["standard"]["rpm"]
        reduced = int(base_rpm * ADAPTIVE_BACKOFF_FACTOR)

        # Before backoff, full limit
        assert throttle._effective_limit("standard", "rpm") == base_rpm

        # Trigger backoff
        throttle.record_429(model)

        # After backoff, reduced limit
        assert throttle._effective_limit("standard", "rpm") == reduced

    def test_backoff_blocks_earlier(self, throttle):
        model = "mistralai/mistral-small-2409"
        base_rpm = OPENROUTER_RATE_LIMITS["standard"]["rpm"]
        reduced = int(base_rpm * ADAPTIVE_BACKOFF_FACTOR)

        # Trigger backoff
        throttle.record_429(model)

        # Exhaust reduced limit
        for _ in range(reduced):
            throttle.record_request(model)

        # Should be blocked even though base limit isn't reached
        assert throttle.check_allowed(model) is False

    def test_backoff_key_has_correct_ttl(self, throttle):
        model = "mistralai/mistral-small-2409"
        throttle.record_429(model)

        backoff_key = throttle._backoff_key("standard")
        assert throttle._get_redis().exists(backoff_key)
        assert throttle._get_redis()._ttls[backoff_key] == ADAPTIVE_BACKOFF_TTL_SECONDS

    def test_free_tier_backoff_logged(self, throttle, caplog):
        import logging
        with caplog.at_level(logging.WARNING):
            throttle.record_429("meta-llama/llama-3.3-70b-instruct:free")
        assert "FREE-TIER FALLBACK" in caplog.text
        assert "adaptive backoff activated" in caplog.text

    def test_no_redis_backoff_still_logs(self, caplog):
        import logging
        throttle = OpenRouterThrottle(redis_client=None)
        with caplog.at_level(logging.WARNING):
            throttle.record_429("mistralai/mistral-small-2409")
        assert "adaptive backoff activated" in caplog.text


class TestGetStatus:
    """Status reporting for observability."""

    def test_status_returns_correct_structure(self, throttle):
        model = "mistralai/mistral-small-2409"
        status = throttle.get_status(model)

        assert status["tier"] == "standard"
        assert status["model"] == model
        assert "rpm" in status
        assert "rpd" in status
        assert "adaptive_backoff_active" in status
        assert status["adaptive_backoff_active"] is False

    def test_status_reflects_backoff(self, throttle):
        model = "mistralai/mistral-small-2409"
        throttle.record_429(model)
        status = throttle.get_status(model)
        assert status["adaptive_backoff_active"] is True
