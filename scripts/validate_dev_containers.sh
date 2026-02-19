#!/bin/bash

# Validate all 8 containers are present in docker-compose.yml
# Agent A - Phase 1: Development Environment Validation

COMPOSE_FILE="docker-compose.yml"

echo "=========================================="
echo "Container Validation Script"
echo "=========================================="
echo ""

# Expected services
EXPECTED_SERVICES=("postgres" "redis" "backend" "celery-worker" "celery-beat" "frontend" "nginx" "telegram-bot")

echo "Checking for expected services in $COMPOSE_FILE..."
echo ""

# Check if compose file exists
if [ ! -f "$COMPOSE_FILE" ]; then
    echo "ERROR: $COMPOSE_FILE not found!"
    exit 1
fi

PASS_COUNT=0
FAIL_COUNT=0

for service in "${EXPECTED_SERVICES[@]}"; do
    if grep -q "^  $service:" "$COMPOSE_FILE"; then
        echo "✓ FOUND: $service"
        PASS_COUNT=$((PASS_COUNT + 1))
    else
        echo "✗ MISSING: $service"
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
done

echo ""
echo "=========================================="
echo "Summary: $PASS_COUNT passed, $FAIL_COUNT failed"
echo "=========================================="

# Check for optional prometheus service
if grep -q "^  prometheus:" "$COMPOSE_FILE"; then
    echo "Note: prometheus service found (optional, profile-based)"
fi

if [ $FAIL_COUNT -eq 0 ]; then
    echo "✓ All 8 required containers are present!"
    exit 0
else
    echo "✗ Some required containers are missing!"
    exit 1
fi
