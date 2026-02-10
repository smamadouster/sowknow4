#!/bin/bash
# SOWKNOW Test Runner
# Runs all tests with coverage reporting

set -e

echo "========================================="
echo "SOWKNOW Test Suite"
echo "========================================="

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Test results
TESTS_PASSED=0
TESTS_FAILED=0

# Function to run test suite
run_tests() {
    local test_type=$1
    local test_path=$2
    local extra_args=$3

    echo -e "\n${YELLOW}Running $test_type tests...${NC}"

    if [ -f "$test_path" ]; then
        if python -m pytest "$test_path" -v --tb=short --color=yes $extra_args; then
            TESTS_PASSED=$((TESTS_PASSED + $?))
            echo -e "${GREEN}✓ $test_type tests passed${NC}"
        else
            TESTS_FAILED=$((TESTS_FAILED + 1))
            echo -e "${RED}✗ $test_type tests failed${NC}"
        fi
    else
        echo -e "${YELLOW}⚠ $test_type tests not found at $test_path${NC}"
    fi
}

# Check if running in Docker
if [ -f "/.dockerenv" ]; then
    echo "Running inside Docker container"
    EXTRA_ARGS=""
else
    echo "Running outside Docker - using docker-compose"
    DOCKER_RUN="docker-compose -f docker-compose.yml run --rm backend"
fi

# Unit tests
echo -e "\n========================================="
echo "Unit Tests"
echo "========================================="
run_tests "Unit" "backend/tests/test_unit.py" "$EXTRA_ARGS"

# E2E tests
echo -e "\n========================================="
echo "End-to-End Tests"
echo "========================================="
run_tests "E2E" "backend/tests/test_e2e.py" "$EXTRA_ARGS -m integration"

# Performance tests
echo -e "\n========================================="
echo "Performance Tests"
echo "========================================="
run_tests "Performance" "backend/tests/test_e2e.py" "$EXTRA_ARGS -m performance"

# Knowledge Graph tests
echo -e "\n========================================="
echo "Knowledge Graph Tests"
echo "========================================="
run_tests "Knowledge Graph" "backend/tests/test_knowledge_graph.py" "$EXTRA_ARGS"

# Multi-Agent tests
echo -e "\n========================================="
echo "Multi-Agent Tests"
echo "========================================="
run_tests "Multi-Agent" "backend/tests/test_multi_agent.py" "$EXTRA_ARGS"

# Summary
echo -e "\n========================================="
echo "Test Summary"
echo "========================================="
echo -e "Total Test Suites: $((TESTS_PASSED + TESTS_FAILED))"
echo -e "${GREEN}Passed: $TESTS_PASSED${NC}"
if [ $TESTS_FAILED -gt 0 ]; then
    echo -e "${RED}Failed: $TESTS_FAILED${NC}"
    exit 1
else
    echo -e "${GREEN}All tests passed!${NC}"
    exit 0
fi
