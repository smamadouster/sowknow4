"""
Circuit Breaker utility for protecting CPU/IO-intensive services.

Prevents cascade failures by stopping calls to a failing service
for a cooldown period after N consecutive failures.

Usage:
    from app.utils.circuit_breaker import circuit_breaker

    @circuit_breaker(name="ocr", failure_threshold=3, cooldown_seconds=30)
    async def extract_text(self, ...):
        ...
"""

import logging
import threading
import time
from collections.abc import Callable
from functools import wraps
from typing import Any

logger = logging.getLogger(__name__)


class CircuitBreakerState:
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failing fast
    HALF_OPEN = "half_open"  # Testing recovery


class CircuitBreaker:
    """Thread-safe circuit breaker for protecting service calls."""

    def __init__(
        self,
        name: str,
        failure_threshold: int = 3,
        cooldown_seconds: float = 30.0,
        half_open_max_calls: int = 1,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.half_open_max_calls = half_open_max_calls

        self._state = CircuitBreakerState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: float | None = None
        self._lock = threading.RLock()

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    def _should_open(self) -> bool:
        return self._failure_count >= self.failure_threshold

    def _cooldown_elapsed(self) -> bool:
        if self._last_failure_time is None:
            return True
        return (time.monotonic() - self._last_failure_time) >= self.cooldown_seconds

    def record_success(self) -> None:
        with self._lock:
            if self._state == CircuitBreakerState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.half_open_max_calls:
                    logger.info("Circuit breaker '%s' CLOSED (recovered)", self.name)
                    self._state = CircuitBreakerState.CLOSED
                    self._failure_count = 0
                    self._success_count = 0
            elif self._state == CircuitBreakerState.CLOSED:
                self._failure_count = 0

    def record_failure(self) -> None:
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()

            if self._state == CircuitBreakerState.HALF_OPEN:
                logger.warning("Circuit breaker '%s' OPENED again (recovery failed)", self.name)
                self._state = CircuitBreakerState.OPEN
                self._success_count = 0
            elif self._state == CircuitBreakerState.CLOSED and self._should_open():
                logger.warning(
                    "Circuit breaker '%s' OPENED after %d failures (cooldown=%.0fs)",
                    self.name,
                    self._failure_count,
                    self.cooldown_seconds,
                )
                self._state = CircuitBreakerState.OPEN

    def can_execute(self) -> bool:
        with self._lock:
            if self._state == CircuitBreakerState.CLOSED:
                return True
            if self._state == CircuitBreakerState.OPEN:
                if self._cooldown_elapsed():
                    logger.info("Circuit breaker '%s' HALF_OPEN (testing recovery)", self.name)
                    self._state = CircuitBreakerState.HALF_OPEN
                    self._success_count = 0
                    return True
                return False
            # HALF_OPEN
            return self._success_count < self.half_open_max_calls

    def call(self, func: Callable, *args: Any, **kwargs: Any) -> Any:
        if not self.can_execute():
            raise CircuitBreakerOpenError(
                f"Circuit breaker '{self.name}' is OPEN — service temporarily unavailable"
            )
        try:
            result = func(*args, **kwargs)
            self.record_success()
            return result
        except Exception as exc:
            self.record_failure()
            raise

    async def call_async(self, func: Callable, *args: Any, **kwargs: Any) -> Any:
        if not self.can_execute():
            raise CircuitBreakerOpenError(
                f"Circuit breaker '{self.name}' is OPEN — service temporarily unavailable"
            )
        try:
            result = await func(*args, **kwargs)
            self.record_success()
            return result
        except Exception as exc:
            self.record_failure()
            raise


class CircuitBreakerOpenError(Exception):
    """Raised when a circuit breaker is open and a call is attempted."""

    pass


# Global registry of circuit breakers
_breakers: dict[str, CircuitBreaker] = {}
_registry_lock = threading.Lock()


def get_breaker(
    name: str,
    failure_threshold: int = 3,
    cooldown_seconds: float = 30.0,
) -> CircuitBreaker:
    """Get or create a named circuit breaker."""
    with _registry_lock:
        if name not in _breakers:
            _breakers[name] = CircuitBreaker(
                name=name,
                failure_threshold=failure_threshold,
                cooldown_seconds=cooldown_seconds,
            )
        return _breakers[name]


def circuit_breaker(
    name: str,
    failure_threshold: int = 3,
    cooldown_seconds: float = 30.0,
) -> Callable:
    """Decorator that wraps a function with a circuit breaker."""
    breaker = get_breaker(name, failure_threshold, cooldown_seconds)

    def decorator(func: Callable) -> Callable:
        if asyncio.iscoroutinefunction(func):
            @wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                return await breaker.call_async(func, *args, **kwargs)
            return async_wrapper
        else:
            @wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                return breaker.call(func, *args, **kwargs)
            return sync_wrapper

    return decorator


import asyncio
