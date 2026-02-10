"""
Cache Monitor for tracking Gemini Flash context caching performance.

This module provides comprehensive monitoring of cache hit/miss rates,
token savings, and daily statistics for cost optimization tracking.
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from collections import defaultdict
from threading import Lock
import json

logger = logging.getLogger(__name__)


class DailyCacheStats:
    """
    Statistics for a single day of cache operations.
    Thread-safe for concurrent access.
    """

    def __init__(self, date: datetime):
        self.date = date.date()
        self._hits = 0
        self._misses = 0
        self._tokens_saved = 0
        self._queries = 0
        self._lock = Lock()

    def record_hit(self, tokens_saved: int) -> None:
        """Record a cache hit with tokens saved."""
        with self._lock:
            self._hits += 1
            self._tokens_saved += tokens_saved

    def record_miss(self) -> None:
        """Record a cache miss."""
        with self._lock:
            self._misses += 1

    def record_query(self) -> None:
        """Record a query (increment total queries)."""
        with self._lock:
            self._queries += 1

    @property
    def hits(self) -> int:
        """Get hit count."""
        return self._hits

    @property
    def misses(self) -> int:
        """Get miss count."""
        return self._misses

    @property
    def tokens_saved(self) -> int:
        """Get cumulative tokens saved."""
        return self._tokens_saved

    @property
    def queries(self) -> int:
        """Get total queries."""
        return self._queries

    @property
    def hit_rate(self) -> float:
        """Calculate hit rate as float (0.0 to 1.0)."""
        total = self._hits + self._misses
        if total == 0:
            return 0.0
        return self._hits / total

    def to_dict(self) -> Dict[str, Any]:
        """Convert stats to dictionary."""
        return {
            "date": self.date.isoformat(),
            "hits": self._hits,
            "misses": self._misses,
            "tokens_saved": self._tokens_saved,
            "queries": self._queries,
            "hit_rate": round(self.hit_rate, 4)
        }


class CacheMonitor:
    """
    Monitor for tracking Gemini Flash context cache performance.

    Tracks cache hits, misses, tokens saved, and provides statistics
    for cost optimization analysis. Thread-safe for concurrent use.
    """

    def __init__(self, retention_days: int = 30):
        """
        Initialize the cache monitor.

        Args:
            retention_days: Number of days to retain statistics (default: 30)
        """
        self._retention_days = retention_days
        self._daily_stats: Dict[datetime.date, DailyCacheStats] = {}
        self._lock = Lock()
        self._cache_keys_seen: set = set()

        # Initialize today's stats
        self._get_or_create_today_stats()

        logger.info(
            f"CacheMonitor initialized with {retention_days} days retention"
        )

    def _get_or_create_today_stats(self) -> DailyCacheStats:
        """Get or create stats for today."""
        today = datetime.now().date()
        with self._lock:
            if today not in self._daily_stats:
                self._daily_stats[today] = DailyCacheStats(datetime.now())
            return self._daily_stats[today]

    def _cleanup_old_stats(self) -> None:
        """Remove statistics older than retention period."""
        cutoff_date = (datetime.now() - timedelta(days=self._retention_days)).date()
        with self._lock:
            old_dates = [
                date for date in self._daily_stats.keys() if date < cutoff_date
            ]
            for date in old_dates:
                del self._daily_stats[date]
                logger.debug(f"Cleaned up cache stats for {date}")

    def record_cache_hit(
        self,
        cache_key: str,
        tokens_saved: int,
        user_id: Optional[str] = None
    ) -> None:
        """
        Record a cache hit event.

        Args:
            cache_key: The cache key that was hit
            tokens_saved: Number of tokens saved by this cache hit
            user_id: Optional user ID for per-user tracking
        """
        if tokens_saved < 0:
            logger.warning(
                f"Invalid tokens_saved value: {tokens_saved}. Must be non-negative."
            )
            return

        stats = self._get_or_create_today_stats()
        stats.record_hit(tokens_saved)
        stats.record_query()

        self._cache_keys_seen.add(cache_key)

        logger.debug(
            f"Cache hit: key='{cache_key[:50]}...', "
            f"tokens_saved={tokens_saved}, "
            f"user_id={user_id}"
        )

    def record_cache_miss(
        self,
        cache_key: str,
        user_id: Optional[str] = None
    ) -> None:
        """
        Record a cache miss event.

        Args:
            cache_key: The cache key that was missed
            user_id: Optional user ID for per-user tracking
        """
        stats = self._get_or_create_today_stats()
        stats.record_miss()
        stats.record_query()

        self._cache_keys_seen.add(cache_key)

        logger.debug(
            f"Cache miss: key='{cache_key[:50]}...', user_id={user_id}"
        )

    def get_hit_rate(self, days: int = 1) -> float:
        """
        Calculate cache hit rate for the specified number of days.

        Args:
            days: Number of days to include in calculation (default: 1)

        Returns:
            Hit rate as float between 0.0 and 1.0
        """
        if days < 1:
            logger.warning(f"Invalid days value: {days}. Using 1.")
            days = 1

        total_hits = 0
        total_misses = 0

        cutoff_date = (datetime.now() - timedelta(days=days)).date()

        with self._lock:
            for date, stats in self._daily_stats.items():
                if date >= cutoff_date:
                    total_hits += stats.hits
                    total_misses += stats.misses

        total = total_hits + total_misses
        if total == 0:
            return 0.0

        hit_rate = total_hits / total
        logger.debug(f"Hit rate for {days} day(s): {hit_rate:.4f}")
        return hit_rate

    def get_stats_summary(self, days: int = 7) -> Dict[str, Any]:
        """
        Get comprehensive statistics summary.

        Args:
            days: Number of days to include in summary (default: 7)

        Returns:
            Dictionary containing:
                - period_start: Start date of the period
                - period_end: End date of the period
                - daily_stats: List of daily statistics
                - overall_hit_rate: Hit rate for the period
                - total_tokens_saved: Cumulative tokens saved
                - total_queries: Total number of queries
                - unique_cache_keys: Number of unique cache keys seen
        """
        if days < 1:
            logger.warning(f"Invalid days value: {days}. Using 7.")
            days = 7

        # Cleanup old stats before generating summary
        self._cleanup_old_stats()

        cutoff_date = (datetime.now() - timedelta(days=days)).date()
        daily_stats_list = []
        total_hits = 0
        total_misses = 0
        total_tokens_saved = 0
        total_queries = 0

        with self._lock:
            # Sort dates in descending order (newest first)
            sorted_dates = sorted(
                self._daily_stats.keys(),
                reverse=True
            )

            for date in sorted_dates:
                if date >= cutoff_date:
                    stats = self._daily_stats[date]
                    daily_stats_list.append(stats.to_dict())
                    total_hits += stats.hits
                    total_misses += stats.misses
                    total_tokens_saved += stats.tokens_saved
                    total_queries += stats.queries

            unique_keys = len(self._cache_keys_seen)

        overall_hit_rate = 0.0
        total_operations = total_hits + total_misses
        if total_operations > 0:
            overall_hit_rate = total_hits / total_operations

        summary = {
            "period_start": cutoff_date.isoformat(),
            "period_end": datetime.now().date().isoformat(),
            "days_included": len(daily_stats_list),
            "daily_stats": daily_stats_list,
            "overall_hit_rate": round(overall_hit_rate, 4),
            "total_hits": total_hits,
            "total_misses": total_misses,
            "total_tokens_saved": total_tokens_saved,
            "total_queries": total_queries,
            "unique_cache_keys": unique_keys,
            "generated_at": datetime.now().isoformat()
        }

        logger.info(
            f"Generated stats summary for {days} day(s): "
            f"hit_rate={overall_hit_rate:.4f}, "
            f"tokens_saved={total_tokens_saved}"
        )

        return summary

    def get_today_stats(self) -> Dict[str, Any]:
        """
        Get statistics for today only.

        Returns:
            Dictionary with today's statistics
        """
        stats = self._get_or_create_today_stats()
        return stats.to_dict()

    def get_tokens_saved_today(self) -> int:
        """
        Get cumulative tokens saved today.

        Returns:
            Number of tokens saved today
        """
        stats = self._get_or_create_today_stats()
        return stats.tokens_saved

    def get_total_tokens_saved(self, days: int = 7) -> int:
        """
        Get cumulative tokens saved over specified period.

        Args:
            days: Number of days to include (default: 7)

        Returns:
            Total tokens saved in the period
        """
        if days < 1:
            days = 1

        cutoff_date = (datetime.now() - timedelta(days=days)).date()
        total = 0

        with self._lock:
            for date, stats in self._daily_stats.items():
                if date >= cutoff_date:
                    total += stats.tokens_saved

        return total

    def reset_today_stats(self) -> None:
        """
        Reset today's statistics (useful for testing or manual intervention).

        WARNING: This will irreversibly clear today's data.
        """
        today = datetime.now().date()
        with self._lock:
            if today in self._daily_stats:
                del self._daily_stats[today]
                logger.warning(f"Reset cache statistics for {today}")
            # Create fresh stats
            self._daily_stats[today] = DailyCacheStats(datetime.now())

    def get_all_dates(self) -> List[str]:
        """
        Get list of all dates with recorded statistics.

        Returns:
            List of date strings in ISO format
        """
        with self._lock:
            dates = sorted(self._daily_stats.keys(), reverse=True)
            return [date.isoformat() for date in dates]

    def export_stats_json(self, days: int = 7) -> str:
        """
        Export statistics as JSON string.

        Args:
            days: Number of days to include (default: 7)

        Returns:
            JSON string containing statistics
        """
        summary = self.get_stats_summary(days=days)
        return json.dumps(summary, indent=2)

    def get_retention_days(self) -> int:
        """Get the current retention period in days."""
        return self._retention_days

    def set_retention_days(self, days: int) -> None:
        """
        Update the retention period and cleanup old data.

        Args:
            days: New retention period in days (minimum: 1)
        """
        if days < 1:
            logger.warning(f"Invalid retention days: {days}. Minimum is 1.")
            return

        self._retention_days = days
        self._cleanup_old_stats()
        logger.info(f"Retention period updated to {days} days")


# Global cache monitor instance
cache_monitor = CacheMonitor(retention_days=30)
