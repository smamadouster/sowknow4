"""Tests for MemoryPlugin — incident learning engine."""
from __future__ import annotations

import pytest
from guardian_hc.plugins.memory import MemoryPlugin, PatternMatcher
from guardian_hc.plugin import AnalysisContext, Severity
from guardian_hc.db import MetricsDB


@pytest.fixture
async def db():
    mdb = MetricsDB(pg_dsn=None, fallback_path=":memory:")
    await mdb.connect()
    yield mdb
    await mdb.close()


@pytest.fixture
def plugin():
    return MemoryPlugin(config={"bootstrap_sources": []})


class TestMemoryAttributes:
    def test_name(self, plugin):
        assert plugin.name == "memory"

    def test_enabled(self, plugin):
        assert plugin.enabled is True


@pytest.mark.asyncio
class TestPatternMatcher:
    async def test_matches_when_threshold_exceeded(self, db):
        await db.create_pattern(
            pattern_name="redis-oom-cascade",
            trigger_conditions={"redis.memory_rss": {">": 85}},
            predicted_outcome="backend crash within 20min",
            recommended_action="memory_purge",
            confidence=0.8,
        )
        await db.write_metric("redis.memory_rss", 90.0, service="redis")

        matcher = PatternMatcher(db)
        matches = await matcher.evaluate()
        assert len(matches) == 1
        assert matches[0]["pattern_name"] == "redis-oom-cascade"

    async def test_no_match_when_below_threshold(self, db):
        await db.create_pattern(
            pattern_name="redis-oom-cascade",
            trigger_conditions={"redis.memory_rss": {">": 85}},
            predicted_outcome="crash",
            recommended_action="purge",
            confidence=0.8,
        )
        await db.write_metric("redis.memory_rss", 50.0, service="redis")

        matcher = PatternMatcher(db)
        matches = await matcher.evaluate()
        assert len(matches) == 0

    async def test_skips_low_confidence_patterns(self, db):
        await db.create_pattern(
            pattern_name="low-conf",
            trigger_conditions={"disk.usage_pct": {">": 90}},
            predicted_outcome="disk full",
            recommended_action="cleanup",
            confidence=0.3,
        )
        await db.write_metric("disk.usage_pct", 95.0, service="host")

        matcher = PatternMatcher(db)
        matches = await matcher.evaluate()
        assert len(matches) == 0

    async def test_no_metric_data_means_no_match(self, db):
        await db.create_pattern(
            pattern_name="test",
            trigger_conditions={"nonexistent.metric": {">": 0}},
            predicted_outcome="trouble",
            recommended_action="fix",
            confidence=0.8,
        )

        matcher = PatternMatcher(db)
        matches = await matcher.evaluate()
        assert len(matches) == 0

    async def test_multiple_conditions_all_must_match(self, db):
        await db.create_pattern(
            pattern_name="multi-cond",
            trigger_conditions={
                "redis.memory_rss": {">": 80},
                "celery.total_queue_depth": {">": 100},
            },
            predicted_outcome="cascade",
            recommended_action="purge_and_backpressure",
            confidence=0.8,
        )
        await db.write_metric("redis.memory_rss", 90.0, service="redis")
        await db.write_metric("celery.total_queue_depth", 50.0, service="celery")

        matcher = PatternMatcher(db)
        matches = await matcher.evaluate()
        assert len(matches) == 0  # queue depth below threshold


@pytest.mark.asyncio
class TestMemoryPluginAnalyze:
    async def test_returns_pattern_match_insights(self, plugin, db):
        await db.create_pattern(
            pattern_name="test-pattern",
            trigger_conditions={"redis.memory_rss": {">": 80}},
            predicted_outcome="trouble",
            recommended_action="fix_it",
            confidence=0.85,
        )
        await db.write_metric("redis.memory_rss", 90.0, service="redis")

        ctx = AnalysisContext(config={}, metrics_db=db, patterns_db=db)
        insights = await plugin.analyze(ctx)
        pattern_matches = [i for i in insights if i.insight_type == "pattern_match"]
        assert len(pattern_matches) == 1
        assert pattern_matches[0].pattern_name == "test-pattern"
        assert pattern_matches[0].confidence == 0.85

    async def test_bootstrap_seeds_patterns_on_first_run(self, plugin, db):
        ctx = AnalysisContext(config={}, metrics_db=db, patterns_db=db)
        await plugin.analyze(ctx)

        patterns = await db.get_active_patterns()
        assert len(patterns) >= 3  # At least the seed patterns with confidence >= threshold
        names = [p["pattern_name"] for p in patterns]
        assert "redis-oom-cascade" in names

    async def test_bootstrap_skips_if_patterns_exist(self, db):
        await db.create_pattern(
            pattern_name="existing",
            trigger_conditions={"x": {">": 0}},
            predicted_outcome="y",
            recommended_action="z",
        )

        plugin = MemoryPlugin(config={"bootstrap_sources": []})
        ctx = AnalysisContext(config={}, metrics_db=db, patterns_db=db)
        await plugin.analyze(ctx)

        patterns = await db.get_active_patterns()
        names = [p["pattern_name"] for p in patterns]
        assert "existing" in names
        assert "redis-oom-cascade" not in names  # bootstrap skipped

    async def test_no_db_returns_empty(self, plugin):
        ctx = AnalysisContext(config={}, metrics_db=None)
        insights = await plugin.analyze(ctx)
        assert insights == []

    async def test_check_returns_empty(self, plugin):
        from guardian_hc.plugin import CheckContext
        ctx = CheckContext(patrol_level="standard", config={}, services=[])
        results = await plugin.check(ctx)
        assert results == []
