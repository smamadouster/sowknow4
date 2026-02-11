"""
Structured logging service for SOWKNOW.

Provides JSON-formatted structured logging for log aggregation systems
like ELK Stack, Loki, or simple file-based collection.
"""
import logging
import json
import sys
import os
from datetime import datetime
from typing import Any, Dict, Optional
from contextlib import contextmanager
from pathlib import Path


class StructuredFormatter(logging.Formatter):
    """
    Custom formatter that outputs JSON-structured logs.

    Format compatible with ELK, Loki, and other log aggregators.
    """

    def __init__(self, service_name: str = "sowknow-api", environment: str = "development"):
        super().__init__()
        self.service_name = service_name
        self.environment = environment

    def format(self, record: logging.LogRecord) -> str:
        """
        Format log record as JSON.

        Args:
            record: Log record to format

        Returns:
            JSON-formatted log string
        """
        # Base log data
        log_data = {
            "@timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": self.service_name,
            "environment": self.environment,
        }

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                "message": str(record.exc_info[1]) if record.exc_info[1] else None,
                "traceback": self.formatException(record.exc_info) if record.exc_info else None,
            }

        # Add stack trace if available
        if record.stack_info:
            log_data["stack_trace"] = self.formatStack(record.stack_info)

        # Add function/location info
        log_data["location"] = {
            "file": record.pathname,
            "line": record.lineno,
            "function": record.funcName,
            "module": record.module,
        }

        # Add process/thread info
        log_data["process"] = {
            "id": record.process,
            "name": record.processName,
        }
        log_data["thread"] = {
            "id": record.thread,
            "name": record.threadName,
        }

        # Add custom fields from record
        for key, value in record.__dict__.items():
            if key not in {
                'name', 'msg', 'args', 'levelname', 'levelno', 'pathname',
                'filename', 'module', 'lineno', 'funcName', 'created',
                'msecs', 'relativeCreated', 'thread', 'threadName',
                'processName', 'process', 'getMessage', 'exc_info',
                'exc_text', 'stack_info', 'getMessage'
            }:
                log_data[key] = value

        return json.dumps(log_data, default=str)


class RequestContext:
    """
    Context manager for adding request context to logs.

    Usage:
        with RequestContext(user_id="123", request_id="abc"):
            logger.info("Processing request")
    """

    _context = {}

    @classmethod
    def set(cls, **kwargs):
        """Set context values."""
        cls._context.update(kwargs)

    @classmethod
    def get(cls) -> Dict[str, Any]:
        """Get current context."""
        return cls._context.copy()

    @classmethod
    def clear(cls):
        """Clear context."""
        cls._context.clear()

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.old_context = None

    def __enter__(self):
        self.old_context = self._context.copy()
        self._context.update(self.kwargs)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._context.clear()
        if self.old_context:
            self._context.update(self.old_context)


class RequestContextFilter(logging.Filter):
    """
    Logging filter that adds request context to log records.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Add context to log record."""
        context = RequestContext.get()
        for key, value in context.items():
            setattr(record, key, value)
        return True


def setup_structured_logging(
    service_name: str = "sowknow-api",
    environment: Optional[str] = None,
    level: str = "INFO",
    log_file: Optional[str] = None,
    enable_console: bool = True,
) -> logging.Logger:
    """
    Set up structured logging for the application.

    Args:
        service_name: Name of the service
        environment: Environment (development, production, etc.)
        level: Logging level
        log_file: Optional file to write logs to
        enable_console: Enable console output

    Returns:
        Configured root logger
    """
    if environment is None:
        environment = os.getenv("APP_ENV", "development")

    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Clear existing handlers
    root_logger.handlers.clear()

    # Create formatter
    formatter = StructuredFormatter(
        service_name=service_name,
        environment=environment
    )

    # Add context filter
    context_filter = RequestContextFilter()
    root_logger.addFilter(context_filter)

    # Console handler
    if enable_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        console_handler.setLevel(logging.DEBUG)
        root_logger.addHandler(console_handler)

    # File handler
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=50 * 1024 * 1024,  # 50MB
            backupCount=10,
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(logging.DEBUG)
        root_logger.addHandler(file_handler)

    # Configure specific loggers
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("celery").setLevel(logging.INFO)
    logging.getLogger("redis").setLevel(logging.WARNING)

    return root_logger


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger with the given name.

    Args:
        name: Logger name (usually __name__)

    Returns:
        Logger instance
    """
    return logging.getLogger(name)


class RequestLogger:
    """
    Logger for HTTP requests with timing information.

    Usage:
        request_logger = RequestLogger()
        with request_logger.log_request("/api/v1/documents", "GET"):
            # ... handle request ...
            pass
    """

    def __init__(self):
        self.logger = get_logger("sowknow.requests")

    @contextmanager
    def log_request(
        self,
        path: str,
        method: str,
        user_id: Optional[str] = None,
        request_id: Optional[str] = None,
    ):
        """
        Log HTTP request with timing.

        Args:
            path: Request path
            method: HTTP method
            user_id: Optional user ID
            request_id: Optional request ID
        """
        import time

        start_time = time.time()

        context = {
            "http_path": path,
            "http_method": method,
            "request_start": datetime.utcnow().isoformat() + "Z",
        }

        if user_id:
            context["user_id"] = user_id
        if request_id:
            context["request_id"] = request_id

        with RequestContext(**context):
            self.logger.info("Request started")

        try:
            yield

            duration = time.time() - start_time
            with RequestContext(
                http_duration_seconds=duration,
                http_status="200",
            ):
                self.logger.info("Request completed")

        except Exception as e:
            duration = time.time() - start_time
            with RequestContext(
                http_duration_seconds=duration,
                http_status="500",
                error=str(e),
                error_type=type(e).__name__,
            ):
                self.logger.error("Request failed")


class QueryLogger:
    """
    Logger for database queries with timing.
    """

    def __init__(self):
        self.logger = get_logger("sowknow.queries")

    @contextmanager
    def log_query(
        self,
        query_type: str,
        table: Optional[str] = None,
    ):
        """
        Log database query with timing.

        Args:
            query_type: Type of query (select, insert, update, delete)
            table: Optional table name
        """
        import time

        start_time = time.time()

        context = {
            "query_type": query_type,
        }
        if table:
            context["table"] = table

        try:
            yield
            duration = time.time() - start_time
            if duration > 1.0:  # Log slow queries
                with RequestContext(query_duration_seconds=duration):
                    self.logger.warning(f"Slow query: {query_type} on {table}")

        except Exception as e:
            duration = time.time() - start_time
            with RequestContext(
                query_duration_seconds=duration,
                error=str(e),
            ):
                self.logger.error(f"Query failed: {query_type}")


# Global instances
_request_logger = None
_query_logger = None


def get_request_logger() -> RequestLogger:
    """Get global request logger instance."""
    global _request_logger
    if _request_logger is None:
        _request_logger = RequestLogger()
    return _request_logger


def get_query_logger() -> QueryLogger:
    """Get global query logger instance."""
    global _query_logger
    if _query_logger is None:
        _query_logger = QueryLogger()
    return _query_logger
