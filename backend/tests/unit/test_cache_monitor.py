"""
Unit tests for Cache Monitor service
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from app.services.cache_monitor import (
    CacheMonitor,
    DailyCacheStats
)


@pytest.fixture
def cache_monitor():
    """Create a CacheMonitor instance for testing"""
    # Use a short retention period for testing
    return CacheMonitor(retention_days=7)


@pytest.fixture
def daily_stats():
    """Create a DailyCacheStats instance for testing"""
    return DailyCacheStats(datetime.now())


class TestDailyCacheStats:
    """Test suite for DailyCacheStats class"""

    def test_initialization(self, daily_stats):
        """Test daily stats initialization"""
        assert daily_stats.hits == 0
        assert daily_stats.misses == 0
        assert daily_stats.tokens_saved == 0
        assert daily_stats.queries == 0
        assert daily_stats.hit_rate == 0.0

    def test_record_hit(self, daily_stats):
        """Test recording a cache hit"""
        daily_stats.record_hit(tokens_saved=100)
        assert daily_stats.hits == 1
        assert daily_stats.tokens_saved == 100

        daily_stats.record_hit(tokens_saved=50)
        assert daily_stats.hits == 2
        assert daily_stats.tokens_saved == 150

    def test_record_miss(self, daily_stats):
        """Test recording a cache miss"""
        daily_stats.record_miss()
        assert daily_stats.misses == 1

        daily_stats.record_miss()
        assert daily_stats.misses == 2

    def test_record_query(self, daily_stats):
        """Test recording a query"""
        daily_stats.record_query()
        assert daily_stats.queries == 1

        daily_stats.record_query()
        assert daily_stats.queries == 2

    def test_hit_rate_calculation(self, daily_stats):
        """Test hit rate calculation"""
        # Initially, hit rate should be 0
        assert daily_stats.hit_rate == 0.0

        # Add some hits and misses
        daily_stats.record_hit(tokens_saved=100)
        daily_stats.record_hit(tokens_saved=100)
        daily_stats.record_miss()

        # Hit rate should be 2/3 = 0.666...
        assert abs(daily_stats.hit_rate - 0.6667) < 0.0001

        # All hits
        daily_stats_hit_only = DailyCacheStats(datetime.now())
        for _ in range(5):
            daily_stats_hit_only.record_hit(tokens_saved=100)
        assert daily_stats_hit_only.hit_rate == 1.0

        # All misses
        daily_stats_miss_only = DailyCacheStats(datetime.now())
        for _ in range(5):
            daily_stats_miss_only.record_miss()
        assert daily_stats_miss_only.hit_rate == 0.0

    def test_to_dict(self, daily_stats):
        """Test converting stats to dictionary"""
        daily_stats.record_hit(tokens_saved=100)
        daily_stats.record_miss()
        daily_stats.record_query()

        result = daily_stats.to_dict()

        assert "date" in result
        assert result["hits"] == 1
        assert result["misses"] == 1
        assert result["tokens_saved"] == 100
        assert result["queries"] == 1
        assert "hit_rate" in result
        assert isinstance(result["hit_rate"], float)

    def test_thread_safety_hit(self, daily_stats):
        """Test that recording hits is thread-safe"""
        import threading

        def record_hits():
            for _ in range(100):
                daily_stats.record_hit(tokens_saved=10)

        threads = [threading.Thread(target=record_hits) for _ in range(5)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert daily_stats.hits == 500
        assert daily_stats.tokens_saved == 5000

    def test_thread_safety_miss(self, daily_stats):
        """Test that recording misses is thread-safe"""
        import threading

        def record_misses():
            for _ in range(100):
                daily_stats.record_miss()

        threads = [threading.Thread(target=record_misses) for _ in range(5)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert daily_stats.misses == 500


class TestCacheMonitor:
    """Test suite for CacheMonitor class"""

    def test_initialization(self, cache_monitor):
        """Test cache monitor initialization"""
        assert cache_monitor.get_retention_days() == 7
        assert len(cache_monitor.get_all_dates()) == 1  # Today's stats should be created

    def test_initialization_custom_retention(self):
        """Test cache monitor with custom retention period"""
        monitor = CacheMonitor(retention_days=30)
        assert monitor.get_retention_days() == 30

    def test_record_cache_hit(self, cache_monitor):
        """Test recording a cache hit"""
        cache_monitor.record_cache_hit(
            cache_key="test_key_1",
            tokens_saved=100,
            user_id="user123"
        )

        today_stats = cache_monitor.get_today_stats()
        assert today_stats["hits"] == 1
        assert today_stats["tokens_saved"] == 100
        assert today_stats["queries"] == 1

    def test_record_cache_hit_invalid_tokens(self, cache_monitor):
        """Test recording a cache hit with invalid token count"""
        # Negative tokens should be rejected
        cache_monitor.record_cache_hit(
            cache_key="test_key",
            tokens_saved=-50,
            user_id="user123"
        )

        today_stats = cache_monitor.get_today_stats()
        # Should not record the hit
        assert today_stats["hits"] == 0

    def test_record_cache_miss(self, cache_monitor):
        """Test recording a cache miss"""
        cache_monitor.record_cache_miss(
            cache_key="test_key_2",
            user_id="user456"
        )

        today_stats = cache_monitor.get_today_stats()
        assert today_stats["misses"] == 1
        assert today_stats["queries"] == 1

    def test_record_multiple_hits_and_misses(self, cache_monitor):
        """Test recording multiple cache events"""
        # Record multiple hits
        for i in range(5):
            cache_monitor.record_cache_hit(
                cache_key=f"key_{i}",
                tokens_saved=50 + i * 10,
                user_id=f"user_{i}"
            )

        # Record multiple misses
        for i in range(3):
            cache_monitor.record_cache_miss(
                cache_key=f"miss_key_{i}",
                user_id=f"user_{i}"
            )

        today_stats = cache_monitor.get_today_stats()
        assert today_stats["hits"] == 5
        assert today_stats["misses"] == 3
        assert today_stats["queries"] == 8
        assert today_stats["tokens_saved"] == 350  # Sum of 50, 60, 70, 80, 90

    def test_get_hit_rate_today(self, cache_monitor):
        """Test getting hit rate for today"""
        # No activity yet
        assert cache_monitor.get_hit_rate(days=1) == 0.0

        # Add some activity
        cache_monitor.record_cache_hit("key1", 100)
        cache_monitor.record_cache_hit("key2", 100)
        cache_monitor.record_cache_miss("key3")

        # Hit rate should be 2/3
        hit_rate = cache_monitor.get_hit_rate(days=1)
        assert abs(hit_rate - 0.6667) < 0.0001

    def test_get_hit_rate_multiple_days(self, cache_monitor):
        """Test getting hit rate across multiple days"""
        # Record today's stats
        cache_monitor.record_cache_hit("key1", 100)
        cache_monitor.record_cache_miss("key2")

        # Simulate yesterday's stats by directly manipulating internal state
        yesterday = datetime.now() - timedelta(days=1)
        with cache_monitor._lock:
            yesterday_stats = DailyCacheStats(yesterday)
            yesterday_stats.record_hit(tokens_saved=200)
            yesterday_stats.record_hit(tokens_saved=200)
            yesterday_stats.record_miss()
            cache_monitor._daily_stats[yesterday.date()] = yesterday_stats

        # Today: 1 hit, 1 miss = 0.5
        # Yesterday: 2 hits, 1 miss = 0.666...
        # Combined: 3 hits, 2 misses = 0.6
        hit_rate = cache_monitor.get_hit_rate(days=2)
        assert abs(hit_rate - 0.6) < 0.0001

    def test_get_hit_rate_no_activity(self, cache_monitor):
        """Test hit rate when there's no activity"""
        hit_rate = cache_monitor.get_hit_rate(days=7)
        assert hit_rate == 0.0

    def test_get_hit_rate_invalid_days(self, cache_monitor):
        """Test hit rate with invalid day parameter"""
        cache_monitor.record_cache_hit("key1", 100)

        # Invalid days (< 1) should default to 1
        hit_rate = cache_monitor.get_hit_rate(days=0)
        assert hit_rate == 1.0

        hit_rate = cache_monitor.get_hit_rate(days=-5)
        assert hit_rate == 1.0

    def test_get_stats_summary(self, cache_monitor):
        """Test getting comprehensive statistics summary"""
        # Add some activity
        for i in range(10):
            cache_monitor.record_cache_hit(f"hit_key_{i}", 100)
        for i in range(5):
            cache_monitor.record_cache_miss(f"miss_key_{i}")

        summary = cache_monitor.get_stats_summary(days=7)

        assert "period_start" in summary
        assert "period_end" in summary
        assert "daily_stats" in summary
        assert "overall_hit_rate" in summary
        assert "total_hits" in summary
        assert "total_misses" in summary
        assert "total_tokens_saved" in summary
        assert "total_queries" in summary
        assert "unique_cache_keys" in summary
        assert "generated_at" in summary

        assert summary["total_hits"] == 10
        assert summary["total_misses"] == 5
        assert summary["total_tokens_saved"] == 1000
        assert summary["unique_cache_keys"] == 15

    def test_get_stats_summary_multiple_days(self, cache_monitor):
        """Test stats summary across multiple days"""
        # Add today's activity
        cache_monitor.record_cache_hit("today_hit", 100)

        # Simulate yesterday's activity
        yesterday = datetime.now() - timedelta(days=1)
        with cache_monitor._lock:
            yesterday_stats = DailyCacheStats(yesterday)
            yesterday_stats.record_hit(tokens_saved=200)
            yesterday_stats.record_miss()
            cache_monitor._daily_stats[yesterday.date()] = yesterday_stats

        summary = cache_monitor.get_stats_summary(days=7)

        assert len(summary["daily_stats"]) == 2
        assert summary["total_hits"] == 2
        assert summary["total_misses"] == 1
        assert summary["total_tokens_saved"] == 300

    def test_get_stats_summary_invalid_days(self, cache_monitor):
        """Test stats summary with invalid days parameter"""
        cache_monitor.record_cache_hit("key1", 100)

        # Invalid days should default to 7
        summary = cache_monitor.get_stats_summary(days=0)
        assert summary["total_hits"] >= 1

    def test_cleanup_old_stats(self, cache_monitor):
        """Test cleanup of old statistics"""
        # Add stats for various days
        today = datetime.now().date()
        yesterday = (datetime.now() - timedelta(days=1)).date()
        old_day = (datetime.now() - timedelta(days=10)).date()

        with cache_monitor._lock:
            cache_monitor._daily_stats[old_day] = DailyCacheStats(datetime.now() - timedelta(days=10))
            cache_monitor._daily_stats[yesterday] = DailyCacheStats(datetime.now() - timedelta(days=1))

        # Trigger cleanup (happens automatically in get_stats_summary)
        summary = cache_monitor.get_stats_summary(days=7)

        # Old stats should be removed
        assert old_day not in cache_monitor._daily_stats
        # Recent stats should remain
        assert today in cache_monitor._daily_stats
        assert yesterday in cache_monitor._daily_stats

    def test_get_today_stats(self, cache_monitor):
        """Test getting today's statistics"""
        cache_monitor.record_cache_hit("key1", 150)
        cache_monitor.record_cache_miss("key2")

        today_stats = cache_monitor.get_today_stats()

        assert today_stats["hits"] == 1
        assert today_stats["misses"] == 1
        assert today_stats["tokens_saved"] == 150
        assert today_stats["queries"] == 2
        assert abs(today_stats["hit_rate"] - 0.5) < 0.0001

    def test_get_tokens_saved_today(self, cache_monitor):
        """Test getting tokens saved today"""
        assert cache_monitor.get_tokens_saved_today() == 0

        cache_monitor.record_cache_hit("key1", 100)
        cache_monitor.record_cache_hit("key2", 250)

        assert cache_monitor.get_tokens_saved_today() == 350

    def test_get_total_tokens_saved(self, cache_monitor):
        """Test getting total tokens saved over a period"""
        # Today's tokens
        cache_monitor.record_cache_hit("key1", 100)

        # Yesterday's tokens
        yesterday = datetime.now() - timedelta(days=1)
        with cache_monitor._lock:
            yesterday_stats = DailyCacheStats(yesterday)
            yesterday_stats.record_hit(tokens_saved=200)
            cache_monitor._daily_stats[yesterday.date()] = yesterday_stats

        # Should include both days
        assert cache_monitor.get_total_tokens_saved(days=2) == 300

        # Should only include today
        assert cache_monitor.get_total_tokens_saved(days=1) == 100

    def test_get_all_dates(self, cache_monitor):
        """Test getting all dates with statistics"""
        # Initially should have today
        dates = cache_monitor.get_all_dates()
        assert len(dates) == 1

        # Add yesterday's stats
        yesterday = datetime.now() - timedelta(days=1)
        with cache_monitor._lock:
            yesterday_stats = DailyCacheStats(yesterday)
            yesterday_stats.record_hit(tokens_saved=100)
            cache_monitor._daily_stats[yesterday.date()] = yesterday_stats

        dates = cache_monitor.get_all_dates()
        assert len(dates) == 2
        # Dates should be sorted in descending order (newest first)
        assert dates[0] >= dates[1]

    def test_reset_today_stats(self, cache_monitor):
        """Test resetting today's statistics"""
        cache_monitor.record_cache_hit("key1", 100)
        cache_monitor.record_cache_miss("key2")

        assert cache_monitor.get_today_stats()["hits"] == 1
        assert cache_monitor.get_today_stats()["misses"] == 1

        cache_monitor.reset_today_stats()

        # Should be reset to zero
        today_stats = cache_monitor.get_today_stats()
        assert today_stats["hits"] == 0
        assert today_stats["misses"] == 0
        assert today_stats["tokens_saved"] == 0

    def test_set_retention_days(self, cache_monitor):
        """Test updating retention period"""
        assert cache_monitor.get_retention_days() == 7

        cache_monitor.set_retention_days(30)
        assert cache_monitor.get_retention_days() == 30

    def test_set_retention_days_invalid(self, cache_monitor):
        """Test setting invalid retention period"""
        original = cache_monitor.get_retention_days()

        # Invalid value (< 1) should be ignored
        cache_monitor.set_retention_days(0)
        assert cache_monitor.get_retention_days() == original

        cache_monitor.set_retention_days(-5)
        assert cache_monitor.get_retention_days() == original

    def test_set_retention_days_triggers_cleanup(self, cache_monitor):
        """Test that updating retention triggers cleanup"""
        # Add old stats
        old_day = (datetime.now() - timedelta(days=10)).date()
        with cache_monitor._lock:
            cache_monitor._daily_stats[old_day] = DailyCacheStats(datetime.now() - timedelta(days=10))

        # Update retention to 5 days (should clean up the 10-day-old stats)
        cache_monitor.set_retention_days(5)

        assert old_day not in cache_monitor._daily_stats

    def test_export_stats_json(self, cache_monitor):
        """Test exporting stats as JSON"""
        cache_monitor.record_cache_hit("key1", 100)
        cache_monitor.record_cache_miss("key2")

        json_str = cache_monitor.export_stats_json(days=7)

        assert isinstance(json_str, str)
        assert "total_hits" in json_str
        assert "total_misses" in json_str

        # Verify it's valid JSON
        import json
        data = json.loads(json_str)
        assert data["total_hits"] == 1
        assert data["total_misses"] == 1

    def test_unique_cache_keys_tracking(self, cache_monitor):
        """Test tracking of unique cache keys"""
        # Record hits and misses with the same key
        cache_monitor.record_cache_hit("key1", 100)
        cache_monitor.record_cache_miss("key1")
        cache_monitor.record_cache_hit("key1", 100)

        summary = cache_monitor.get_stats_summary(days=7)
        # Should count unique keys, not total operations
        assert summary["unique_cache_keys"] == 1

        # Add another key
        cache_monitor.record_cache_hit("key2", 50)

        summary = cache_monitor.get_stats_summary(days=7)
        assert summary["unique_cache_keys"] == 2

    def test_thread_safety_concurrent_recording(self, cache_monitor):
        """Test thread safety of concurrent recording"""
        import threading

        def record_hits_and_misses(thread_id):
            for i in range(50):
                cache_monitor.record_cache_hit(
                    cache_key=f"thread_{thread_id}_key_{i}",
                    tokens_saved=10,
                    user_id=f"user_{thread_id}"
                )
                cache_monitor.record_cache_miss(
                    cache_key=f"thread_{thread_id}_miss_{i}",
                    user_id=f"user_{thread_id}"
                )

        threads = [threading.Thread(target=record_hits_and_misses, args=(i,)) for i in range(5)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        summary = cache_monitor.get_stats_summary(days=7)
        # 5 threads * 50 hits each = 250 hits
        assert summary["total_hits"] == 250
        # 5 threads * 50 misses each = 250 misses
        assert summary["total_misses"] == 250
        # 250 hits * 10 tokens each = 2500 tokens
        assert summary["total_tokens_saved"] == 2500
        # 500 queries total
        assert summary["total_queries"] == 500

    def test_empty_stats_summary(self, cache_monitor):
        """Test stats summary when no activity has occurred"""
        summary = cache_monitor.get_stats_summary(days=7)

        assert summary["total_hits"] == 0
        assert summary["total_misses"] == 0
        assert summary["total_tokens_saved"] == 0
        assert summary["total_queries"] == 0
        assert summary["overall_hit_rate"] == 0.0
        assert summary["unique_cache_keys"] == 0
