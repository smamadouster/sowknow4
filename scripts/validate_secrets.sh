#!/bin/bash

# Validate secrets and environment variables in docker-compose.yml
# Agent A - Phase 1: Development Environment Validation

set -e

COMPOSE_FILE="docker-compose.yml"

echo "=========================================="
echo "Secrets & Environment Validation Script"
echo "=========================================="
echo ""

# Check if compose file exists
if [ ! -f "$COMPOSE_FILE" ]; then
    echo "ERROR: $COMPOSE_FILE not found!"
    exit 1
fi

echo "Checking for hardcoded fallback secrets (anti-pattern: ':-ChangeMe' or ':-default')..."
echo ""

# Check for hardcoded fallback secrets (anti-pattern)
HARDCODED=$(grep -n ":-" "$COMPOSE_FILE" | grep -v ":\?-" | grep -v "memory:" | grep -v "cpus:" || true)

if [ -n "$HARDCODED" ]; then
    echo "⚠ WARNING: Found potential hardcoded fallbacks:"
    echo "$HARDCODED"
    echo ""
else
    echo "✓ No hardcoded fallback secrets found"
fi

echo ""
echo "Checking mandatory environment variables (should use :? syntax)..."
echo ""

# Services to check for mandatory env vars
SERVICES=("backend" "postgres" "redis" "celery-worker" "celery-beat" "telegram-bot")

PASS_COUNT=0
FAIL_COUNT=0

for service in "${SERVICES[@]}"; do
    echo "--- $service ---"
    
    # Check if service uses env_file
    if grep -A20 "^  $service:" "$COMPOSE_FILE" | grep -q "env_file:"; then
        echo "  ✓ Uses env_file for environment variables"
        ((PASS_COUNT++))
    else
        echo "  ⚠ May be missing env_file configuration"
    fi
    
    # Check for DATABASE_PASSWORD usage (should be mandatory)
    if grep -A30 "^  $service:" "$COMPOSE_FILE" | grep -q "DATABASE_PASSWORD:\${DATABASE_PASSWORD"; then
        if grep -A30 "^  $service:" "$COMPOSE_FILE" | grep -q "DATABASE_PASSWORD:\${DATABASE_PASSWORD:?"; then
            echo "  ✓ DATABASE_PASSWORD uses mandatory (:?) syntax"
            ((PASS_COUNT++))
        else
            echo "  ✗ DATABASE_PASSWORD may have fallback (should use :?)"
            ((FAIL_COUNT++))
        fi
    fi
    
    # Check for JWT_SECRET usage (should be mandatory)
    if grep -A30 "^  $service:" "$COMPOSE_FILE" | grep -q "JWT_SECRET:\${JWT_SECRET"; then
        if grep -A30 "^  $service:" "$COMPOSE_FILE" | grep -q "JWT_SECRET:\${JWT_SECRET:?"; then
            echo "  ✓ JWT_SECRET uses mandatory (:?) syntax"
            ((PASS_COUNT++))
        else
            echo "  ✗ JWT_SECRET may have fallback (should use :?)"
            ((FAIL_COUNT++))
        fi
    fi
    
    echo ""
done

echo "=========================================="
echo "Summary: $PASS_COUNT passed, $FAIL_COUNT failed"
echo "=========================================="

if [ $FAIL_COUNT -eq 0 ]; then
    echo "✓ Secrets configuration looks good!"
    exit 0
else
    echo "✗ Some secrets need adjustment!"
    exit 1
fi
