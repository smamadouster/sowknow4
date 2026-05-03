#!/bin/bash
# SOWKNOW4 Emergency Restart — High CPU Recovery
# Run this on vps1 as the user that owns the Docker sockets.
#
# Usage:
#   cd /var/docker/sowknow4
#   ./scripts/emergency-restart.sh

set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
PROJECT_DIR="${PROJECT_DIR:-/var/docker/sowknow4}"
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[$(date +'%H:%M:%S')]${NC} $*"; }
warn() { echo -e "${YELLOW}[$(date +'%H:%M:%S')] WARN${NC} $*"; }
err()  { echo -e "${RED}[$(date +'%H:%M:%S')] ERR${NC} $*"; }

cd "$PROJECT_DIR" || { err "Cannot cd to $PROJECT_DIR"; exit 1; }

log "=== SOWKNOW4 Emergency Restart ==="
log "Compose file: $COMPOSE_FILE"
log ""

# ── 1. Stop Celery Beat first (prevents sweeper from firing during restart) ──
log "Step 1/5: Stopping celery-beat to pause scheduled tasks..."
docker compose -f "$COMPOSE_FILE" stop sowknow4-celery-beat || warn "celery-beat not running"
sleep 2

# ── 2. Gracefully stop the high-CPU containers ──
log "Step 2/5: Stopping high-CPU containers..."
docker compose -f "$COMPOSE_FILE" stop sowknow4-backend sowknow4-embed-server sowknow4-embed-server-2 || true
sleep 3

# ── 3. Rebuild & restart (uses cached layers — fast) ──
log "Step 3/5: Rebuilding & restarting backend + embed servers..."
docker compose -f "$COMPOSE_FILE" up -d --build sowknow4-backend sowknow4-embed-server sowknow4-embed-server-2

log "Waiting 15s for containers to start..."
sleep 15

# ── 4. Health checks ──
log "Step 4/5: Running health checks..."
HEALTHY=0

if docker exec sowknow4-backend curl -sf http://localhost:8000/api/v1/health >/dev/null 2>&1 || \
   docker exec sowknow4-backend curl -sf http://localhost:8000/health >/dev/null 2>&1; then
    log "  ✓ backend health OK"
    HEALTHY=$((HEALTHY + 1))
else
    err "  ✗ backend health FAILED"
fi

if docker exec sowknow4-embed-server curl -sf http://localhost:8000/health >/dev/null 2>&1; then
    log "  ✓ embed-server health OK"
    HEALTHY=$((HEALTHY + 1))
else
    err "  ✗ embed-server health FAILED"
fi

if docker exec sowknow4-embed-server-2 curl -sf http://localhost:8000/health >/dev/null 2>&1; then
    log "  ✓ embed-server-2 health OK"
    HEALTHY=$((HEALTHY + 1))
else
    err "  ✗ embed-server-2 health FAILED"
fi

# ── 5. Restart Celery Beat ──
log "Step 5/5: Restarting celery-beat..."
docker compose -f "$COMPOSE_FILE" up -d sowknow4-celery-beat

# ── Summary ──
log ""
log "=== Restart Summary ==="
log "Healthy services: $HEALTHY/3"
docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}" sowknow4-backend sowknow4-embed-server sowknow4-embed-server-2 2>/dev/null || true
log ""
log "If CPU is still high after 2 minutes, run:"
log "  docker logs --tail 50 sowknow4-backend"
log "  docker logs --tail 50 sowknow4-embed-server"
log "  docker exec sowknow4-postgres psql -U sowknow -c \"SELECT stage, status, COUNT(*) FROM sowknow.pipeline_stages GROUP BY stage, status;\""
log ""

if [ "$HEALTHY" -eq 3 ]; then
    log "${GREEN}All services healthy.${NC}"
    exit 0
else
    err "Some services are unhealthy. Investigate logs."
    exit 1
fi
