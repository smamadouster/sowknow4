#!/bin/bash
###############################################################################
# SOWKNOW4 Pre-Flight Validator
#
# Run BEFORE "docker compose build" to catch problems at build time.
# Usage: bash monitoring/guardian-hc/scripts/preflight.sh
###############################################################################

set -uo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

PASS=0
FAIL=0
WARN=0

check_pass() { echo -e "  ${GREEN}+${NC} $1"; ((PASS++)); }
check_fail() { echo -e "  ${RED}x${NC} $1"; ((FAIL++)); }
check_warn() { echo -e "  ${YELLOW}!${NC} $1"; ((WARN++)); }

PROJECT_DIR="${1:-$(pwd)}"
cd "$PROJECT_DIR" || { echo "Cannot cd to $PROJECT_DIR"; exit 1; }

echo ""
echo -e "${BOLD}SOWKNOW4 Pre-Flight Validator${NC}"
echo -e "Project: $PROJECT_DIR"
echo ""

# -- 1. Check .env file --
echo -e "${BOLD}1. Environment${NC}"
if [ -f ".env" ]; then
    check_pass ".env file exists"

    REQUIRED_VARS="DATABASE_PASSWORD JWT_SECRET REDIS_PASSWORD TELEGRAM_BOT_TOKEN"
    for var in $REQUIRED_VARS; do
        val=$(grep "^${var}=" .env 2>/dev/null | cut -d'=' -f2-)
        if [ -n "$val" ] && [ "$val" != "REPLACE_WITH_YOUR_${var}" ]; then
            check_pass "$var is set"
        else
            check_fail "$var is MISSING or placeholder"
        fi
    done
else
    check_fail ".env NOT FOUND -- copy .env.example to .env and fill in values"
fi

# -- 2. Check docker-compose.yml --
echo ""
echo -e "${BOLD}2. Docker Compose${NC}"
if [ -f "docker-compose.yml" ]; then
    check_pass "docker-compose.yml exists"

    # Check all expected services have sowknow4- prefix containers
    for svc in backend postgres redis vault nats celery-worker celery-beat frontend telegram-bot; do
        if grep -q "sowknow4-${svc}" docker-compose.yml; then
            check_pass "Container 'sowknow4-${svc}' defined"
        else
            check_fail "Container 'sowknow4-${svc}' MISSING from docker-compose.yml"
        fi
    done

    # Check no internal ports exposed
    if grep -A5 "postgres:" docker-compose.yml | grep -q "ports:"; then
        check_fail "PostgreSQL ports exposed to host -- SECURITY VIOLATION"
    else
        check_pass "PostgreSQL not exposed (internal only)"
    fi

    if grep -A5 "redis:" docker-compose.yml | grep -q "ports:"; then
        check_fail "Redis ports exposed to host -- SECURITY VIOLATION"
    else
        check_pass "Redis not exposed (internal only)"
    fi
else
    check_fail "docker-compose.yml NOT FOUND"
fi

# -- 3. Check Python syntax --
echo ""
echo -e "${BOLD}3. Python Syntax${NC}"
if command -v python3 &>/dev/null; then
    SYNTAX_ERRORS=0
    while IFS= read -r -d '' pyfile; do
        if ! python3 -c "import py_compile; py_compile.compile('$pyfile', doraise=True)" 2>/dev/null; then
            check_fail "Syntax error: $pyfile"
            ((SYNTAX_ERRORS++))
        fi
    done < <(find backend/app -name '*.py' ! -path '*__pycache__*' -print0 2>/dev/null)

    if [ $SYNTAX_ERRORS -eq 0 ]; then
        TOTAL_PY=$(find backend/app -name '*.py' ! -path '*__pycache__*' 2>/dev/null | wc -l)
        check_pass "All $TOTAL_PY Python files compile"
    fi
else
    check_warn "python3 not available on host (syntax check skipped)"
fi

# -- 4. Check Dockerfiles --
echo ""
echo -e "${BOLD}4. Dockerfiles${NC}"
for df in backend/Dockerfile.minimal backend/Dockerfile.worker backend/Dockerfile.telegram frontend/Dockerfile; do
    if [ -f "$df" ]; then
        if grep -q "FROM" "$df"; then
            check_pass "$df has valid FROM"
        else
            check_fail "$df missing FROM statement"
        fi

        # Check for slim base images (not bloated full images)
        if grep -q "python:3.*-slim\|python:3.*-alpine\|node:.*-alpine" "$df"; then
            check_pass "$df uses slim/alpine base"
        elif grep -q "FROM python\|FROM node" "$df"; then
            check_warn "$df may use bloated base image -- prefer slim/alpine"
        fi
    else
        check_warn "$df not found (may use alternate Dockerfile)"
    fi
done

# -- 5. Check Docker daemon --
echo ""
echo -e "${BOLD}5. Docker Daemon${NC}"
if docker info > /dev/null 2>&1; then
    VERSION=$(docker version --format '{{.Server.Version}}' 2>/dev/null || echo "?")
    check_pass "Docker daemon running (v$VERSION)"

    if docker compose version > /dev/null 2>&1; then
        COMPOSE_V=$(docker compose version --short 2>/dev/null || echo "?")
        check_pass "Docker Compose available (v$COMPOSE_V)"
    else
        check_fail "Docker Compose NOT available"
    fi
else
    check_fail "Docker daemon NOT running"
fi

# -- 6. Check disk space --
echo ""
echo -e "${BOLD}6. Disk Space${NC}"
USAGE=$(df / --output=pcent | tail -1 | tr -d ' %')
AVAIL=$(df / --output=avail -h | tail -1 | tr -d ' ')
if [ "$USAGE" -lt 70 ]; then
    check_pass "Disk at ${USAGE}% (${AVAIL} available)"
elif [ "$USAGE" -lt 85 ]; then
    check_warn "Disk at ${USAGE}% -- consider cleanup before build"
else
    check_fail "Disk at ${USAGE}% -- build may fail! Run: docker system prune -a -f"
fi

# -- 7. Check memory --
echo ""
echo -e "${BOLD}7. System Memory${NC}"
TOTAL_MEM=$(free -g | awk '/^Mem:/{print $2}')
AVAIL_MEM=$(free -g | awk '/^Mem:/{print $7}')
if [ "$TOTAL_MEM" -ge 16 ]; then
    check_pass "Total RAM: ${TOTAL_MEM}GB (${AVAIL_MEM}GB available)"
else
    check_warn "Total RAM: ${TOTAL_MEM}GB -- SOWKNOW4 recommends 16GB+"
fi

# -- Summary --
echo ""
echo -e "${BOLD}=======================================${NC}"
echo -e "  Passed: ${GREEN}$PASS${NC}  Failed: ${RED}$FAIL${NC}  Warnings: ${YELLOW}$WARN${NC}"

if [ $FAIL -gt 0 ]; then
    echo -e "  ${RED}${BOLD}PRE-FLIGHT FAILED${NC} -- Fix errors above before building."
    exit 1
else
    echo -e "  ${GREEN}${BOLD}PRE-FLIGHT PASSED${NC} -- Safe to build."
    echo ""
    echo "  Next: docker compose build --no-cache && docker compose up -d"
    exit 0
fi
