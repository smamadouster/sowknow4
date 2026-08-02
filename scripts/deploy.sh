#!/bin/bash
###############################################################################
# SOWKNOW4 deploy — the ONLY sanctioned way to deploy this stack.
#
# Hard-won rules (P0 incident 2026-07-28):
#  1. EVERY service has its own image tag (backend, celery-*, telegram-bot,
#     embed-server, guardian-hc). Building only "backend" leaves the fleet on
#     stale code — always build all.
#  2. ALWAYS --no-deps on up: after .env edits, compose considers every
#     env_file consumer stale and will recreate POSTGRES as a dependency,
#     killing searches and index builds mid-flight.
#  3. Never `compose down` (and never with -v). Recreate services individually.
#  4. Index-building migrations must be CONCURRENTLY — run heavy migrations
#     as explicit ops steps, not during a routine deploy.
#
# Usage:
#   scripts/deploy.sh            # build all + recreate changed services
#   scripts/deploy.sh backend    # build + recreate one service
###############################################################################
set -euo pipefail
cd "$(dirname "$0")/.."

COMPOSE="docker compose -f docker-compose.production.yml"
SERVICES="backend celery-light celery-heavy celery-entities celery-articles celery-collections celery-beat telegram-bot embed-server embed-server-2 rerank-server guardian-hc frontend"
TARGET="${1:-$SERVICES}"

echo "=== [1/3] Pre-deploy checks ==="
if ! docker exec sowknow-postgres pg_isready -U "${POSTGRES_USER:-sowknow}" >/dev/null 2>&1; then
    echo "FATAL: postgres not ready"; exit 1
fi
# Refuse to deploy during long-running index maintenance
MAINT=$(docker exec sowknow-postgres psql -U "${POSTGRES_USER:-sowknow}" -d "${POSTGRES_DB:-sowknow}" -tAc \
    "SELECT count(*) FROM pg_stat_progress_create_index" 2>/dev/null || echo "0")
if [ "$MAINT" != "0" ]; then
    echo "FATAL: index build in progress (pg_stat_progress_create_index non-empty) — wait for it"; exit 1
fi

echo "=== [2/3] Build: $TARGET ==="
# Build stamp for the frontend UI (git short hash + UTC time) — lets users
# tell whether they run the latest version (shown above the logout button).
export NEXT_PUBLIC_BUILD_STAMP="$(git rev-parse --short HEAD 2>/dev/null || echo nogit)-$(date -u +%Y%m%d-%H%M)"
echo "build stamp: $NEXT_PUBLIC_BUILD_STAMP"
$COMPOSE build $TARGET

echo "=== [3/3] Recreate (--no-deps): $TARGET ==="
$COMPOSE up -d --no-deps $TARGET

echo "=== Post-deploy smoke ==="
sleep 10
H=$(curl -s -m 15 http://127.0.0.1:8001/api/v1/health || echo '{}')
echo "health: $H"
echo "$H" | grep -q '"status":"ok"' || { echo "SMOKE FAIL: backend unhealthy"; exit 1; }
S=$(curl -s -m 15 http://127.0.0.1:8001/api/v1/search/health || echo '{}')
echo "search: $S"
echo "$S" | grep -q '"status":"healthy"' || { echo "SMOKE FAIL: search unhealthy"; exit 1; }
echo "=== Deploy OK ==="
