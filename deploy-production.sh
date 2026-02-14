#!/bin/bash
# SOWKNOW4 Production Deployment Script (Simplified)
# Run this script on the production server via SSH

set -e

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Configuration
PRODUCTION_SERVER="${1:-72.62.17.136}"
PRODUCTION_PATH="${2:-/var/docker/sowknow4}"
GIT_REPO="${3:-root@72.62.17.136:/var/docker/sowknow4.git}"
ENV_FILE=".env.production"

echo -e "${GREEN}========================================"
echo -e "${GREEN}SOWKNOW4 PRODUCTION DEPLOYMENT"
echo -e "${GREEN}========================================"
echo ""

echo -e "Server:     ${YELLOW}$PRODUCTION_SERVER${NC}"
echo -e "Path:       ${YELLOW}$PRODUCTION_PATH${NC}"
echo -e "Repository: ${YELLOW}$GIT_REPO${NC}"
echo ""

# Function to print colored status
print_status() {
    local status=$1
    local message=$2
    if [ "$1" == "0" ]; then
        echo -e "${GREEN}[✓]${NC} $2"
    elif [ "$1" == "1" ]; then
        echo -e "${YELLOW}[!]${NC} $2"
    elif [ "$1" == "2" ]; then
        echo -e "${RED}[✗]${NC} $2"
    fi
}

# Step 1: Navigate to project
echo -e "${GREEN}Step 1:${NC} Navigate to Project Directory"
print_status 0 "cd $PRODUCTION_PATH"
cd "$PRODUCTION_PATH" || exit 1

# Step 2: Check if Docker Compose exists
echo ""
echo -e "${GREEN}Step 2:${NC} Check for Docker Compose File${NC}"
if [ ! -f "docker-compose.yml" ] && [ ! -f "docker-compose.production.yml" ]; then
    echo -e "${YELLOW}[!]${NC} No docker-compose file found!"
    echo -e "${YELLOW}    Creating docker-compose.yml from template...${NC}"

    cat > docker-compose.yml << 'EOF'
version: "3.8"

# Require .env file to be present for all services
x-common-env: &common-env
  env_file:
    - .env

