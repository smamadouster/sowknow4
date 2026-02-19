"""
Integration tests for DNS resilience and network utilities.
"""
import pytest
import socket
import time
import os
import sys
from unittest.mock import Mock, patch, AsyncMock, MagicMock
import subprocess
import importlib.util

# Setup path for dns_validator (relative to this test file)
test_dir = os.path.dirname(__file__)
backend_dir = os.path.join(test_dir, "..", "..")
root_dir = os.path.join(test_dir, "..", "..", "..")

scripts_path = os.path.join(root_dir, "scripts")
app_path = os.path.join(backend_dir, "app")
sys.path.insert(0, app_path)
sys.path.insert(0, scripts_path)

# Import dns_validator directly
dns_validator_path = os.path.join(scripts_path, "dns_validator.py")
spec = importlib.util.spec_from_file_location("dns_validator", dns_validator_path)
if spec and spec.loader:
    dns_validator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dns_validator)
    check_dns_resolution = dns_validator.check_dns_resolution
    validate_before_startup = dns_validator.validate_before_startup
    analyze_dns_config = dns_validator.analyze_dns_config

# Import network utils using importlib
network_utils_path = os.path.join(app_path, "network_utils.py")
spec2 = importlib.util.spec_from_file_location("network_utils", network_utils_path)
if spec2 and spec2.loader:
    network_utils = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(network_utils)
    with_retry = network_utils.with_retry
    CircuitBreaker = network_utils.CircuitBreaker
    ResilientAsyncClient = network_utils.ResilientAsyncClient
    CircuitBreakerOpenError = network_utils.CircuitBreakerOpenError
    RETRYABLE_EXCEPTIONS = network_utils.RETRYABLE_EXCEPTIONS


class TestDNSValidation:
    """Test DNS validation functionality"""

    def test_dns_resolution_success(self):
        """Test successful DNS resolution"""
        success, message = check_dns_resolution("google.com")
        assert success is True
        assert "resolved" in message.lower() or "google.com" in message

    def test_dns_resolution_failure(self):
        """Test DNS resolution failure"""
        with patch('socket.gethostbyname') as mock_gethost:
            mock_gethost.side_effect = socket.gaierror("Name or service not known")
            success, message = check_dns_resolution("invalid.domain.test")
            assert success is False
            assert "DNS resolution failed" in message or "failed" in message.lower()

    def test_validate_before_startup_all_passing(self):
        """Test pre-flight validation when all checks pass"""
        with patch('tests.integration.test_dns_resilience.check_dns_resolution') as mock_check:
            mock_check.return_value = (True, "resolved")
            result = validate_before_startup()
            assert result is True

    def test_validate_before_startup_with_failure(self):
        """Test pre-flight validation when some checks fail"""
        call_count = 0
        
        def mock_check(hostname):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                return (False, "failed")
            return (True, "resolved")
        
        dns_validator.check_dns_resolution = mock_check
        original_func = dns_validator.check_dns_resolution
        
        try:
            result = validate_before_startup()
            assert result is False
        finally:
            dns_validator.check_dns_resolution = original_func

    def test_analyze_dns_config(self):
        """Test DNS configuration analysis"""
        config = analyze_dns_config()
        assert "platform" in config
        assert "dns_servers" in config
        assert "timestamp" in config


class TestRetryLogic:
    """Test retry mechanism"""

    @pytest.mark.asyncio
    async def test_with_retry_success_first_attempt(self):
        """Test retry decorator with immediate success"""
        mock_func = AsyncMock(return_value="success")
        
        @with_retry(max_attempts=3)
        async def decorated():
            return await mock_func()
        
        result = await decorated()
        assert result == "success"
        assert mock_func.call_count == 1

    @pytest.mark.asyncio
    async def test_with_retry_eventual_success(self):
        """Test retry after failures"""
        import httpx
        call_count = 0
        
        async def failing_func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise httpx.ConnectError("Connection failed")
            return "success"
        
        @with_retry(max_attempts=3, min_wait=0.1)
        async def decorated():
            return await failing_func()
        
        result = await decorated()
        assert result == "success"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_with_retry_all_failures(self):
        """Test retry with all attempts failing"""
        import httpx
        
        async def always_fail():
            raise httpx.ConnectError("Connection failed")
        
        @with_retry(max_attempts=3, min_wait=0.1)
        async def decorated():
            return await always_fail()
        
        with pytest.raises(httpx.ConnectError):
            await decorated()


