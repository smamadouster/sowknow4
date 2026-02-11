#!/bin/bash
# SOWKNOW4 Production Deployment Script
# This script automates the production deployment process

set -e

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=========================================${NC}"
echo -e "${GREEN}SOWKNOW4 Production Deployment${NC}"
echo -e "${GREEN}=========================================${NC}"

# Configuration
PRODUCTION_SERVER="${1:-72.62.17.136}"
PRODUCTION_PATH="${2:-/var/docker/sowknow4}"
GIT_REPO="${3:-smamadouster/sowknow4.git}"
ENV_FILE=".env.production"

echo -e "${YELLOW}Production Server:${NC} $PRODUCTION_SERVER"
echo -e "${YELLOW}Production Path:${NC} $PRODUCTION_PATH"
echo -e "${YELLOW}Git Repository:${NC} $GIT_REPO"
echo ""

# Function to print colored status
print_status() {
    local status=$1
    local message=$2
    if [ "$1" == "0" ]; then
        echo -e "${GREEN}[✓]${NC} $2"
    elif [ "$1" == "1" ]; then
        echo -e "${YELLOW}[⚠]${NC} $2"
    elif [ "$1" == "2" ]; then
        echo -e "${RED}[✗]${NC} $2"
    fi
}

# Step 1: Check current directory
echo -e "\n${GREEN}Step 1: Check Current Directory${NC}"
CURRENT_DIR=$(pwd)
if [ "$CURRENT_DIR" != "$PRODUCTION_PATH" ]; then
    print_status 2 "Wrong directory. Navigating to: $PRODUCTION_PATH"
    cd "$PRODUCTION_PATH" || exit 1
else
    print_status 0 "Already in correct directory: $PRODUCTION_PATH"
fi

# Step 2: Pull latest code
echo -e "\n${GREEN}Step 2: Pull Latest Code${NC}"
if [ -d ".git" ]; then
    print_status 1 "Cloning repository..."
    git clone "$GIT_REPO" temp_sowknow4 || exit 1
    cd temp_sowknow4 || exit 1
    git remote set-url origin "$GIT_REPO"
    cd .. || exit 1
    rm -rf temp_sowknow4
else
    print_status 1 "Pulling latest changes..."
    git fetch origin || print_status 2 "Failed to fetch from origin"
    git pull origin master || print_status 2 "Failed to pull from origin"
fi

# Step 3: Create production environment file
echo -e "\n${GREEN}Step 3: Create Production Environment${NC}"

if [ ! -f "$ENV_FILE" ]; then
    print_status 2 "Creating $ENV_FILE..."
    cat > "$ENV_FILE" << 'ENVEOF'
# ===================================================
# SOWKNOW4 PRODUCTION ENVIRONMENT
# ===================================================

# Database Configuration
DATABASE_PASSWORD=CHANGE_ME_TO_SECURE_PASSWORD

# Security
JWT_SECRET=CHANGE_ME_TO_64_CHAR_SECRET
APP_ENV=production
ALLOWED_ORIGINS=https://sowknow.gollamtech.com,https://www.sowknow.gollamtech.com
ALLOWED_HOSTS=sowknow.gollamtech.com,www.sowknow.gollamtech.com

# AI Services
# Primary AI Service (Gemini 2.0 Flash)
GEMINI_API_KEY=YOUR_GEMINI_API_KEY_HERE

# Secondary AI Service (Kimi 2.5 - Fallback)
KIMI_API_KEY=YOUR_KIMI_API_KEY_HERE

# Tertiary AI Service (Ollama for confidential docs)
LOCAL_LLM_URL=http://host.docker.internal:11434

# Monitoring
GEMINI_DAILY_BUDGET_USD=5.00

# Optional Services
TELEGRAM_BOT_TOKEN=YOUR_TELEGRAM_BOT_TOKEN_HERE
ENVEOF

    print_status 0 "Created $ENV_FILE"
else
    print_status 0 "Environment file already exists. Edit values with:"
    echo "nano $ENV_FILE"
fi

# Step 4: Stop existing containers (if running)
echo -e "\n${GREEN}Step 4: Stop Existing Containers${NC}"

# Check if Docker Compose is running
if docker compose ps &>/dev/null; then
    print_status 1 "Stopping Docker Compose..."
    docker compose down
    sleep 5
    print_status 0 "Containers stopped"
else
    print_status 0 "No Docker Compose running"
