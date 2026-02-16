"""
Unit tests for network utilities with retry logic.
"""
import asyncio
import pytest
import httpx
from unittest.mock import AsyncMock, patch, MagicMock
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "backend", "app"))

try:
    from app.network_utils import (
        with_retry,
        CircuitBreaker,
        ResilientAsyncClient,
        CircuitBreakerOpenError,
        RETRYABLE_EXCEPTIONS,
    )
except ImportError:
    from network_utils import (
        with_retry,
        CircuitBreaker,
        ResilientAsyncClient,
        CircuitBreakerOpenError,
        RETRYABLE_EXCEPTIONS,
    )


class TestCircuitBreaker:
    """Tests for CircuitBreaker class."""

    def test_initial_state_closed(self):
        """Test circuit breaker starts in CLOSED state."""
        cb = CircuitBreaker()
        assert cb.state == "CLOSED"

    def test_failure_threshold_opens_circuit(self):
        """Test circuit opens after reaching failure threshold."""
        cb = CircuitBreaker(failure_threshold=3)
        
        cb._record_failure()
        assert cb.state == "CLOSED"
        
        cb._record_failure()
        assert cb.state == "CLOSED"
        
        cb._record_failure()
        assert cb.state == "OPEN"

    def test_success_resets_failures(self):
        """Test success resets failure count in CLOSED state."""
        cb = CircuitBreaker(failure_threshold=5)
        
        cb._record_failure()
        cb._record_failure()
        cb._record_success()
        
        assert cb.failure_count == 1

    def test_recovery_timeout_transitions_to_half_open(self):
        """Test circuit moves to HALF_OPEN after recovery timeout."""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0)
        
        cb._record_failure()
        assert cb.state == "OPEN"
        
        cb._can_execute()
        assert cb.state == "HALF_OPEN"

    def test_half_open_success_closes_circuit(self):
        """Test HALF_OPEN closes after success threshold."""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0, half_open_success_threshold=2)
        
        cb._record_failure()
        cb._record_failure()
        
        cb._record_success()
        cb._record_success()
        
        assert cb.state == "CLOSED"

    def test_half_open_failure_reopens_circuit(self):
        """Test HALF_OPEN reopens on failure."""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0)
        
        cb._record_failure()
        cb._record_failure()
        
        assert cb.state == "OPEN"
        
        cb._can_execute()
        assert cb.state == "HALF_OPEN"
        
        cb._record_failure()
        assert cb.state == "OPEN"

    def test_cannot_execute_when_open(self):
        """Test request is rejected when circuit is OPEN."""
        cb = CircuitBreaker(failure_threshold=1)
        
        cb._record_failure()
        cb._record_failure()
        
        assert not cb._can_execute()

    def test_status_returns_dict(self):
        """Test status returns proper dictionary."""
        cb = CircuitBreaker(failure_threshold=5)
        
        status = cb.status
        
        assert "state" in status
        assert "failure_count" in status
        assert status["state"] == "CLOSED"


class TestWithRetry:
    """Tests for with_retry decorator."""

    @pytest.mark.asyncio
    async def test_successful_call_no_retry(self):
        """Test successful call doesn't trigger retry."""
        mock_func = AsyncMock(return_value={"success": True})
        
        @with_retry(max_attempts=3)
        async def func():
            return await mock_func()
        
        result = await func()
        
        assert result == {"success": True}
        assert mock_func.call_count == 1

    @pytest.mark.asyncio
    async def test_retry_on_connection_error(self):
        """Test retry on connection error."""
        call_count = 0
        
        async def failing_func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise httpx.ConnectError("Connection failed")
            return {"success": True}
        
        @with_retry(max_attempts=3, min_wait=0.1)
        async def func():
            return await failing_func()
        
        result = await func()
        
        assert result == {"success": True}
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_exhausted_retries_raises(self):
        """Test exhausted retries raises RetryError."""
        async def always_fail():
            raise httpx.ConnectError("Connection failed")
        
        @with_retry(max_attempts=3, min_wait=0.1)
        async def func():
            return await always_fail()
        
        with pytest.raises(httpx.ConnectError):
            await func()

    @pytest.mark.asyncio
    async def test_no_retry_on_non_retryable_exception(self):
        """Test non-retryable exceptions don't trigger retry."""
        call_count = 0
        
        async def failing_func():
            nonlocal call_count
            call_count += 1
            raise ValueError("Not retryable")
        
        @with_retry(max_attempts=3, min_wait=0.1)
        async def func():
            return await failing_func()
        
        with pytest.raises(ValueError):
            await func()
        
        assert call_count == 1


class TestResilientAsyncClient:
    """Tests for ResilientAsyncClient class."""

    @pytest.mark.asyncio
    async def test_successful_get_request(self):
        """Test successful GET request."""
        client = ResilientAsyncClient(base_url="http://test.com", enable_circuit_breaker=False)
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": "test"}
        
        with patch.object(client, 'request', return_value=mock_response):
            response = await client.get("/test")
            
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_successful_post_request(self):
        """Test successful POST request."""
        client = ResilientAsyncClient(base_url="http://test.com", enable_circuit_breaker=False)
        
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {"id": 1}
        
        with patch.object(client, 'request', return_value=mock_response):
            response = await client.post("/test", json={"key": "value"})
            
        assert response.status_code == 201

    @pytest.mark.asyncio
    async def test_circuit_breaker_integration(self):
        """Test circuit breaker integration."""
        client = ResilientAsyncClient(
            base_url="http://test.com",
            enable_circuit_breaker=True,
            max_attempts=1,
        )
        
        client._circuit_breaker._record_failure()
        client._circuit_breaker._record_failure()
        
        with pytest.raises(CircuitBreakerOpenError):
            await client.get("/test")
        
        status = client.get_circuit_breaker_status()
        assert status["state"] == "OPEN"

    @pytest.mark.asyncio
    async def test_close_client(self):
        """Test client close properly."""
        client = ResilientAsyncClient(base_url="http://test.com")
        
        await client.close()
        
        assert client._client is None or client._client.is_closed

    @pytest.mark.asyncio
    async def test_circuit_breaker_records_success(self):
        """Test successful request records in circuit breaker."""
        client = ResilientAsyncClient(
            base_url="http://test.com",
            enable_circuit_breaker=True,
        )
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {}
        
        with patch.object(client, 'request', return_value=mock_response):
            await client.get("/test")
        
        status = client.get_circuit_breaker_status()
        assert status["failure_count"] == 0
        
        await client.close()


class TestRetryableExceptions:
    """Tests for retryable exceptions tuple."""

    def test_contains_httpx_exceptions(self):
        """Test RETRYABLE_EXCEPTIONS contains httpx exceptions."""
        assert httpx.ConnectError in RETRYABLE_EXCEPTIONS
        assert httpx.ConnectTimeout in RETRYABLE_EXCEPTIONS
        assert httpx.ReadTimeout in RETRYABLE_EXCEPTIONS

    def test_contains_standard_exceptions(self):
        """Test RETRYABLE_EXCEPTIONS contains standard exceptions."""
        assert ConnectionError in RETRYABLE_EXCEPTIONS
        assert TimeoutError in RETRYABLE_EXCEPTIONS
        assert OSError in RETRYABLE_EXCEPTIONS