class TestCircuitBreakerIntegration:
    """Test circuit breaker functionality"""

    def test_circuit_breaker_states(self):
        """Test circuit breaker state transitions"""
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60)
        
        assert cb.state == "CLOSED"
        
        cb._record_failure()
        assert cb.state == "CLOSED"
        
        cb._record_failure()
        assert cb.state == "CLOSED"
        
        cb._record_failure()
        assert cb.state == "OPEN"
        
        # With recovery_timeout=60, _can_execute should still return False
        assert not cb._can_execute()

    def test_circuit_breaker_recovery(self):
        """Test circuit breaker recovery to half-open"""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0)
        
        cb._record_failure()
        assert cb.state == "OPEN"
        
        cb._can_execute()
        assert cb.state == "HALF_OPEN"


class TestResilientClient:
    """Test resilient async client"""

    @pytest.mark.asyncio
    async def test_make_request_with_circuit_breaker(self):
        """Test request with circuit breaker protection"""
        client = ResilientAsyncClient(
            base_url="http://httpbin.org",
            enable_circuit_breaker=True,
            max_attempts=3,
        )
        
        client._circuit_breaker._record_failure()
        client._circuit_breaker._record_failure()
        client._circuit_breaker._record_failure()
        client._circuit_breaker._record_failure()
        client._circuit_breaker._record_failure()
        
        with pytest.raises(CircuitBreakerOpenError):
            await client.get("/status/200")
        
        status = client.get_circuit_breaker_status()
        assert status["state"] == "OPEN"
        
        await client.close()

    @pytest.mark.asyncio
    async def test_client_close(self):
        """Test client properly closes"""
        client = ResilientAsyncClient(base_url="http://test.com")
        await client.close()
        assert client._client is None or client._client.is_closed


class TestDockerConfiguration:
    """Test Docker configuration"""

    def test_dockerfile_dns_config(self):
        """Verify Dockerfile has proper DNS configuration"""
        dockerfile_path = os.path.join(os.path.dirname(__file__), "..", "..", "backend", "Dockerfile")
        if os.path.exists(dockerfile_path):
            with open(dockerfile_path, 'r') as f:
                content = f.read()
                assert 'nameserver 8.8.8.8' in content or '8.8.8.8' in content

    def test_docker_compose_dns(self):
        """Verify docker-compose has DNS configuration"""
        compose_path = os.path.join(os.path.dirname(__file__), "..", "..", "docker-compose.yml")
        if os.path.exists(compose_path):
            import yaml
            with open(compose_path, 'r') as f:
                config = yaml.safe_load(f)
                if 'services' in config and 'postgres' in config['services']:
                    dns_servers = config['services'].get('postgres', {}).get('dns', [])
                    assert '8.8.8.8' in dns_servers or '1.1.1.1' in dns_servers


class TestNetworkResilience:
    """Test network resilience scenarios"""

    @pytest.mark.asyncio
    async def test_timeout_configuration(self):
        """Test that timeout is properly configured"""
        client = ResilientAsyncClient(timeout=30.0)
        assert client.timeout == 30.0
        await client.close()

    def test_retryable_exceptions_defined(self):
        """Test that retryable exceptions are properly defined"""
        assert ConnectionError in RETRYABLE_EXCEPTIONS
        assert TimeoutError in RETRYABLE_EXCEPTIONS
        assert len(RETRYABLE_EXCEPTIONS) > 0


def test_end_to_end_dns_failure_scenario():
    """End-to-end test simulating DNS failure scenario"""
    
    with patch('socket.gethostbyname') as mock_dns:
        mock_dns.side_effect = socket.gaierror("Temporary failure in name resolution")
        
        success, message = check_dns_resolution("api.telegram.org")
        assert success is False
        
        mock_dns.side_effect = None
        
        success, message = check_dns_resolution("google.com")
        assert success is True


def test_circuit_breaker_full_cycle():
    """Test full circuit breaker lifecycle"""
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0, half_open_success_threshold=2)
    
    cb._record_failure()
    cb._record_failure()
    assert cb.state == "OPEN"
    
    cb._can_execute()
    assert cb.state == "HALF_OPEN"
    
    cb._record_success()
    cb._record_success()
    assert cb.state == "CLOSED"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
