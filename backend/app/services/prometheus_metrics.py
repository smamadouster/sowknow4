"""
Prometheus metrics exporter for SOWKNOW monitoring.

Exposes metrics in Prometheus format for scraping by Prometheus server.
Per PRD requirements for observability.
"""
import time
import logging
from typing import Dict, Callable, Optional
from functools import wraps
from collections import defaultdict
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class Metric:
    """Base class for Prometheus metrics."""

    def __init__(self, name: str, help_text: str, labels: list = None):
        """
        Initialize a metric.

        Args:
            name: Metric name (must follow Prometheus naming conventions)
            help_text: HELP text for the metric
            labels: Optional list of label names
        """
        self.name = name
        self.help_text = help_text
        self.labels = labels or []
        self._values: Dict[tuple, float] = {}

    def _key(self, label_values: dict) -> tuple:
        """Convert label dict to tuple key."""
        if not self.labels:
            return ()
        return tuple(label_values.get(label, "") for label in self.labels)

    def set(self, value: float, labels: dict = None):
        """Set metric value."""
        key = self._key(labels or {})
        self._values[key] = value

    def inc(self, delta: float = 1.0, labels: dict = None):
        """Increment metric value."""
        key = self._key(labels or {})
        self._values[key] = self._values.get(key, 0) + delta

    def observe(self, value: float, labels: dict = None):
        """Observe a value (for histograms)."""
        key = self._key(labels or {})
        self._values[key] = value

    def format(self) -> str:
        """Format metric for Prometheus export."""
        lines = [f"# HELP {self.name} {self.help_text}", f"# TYPE {self.name} gauge"]

        for key, value in self._values.items():
            if self.labels and key:
                label_str = ",".join(
                    f'{k}="{v}"' for k, v in zip(self.labels, key) if v
                )
                lines.append(f'{self.name}{{{label_str}}} {value}')
            else:
                lines.append(f"{self.name} {value}")

        return "\n".join(lines)


class Counter(Metric):
    """Prometheus counter metric."""

    def __init__(self, name: str, help_text: str, labels: list = None):
        super().__init__(name, help_text, labels)

    def format(self) -> str:
        """Format counter metric."""
        lines = [f"# HELP {self.name} {self.help_text}", f"# TYPE {self.name} counter"]

        for key, value in self._values.items():
            if self.labels and key:
                label_str = ",".join(
                    f'{k}="{v}"' for k, v in zip(self.labels, key) if v
                )
                lines.append(f'{self.name}{{{label_str}}} {value}')
            else:
                lines.append(f"{self.name} {value}")

        return "\n".join(lines)


class Histogram(Metric):
    """Prometheus histogram metric with buckets."""

    DEFAULT_BUCKETS = [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, float('inf')]

    def __init__(self, name: str, help_text: str, labels: list = None, buckets: list = None):
        super().__init__(name, help_text, labels)
        self.buckets = buckets or self.DEFAULT_BUCKETS
        self._observations: Dict[tuple, list] = defaultdict(list)

    def observe(self, value: float, labels: dict = None):
        """Observe a value."""
        key = self._key(labels or {})
        self._observations[key].append(value)

    def format(self) -> str:
        """Format histogram metric."""
        lines = [f"# HELP {self.name} {self.help_text}", f"# TYPE {self.name} histogram"]

        bucket_label = "le"
        label_names = self.labels + [bucket_label] if self.labels else [bucket_label]

        for key, observations in self._observations.items():
            # Sort observations
            sorted_obs = sorted(observations)
            total_count = len(sorted_obs)

            # Calculate bucket counts
            for bucket in self.buckets:
                bucket_count = sum(1 for v in sorted_obs if v <= bucket)
                bucket_str = "+Inf" if bucket == float('inf') else str(bucket)

                if self.labels:
                    label_str = ",".join(
                        f'{k}="{v}"' for k, v in zip(self.labels, key) if v
                    )
                    lines.append(f'{self.name}{{{label_str},{bucket_label}="{bucket_str}"}} {bucket_count}')
                else:
                    lines.append(f'{self.name}{{{bucket_label}="{bucket_str}"}} {bucket_count}')

            # Add sum and count
            sum_val = sum(sorted_obs)
            if self.labels:
                label_str = ",".join(
                    f'{k}="{v}"' for k, v in zip(self.labels, key) if v
                )
                lines.append(f'{self.name}_sum{{{label_str}}} {sum_val}')
                lines.append(f'{self.name}_count{{{label_str}}} {total_count}')
            else:
                lines.append(f'{self.name}_sum {sum_val}')
                lines.append(f'{self.name}_count {total_count}')

        return "\n".join(lines)