services:
  postgres:
    <<: *common-env
    image: pgvector/pgvector:pg16
    container_name: sowknow4-postgres
    restart: unless-stopped
    environment:
      - POSTGRES_DB=${DATABASE_NAME:-sowknow}
      - POSTGRES_USER=${DATABASE_USER:-sowknow}
      - POSTGRES_PASSWORD=${DATABASE_PASSWORD:?DATABASE_PASSWORD must be set in .env}
    volumes:
      - sowknow-postgres-data:/var/lib/postgresql/data
    networks:
      - sowknow-net

  redis:
    <<: *common-env
    image: redis:7-alpine
    container_name: sowknow4-redis
    restart: unless-stopped
    command: redis-server --appendonly yes
    volumes:
      - sowknow-redis-data:/data
    networks:
      - sowknow-net

  backend:
    <<: *common-env
    build:
      context: ./backend
      dockerfile: Dockerfile.minimal
    container_name: sowknow4-backend
    restart: unless-stopped
    environment:
      - DATABASE_URL=postgresql://${DATABASE_USER:-sowknow}:${DATABASE_PASSWORD:?DATABASE_PASSWORD must be set in .env}@postgres:5432/${DATABASE_NAME:-sowknow}
      - REDIS_URL=redis://redis:6379/0
      - JWT_SECRET=${JWT_SECRET:?JWT_SECRET must be set in .env}
      - APP_ENV=${APP_ENV:-production}
      - GEMINI_API_KEY=${GEMINI_API_KEY}
      - MOONSHOT_API_KEY=${MOONSHOT_API_KEY}
      - HUNYUAN_API_KEY=${HUNYUAN_API_KEY}
      - KIMI_API_KEY=${KIMI_API_KEY}
      - GEMINI_DAILY_BUDGET_USD=${GEMINI_DAILY_BUDGET_USD:-5.00}
      - LOCAL_LLM_URL=http://host.docker.internal:11434
      - TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
    volumes:
      - sowknow-public-data:/data/public
      - sowknow-confidential-data:/data/confidential
      - ./backend:/app
    extra_hosts:
      - "host.docker.internal:host-gateway"
    networks:
      - sowknow-net

  celery-worker:
    <<: *common-env
    build:
      context: ./backend
      dockerfile: Dockerfile.worker
    container_name: sowknow4-celery-worker
    restart: unless-stopped
    environment:
      - DATABASE_URL=postgresql://${DATABASE_USER:-sowknow}:${DATABASE_PASSWORD:?DATABASE_PASSWORD must be set in .env}@postgres:5432/${DATABASE_NAME:-sowknow}
      - REDIS_URL=redis://redis:6379/0
      - GEMINI_API_KEY=${GEMINI_API_KEY}
      - HUNYUAN_API_KEY=${HUNYUAN_API_KEY}
      - KIMI_API_KEY=${KIMI_API_KEY}
      - GEMINI_DAILY_BUDGET_USD=${GEMINI_DAILY_BUDGET_USD:-5.00}
      - LOCAL_LLM_URL=http://host.docker.internal:11434
    volumes:
      - sowknow-public-data:/data/public
      - sowknow-confidential-data:/data/confidential
      - ./backend:/app
    extra_hosts:
      - "host.docker.internal:host-gateway"
    networks:
      - sowknow-net

  celery-beat:
    <<: *common-env
    build:
      context: ./backend
      dockerfile: Dockerfile.worker
    container_name: sowknow4-celery-beat
    restart: unless-stopped
    environment:
      - DATABASE_URL=postgresql://${DATABASE_USER:-sowknow}:${DATABASE_PASSWORD:?DATABASE_PASSWORD must be set in .env}@postgres:5432/${DATABASE_NAME:-sowknow}
      - REDIS_URL=redis://redis:6379/0
      - GEMINI_API_KEY=${GEMINI_API_KEY}
      - KIMI_API_KEY=${KIMI_API_KEY}
      - GEMINI_DAILY_BUDGET_USD=${GEMINI_DAILY_BUDGET_USD:-5.00}
      - LOCAL_LLM_URL=http://host.docker.internal:11434
    volumes:
      - ./backend:/app
    networks:
      - sowknow-net
    command: celery -A app.celery_app beat --loglevel=info

  frontend:
    <<: *common-env
    build:
      context: ./frontend
      dockerfile: Dockerfile
    container_name: sowknow4-frontend
    restart: unless-stopped
    environment:
      - NEXT_PUBLIC_API_URL=http://localhost:8000
      - APP_ENV=${APP_ENV:-production}
    ports:
      - "127.0.0.1:3000"
    networks:
      - sowknow-net
    depends_on:
      - backend

  telegram-bot:
    <<: *common-env
    build:
      context: ./backend
      dockerfile: Dockerfile.telegram
    container_name: sowknow4-telegram-bot
    restart: unless-stopped
    environment:
      - DATABASE_URL=postgresql://${DATABASE_USER:-sowknow}:${DATABASE_PASSWORD:?DATABASE_PASSWORD must be set in .env}@postgres:5432/${DATABASE_NAME:-sowknow}
      - BACKEND_URL=http://backend:8000
      - TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
      - APP_ENV=${APP_ENV:-production}
    volumes:
      - ./backend:/app
    depends_on:
      - backend
    networks:
      - sowknow-net

networks:
  sowknow-net:
    driver: bridge

volumes:
  sowknow-postgres-data:
  sowknow-redis-data:
  sowknow-public-data:
  sowknow-confidential-data:
EOF

    print_status 0 "docker-compose.yml created"
else
    print_status 0 "docker-compose.yml already exists"
fi

# Step 3: Create environment file from template
echo ""
echo -e "${GREEN}Step 3:${NC} Create Environment File${NC}"

# Check if env file exists
if [ -f "$ENV_FILE" ]; then
    print_status 1 "Environment file exists, editing..."
else
    print_status 0 "Creating $ENV_FILE from template..."
fi

# Create/update env file with production values
cat > "$ENV_FILE" << 'EOF'
# ===================================================
# SOWKNOW4 PRODUCTION ENVIRONMENT
# ===================================================

# Database Configuration
DATABASE_PASSWORD=CHANGE_ME_TO_SECURE_PASSWORD

# Security (CRITICAL)
JWT_SECRET=CHANGE_ME_TO_64_CHAR_SECRET
APP_ENV=production
ALLOWED_ORIGINS=https://sowknow.gollamtech.com,https://www.sowknow.gollamtech.com
ALLOWED_HOSTS=sowknow.gollamtech.com,www.sowknow.gollamtech.com

