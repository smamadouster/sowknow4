#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════
#  SOWKNOW — Production Verification Script
#  Usage:  ./sowknow_verify.sh              (local mode — all checks)
#          ./sowknow_verify.sh --remote     (remote mode — HTTP only)
#          ./sowknow_verify.sh --help
# ═══════════════════════════════════════════════════════════════════════
set -uo pipefail

BASE="${SOWKNOW_URL:-https://sowknow.gollamtech.com}"
TOKEN="${SOWKNOW_TOKEN:-}"
MODE="local"
PASS_COUNT=0
FAIL_COUNT=0
WARN_COUNT=0

# ── Usage ──────────────────────────────────────────────────────────────
usage() {
    echo "Usage: $0 [--remote|--local|--help]"
    echo ""
    echo "  --local   Run all checks (HTTP + filesystem + Docker + code quality)"
    echo "  --remote  Run HTTP-only checks (headers, health, auth, metrics)"
    echo "  --help    Show this help message"
    echo ""
    echo "Environment variables:"
    echo "  SOWKNOW_URL    Base URL (default: https://sowknow.gollamtech.com)"
    echo "  SOWKNOW_TOKEN  JWT token for authenticated endpoint checks"
    exit 0
}

# ── Parse args ─────────────────────────────────────────────────────────
for arg in "$@"; do
    case "$arg" in
        --remote) MODE="remote" ;;
        --local)  MODE="local"  ;;
        --help|-h) usage ;;
        *) echo "Unknown option: $arg"; usage ;;
    esac
done

# ── Helpers ────────────────────────────────────────────────────────────
check() {
    local label=$1; local cmd=$2; local expect=$3
    result=$(eval "$cmd" 2>/dev/null)
    if echo "$result" | grep -qE "$expect"; then
        echo "  ✅ $label"
        ((PASS_COUNT++))
    else
        echo "  ❌ $label (got: ${result:0:80})"
        ((FAIL_COUNT++))
    fi
}

warn_check() {
    local label=$1; local cmd=$2; local expect=$3
    result=$(eval "$cmd" 2>/dev/null)
    if echo "$result" | grep -qE "$expect"; then
        echo "  ✅ $label"
        ((PASS_COUNT++))
    else
        echo "  ⚠️  $label (got: ${result:0:80})"
        ((WARN_COUNT++))
    fi
}

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  SOWKNOW — POST-FIX VERIFICATION ($MODE mode)"
echo "  Target: $BASE"
echo "═══════════════════════════════════════════════════════"

# ══════════════════════════════════════════════════════════════════════
#  SECTION 1 — Security Headers
# ══════════════════════════════════════════════════════════════════════
echo ""
echo "── Security Headers ──────────────────────────────────"

check "HSTS header" \
    "curl -sI $BASE | grep -i strict-transport" \
    "max-age=31536000"

check "CSP header" \
    "curl -sI $BASE | grep -i content-security" \
    "default-src"

check "X-Frame-Options" \
    "curl -sI $BASE | grep -i x-frame" \
    "DENY"

check "X-Content-Type-Options" \
    "curl -sI $BASE | grep -i x-content-type" \
    "nosniff"

check "Referrer-Policy" \
    "curl -sI $BASE | grep -i referrer-policy" \
    "strict-origin"

check "No Server header leak" \
    "curl -sI $BASE | grep -ci '^Server:'" \
    "^0$"

# ══════════════════════════════════════════════════════════════════════
#  SECTION 2 — Health Endpoints
# ══════════════════════════════════════════════════════════════════════
echo ""
echo "── Health Endpoints ────────────────────────────────────"

check "FastAPI /api/v1/health returns 200" \
    "curl -so /dev/null -w '%{http_code}' $BASE/api/v1/health" \
    "200"

check "Health has 'database' field" \
    "curl -s $BASE/api/v1/health" \
    '"database"'

check "Health has 'redis' field" \
    "curl -s $BASE/api/v1/health" \
    '"redis"'

check "Health has 'vault' field" \
    "curl -s $BASE/api/v1/health" \
    '"vault"'

check "Health has 'nats' field" \
    "curl -s $BASE/api/v1/health" \
    '"nats"'

check "Root /health returns 200" \
    "curl -so /dev/null -w '%{http_code}' $BASE/health" \
    "200"

# ══════════════════════════════════════════════════════════════════════
#  SECTION 3 — Auth-Protected Routes (must be 401, not 404)
# ══════════════════════════════════════════════════════════════════════
echo ""
echo "── Auth-Protected Routes (expect 401) ──────────────────"

for path in \
    "/api/v1/documents" \
    "/api/v1/search/query" \
    "/api/v1/chat/sessions" \
    "/api/v1/collections" \
    "/api/v1/admin/users" \
    "/api/v1/smart-folders" \
    "/api/v1/knowledge-graph/entities" \
; do
    check "Auth on $path (401, not 404)" \
        "curl -so /dev/null -w '%{http_code}' $BASE$path" \
        "401"
done

# ══════════════════════════════════════════════════════════════════════
#  SECTION 4 — Prometheus Metrics
# ══════════════════════════════════════════════════════════════════════
echo ""
echo "── Prometheus Metrics ──────────────────────────────────"

check "Metrics endpoint /api/v1/metrics reachable" \
    "curl -so /dev/null -w '%{http_code}' $BASE/api/v1/metrics" \
    "200"