fi

# Step 5: Rebuild images with non-root user
echo -e "\n${GREEN}Step 5: Rebuild Images (Non-Root User)${NC}"

print_status 1 "Rebuilding backend, celery-worker, telegram-bot..."
docker compose build backend celery-worker telegram-bot || print_status 2 "Build failed"

print_status 1 "Verifying non-root user in images..."
docker images --format "{{.Repository}}" | grep sowknow4 | grep -vE "(builder|latest)" | grep appuser || print_status 0 "Non-root user confirmed"

# Step 6: Start production services
echo -e "\n${GREEN}Step 6: Start Production Services${NC}"

echo ""
print_status 1 "Starting services with Caddy reverse proxy..."
docker compose --env-file "$ENV_FILE" -f Caddyfile.production up -d || print_status 2 "Failed to start services"

# Wait for services to be healthy
echo ""
print_status 0 "Waiting for services to start..."
sleep 30

# Step 7: Verify deployment
echo -e "\n${GREEN}Step 7: Verify Deployment${NC}"

echo ""
print_status 1 "Checking container status..."
RUNNING=$(docker compose ps | grep -c "Up" | wc -l)
if [ "$RUNNING" -ge 6 ]; then
    print_status 0 "All containers running ($RUNNING/6)"
else
    print_status 2 "Some containers not running!"
fi

echo ""
print_status 1 "Checking health endpoint..."
HEALTH=$(curl -s http://localhost:8000/health 2>/dev/null || echo "failed")
if echo "$HEALTH" | grep -q "healthy"; then
    print_status 0 "Health check passed"
else
    print_status 2 "Health check returned: $HEALTH"
fi

echo ""
print_status 1 "Checking non-root user..."
NONROOT=$(docker compose exec backend whoami 2>/dev/null)
if [ "$NONROOT" = "appuser" ]; then
    print_status 0 "Non-root user confirmed: appuser"
else
    print_status 2 "Security issue: Running as $NONROOT"
fi

# Summary
echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Deployment Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "${GREEN}Next Steps:${NC}"
echo "1. Verify all monitoring endpoints:"
echo "   curl http://localhost:8000/api/v1/health/detailed | jq ."
echo "   curl http://localhost:8000/api/v1/monitoring/costs | jq ."
echo "   curl http://localhost:8000/metrics | head -20"
echo ""
echo "2. Set your production environment:"
echo "   nano $ENV_FILE"
echo "   Update DATABASE_PASSWORD, JWT_SECRET"
echo "   Add GEMINI_API_KEY and/or KIMI_API_KEY"
echo ""
echo "3. Enable nginx (if needed):"
echo "   docker compose --profile nginx up -d"
echo ""
echo -e "${YELLOW}Note: Caddy is handling reverse proxy on ports 80/443${NC}"
echo -e "${YELLOW}SOWKNOW will be available at:${NC}"
echo -e "  - https://sowknow.gollamtech.com (main)"
echo -e "  - https://www.sowknow.gollamtech.com (WWW redirect)"
echo ""

# Rollback instructions
echo "If deployment fails:"
echo "1. Revert to previous state:"
echo "   cd /var/docker/sowknow4"
echo "   git checkout HEAD~1"
echo "   docker compose --env-file $ENV_FILE.backup up -d"
echo ""
echo "2. Check logs:"
echo "   docker compose logs -f --tail=100"
echo ""
echo "3. Get support:"
echo "   Check MONITORING.md for troubleshooting"
echo "   Review logs for error messages"
echo ""
echo -e "${RED}IMPORTANT: Change all default passwords!${NC}"
echo -e "${RED}DATABASE_PASSWORD=CHANGE_ME_TO_SECURE_PASSWORD${NC}"
echo -e "${RED}JWT_SECRET=CHANGE_ME_TO_64_CHAR_SECRET${NC}"
echo -e "${RED}GEMINI_API_KEY=YOUR_GEMINI_API_KEY_HERE${NC}"
echo ""
echo -e "${GREEN}Deployment script complete!${NC}"
echo "Run this script on production server: ${NC}"
echo ""
echo "Commands:"
echo "  scp deploy-production.sh root@$PRODUCTION_SERVER:/var/docker/sowknow4/"
echo "  ssh root@$PRODUCTION_SERVER"
echo "  cd /var/docker/sowknow4"
echo "  bash deploy-production.sh"
echo ""