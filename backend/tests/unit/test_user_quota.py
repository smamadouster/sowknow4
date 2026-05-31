"""
Unit tests for UserQuotaManager — role-based token quotas with Admin total priority.
"""
import pytest

from app.services.user_quota import (
    ROLE_QUOTAS,
    QuotaExceededError,
    UserQuotaManager,
)


class FakeRedis:
    """In-memory Redis mock for unit tests."""

    def __init__(self):
        self._data = {}
        self._pipelines = []

    def get(self, key):
        return self._data.get(key)

    def incrby(self, key, amount):
        val = self._data.get(key, 0)
        if isinstance(val, bytes):
            val = int(val)
        self._data[key] = val + amount
        return self._data[key]

    def decrby(self, key, amount):
        val = self._data.get(key, 0)
        if isinstance(val, bytes):
            val = int(val)
        self._data[key] = val - amount
        return self._data[key]

    def expire(self, key, seconds):
        pass

    def pipeline(self):
        return FakePipeline(self)


class FakePipeline:
    def __init__(self, redis):
        self._redis = redis
        self._ops = []

    def incrby(self, key, amount):
        self._ops.append(("incrby", key, amount))
        return self

    def expire(self, key, seconds):
        self._ops.append(("expire", key, seconds))
        return self

    def execute(self):
        results = []
        for op in self._ops:
            if op[0] == "incrby":
                results.append(self._redis.incrby(op[1], op[2]))
            elif op[0] == "expire":
                results.append(self._redis.expire(op[1], op[2]))
        self._ops = []
        return results


@pytest.fixture
def manager():
    return UserQuotaManager()


@pytest.fixture
def manager_with_redis():
    return UserQuotaManager(redis_client=FakeRedis())


class TestRoleQuotas:
    """Verify the blueprint quota table is wired correctly."""

    def test_admin_quota(self):
        q = ROLE_QUOTAS["admin"]
        assert q["tokens_per_day"] == 100_000
        assert q["concurrent"] == 3
        assert q["max_input_tokens"] == 50_000

    def test_superuser_quota(self):
        q = ROLE_QUOTAS["superuser"]
        assert q["tokens_per_day"] == 40_000
        assert q["concurrent"] == 2
        assert q["max_input_tokens"] == 20_000

    def test_user_quota(self):
        q = ROLE_QUOTAS["user"]
        assert q["tokens_per_day"] == 15_000
        assert q["concurrent"] == 1
        assert q["max_input_tokens"] == 5_000

    def test_unknown_role_falls_back_to_user(self, manager_with_redis):
        quota = manager_with_redis.get_quota("unknown")
        assert quota == ROLE_QUOTAS["user"]


class TestAdminTotalPriority:
    """Admin must bypass all quota enforcement while still being tracked."""

    def test_admin_never_raises_quota_exceeded(self, manager_with_redis):
        """Admin can consume any amount of tokens without hitting a ceiling."""
        result = manager_with_redis.check_and_consume(
            user_id="admin-1", role="admin", estimated_tokens=1_000_000
        )
        assert result["allowed"] is True
        assert result["limit"] == -1
        assert result["remaining"] == -1

    def test_admin_usage_is_tracked(self, manager_with_redis):
        """Admin consumption is still recorded in Redis for observability."""
        manager_with_redis.check_and_consume(
            user_id="admin-1", role="admin", estimated_tokens=5_000
        )
        usage = manager_with_redis.get_usage("admin-1")
        assert usage["used"] == 5_000

    def test_admin_multiple_calls_accumulate(self, manager_with_redis):
        for _ in range(5):
            manager_with_redis.check_and_consume(
                user_id="admin-1", role="admin", estimated_tokens=10_000
            )
        usage = manager_with_redis.get_usage("admin-1")
        assert usage["used"] == 50_000

    def test_admin_without_redis_is_allowed(self, manager):
        """If Redis is down, Admin is still allowed (fail-open)."""
        result = manager.check_and_consume(
            user_id="admin-1", role="admin", estimated_tokens=999_999
        )
        assert result["allowed"] is True


class TestSuperUserAndUserEnforcement:
    """Non-admin roles must respect their daily token ceilings."""

    def test_user_within_budget_allowed(self, manager_with_redis):
        result = manager_with_redis.check_and_consume(
            user_id="user-1", role="user", estimated_tokens=5_000
        )
        assert result["allowed"] is True
        assert result["limit"] == 15_000
        assert result["remaining"] == 10_000

    def test_user_exceeds_budget_blocked(self, manager_with_redis):
        with pytest.raises(QuotaExceededError) as exc_info:
            manager_with_redis.check_and_consume(
                user_id="user-1", role="user", estimated_tokens=20_000
            )
        assert "user-1" in str(exc_info.value)
        assert "user" in str(exc_info.value)

    def test_superuser_within_budget_allowed(self, manager_with_redis):
        result = manager_with_redis.check_and_consume(
            user_id="su-1", role="superuser", estimated_tokens=30_000
        )
        assert result["allowed"] is True
        assert result["limit"] == 40_000
        assert result["remaining"] == 10_000

    def test_superuser_exceeds_budget_blocked(self, manager_with_redis):
        with pytest.raises(QuotaExceededError) as exc_info:
            manager_with_redis.check_and_consume(
                user_id="su-1", role="superuser", estimated_tokens=50_000
            )
        assert "su-1" in str(exc_info.value)
        assert "superuser" in str(exc_info.value)

    def test_quota_rolls_back_on_rejection(self, manager_with_redis):
        """When a request is rejected, the increment must be rolled back."""
        try:
            manager_with_redis.check_and_consume(
                user_id="user-1", role="user", estimated_tokens=20_000
            )
        except QuotaExceededError:
            pass
        usage = manager_with_redis.get_usage("user-1")
        assert usage["used"] == 0

    def test_cumulative_usage_tracked_across_calls(self, manager_with_redis):
        manager_with_redis.check_and_consume(
            user_id="user-1", role="user", estimated_tokens=5_000
        )
        manager_with_redis.check_and_consume(
            user_id="user-1", role="user", estimated_tokens=5_000
        )
        usage = manager_with_redis.get_usage("user-1")
        assert usage["used"] == 10_000

    def test_different_users_isolated(self, manager_with_redis):
        manager_with_redis.check_and_consume(
            user_id="user-a", role="user", estimated_tokens=10_000
        )
        manager_with_redis.check_and_consume(
            user_id="user-b", role="user", estimated_tokens=10_000
        )
        assert manager_with_redis.get_usage("user-a")["used"] == 10_000
        assert manager_with_redis.get_usage("user-b")["used"] == 10_000

    def test_redis_unavailable_fail_open(self, manager):
        """Without Redis, quotas cannot be enforced; allow through."""
        result = manager.check_and_consume(
            user_id="user-1", role="user", estimated_tokens=999_999
        )
        assert result["allowed"] is True


class TestMaxInputTokensWarning:
    """Requests that exceed per-role max_input_tokens should log a warning."""

    def test_user_exceeds_max_input_logs_warning(self, manager_with_redis, caplog):
        import logging
        with caplog.at_level(logging.WARNING):
            manager_with_redis.check_and_consume(
                user_id="user-1", role="user", estimated_tokens=10_000
            )
        assert "exceeds max_input_tokens" in caplog.text