check "Metrics endpoint /metrics reachable" \
    "curl -so /dev/null -w '%{http_code}' $BASE/metrics" \
    "200"

check ">=20 sowknow_ metric families" \
    "curl -s $BASE/api/v1/metrics | grep -c '^# HELP sowknow_'" \
    "2[0-9]"

warn_check "sowknow_uptime_seconds present" \
    "curl -s $BASE/api/v1/metrics | grep -c 'sowknow_uptime_seconds'" \
    "[1-9]"

warn_check "sowknow_http_requests_total present" \
    "curl -s $BASE/api/v1/metrics | grep -c 'sowknow_http_requests_total'" \
    "[1-9]"

# ══════════════════════════════════════════════════════════════════════
#  SECTION 5 — Infrastructure (local mode only)
# ══════════════════════════════════════════════════════════════════════
if [ "$MODE" = "local" ]; then
    echo ""
    echo "── Infrastructure ────────────────────────────────────"

    check "soul.md exists" \
        "test -f soul.md && echo found" \
        "found"

    check "memory limits in docker-compose.yml" \
        "grep -c 'memory:' docker-compose.yml" \
        "^[5-9]$|^1[0-9]$"

    check "cpus in docker-compose.yml" \
        "grep -c 'cpus:' docker-compose.yml" \
        "^[5-9]$|^1[0-9]$"

    warn_check ".claude/worktrees removed" \
        "ls .claude/worktrees 2>&1" \
        "No such file"

    warn_check "No .env tracked by git" \
        "git ls-files --cached '.env' '.env.production' 'backend/.env.production' 'frontend/.env.production' 2>/dev/null | wc -l" \
        "^0$"

    # Docker health (non-fatal if Docker not running)
    if command -v docker &>/dev/null && docker compose ps &>/dev/null; then
        warn_check "All Docker services healthy" \
            "docker compose ps | grep -c 'healthy'" \
            "^[5-9]$|^1[0-2]$"
    else
        echo "  ⚠️  Docker not running — skipping container health check"
        ((WARN_COUNT++))
    fi
fi

# ══════════════════════════════════════════════════════════════════════
#  SECTION 6 — Code Quality (local mode only)
# ══════════════════════════════════════════════════════════════════════
if [ "$MODE" = "local" ]; then
    echo ""
    echo "── Code Quality ──────────────────────────────────────"

    if command -v ruff &>/dev/null || python3 -c "import ruff" &>/dev/null; then
        check "Ruff: zero lint errors" \
            "cd backend && ruff check . --quiet 2>&1 | wc -l" \
            "^0$"
    else
        echo "  ⚠️  ruff not installed — skipping lint check"
        ((WARN_COUNT++))
    fi

    if python3 -c "import pytest" &>/dev/null; then
        warn_check "pytest: passes" \
            "cd backend && python3 -m pytest tests/ -q --tb=no 2>&1 | tail -1" \
            "passed"
    else
        echo "  ⚠️  pytest not available — skipping test check"
        ((WARN_COUNT++))
    fi
fi

# ══════════════════════════════════════════════════════════════════════
#  SECTION 7 — Authenticated Checks (optional, with SOWKNOW_TOKEN)
# ══════════════════════════════════════════════════════════════════════
if [ -n "$TOKEN" ]; then
    echo ""
    echo "── Authenticated Checks ─────────────────────────────"

    check "GET /api/v1/documents with token (200)" \
        "curl -so /dev/null -w '%{http_code}' -H 'Authorization: Bearer $TOKEN' $BASE/api/v1/documents" \
        "200"

    check "GET /api/v1/chat/sessions with token (200)" \
        "curl -so /dev/null -w '%{http_code}' -H 'Authorization: Bearer $TOKEN' $BASE/api/v1/chat/sessions" \
        "200"

    check "GET /api/v1/collections with token (200)" \
        "curl -so /dev/null -w '%{http_code}' -H 'Authorization: Bearer $TOKEN' $BASE/api/v1/collections" \
        "200"

    check "GET /api/v1/auth/me with token (200)" \
        "curl -so /dev/null -w '%{http_code}' -H 'Authorization: Bearer $TOKEN' $BASE/api/v1/auth/me" \
        "200"

    check "Auth /me returns 'email' field" \
        "curl -s -H 'Authorization: Bearer $TOKEN' $BASE/api/v1/auth/me" \
        '"email"'
fi

# ══════════════════════════════════════════════════════════════════════
#  SUMMARY
# ══════════════════════════════════════════════════════════════════════
echo ""
echo "═══════════════════════════════════════════════════════"
echo "  RESULTS"
echo "═══════════════════════════════════════════════════════"
TOTAL=$((PASS_COUNT + FAIL_COUNT + WARN_COUNT))
echo "  Total checks : $TOTAL"
echo "  ✅ PASS      : $PASS_COUNT"
echo "  ❌ FAIL      : $FAIL_COUNT"
echo "  ⚠️  WARN      : $WARN_COUNT"
echo ""

if [ "$FAIL_COUNT" -eq 0 ] && [ "$WARN_COUNT" -eq 0 ]; then
    echo "  🏆 ALL CLEAR — every check passed"
elif [ "$FAIL_COUNT" -eq 0 ]; then
    echo "  ✅ PASS WITH WARNINGS — $WARN_COUNT item(s) need attention"
else
    echo "  ❌ FAIL — $FAIL_COUNT critical check(s) failed, $WARN_COUNT warning(s)"
fi
echo ""

exit "$FAIL_COUNT"
