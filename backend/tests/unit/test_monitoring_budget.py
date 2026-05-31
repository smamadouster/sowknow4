"""
Unit tests for PerUserCostBudget — role-aware daily cost limits with Admin total priority.
"""
import pytest

from app.services.monitoring import BudgetExceededError, PerUserCostBudget


class FakeRedis:
    """In-memory Redis mock for unit tests."""

    def __init__(self):
        self._data = {}

    def get(self, key):
        return self._data.get(key)

    def incrbyfloat(self, key, amount):
        val = float(self._data.get(key, 0.0))
        self._data[key] = val + amount
        return self._data[key]

    def expire(self, key, seconds):
        pass

    def pipeline(self):
        return FakePipeline(self)


class FakePipeline:
    def __init__(self, redis):
        self._redis = redis
        self._ops = []

    def incrbyfloat(self, key, amount):
        self._ops.append(("incrbyfloat", key, amount))
        return self

    def expire(self, key, seconds):
        self._ops.append(("expire", key, seconds))
        return self

    def execute(self):
        results = []
        for op in self._ops:
            if op[0] == "incrbyfloat":
                results.append(self._redis.incrbyfloat(op[1], op[2]))
            elif op[0] == "expire":
                results.append(self._redis.expire(op[1], op[2]))
        self._ops = []
        return results


@pytest.fixture
def budget():
    # Always inject fake Redis so tests never hit the network
    return PerUserCostBudget(redis_client=FakeRedis())


@pytest.fixture
def budget_with_redis():
    return PerUserCostBudget(redis_client=FakeRedis())


class TestRoleBudgets:
    """Verify the blueprint cost budget table is wired correctly."""

    def test_admin_budget_default(self, budget):
        assert budget.get_budget("admin") == 2.0

    def test_superuser_budget_default(self, budget):
        assert budget.get_budget("superuser") == 1.0

    def test_user_budget_default(self, budget):
        assert budget.get_budget("user") == 0.5

    def test_unknown_role_falls_back(self, budget):
        assert budget.get_budget("unknown") == budget.get_budget("user")


class TestAdminTotalPriority:
    """Admin must bypass all cost budget enforcement while still being tracked."""

    def test_admin_never_raises_budget_exceeded(self, budget_with_redis):
        result = budget_with_redis.check_and_consume(
            user_id="admin-1", role="admin", estimated_cost=999.99
        )
        assert result["allowed"] is True
        assert result["limit"] == -1.0
        assert result["remaining"] == -1.0

    def test_admin_spending_is_tracked(self, budget_with_redis):
        budget_with_redis.check_and_consume(
            user_id="admin-1", role="admin", estimated_cost=5.00
        )
        budget_with_redis.check_and_consume(
            user_id="admin-1", role="admin", estimated_cost=3.50
        )
        # Redis key format: sowknow:cost_budget:{date}:{user_id}
        key = budget_with_redis._key("admin-1")
        assert float(budget_with_redis._get_redis().get(key)) == 8.50

    def test_admin_without_redis_is_allowed(self, budget):
        result = budget.check_and_consume(
            user_id="admin-1", role="admin", estimated_cost=999.99
        )
        assert result["allowed"] is True


class TestUserAndSuperUserEnforcement:
    """Non-admin roles must respect their daily cost ceilings."""

    def test_user_within_budget_allowed(self, budget_with_redis):
        result = budget_with_redis.check_and_consume(
            user_id="user-1", role="user", estimated_cost=0.30
        )
        assert result["allowed"] is True
        assert result["limit"] == 0.5
        assert result["remaining"] == pytest.approx(0.2)

    def test_user_exceeds_budget_blocked(self, budget_with_redis):
        with pytest.raises(BudgetExceededError) as exc_info:
            budget_with_redis.check_and_consume(
                user_id="user-1", role="user", estimated_cost=1.00
            )
        assert "user-1" in str(exc_info.value)
        assert "user" in str(exc_info.value)

    def test_superuser_within_budget_allowed(self, budget_with_redis):
        result = budget_with_redis.check_and_consume(
            user_id="su-1", role="superuser", estimated_cost=0.80
        )
        assert result["allowed"] is True
        assert result["limit"] == 1.0
        assert result["remaining"] == pytest.approx(0.2)

    def test_superuser_exceeds_budget_blocked(self, budget_with_redis):
        with pytest.raises(BudgetExceededError) as exc_info:
            budget_with_redis.check_and_consume(
                user_id="su-1", role="superuser", estimated_cost=2.00
            )
        assert "su-1" in str(exc_info.value)
        assert "superuser" in str(exc_info.value)

    def test_budget_rolls_back_on_rejection(self, budget_with_redis):
        try:
            budget_with_redis.check_and_consume(
                user_id="user-1", role="user", estimated_cost=1.00
            )
        except BudgetExceededError:
            pass
        key = budget_with_redis._key("user-1")
        assert float(budget_with_redis._get_redis().get(key) or 0) == 0.0

    def test_redis_unavailable_fail_open(self, monkeypatch):
        budget = PerUserCostBudget(redis_client=None)
        monkeypatch.setattr(budget, "_get_redis", lambda: None)
        result = budget.check_and_consume(
            user_id="user-1", role="user", estimated_cost=999.99
        )
        assert result["allowed"] is True
