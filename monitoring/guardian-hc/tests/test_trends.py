"""Tests for TrendsPlugin — metrics collection and trend analysis."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock
from guardian_hc.plugins.trends import TrendsPlugin
from guardian_hc.plugin import CheckContext, AnalysisContext, Severity
from guardian_hc.db import MetricsDB


@pytest.fixture
async def db():
    mdb = MetricsDB(pg_dsn=None, fallback_path=":memory:")
    await mdb.connect()
    yield mdb
    await mdb.close()


@pytest.fixture
def plugin():
    return TrendsPlugin(config={
        "retention_raw": "48h",
        "retention_hourly": "14d",
        "redis_host": "redis",
        "redis_port": 6379,
        "redis_password": "",
    })


class TestTrendsAttributes:
    def test_name(self, plugin):
        assert plugin.name == "trends"

    def test_enabled(self, plugin):
        assert plugin.enabled is True


@pytest.mark.asyncio
class TestTrendsCheck:
    async def test_check_writes_to_db(self, plugin, db):
        ctx = CheckContext(patrol_level="standard", config={}, services=[], metrics_db=db)
        plugin._collect_host_metrics = AsyncMock(return_value=[
            ("disk.usage_pct", 72.0, "host", {}),
            ("vps.load1", 1.5, "host", {}),
        ])
        plugin._collect_redis_metrics = AsyncMock(return_value=[])
        plugin._collect_pg_metrics = AsyncMock(return_value=[])
        plugin._collect_celery_metrics = AsyncMock(return_value=[])
        plugin._collect_backend_metrics = AsyncMock(return_value=[])

        results = await plugin.check(ctx)
        assert results == []

        rows = await db.query_metrics("disk.usage_pct", hours=1)
        assert len(rows) == 1
        assert rows[0]["value"] == 72.0

    async def test_check_no_db_returns_empty(self, plugin):
        ctx = CheckContext(patrol_level="standard", config={}, services=[], metrics_db=None)
        results = await plugin.check(ctx)
        assert results == []

    async def test_collector_exception_does_not_crash(self, plugin, db):
        ctx = CheckContext(patrol_level="standard", config={}, services=[], metrics_db=db)
        plugin._collect_host_metrics = AsyncMock(side_effect=RuntimeError("boom"))
        plugin._collect_redis_metrics = AsyncMock(return_value=[
            ("redis.memory_rss", 50.0, "redis", {}),
        ])
        plugin._collect_pg_metrics = AsyncMock(return_value=[])
        plugin._collect_celery_metrics = AsyncMock(return_value=[])
        plugin._collect_backend_metrics = AsyncMock(return_value=[])

        results = await plugin.check(ctx)
        assert results == []
        rows = await db.query_metrics("redis.memory_rss", hours=1)
        assert len(rows) == 1


@pytest.mark.asyncio
class TestTrendsAnalyze:
    async def test_anomaly_detected(self, plugin, db):
        for _ in range(20):
            await db.write_metric("redis.memory_rss", 50.0, service="redis")
        await db.write_metric("redis.memory_rss", 95.0, service="redis")

        ctx = AnalysisContext(config={}, metrics_db=db)
        insights = await plugin.analyze(ctx)
        anomalies = [i for i in insights if i.insight_type == "anomaly"]
        assert len(anomalies) >= 1
        assert anomalies[0].metric == "redis.memory_rss"

    async def test_no_db_returns_empty(self, plugin):
        ctx = AnalysisContext(config={}, metrics_db=None)
        insights = await plugin.analyze(ctx)
        assert insights == []

    async def test_no_data_returns_empty(self, plugin, db):
        ctx = AnalysisContext(config={}, metrics_db=db)
        insights = await plugin.analyze(ctx)
        assert insights == []
