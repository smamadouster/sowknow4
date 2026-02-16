"""
Network utilities with retry logic for SOWKNOW services
Provides resilient HTTP client with exponential backoff and circuit breaker
"""
import asyncio
import functools
import logging
import time
from typing import Any, Callable, Optional, Tuple, Type
import httpx
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
    RetryError
)

logger = logging.getLogger(__name__)

RETRYABLE_EXCEPTIONS = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.HTTPError,
    ConnectionError,
    TimeoutError,
    OSError,
)


def with_retry(
    max_attempts: int = 3,
    min_wait: float = 1,
    max_wait: float = 10,
    retry_exceptions: Tuple[Type[Exception], ...] = RETRYABLE_EXCEPTIONS,
) -> Callable:
    """
    Decorator factory for adding retry logic to async network functions.
    
    Args:
        max_attempts: Maximum number of retry attempts
        min_wait: Minimum wait time between retries (exponential backoff)
        max_wait: Maximum wait time between retries
        retry_exceptions: Tuple of exception types to retry on
        
    Returns:
        Decorated function with retry logic
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        @retry(
            stop=stop_after_attempt(max_attempts),
            wait=wait_exponential(multiplier=min_wait, max=max_wait),
            retry=retry_if_exception_type(retry_exceptions),
            before_sleep=before_sleep_log(logger, logging.WARNING),
            reraise=True,
        )
        async def wrapper(*args, **kwargs) -> Any:
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                logger.warning(f"Attempt failed for {func.__name__}: {str(e)}")
                raise
        return wrapper
    return decorator


class CircuitBreaker:
    """
    Circuit breaker to prevent cascading failures.
    
    States:
    - CLOSED: Normal operation, requests pass through
    - OPEN: Too many failures, requests fail immediately
    - HALF_OPEN: Testing if service recovered
    """
    
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        half_open_success_threshold: int = 2,
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_success_threshold = half_open_success_threshold
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time: Optional[float] = None
        self.state = "CLOSED"
        
    def _can_execute(self) -> bool:
        """Check if request can be executed based on circuit state."""
        if self.state == "CLOSED":
            return True
        
        if self.state == "OPEN":
            if time.time() - self.last_failure_time >= self.recovery_timeout:
                self.state = "HALF_OPEN"
                self.success_count = 0
                logger.info("Circuit breaker: OPEN -> HALF_OPEN")
                return True
            return False
        
        if self.state == "HALF_OPEN":
            return True
            
        return False
    
    def _record_success(self) -> None:
        """Record successful request."""
        if self.state == "HALF_OPEN":
            self.success_count += 1
            if self.success_count >= self.half_open_success_threshold:
                self.state = "CLOSED"
                self.failure_count = 0
                self.success_count = 0
                logger.info("Circuit breaker: HALF_OPEN -> CLOSED")
        elif self.state == "CLOSED":
            self.failure_count = max(0, self.failure_count - 1)
    
    def _record_failure(self) -> None:
        """Record failed request."""
        self.failure_count += 1
        self.last_failure_time = time.time()
        
        if self.state == "HALF_OPEN":
            self.state = "OPEN"
            logger.warning("Circuit breaker: HALF_OPEN -> OPEN")
        elif self.failure_count >= self.failure_threshold:
            self.state = "OPEN"
            logger.warning(f"Circuit breaker: CLOSED -> OPEN (failures: {self.failure_count})")
    
    @property
    def status(self) -> dict:
        """Get circuit breaker status."""
        return {
            "state": self.state,
            "failure_count": self.failure_count,
            "success_count": self.success_count,
            "last_failure_time": self.last_failure_time,
        }


class ResilientAsyncClient:
    """
    Async HTTP client with built-in retry logic and circuit breaker.
    """
    
    def __init__(
        self,
        base_url: str = "",
        max_attempts: int = 3,
        min_wait: float = 1,
        max_wait: float = 10,
        timeout: float = 30.0,
        enable_circuit_breaker: bool = True,
    ):
        self.base_url = base_url
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None
        self._circuit_breaker = CircuitBreaker() if enable_circuit_breaker else None
        
        self._max_attempts = max_attempts
        self._min_wait = min_wait
        self._max_wait = max_wait
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create httpx client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(self.timeout),
            )
        return self._client
    
    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
    
    async def request(
        self,
        method: str,
        url: str,
        **kwargs,
    ) -> httpx.Response:
        """
        Make HTTP request with retry and circuit breaker.
        """
        if self._circuit_breaker and not self._circuit_breaker._can_execute():
            raise CircuitBreakerOpenError(
                f"Circuit breaker is {self._circuit_breaker.state}"
            )
        
        client = await self._get_client()
        last_exception: Optional[Exception] = None
        
        for attempt in range(1, self._max_attempts + 1):
            try:
                response = await client.request(method, url, **kwargs)
                
                if self._circuit_breaker:
                    self._circuit_breaker._record_success()
                    
                return response
                
            except RETRYABLE_EXCEPTIONS as e:
                last_exception = e
                logger.warning(
                    f"Request attempt {attempt}/{self._max_attempts} failed: {str(e)}"
                )
                
                if attempt < self._max_attempts:
                    wait_time = min(
                        self._min_wait * (2 ** (attempt - 1)),
                        self._max_wait
                    )
                    logger.info(f"Retrying in {wait_time}s...")
                    await asyncio.sleep(wait_time)
                else:
                    if self._circuit_breaker:
                        self._circuit_breaker._record_failure()
                    raise
        
        if last_exception:
            raise last_exception
    
    @with_retry()
    async def get(self, url: str, **kwargs) -> httpx.Response:
        """GET request with retry."""
        return await self.request("GET", url, **kwargs)
    
    @with_retry()
    async def post(self, url: str, **kwargs) -> httpx.Response:
        """POST request with retry."""
        return await self.request("POST", url, **kwargs)
    
    @with_retry()
    async def put(self, url: str, **kwargs) -> httpx.Response:
        """PUT request with retry."""
        return await self.request("PUT", url, **kwargs)
    
    @with_retry()
    async def delete(self, url: str, **kwargs) -> httpx.Response:
        """DELETE request with retry."""
        return await self.request("DELETE", url, **kwargs)
    
    def get_circuit_breaker_status(self) -> Optional[dict]:
        """Get circuit breaker status if enabled."""
        if self._circuit_breaker:
            return self._circuit_breaker.status
        return None


class CircuitBreakerOpenError(Exception):
    """Raised when circuit breaker is open and request is rejected."""
    pass


async def resilient_request(
    method: str,
    url: str,
    max_attempts: int = 3,
    timeout: float = 30.0,
    **kwargs,
) -> httpx.Response:
    """
    Convenience function for making a single resilient request.
    """
    client = ResilientAsyncClient(timeout=timeout)
    try:
        return await client.request(method, url, **kwargs)
    finally:
        await client.close()
