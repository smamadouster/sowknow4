from __future__ import annotations

import pytest
import pytest_asyncio
import time

from guardian_hc.db import MetricsDB


@pytest_asyncio.fixture
async def db():
    """In-memory SQLite MetricsDB instance for tests."""
    instance = MetricsDB(pg_dsn=None, fallback_path=":memory:")
    await instance.connect()
    yield instance
    await instance.close()


@pytest.mark.asyncio
async def test_write_metric_and_query(db: MetricsDB):
    await db.write_metric("cpu_usage", 55.0, service="backend")
    results = await db.query_metrics("cpu_usage", hours=1, service="backend")
    assert len(results) == 1
    assert results[0]["metric"] == "cpu_usage"
    assert results[0]["value"] == pytest.approx(55.0)
    assert results[0]["service"] == "backend"


@pytest.mark.asyncio
async def test_write_batch_and_query(db: MetricsDB):
    batch = [
        ("mem_usage", 30.0, "backend", {"unit": "percent"}),
        ("mem_usage", 40.0, "backend", {}),
        ("mem_usage", 50.0, "frontend", {}),
    ]
    await db.write_batch(batch)
    results = await db.query_metrics("mem_usage", hours=1)
    assert len(results) == 3


@pytest.mark.asyncio
async def test_query_metrics_time_filter(db: MetricsDB):
    """Only metrics within the time window should be returned."""
    await db.write_metric("disk_io", 100.0, service="host")
    # Query with 0 hours should return nothing (strictly > now)
    results = await db.query_metrics("disk_io", hours=0, service="host")
    assert len(results) == 0
    # Query with 1 hour should return the metric
    results = await db.query_metrics("disk_io", hours=1, service="host")
    assert len(results) == 1


@pytest.mark.asyncio
async def test_get_latest_returns_most_recent(db: MetricsDB):
    await db.write_metric("cpu_usage", 10.0, service="svc")
    await db.write_metric("cpu_usage", 99.0, service="svc")
    latest = await db.get_latest("cpu_usage", service="svc")
    assert latest == pytest.approx(99.0)


@pytest.mark.asyncio
async def test_get_latest_no_data(db: MetricsDB):
    result = await db.get_latest("nonexistent_metric")
    assert result is None


@pytest.mark.asyncio
async def test_get_slope_positive_for_increasing(db: MetricsDB):
    """Write metrics with increasing values to verify positive slope."""
    import asyncio

    # Write values with small delays to ensure distinct timestamps
    for i, val in enumerate([10.0, 20.0, 30.0, 40.0, 50.0]):
        await db.write_metric("load_avg", val, service="host")
        await asyncio.sleep(0.01)

    slope = await db.get_slope("load_avg", hours=6, service="host")
    assert slope is not None
    assert slope > 0, f"Expected positive slope, got {slope}"


@pytest.mark.asyncio
async def test_get_slope_none_when_insufficient_data(db: MetricsDB):
    """Single data point cannot produce a meaningful slope."""
    await db.write_metric("solo_metric", 42.0)
    slope = await db.get_slope("solo_metric", hours=6)
    # With only 1 point, regression denominator is 0 → return None
    assert slope is None


@pytest.mark.asyncio
async def test_get_mean_stddev(db: MetricsDB):
    values = [10.0, 20.0, 30.0, 40.0, 50.0]
    for v in values:
        await db.write_metric("rtt", v, service="net")

    mean, stddev = await db.get_mean_stddev("rtt", hours=1, service="net")
    assert mean == pytest.approx(30.0, abs=0.01)
    # Sample stddev for [10,20,30,40,50] = sqrt(250) ≈ 15.811
    assert stddev == pytest.approx(15.811, abs=0.01)


@pytest.mark.asyncio
async def test_get_mean_stddev_single_value(db: MetricsDB):
    await db.write_metric("singleton", 7.0)
    mean, stddev = await db.get_mean_stddev("singleton", hours=1)
    assert mean == pytest.approx(7.0)
    assert stddev == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_get_mean_stddev_no_data(db: MetricsDB):
    mean, stddev = await db.get_mean_stddev("ghost_metric", hours=1)
    assert mean == pytest.approx(0.0)
    assert stddev == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_pattern_crud(db: MetricsDB):
    pid = await db.create_pattern(
        pattern_name="high_cpu_then_oom",
        trigger_conditions={"cpu": ">90", "mem": ">80"},
        predicted_outcome="OOM kill within 10min",
        recommended_action="restart heavy worker",
        confidence=0.6,
    )
    assert isinstance(pid, int)
    assert pid > 0

    patterns = await db.get_active_patterns()
    assert len(patterns) == 1
    p = patterns[0]
    assert p["pattern_name"] == "high_cpu_then_oom"
    assert p["confidence"] == pytest.approx(0.6)
    assert isinstance(p["trigger_conditions"], dict)


@pytest.mark.asyncio
async def test_update_pattern_confidence_correct(db: MetricsDB):
    pid = await db.create_pattern(
        pattern_name="test_pattern",
        trigger_conditions={"k": "v"},
        predicted_outcome="outcome",
        recommended_action="action",
        confidence=0.5,
    )
    await db.update_pattern_confidence(pid, matched=True, correct=True)
    patterns = await db.get_active_patterns()
    assert patterns[0]["confidence"] == pytest.approx(0.6)


@pytest.mark.asyncio
async def test_update_pattern_confidence_incorrect(db: MetricsDB):
    pid = await db.create_pattern(
        pattern_name="test_pattern_incorrect",
        trigger_conditions={},
        predicted_outcome="o",
        recommended_action="a",
        confidence=0.5,
    )
    await db.update_pattern_confidence(pid, matched=True, correct=False)
    patterns = await db.get_active_patterns()
    assert patterns[0]["confidence"] == pytest.approx(0.45)


@pytest.mark.asyncio
async def test_update_pattern_deactivates_low_confidence(db: MetricsDB):
    pid = await db.create_pattern(
        pattern_name="dying_pattern",
        trigger_conditions={},
        predicted_outcome="o",
        recommended_action="a",
        confidence=0.2,
    )
    # Drop below 0.2 threshold
    await db.update_pattern_confidence(pid, matched=True, correct=False)
    patterns = await db.get_active_patterns()
    assert len(patterns) == 0


@pytest.mark.asyncio
async def test_update_pattern_confidence_caps_at_095(db: MetricsDB):
    pid = await db.create_pattern(
        pattern_name="nearly_perfect",
        trigger_conditions={},
        predicted_outcome="o",
        recommended_action="a",
        confidence=0.9,
    )
    await db.update_pattern_confidence(pid, matched=True, correct=True)
    patterns = await db.get_active_patterns()
    assert patterns[0]["confidence"] == pytest.approx(0.95)

    # One more correct — should stay at 0.95 (cap)
    await db.update_pattern_confidence(pid, matched=True, correct=True)
    patterns = await db.get_active_patterns()
    assert patterns[0]["confidence"] == pytest.approx(0.95)


@pytest.mark.asyncio
async def test_purge_raw_metrics(db: MetricsDB):
    # Write a metric
    await db.write_metric("old_metric", 1.0)
    results = await db.query_metrics("old_metric", hours=1)
    assert len(results) == 1

    # Purge with 0 hours — deletes everything older than now
    deleted = await db.purge_raw_metrics(hours=0)
    assert deleted >= 1

    results = await db.query_metrics("old_metric", hours=1)
    assert len(results) == 0


@pytest.mark.asyncio
async def test_is_pg_false_for_sqlite(db: MetricsDB):
    assert db.is_pg is False
