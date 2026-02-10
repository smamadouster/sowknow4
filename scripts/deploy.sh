#!/bin/bash
# SOWKNOW Phase 1 Production Deployment Script
# Date: February 2026

set -e

echo "================================"
echo "SOWKNOW Phase 1 Deployment"
echo "================================"
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
PROJECT_NAME="sowknow4"
BACKUP_DIR="/backups"
LOG_FILE="deployment_$(date +%Y%m%d_%H%M%S).log"

# Functions
log() {
    echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $1" | tee -a "$LOG_FILE"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1" | tee -a "$LOG_FILE"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1" | tee -a "$LOG_FILE"
}

# Pre-flight checks
preflight_checks() {
    log "Running pre-flight checks..."

    # Check Docker
    if ! command -v docker &> /dev/null; then
        error "Docker is not installed"
        exit 1
    fi

    # Check Docker Compose
    if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
        error "Docker Compose is not installed"
        exit 1
    fi

    # Check .env file
    if [ ! -f ".env" ]; then
        error ".env file not found. Please create it from .env.example"
        exit 1
    fi

    # Check required environment variables
    source .env
    REQUIRED_VARS=("DATABASE_PASSWORD" "JWT_SECRET" "MOONSHOT_API_KEY" "HUNYUAN_API_KEY" "TELEGRAM_BOT_TOKEN")
    MISSING_VARS=()

    for var in "${REQUIRED_VARS[@]}"; do
        if [ -z "${!var}" ]; then
            MISSING_VARS+=("$var")
        fi
    done

    if [ ${#MISSING_VARS[@]} -gt 0 ]; then
        error "Missing required environment variables: ${MISSING_VARS[*]}"
        exit 1
    fi

    # Check Ollama connectivity
    log "Checking Ollama connectivity..."
    if curl -s http://localhost:11434/api/tags > /dev/null; then
        log "Ollama is accessible"
    else
        warn "Ollama is not accessible. Confidential document processing will be degraded."
    fi

    log "Pre-flight checks completed"
}

# Backup existing data
backup_data() {
    log "Creating backup of existing data..."

    mkdir -p "$BACKUP_DIR"

    # Backup PostgreSQL
    if docker ps | grep -q "$PROJECT_NAME-postgres"; then
        log "Backing up PostgreSQL..."
        docker exec "$PROJECT_NAME-postgres" pg_dump -U sowknow sowknow | gzip > "$BACKUP_DIR/postgres_backup_$(date +%Y%m%d_%H%M%S).sql.gz"
        log "PostgreSQL backup completed"
    fi

    # Backup document volumes
    log "Backing up document volumes..."
    docker run --rm -v "$PROJECT_NAME-sowknow-public-data:/data/public" -v "$BACKUP_DIR:/backup" \
        alpine tar czf "/backup/public_docs_$(date +%Y%m%d_%H%M%S).tar.gz" -C /data public || true

    docker run --rm -v "$PROJECT_NAME-sowknow-confidential-data:/data/confidential" -v "$BACKUP_DIR:/backup" \
        alpine tar czf "/backup/confidential_docs_$(date +%Y%m%d_%H%M%S).tar.gz" -C /data confidential || true

    log "Backup completed"
}

# Build and deploy
deploy() {
    log "Building Docker images..."
    docker-compose build --no-cache

    log "Stopping existing containers..."
    docker-compose down

    log "Starting containers..."
    docker-compose up -d

    log "Waiting for services to be healthy..."
    sleep 30

    # Run database migrations
    log "Running database migrations..."
    docker-compose exec -T backend alembic upgrade head || error "Migration failed"

    log "Deployment completed"
}

# Health checks
health_checks() {
    log "Running health checks..."

    # Check backend
    log "Checking backend health..."
    if curl -f http://localhost:8000/health > /dev/null; then
        log "Backend is healthy"
    else
        error "Backend health check failed"
        return 1
    fi

    # Check frontend
    log "Checking frontend health..."
    if curl -f http://localhost:3000 > /dev/null; then
        log "Frontend is healthy"
    else
        error "Frontend health check failed"
        return 1
    fi

    # Check PostgreSQL
    log "Checking PostgreSQL health..."
    if docker exec "$PROJECT_NAME-postgres" pg_isready -U sowknow > /dev/null; then
        log "PostgreSQL is healthy"
    else
        error "PostgreSQL health check failed"
        return 1
    fi

    # Check Redis
    log "Checking Redis health..."
    if docker exec "$PROJECT_NAME-redis" redis-cli ping > /dev/null; then
        log "Redis is healthy"
    else
        error "Redis health check failed"
        return 1
    fi

    # Check Celery worker
    log "Checking Celery worker..."
    if docker-compose exec -T celery-worker celery -A app.celery_app inspect ping > /dev/null; then
        log "Celery worker is healthy"
    else
        warn "Celery worker health check failed"
    fi

    log "All health checks completed"
}

# Create admin user
create_admin_user() {
    log "Creating admin user..."

    source .env
    ADMIN_EMAIL="${ADMIN_EMAIL:-admin@sowknow.local}"
    ADMIN_PASSWORD="${ADMIN_PASSWORD:-Admin123!}"

    docker-compose exec -T backend python -c "
from app.database import SessionLocal
from app.models.user import User, UserRole
from app.utils.security import get_password_hash

db = SessionLocal()
admin = db.query(User).filter(User.email == '$ADMIN_EMAIL').first()

if not admin:
    admin = User(
        email='$ADMIN_EMAIL',
        hashed_password=get_password_hash('$ADMIN_PASSWORD'),
        full_name='System Administrator',
        role=UserRole.ADMIN,
        is_superuser=True,
        can_access_confidential=True,
        is_active=True
    )
    db.add(admin)
    db.commit()
    print('Admin user created successfully')
else:
    print('Admin user already exists')
"

    log "Admin user setup completed"
}

# Display deployment summary
deployment_summary() {
    log ""
    log "================================"
    log "Deployment Summary"
    log "================================"
    log ""
    log "Services deployed:"
    log "  - PostgreSQL (pgvector): localhost:5432"
    log "  - Redis: localhost:6379"
    log "  - Backend API: http://localhost:8000"
    log "  - Frontend: http://localhost:3000"
    log "  - Nginx: http://localhost (HTTP), http://localhost:443 (HTTPS)"
    log ""
    log "Admin credentials:"
    source .env
    log "  Email: ${ADMIN_EMAIL:-admin@sowknow.local}"
    log "  (Password set during setup, change on first login)"
    log ""
    log "Next steps:"
    log "  1. Access the application at http://localhost"
    log "  2. Login with admin credentials"
    log "  3. Upload your first document"
    log "  4. Test search functionality"
    log "  5. Start a chat conversation"
    log ""
    log "Logs: docker-compose logs -f"
    log "Status: docker-compose ps"
    log ""
}

# Main execution
main() {
    log "Starting SOWKNOW Phase 1 deployment..."

    preflight_checks
    backup_data
    deploy
    health_checks
    create_admin_user
    deployment_summary

    log "Deployment completed successfully!"
    log "Log file: $LOG_FILE"
}

# Run main function
main "$@"