class PrometheusMetrics:
    """
    Central registry for Prometheus metrics.

    Provides a singleton interface for defining and accessing metrics.
    """

    _instance: Optional['PrometheusMetrics'] = None

    def __init__(self):
        """Initialize metrics registry."""
        self._metrics: Dict[str, Metric] = {}
        self._start_time = time.time()

    @classmethod
    def get_instance(cls) -> 'PrometheusMetrics':
        """Get singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def counter(self, name: str, help_text: str, labels: list = None) -> Counter:
        """
        Get or create a counter metric.

        Args:
            name: Metric name
            help_text: HELP text
            labels: Optional label names

        Returns:
            Counter metric
        """
        if name not in self._metrics:
            self._metrics[name] = Counter(name, help_text, labels)
        return self._metrics[name]

    def gauge(self, name: str, help_text: str, labels: list = None) -> Metric:
        """
        Get or create a gauge metric.

        Args:
            name: Metric name
            help_text: HELP text
            labels: Optional label names

        Returns:
            Gauge metric
        """
        if name not in self._metrics:
            self._metrics[name] = Metric(name, help_text, labels)
        return self._metrics[name]

    def histogram(self, name: str, help_text: str, labels: list = None, buckets: list = None) -> Histogram:
        """
        Get or create a histogram metric.

        Args:
            name: Metric name
            help_text: HELP text
            labels: Optional label names
            buckets: Optional bucket boundaries

        Returns:
            Histogram metric
        """
        if name not in self._metrics:
            self._metrics[name] = Histogram(name, help_text, labels, buckets)
        return self._metrics[name]

    def export(self) -> str:
        """
        Export all metrics in Prometheus format.

        Returns:
            String containing all metrics
        """
        lines = []

        # Add startup time metric
        uptime = time.time() - self._start_time
        lines.append(f"# HELP sowknow_uptime_seconds Seconds since startup")
        lines.append(f"# TYPE sowknow_uptime_seconds gauge")
        lines.append(f"sowknow_uptime_seconds {uptime:.2f}")

        # Add export timestamp
        lines.append(f"# HELP sowknow_export_timestamp_seconds Unix timestamp of last export")
        lines.append(f"# TYPE sowknow_export_timestamp_seconds gauge")
        lines.append(f"sowknow_export_timestamp_seconds {time.time():.2f}")

        # Add all registered metrics
        for metric in self._metrics.values():
            lines.append("")
            lines.append(metric.format())

        return "\n".join(lines)


# Global metrics instance
def get_metrics() -> PrometheusMetrics:
    """Get the global metrics registry."""
    return PrometheusMetrics.get_instance()


# Define standard metrics
def setup_standard_metrics():
    """
    Set up standard SOWKNOW metrics.

    Call this during application startup to initialize all metrics.
    """
    m = get_metrics()

    # HTTP metrics
    m.counter(
        "sowknow_http_requests_total",
        "Total number of HTTP requests",
        ["method", "endpoint", "status"]
    )

    m.histogram(
        "sowknow_http_request_duration_seconds",
        "HTTP request latency in seconds",
        ["method", "endpoint"],
        buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
    )

    # Database metrics
    m.gauge(
        "sowknow_database_connections",
        "Number of database connections",
        ["state"]
    )

    m.histogram(
        "sowknow_database_query_duration_seconds",
        "Database query latency in seconds",
        ["query_type"],
        buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0]
    )

    # Queue metrics
    m.gauge(
        "sowknow_celery_queue_depth",
        "Number of tasks in Celery queue",
        ["queue_name"]
    )

    m.gauge(
        "sowknow_celery_workers_active",
        "Number of active Celery workers"
    )

    m.counter(
        "sowknow_celery_tasks_total",
        "Total number of Celery tasks processed",
        ["task_name", "status"]
    )

    m.histogram(
        "sowknow_celery_task_duration_seconds",
        "Celery task duration in seconds",
        ["task_name"],
        buckets=[0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 300.0]
    )

    # LLM metrics
    m.counter(
        "sowknow_llm_requests_total",
        "Total number of LLM API requests",
        ["service", "model", "operation"]
    )

    m.counter(
        "sowknow_llm_tokens_total",
        "Total number of tokens processed",
        ["service", "model", "type"]  # type: input, output, cached
    )

    m.histogram(
        "sowknow_llm_request_duration_seconds",
        "LLM API request latency in seconds",
        ["service", "model"],
        buckets=[0.5, 1.0, 2.5, 5.0, 10.0, 20.0, 30.0]
    )

    m.gauge(
        "sowknow_llm_cost_usd",
        "Total LLM API cost in USD",
        ["service"]
    )

    # Cache metrics
    m.gauge(
        "sowknow_cache_hit_rate",
        "Cache hit rate (0-1)",
        ["cache_type"]
    )

    m.counter(
        "sowknow_cache_hits_total",
        "Total number of cache hits",
        ["cache_type"]
    )

    m.counter(
        "sowknow_cache_misses_total",
        "Total number of cache misses",
        ["cache_type"]
    )

    # Document processing metrics
    m.counter(
        "sowknow_documents_processed_total",
        "Total number of documents processed",
        ["status", "document_type"]
    )

    m.histogram(
        "sowknow_document_processing_duration_seconds",
        "Document processing duration in seconds",
        ["document_type", "processing_stage"],
        buckets=[1.0, 5.0, 10.0, 30.0, 60.0, 300.0, 600.0]
    )

    m.gauge(
        "sowknow_documents_stuck",
        "Number of documents stuck in processing > 24h",
        ["bucket"]
    )

    # System metrics
    m.gauge(
        "sowknow_memory_usage_bytes",
        "Memory usage in bytes",
        ["container"]
    )

    m.gauge(
        "sowknow_memory_usage_percent",
        "Memory usage percentage",
        ["container"]
    )

    m.gauge(
        "sowknow_disk_usage_bytes",
        "Disk usage in bytes",
        ["mount_point"]
    )

    m.gauge(
        "sowknow_disk_usage_percent",
        "Disk usage percentage",
        ["mount_point"]
    )

    # User metrics
    m.gauge(
        "sowknow_users_active",
        "Number of active users"
    )

    m.counter(
        "sowknow_user_sessions_total",
        "Total number of user sessions",
        ["status"]  # started, ended
    )


def track_http_request(func: Callable):
    """
    Decorator to track HTTP requests in Prometheus metrics.

    Usage:
        @app.get("/api/example")
        @track_http_request
        async def example_endpoint():
            return {"status": "ok"}
    """
    @wraps(func)
    async def wrapper(*args, **kwargs):
        start_time = time.time()

        # Try to get request info from args
        method = "unknown"
        endpoint = "unknown"
        status = "200"

        result = await func(*args, **kwargs)

        # Calculate duration
        duration = time.time() - start_time

        # Record metrics
        m = get_metrics()
        m.counter("sowknow_http_requests_total").inc(1, {"method": method, "endpoint": endpoint, "status": status})
        m.histogram("sowknow_http_request_duration_seconds").observe(duration, {"method": method, "endpoint": endpoint})

        return result

    return wrapper


# Initialize standard metrics on import
setup_standard_metrics()
