# Docker Compliance Testing

## Overview

This document describes the Docker Compliance Test Suite for SOWKNOW, which validates that the Docker Compose configuration meets production-ready standards.

## Test Suite Purpose

The test suite ensures:
- Correct number of services are configured
- Resource limits (memory/CPU) are properly set
- Volumes are defined for persistent data
- Ollama uses shared instance (not containerized)
- Health checks are configured for critical services
- No hardcoded secrets in configuration files
- Production compose file is valid

## Running Tests Locally

### Basic Execution

```bash
./scripts/test_docker_compliance.sh
```

### Verbose Mode

```bash
./scripts/test_docker_compliance.sh --verbose
```

### JSON Output (for CI systems)

```bash
./scripts/test_docker_compliance.sh --json
```

### Preflight Checks Only

```bash
./scripts/test_docker_compliance.sh --preflight
```

## Understanding Test Results

### Exit Codes

- `0` - All tests passed
- `1` - One or more tests failed

### Output Colors

- **Green [PASS]**: Test successful
- **Red [FAIL]**: Test failed
- **Yellow [WARN]**: Warning (non-critical)
- **Blue [INFO]**: Informational message

## Test Cases

### Test 1: Container Count Validation

Verifies at least 7 core services are configured in docker-compose.yml.

**Expected Services:**
- postgres (Database)
- redis (Cache/Queue)
- backend (FastAPI)
- celery-worker (Background tasks)
- celery-beat (Scheduled tasks)
- frontend (Next.js)
- telegram-bot (Mobile interface)

### Test 2: Memory Limits Verification

Ensures all services have memory limits defined in deploy.resources.limits.memory.

**Required for:** All services

### Test 3: CPU Limits Validation

Ensures all services have CPU limits defined in deploy.resources.limits.cpus.

**Required for:** All services

### Test 4: Volume Existence Checks

Verifies at least 3 volumes are defined for persistent data storage.

**Standard Volumes:**
- postgres_data
- redis_data
- uploads
- backups

### Test 5: Ollama Exclusion Verification

Confirms Ollama is NOT containerized in compose files.

**Rationale:** Ollama uses the shared host instance (ghostshell-api) to save ~2GB memory.

### Test 6: Health Check Validation

Ensures at least 6 services have health checks configured.

**Required Health Checks:**
- postgres
- redis
- backend
- frontend
- celery-worker
- telegram-bot

### Test 7: Hardcoded Secrets Detection

Scans for potential hardcoded passwords, API keys, or secrets.

**Checked Patterns:**
- `password='...'`
- `api_key='...'`
- `secret='...'`

**Note:** Uses environment variables (${VAR}) which are exempt.

### Test 8: Production Compose Verification

Validates docker-compose.production.yml exists and is syntactically correct.

## Adding New Tests

To add a new test:

1. Create a test function in `scripts/test_docker_compliance.sh`:

```bash
test_new_check() {
    # Your validation logic
    if [ condition ]; then
        return 0
    else
        return 1
    fi
}
```

2. Add the test to the main function:

```bash
run_test "Test Name" test_new_check
```

3. Update TOTAL_TESTS if needed (automatic with run_test)

## Troubleshooting

### "docker-compose.yml not found"

Ensure you're running from the project root directory.

### "Docker not found"

Install Docker or run tests in an environment with Docker available.

### "Docker Compose v2 not found"

Upgrade to Docker Compose v2:
```bash
apt-get update && apt-get install docker-compose-v2
```

### Tests fail in CI but pass locally

Ensure Docker is properly configured in GitHub Actions:
```yaml
- uses: docker/setup-docker@v4
```

## CI/CD Integration

The test suite integrates with GitHub Actions via `.github/workflows/docker-compliance.yml`.

### Workflow Triggers

- Push to main/master/develop branches
- Pull requests to main/master
- Changes to docker-compose*.yml files

### Failure Notifications

On test failure, an artifact with results is uploaded for debugging.

## Performance Considerations

- Tests run in ~5 seconds
- Minimal Docker API calls (cached config)
- No containers started during testing
