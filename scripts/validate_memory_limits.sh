#!/bin/bash

# Validate memory limits for all containers
# Agent A - Phase 1: Development Environment Validation

COMPOSE_FILE="docker-compose.yml"

echo "=========================================="
echo "Memory Limits Validation Script"
echo "=========================================="
echo ""

# Expected memory limits
declare -A EXPECTED_MEMORY=(
    ["nginx"]="256"
    ["postgres"]="2048"
    ["redis"]="512"
    ["backend"]="1024"
    ["celery-worker"]="1536"
    ["celery-beat"]="512"
    ["frontend"]="512"
    ["telegram-bot"]="256"
)

echo "Checking memory limits in $COMPOSE_FILE..."
echo ""

PASS_COUNT=0
FAIL_COUNT=0

for service in "${!EXPECTED_MEMORY[@]}"; do
    expected="${EXPECTED_MEMORY[$service]}"
    
    # Extract memory limit from docker-compose.yml using grep
    # Look for the service and extract memory value
    memory=$(sed -n "/^  $service:/,/^  [a-z]/p" "$COMPOSE_FILE" 2>/dev/null | grep -A3 "memory:" | grep -oP '\d+' | head -1)
    
    if [ -z "$memory" ]; then
        echo "✗ $service: NOT SET (expected: ${expected}M)"
        FAIL_COUNT=$((FAIL_COUNT + 1))
    elif [ "$memory" = "$expected" ]; then
        echo "✓ $service: ${memory}M (expected: ${expected}M)"
        PASS_COUNT=$((PASS_COUNT + 1))
    else
        echo "✗ $service: ${memory}M (expected: ${expected}M)"
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
done

echo ""
echo "=========================================="
echo "Summary: $PASS_COUNT passed, $FAIL_COUNT failed"
echo "=========================================="

# Calculate total memory
TOTAL=0
for mem in "${EXPECTED_MEMORY[@]}"; do
    TOTAL=$((TOTAL + mem))
done
echo "Total expected memory: ${TOTAL}M (${TOTAL}/1024 = $((TOTAL/1024))GB)"

if [ $FAIL_COUNT -eq 0 ]; then
    echo "✓ All memory limits are correctly configured!"
    exit 0
else
    echo "✗ Some memory limits need adjustment!"
    exit 1
fi
