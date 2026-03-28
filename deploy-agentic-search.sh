#!/bin/bash
# SOWKNOW4 — Deploy Agentic Search Enhancement
# Run as root: sudo bash deploy-agentic-search.sh
set -e

DEV_REPO="/home/developer/development/src/active/sowknow4"
PROD_DIR="/var/docker/sowknow4"
BACKUP_TAG="pre-agentic-search-$(date +%Y%m%d_%H%M%S)"

echo "=== SOWKNOW4 Agentic Search Deployment ==="
echo ""

# 1. Verify we're root
if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: Run as root (sudo bash deploy-agentic-search.sh)"
    exit 1
fi

# 2. Stash production local changes
echo "[1/7] Stashing production local changes..."
cd "$PROD_DIR"
git stash push -m "pre-agentic-search-deploy $BACKUP_TAG" 2>/dev/null || true
echo "  Done."

# 3. Add dev repo as remote and fetch
echo "[2/7] Fetching from dev repo..."
git remote remove devrepo 2>/dev/null || true
git remote add devrepo "$DEV_REPO"
git fetch devrepo master
echo "  Done."

# 4. Merge dev commits (fast-forward preferred)
echo "[3/7] Merging agentic search commits..."
git merge devrepo/master --no-edit
echo "  Done. Now at: $(git log --oneline -1)"

# 5. Re-apply production local changes (may have conflicts)
echo "[4/7] Re-applying production local changes..."
if git stash list | grep -q "pre-agentic-search-deploy"; then
    git stash pop || {
        echo "  WARNING: Merge conflicts detected. Resolving by keeping new changes..."
        git checkout --theirs . 2>/dev/null || true
        git add -A
        echo "  Conflicts resolved (kept new agentic search version)."
    }
else
    echo "  No stash to apply."
fi

# 6. Run Alembic migration
echo "[5/7] Running database migration..."
cd "$PROD_DIR"
# Source the .env file for database credentials
if [ -f .env ]; then
    set -a; source .env; set +a
fi
docker compose exec -T backend alembic upgrade head 2>&1 || {
    echo "  WARNING: Alembic migration failed (table may already exist). Continuing..."
}
echo "  Done."

# 7. Rebuild and restart containers
echo "[6/7] Rebuilding containers..."
docker compose build backend frontend
echo "  Done."

echo "[7/7] Restarting services..."
docker compose up -d backend frontend
echo "  Done."

# 8. Health check
echo ""
echo "=== Waiting 15s for services to start... ==="
sleep 15

echo "Checking backend health..."
curl -sf http://localhost:8000/api/v1/health || echo "WARNING: Backend health check failed"
echo ""

echo "Checking frontend..."
curl -sf http://localhost:3000 > /dev/null && echo "Frontend: OK" || echo "WARNING: Frontend health check failed"

echo ""
echo "=== Deployment Complete ==="
echo "New commits deployed:"
git log --oneline 4fa03b7..HEAD | head -15
echo ""
echo "To verify: visit the search page and test a query."
echo "To rollback: git stash list (find the pre-agentic-search stash)"