# AI Services Configuration
# Primary AI Service (Gemini 2.0 Flash)
GEMINI_API_KEY=${GEMINI_API_KEY}

# Secondary AI Service (Kimmi 2.5 - Fallback)
KIMI_API_KEY=${KIMI_API_KEY}

# Tertiary AI Service (Ollama for confidential)
LOCAL_LLM_URL=http://host.docker.internal:11434

# Monitoring Configuration
GEMINI_DAILY_BUDGET_USD=5.00

# Optional Services
TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
EOF

chmod 600 "$ENV_FILE"
print_status 0 "$ENV_FILE created/updated"

# Step 4: Pull latest code
echo ""
echo -e "${GREEN}Step 4:${NC} Pull Latest Code${NC}"
print_status 0 "Fetching from origin..."
git fetch origin || print_status 2 "Failed to fetch from origin"
print_status 0 "Pulling from origin..."
git pull origin master || print_status 2 "Failed to pull from origin"
print_status 0 "Code updated"

# Step 5: Stop existing Docker containers
echo ""
echo -e "${GREEN}Step 5:${NC} Stop Existing Containers${NC}"

# Try to stop containers if they exist
if docker compose ps &>/dev/null; then
    print_status 0 "Stopping containers..."
    docker compose down
    sleep 5
    print_status 0 "Containers stopped"
else
    print_status 1 "No containers running"
fi

# Step 6: Start services
echo ""
echo -e "${GREEN}Step 6:${NC} Start Services${NC}"

# Check if docker compose is available
if ! command -v docker compose &>/dev/null; then
    print_status 2 "Docker Compose not found!"
    echo -e "${YELLOW}Please install Docker Compose on production server${NC}"
    exit 1
fi

print_status 0 "Starting Docker Compose services..."
docker compose up -d || print_status 2 "Failed to start services"

# Wait for services to be ready
echo ""
print_status 0 "Waiting for services to start..."
sleep 30

# Step 7: Verify deployment
echo ""
echo -e "${GREEN}Step 7:${NC} Verify Deployment${NC}"
echo ""

# Check container status
RUNNING=$(docker compose ps | grep -c "Up" | wc -l)
TOTAL=$(docker compose ps | grep -c "sowknow4" | wc -l)

echo -e "Containers running: ${GREEN}$RUNNING${NC} / $TOTAL total"

# Check health endpoint
HEALTH=$(curl -s http://localhost:8000/health 2>/dev/null || echo "failed")
if echo "$HEALTH" | grep -q "healthy"; then
    print_status 0 "Health check: ${GREEN}PASSED${NC}"
else
    print_status 2 "Health check: ${RED}FAILED${NC}"
    echo "$HEALTH"
fi

# Check non-root user
NONROOT=$(docker compose exec backend whoami 2>/dev/null)
if [ "$NONROOT" = "appuser" ]; then
    print_status 0 "Non-root user: ${GREEN}CONFIRMED${NC} (appuser)"
else
    print_status 2 "Security issue: ${RED}RUNNING AS ROOT: $NONROOT${NC}"
fi

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Deployment Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "${GREEN}Next Steps:${NC}"
echo "1. Set your production environment:"
echo "   nano $ENV_FILE"
echo "   Update DATABASE_PASSWORD with secure password"
echo "   Update GEMINI_API_KEY with your API key"
echo "   Update other API keys as needed"
echo ""
echo "2. Monitor your deployment:"
echo "   docker compose ps -a"
echo "   docker compose logs -f --tail=100 backend"
echo ""
echo "3. For SSL setup:"
echo "   See DEPLOYMENT-PRODUCTION.md guide"
echo "   Run: bash scripts/setup-ssl-auto.sh"
echo ""
echo -e "${YELLOW}IMPORTANT: Change default passwords!${NC}"
echo -e "DATABASE_PASSWORD and JWT_SECRET must be changed!"
echo ""
echo -e "${GREEN}Documentation:${NC}"
echo "  - Full deployment guide: DEPLOYMENT-PRODUCTION.md"
echo "  - Monitoring guide: MONITORING.md"
echo "  - AI services: AI-SERVICES-CONFIGURATION.md"
echo "  - Database: DATABASE-PASSWORD-GUIDE.md"
echo ""
echo -e "${GREEN}Production URL:${NC} https://sowknow.gollamtech.com"
echo ""