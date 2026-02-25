# SOWKNOW Deployment Guide

**Version**: 3.0.0 (Phase 3)
**Last Updated**: February 24, 2026
**Status**: Production Ready

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [System Architecture](#system-architecture)
3. [Environment Setup](#environment-setup)
4. [Local Development](#local-development)
5. [Production Deployment](#production-deployment)
6. [Database Setup](#database-setup)
7. [Testing](#testing)
8. [Health Checks](#health-checks)
9. [Monitoring](#monitoring)
10. [Troubleshooting](#troubleshooting)
11. [Backup & Recovery](#backup--recovery)
12. [Updates & Maintenance](#updates--maintenance)

---

## Prerequisites

### Hardware Requirements

- **CPU**: 4+ cores (Intel/AMD x86_64)
- **RAM**: 16GB minimum (SOWKNOW uses max 6.4GB)
- **Storage**: 100GB+ SSD recommended
- **Network**: Stable internet connection for API calls
- **OS**: Linux (Ubuntu 20.04+ recommended) or Docker Desktop (Mac/Windows)

### Software Requirements

| Component | Version | Purpose |
|-----------|---------|---------|
| Docker | 20.10+ | Container runtime |
| Docker Compose | 2.0+ | Container orchestration |
| Git | 2.0+ | Version control |
| Python | 3.11+ | (for local dev only) |
| PostgreSQL | 16 | Database (via Docker) |
| Redis | 7+ | Cache/queue (via Docker) |

### Port Requirements

| Service | Port | Used In |
|---------|------|---------|
| Frontend | 3000 | Development only |
| Backend API | 8000/8001 | Internal, exposed on 8001 |
| PostgreSQL | 5432 | Internal only |
| Redis | 6379 | Internal only |
| Nginx/Caddy | 80, 443 | Production reverse proxy |
| Prometheus | 9090 | Monitoring (optional) |

### Network Prerequisites

- Domain name with DNS control (for production)
- Email for Let's Encrypt certificates
- API keys for:
  - Kimi/Moonshot API (chatbot/search)
  - MiniMax/OpenRouter (public docs)
  - (Optional) Gemini Flash (legacy support)

---

## System Architecture

### Container Topology

```
┌─────────────────────────────────────────────────────┐
│              Docker Compose Network                  │
│              (sowknow-net bridge)                    │
├─────────────────────────────────────────────────────┤
│                                                       │
│  ┌──────────────┐     ┌──────────────┐             │
│  │   Frontend   │     │   Nginx/Caddy│             │
│  │ (Next.js)    │     │ (Reverse Proxy)            │
│  │  Port 3000   │     │  Ports 80/443             │
│  └──────────────┘     └──────────────┘             │
│         │                    ▲                       │
│         └────────┬───────────┘                      │
│                  │                                   │
│         ┌────────▼────────┐                         │
│         │  Backend API    │                         │
│         │   (FastAPI)     │                         │
│         │  Port 8000      │                         │
│         └────────┬────────┘                         │
│                  │                                   │
│    ┌─────────────┼─────────────┐                   │
│    │             │             │                   │
│ ┌──▼──┐    ┌──────▼────┐  ┌───▼─────┐             │
│ │Postgres  │  Redis    │  │Celery   │             │
│ │(pgvector)│  (Cache)  │  │(Queue)  │             │
│ └─────┘    └───────────┘  └─────────┘             │
│    │                           │                    │
│    └───────────────┬───────────┘                   │
│                    │                                │
│         ┌──────────▼────────────┐                  │
│         │  Celery Worker &     │                  │
│         │  Beat Scheduler      │                  │
│         └──────────────────────┘                  │
│                                                     │
│  (Ollama runs on host, accessible via             │
│   host.docker.internal:11434)                     │
└─────────────────────────────────────────────────────┘
```

### Memory Allocation (6.4GB total)

| Service | Limit | Purpose |
|---------|-------|---------|
| PostgreSQL | 2048MB | Indexes, query cache, pgvector |
| Redis | 512MB | Session cache, queue storage |
| Backend (API) | 512MB | FastAPI app, request handling |
| Celery Worker | 2048MB | Embedding model (1.3GB) + Python |
| Celery Beat | 256MB | Task scheduling only |
| Frontend | 512MB | Next.js build + runtime |
| Nginx/Telegram | 256MB | Reverse proxy + bot |
| **Total** | **6.4GB** | Shared with host system |

### Tri-LLM Routing

```
Document → Is Confidential?
              │
          ┌───┴────┐
         YES       NO
          │        │
          ▼        ▼
        Ollama   Which Type?
       (Local)    │
              ┌───┼───┐
             Chat Search Public
              │    │    │
              ▼    ▼    ▼
             Kimi Kimi  MiniMax
         (Moonshot) (OpenRouter)
```

**Routing Rules**:
- **Confidential documents** → Ollama (local, zero PII)
- **Chat queries** → Kimi/Moonshot API
- **Search queries** → Kimi/Moonshot API
- **Public documents** → MiniMax/OpenRouter
- **Fallback** → Ollama if APIs fail

---

## Environment Setup

### 1. Clone Repository

```bash
git clone https://github.com/anomalyco/sowknow4.git
cd sowknow4
```

### 2. Create Environment File

Create `.env` in project root:

```bash
# Database Configuration (CRITICAL)
DATABASE_USER=sowknow
DATABASE_NAME=sowknow
DATABASE_PASSWORD=<generate-secure-password>  # Must be 24+ chars, alphanumeric + symbols
REDIS_PASSWORD=<generate-secure-password>    # Must be 24+ chars, alphanumeric + symbols

# JWT Security (CRITICAL)
JWT_SECRET=<generate-64-char-secret>  # Use: python3 -c "import secrets; print(secrets.token_urlsafe(48))"

# LLM API Keys (Required for deployment)
KIMI_API_KEY=sk-<your-kimi-key>
MINIMAX_API_KEY=<your-minimax-key>
OPENROUTER_API_KEY=<your-openrouter-key>

# Optional: Legacy Gemini Support
GEMINI_API_KEY=<your-gemini-key>

# Local LLM (Ollama)
LOCAL_LLM_URL=http://host.docker.internal:11434
OLLAMA_MODEL=mistral  # or other model

# CORS & Cookie Configuration
ALLOWED_ORIGINS=http://localhost:3000,http://localhost:8000
ALLOWED_HOSTS=localhost
COOKIE_DOMAIN=localhost  # Change to .yourdomain.com in production

# Application Settings
APP_ENV=development  # Change to 'production' for deployment
DEBUG=False

# Monitoring & Costs
GEMINI_DAILY_BUDGET_USD=5.00
MiniMAX_DAILY_BUDGET_USD=3.00

# Telegram Bot (Optional)
# NOTE: The Telegram bot uses Redis for persistent session storage.
# Redis must be running before the telegram-bot container starts.
# Sessions are stored under key telegram:user_context:{telegram_user_id} with
# a 24-hour TTL.  If Redis is unavailable, the bot falls back to in-memory
# storage (sessions lost on restart).
TELEGRAM_BOT_TOKEN=<your-telegram-token>
TELEGRAM_CHAT_ID=<admin-chat-id>

# AWS S3 (Optional - for backups)
AWS_ACCESS_KEY_ID=<optional>
AWS_SECRET_ACCESS_KEY=<optional>
AWS_BACKUP_BUCKET=sowknow-backups
```

### 3. Generate Secure Passwords

```bash
# Generate DATABASE_PASSWORD
openssl rand -base64 24

# Generate JWT_SECRET
python3 -c "import secrets; print(secrets.token_urlsafe(48))"

# Generate REDIS_PASSWORD
openssl rand -base64 24
```

### 4. Verify Environment

```bash
# Check required variables are set
grep -E "^[A-Z_]+=" .env | wc -l  # Should be >= 15

# Test Docker configuration
docker-compose config > /dev/null && echo "✓ Docker Compose valid"
```

---

## Local Development

### 1. Build Development Containers

```bash
# Build backend, worker, and optional services
docker-compose build backend celery-worker frontend

# Build with no cache if you encounter issues
docker-compose build --no-cache backend
```

### 2. Start Services

```bash
# Start all core services (exclude nginx, prometheus)
docker-compose up -d postgres redis backend frontend celery-worker celery-beat

# Verify all services are healthy
docker-compose ps

# Expected output:
# STATUS should be "Up (healthy)" for postgres, redis, backend
```

### 3. Database Initialization

```bash
# Run migrations
docker-compose exec backend alembic upgrade head

# Seed initial data (admin user, test documents)
docker-compose exec backend python -m app.scripts.seed_database

# Verify tables created
docker-compose exec postgres psql -U sowknow sowknow -c "\dt"
```

### 4. Access Services

| Service | URL | Notes |
|---------|-----|-------|
| Frontend | http://localhost:3000 | Next.js development |
| Backend API | http://localhost:8001 | FastAPI |
| API Docs | http://localhost:8001/api/docs | Swagger UI |
| API ReDoc | http://localhost:8001/api/redoc | ReDoc |

### 5. Health Checks

```bash
# Backend health
curl http://localhost:8001/health | jq .

# Database connection
docker-compose exec backend curl -s http://localhost:8000/api/v1/status | jq .

# Redis connection
docker-compose exec redis redis-cli ping
```

### 6. Development Workflow

```bash
# Monitor logs in real-time
docker-compose logs -f backend

# Restart after code changes
docker-compose restart backend celery-worker

# Stop all services
docker-compose down

# Stop and remove volumes (clean slate)
docker-compose down -v
```

---

## Production Deployment

### 1. Pre-Deployment Checklist

```bash
# ✓ Code is committed and tested
git status  # Should be clean

# ✓ Environment variables configured
test -f .env && echo "✓ .env exists" || echo "✗ Create .env"

# ✓ Secrets are not in git
git log --all --full-history --source -- "*.env" || echo "✓ No .env in history"

# ✓ All tests pass
./scripts/run-tests.sh
```

### 2. Configure for Production

Update `.env`:

```bash
# Production settings
APP_ENV=production
DEBUG=False

# Production domain
ALLOWED_ORIGINS=https://yourdomain.com,https://www.yourdomain.com
ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com
COOKIE_DOMAIN=.yourdomain.com

# Increase budgets for production
GEMINI_DAILY_BUDGET_USD=10.00
MiniMAX_DAILY_BUDGET_USD=5.00
```

### 3. Set Up SSL Certificates

**Option A: Using Caddy (Recommended)**

```bash
# Caddy auto-renews certificates
# Just configure domain in caddy config
export DOMAIN="yourdomain.com"
export EMAIL="admin@yourdomain.com"

# Edit nginx/Caddyfile and set your domain
nano nginx/Caddyfile

# Start Caddy (it will auto-provision certificates)
# This is handled by production docker-compose
```

**Option B: Using Let's Encrypt + Certbot**

```bash
# Request certificate
docker run --rm -it \
  -p 80:80 \
  -v $(pwd)/certbot-conf:/etc/letsencrypt \
  certbot/certbot certonly --standalone \
  --email admin@yourdomain.com \
  --agree-tos \
  -d yourdomain.com \
  -d www.yourdomain.com

# Copy certificates
mkdir -p nginx/ssl
cp certbot-conf/live/yourdomain.com/fullchain.pem nginx/ssl/
cp certbot-conf/live/yourdomain.com/privkey.pem nginx/ssl/

# Auto-renewal cron job
echo "0 0,12 * * * /root/development/src/active/sowknow4/scripts/renew-ssl.sh" | crontab -
```

### 4. Deploy to Production

```bash
# 1. Build production images
docker-compose -f docker-compose.production.yml build

# 2. Start services
docker-compose -f docker-compose.production.yml up -d

# 3. Run migrations
docker-compose -f docker-compose.production.yml exec backend alembic upgrade head

# 4. Verify health
curl https://yourdomain.com/health | jq .

# 5. Check all services
docker-compose -f docker-compose.production.yml ps
```

### 5. Production Verification

```bash
# Test HTTPS connection
curl -I https://yourdomain.com/

# Check API endpoints
curl -s https://yourdomain.com/api/v1/status | jq .

# Verify database connectivity
curl -s https://yourdomain.com/api/v1/health/detailed | jq .

# Check monitoring endpoints
curl -s https://yourdomain.com/api/v1/monitoring/system | jq .
```

### 6. Post-Deployment Tasks

```bash
# Create admin account
docker-compose -f docker-compose.production.yml exec backend \
  python -c "
from app.services.user_service import create_user
create_user(
    email='admin@yourdomain.com',
    password='<temporary-password>',
    role='admin'
)
print('Admin user created')
"

# Set up monitoring
docker-compose -f docker-compose.production.yml logs postgres > /var/log/sowknow-postgres.log
docker-compose -f docker-compose.production.yml logs backend > /var/log/sowknow-backend.log

# Configure log rotation
sudo tee /etc/logrotate.d/sowknow > /dev/null <<EOF
/var/docker/sowknow4/*.log {
    daily
    rotate 14
    compress
    delaycompress
    notifempty
    create 0640 root root
    sharedscripts
    postrotate
        docker-compose -f /var/docker/sowknow4/docker-compose.production.yml restart backend
    endscript
}
EOF
```

---

## Database Setup

### 1. PostgreSQL with pgvector

The database starts automatically with `docker-compose up`. To manually initialize:

```bash
# Connect to database
docker-compose exec postgres psql -U sowknow sowknow

# List extensions
\dx

# Check for pgvector (should be installed)
SELECT * FROM pg_extension WHERE extname = 'vector';

# Exit
\q
```

### 2. Run Migrations

```bash
# Apply all migrations
docker-compose exec backend alembic upgrade head

# Check migration status
docker-compose exec backend alembic current

# View migration history
docker-compose exec backend alembic history --oneline
```

### 3. Seed Initial Data

```bash
# Create admin user
docker-compose exec backend python -c "
from app.services.user_service import create_user
user = create_user(
    email='admin@example.com',
    password='<temporary>',
    role='admin'
)
print(f'Created user: {user.email}')
"

# Create test collections
docker-compose exec backend python -c "
from app.services.collection_service import create_collection
coll = create_collection(
    name='Test Collection',
    description='Initial test collection',
    is_public=True
)
print(f'Created collection: {coll.name}')
"
```

### 4. Backup Strategy

```bash
# Daily automated backup (add to crontab)
crontab -e

# Add this line:
# 2 AM daily - PostgreSQL dump
0 2 * * * docker-compose -f /var/docker/sowknow4/docker-compose.yml \
  exec -T postgres pg_dump -U sowknow sowknow | \
  gzip > /backups/sowknow_$(date +\%Y\%m\%d).sql.gz

# Weekly backup to S3 (if configured)
0 3 * * 0 aws s3 cp /backups/sowknow_$(date +\%Y\%m\%d).sql.gz \
  s3://your-backup-bucket/
```

### 5. Database Restore

```bash
# List available backups
ls -lh /backups/

# Restore from backup
docker-compose exec -T postgres psql -U sowknow sowknow < \
  /backups/sowknow_20260224.sql

# Verify restore
docker-compose exec postgres psql -U sowknow sowknow -c "SELECT COUNT(*) FROM users;"
```

---

## Testing

### 1. Test Environment Setup

```bash
# Create separate test database
export TEST_DATABASE_URL="postgresql://sowknow:sowknow@localhost:5432/sowknow_test"

# Initialize test database
docker-compose exec postgres createdb -U sowknow sowknow_test

# Run migrations on test database
TEST_DATABASE_URL=$TEST_DATABASE_URL \
  docker-compose exec backend alembic upgrade head
```

### 2. Run Test Suite

```bash
# All tests
./scripts/run-tests.sh

# Unit tests only
pytest backend/tests/unit -v

# Integration tests
pytest backend/tests/integration -v

# E2E tests
pytest backend/tests/e2e -v

# Performance tests
pytest backend/tests/performance -v

# Security tests
pytest backend/tests/security -v

# Specific test file
pytest backend/tests/e2e/test_document_upload.py -v

# With coverage
pytest --cov=app backend/tests/
```

### 3. Test Reports

```bash
# Generate HTML report
pytest --html=reports/test_report.html --self-contained-html

# View results
open reports/test_report.html  # or use browser
```

### 4. Manual Testing

```bash
# Test authentication
curl -X POST http://localhost:8001/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@example.com","password":"<password>"}'

# Test document upload
curl -X POST http://localhost:8001/api/v1/documents/upload \
  -H "Authorization: Bearer <token>" \
  -F "file=@test.pdf"

# Test search
curl -X GET "http://localhost:8001/api/v1/search?q=test" \
  -H "Authorization: Bearer <token>"

# Test collections
curl -X GET http://localhost:8001/api/v1/collections \
  -H "Authorization: Bearer <token>"
```

---

## Health Checks

### 1. Service Health Endpoints

```bash
# Basic health (no auth required)
curl http://localhost:8001/health

# Detailed health check
curl http://localhost:8001/api/v1/health/detailed | jq .

# Expected response:
# {
#   "status": "healthy",
#   "services": {
#     "database": "connected",
#     "redis": "connected",
#     "celery": "connected"
#   },
#   "timestamp": "2026-02-24T10:00:00Z"
# }
```

### 2. Container Health

```bash
# Check all containers
docker-compose ps

# Deep dive on specific container
docker inspect sowknow4-backend | jq '.[0].State.Health'

# Check resource usage
docker stats --no-stream

# Memory limits vs actual usage
docker-compose exec backend python -c "
import psutil
print(f'Memory usage: {psutil.Process().memory_info().rss / 1024 / 1024:.1f} MB')
"
```

### 3. Database Health

```bash
# Connection pool status
docker-compose exec backend python -c "
from app.database import SessionLocal
with SessionLocal() as session:
    result = session.execute('SELECT 1')
    print('✓ Database connected')
"

# Query performance (check slow queries)
docker-compose exec postgres psql -U sowknow sowknow -c "
  SELECT query, calls, mean_exec_time
  FROM pg_stat_statements
  ORDER BY mean_exec_time DESC LIMIT 10;
"
```

### 4. Monitoring Endpoints

```bash
# System resources
curl http://localhost:8001/api/v1/monitoring/system | jq .

# API costs (Kimi, MiniMax)
curl http://localhost:8001/api/v1/monitoring/costs | jq .

# Processing queue status
curl http://localhost:8001/api/v1/monitoring/queue | jq .

# Error rate (5xx)
curl http://localhost:8001/api/v1/monitoring/errors | jq .
```

---

## Monitoring

### 1. Log Aggregation

```bash
# Real-time backend logs
docker-compose logs -f backend

# Last 100 lines
docker-compose logs --tail=100 backend

# Specific service logs
docker-compose logs -f celery-worker

# Save logs to file
docker-compose logs > logs_$(date +%Y%m%d-%H%M%S).txt
```

### 2. Prometheus Metrics (Optional)

Enable monitoring profile:

```bash
# Start with Prometheus
docker-compose --profile monitoring up -d

# Access Prometheus
open http://localhost:9090

# Useful queries:
# - request_duration_seconds (search latency)
# - http_request_total (request count)
# - container_memory_usage_bytes (memory)
```

### 3. Cost Tracking

```bash
# Daily API cost report
curl http://localhost:8001/api/v1/monitoring/costs | jq '{
  kimi: .kimi_daily_spend,
  minimax: .minimax_daily_spend,
  total_month: .total_monthly_spend,
  remaining_budget: .remaining_budget
}'

# Weekly cost summary
# Add to crontab:
0 9 * * 1 curl -s http://localhost:8001/api/v1/monitoring/costs | \
  jq '.' > /var/log/sowknow-weekly-costs-$(date +\%Y\%m\%d).json
```

### 4. Anomaly Alerts

The system sends daily anomaly reports at 09:00 AM:

```bash
# Manual trigger
curl -X POST http://localhost:8001/api/v1/admin/anomaly-report

# Review recent anomalies
curl http://localhost:8001/api/v1/admin/anomalies?limit=10 | jq .

# Expected anomalies to track:
# - Stuck processing jobs (queue depth > 100)
# - Slow search responses (> 8s)
# - High error rates (> 5% 5xx)
# - Database connection issues
# - OOM conditions
```

---

## Troubleshooting

### Backend Won't Start

```bash
# 1. Check logs
docker-compose logs backend

# 2. Verify database is ready
docker-compose exec postgres pg_isready -U sowknow

# 3. Check environment variables
docker-compose exec backend env | grep DATABASE

# 4. Verify migrations ran
docker-compose exec backend alembic current

# Solution: If database issue
docker-compose down
docker-compose up -d postgres
sleep 10
docker-compose up -d backend
```

### Health Check Failing

```bash
# 1. Test individual services
docker-compose exec postgres pg_isready -U sowknow
docker-compose exec redis redis-cli ping
docker-compose exec backend curl -s http://localhost:8000/health

# 2. Check port conflicts
lsof -i :8001  # Backend port
lsof -i :5432  # Database port

# Solution: Restart individual service
docker-compose restart backend
```

### High Memory Usage

```bash
# 1. Check current usage
docker stats --no-stream

# 2. Identify memory leak
docker-compose exec backend python -c "
import tracemalloc
tracemalloc.start()
# Your code here
current, peak = tracemalloc.get_traced_memory()
print(f'Current: {current / 1024 / 1024:.1f} MB; Peak: {peak / 1024 / 1024:.1f} MB')
"

# 3. Adjust limits in docker-compose.yml
# backend:
#   deploy:
#     resources:
#       limits:
#         memory: 1024M  # Increase if needed

docker-compose up -d backend
```

### SSL Certificate Issues

```bash
# 1. Check expiry
openssl x509 -in nginx/ssl/fullchain.pem -text -noout | grep -A2 "Valid"

# 2. Verify certificate chain
openssl s_client -connect yourdomain.com:443 -showcerts

# 3. Renew if expired
./scripts/renew-ssl.sh

# 4. Check renewal logs
tail -f /var/log/letsencrypt/renew.log
```

### Redis Connection Issues

```bash
# 1. Test connection
docker-compose exec redis redis-cli -a $REDIS_PASSWORD ping

# 2. Check memory
docker-compose exec redis redis-cli INFO memory

# 3. Clear if needed
docker-compose exec redis redis-cli FLUSHALL

# 4. Check queues
docker-compose exec redis redis-cli LLEN celery
```

### Database Connection Pool Exhausted

```bash
# 1. Check active connections
docker-compose exec postgres psql -U sowknow sowknow -c "
  SELECT datname, count(*) FROM pg_stat_activity GROUP BY datname;
"

# 2. Increase pool size in docker-compose.yml backend section:
# environment:
#   - SQLALCHEMY_POOL_SIZE=20
#   - SQLALCHEMY_MAX_OVERFLOW=10

# 3. Kill idle connections if needed
docker-compose exec postgres psql -U sowknow sowknow -c "
  SELECT pg_terminate_backend(pid)
  FROM pg_stat_activity
  WHERE state = 'idle' AND query_start < NOW() - INTERVAL '1 hour';
"
```

---

## Backup & Recovery

### 1. Database Backup

```bash
# Manual backup
docker-compose exec -T postgres pg_dump -U sowknow sowknow | \
  gzip > backup_$(date +%Y%m%d-%H%M%S).sql.gz

# Verify backup
gunzip -c backup_*.sql.gz | head -20

# Backup size
du -h backup_*.sql.gz
```

### 2. Volume Backup

```bash
# Backup all volumes
for volume in sowknow-postgres-data sowknow-redis-data sowknow-public-data; do
  docker run --rm -v $volume:/data -v $(pwd):/backup \
    alpine tar czf /backup/${volume}_$(date +%Y%m%d).tar.gz -C /data .
done

# List backups
ls -lh *_$(date +%Y%m%d).tar.gz
```

### 3. Database Restore

```bash
# Restore from SQL dump
docker-compose exec -T postgres psql -U sowknow sowknow < backup_20260224-100000.sql

# Verify restore
docker-compose exec postgres psql -U sowknow sowknow -c "
  SELECT 'Users' as table_name, COUNT(*) as count FROM users
  UNION ALL
  SELECT 'Documents', COUNT(*) FROM documents
  UNION ALL
  SELECT 'Collections', COUNT(*) FROM collections;
"
```

### 4. Point-in-Time Recovery

```bash
# Enable WAL archiving (in docker-compose.yml)
# environment:
#   - POSTGRES_INITDB_ARGS: "-c wal_level=replica -c archive_mode=on"

# List available backups
ls -lt backup_*.sql.gz | head

# Restore to specific point
# Edit backup file timestamp as needed
docker-compose exec -T postgres psql -U sowknow sowknow < backup_20260224.sql
```

---

## Updates & Maintenance

### 1. Code Updates

```bash
# Pull latest code
git pull origin master

# Rebuild affected services
docker-compose build backend celery-worker

# Restart services
docker-compose up -d

# Verify health
curl http://localhost:8001/health
```

### 2. Database Migrations

```bash
# Create new migration (if needed)
docker-compose exec backend alembic revision --autogenerate -m "description"

# Apply pending migrations
docker-compose exec backend alembic upgrade head

# Rollback (if needed - be careful!)
docker-compose exec backend alembic downgrade -1
```

### 3. Dependency Updates

```bash
# Check for updates
docker-compose exec backend pip list --outdated

# Update requirements
docker-compose exec backend pip install --upgrade -r requirements.txt

# Rebuild to include updates
docker-compose build --no-cache backend
```

### 4. OS & Docker Updates

```bash
# Update Docker and Docker Compose
sudo apt-get update && sudo apt-get upgrade docker.io docker-compose-plugin

# Restart Docker
sudo systemctl restart docker

# Verify no running containers lost
docker ps
```

### 5. Scheduled Maintenance

```bash
# Set maintenance window (weekly Sunday 2 AM)
# Add to crontab:
0 2 * * 0 /root/development/src/active/sowknow4/scripts/maintenance.sh

# Maintenance script includes:
# - Log rotation
# - Cache cleanup
# - Database optimization
# - Backup verification
```

---

## Performance Tuning

### 1. PostgreSQL Optimization

```bash
# Analyze query performance
docker-compose exec postgres psql -U sowknow sowknow -c "
  ANALYZE;
  SELECT * FROM pg_stat_statements
  ORDER BY mean_exec_time DESC LIMIT 10;
"

# Create missing indexes
docker-compose exec postgres psql -U sowknow sowknow -c "
  CREATE INDEX idx_documents_created_at ON documents(created_at DESC);
  CREATE INDEX idx_documents_confidential ON documents(is_confidential);
  CREATE INDEX idx_chat_user_id ON chat_sessions(user_id);
"
```

### 2. Redis Optimization

```bash
# Monitor memory usage
docker-compose exec redis redis-cli INFO memory

# Configure max memory policy
docker-compose exec redis redis-cli CONFIG SET maxmemory-policy allkeys-lru

# Check slow log
docker-compose exec redis redis-cli SLOWLOG GET 10
```

### 3. Application Tuning

```bash
# Increase worker concurrency (if resources allow)
# In docker-compose.yml celery-worker:
# command: celery -A app.celery_app worker --loglevel=info --concurrency=2

# Enable query caching
# In backend code:
# from functools import lru_cache
# @lru_cache(maxsize=128)
# def get_cached_result(query):
#     return expensive_operation(query)

# Monitor response times
curl -X GET "http://localhost:8001/api/v1/search?q=test" \
  -H "Authorization: Bearer <token>" \
  -w "\nResponse time: %{time_total}s\n"
```

---

## Support & Documentation

For detailed information, see:

- **API Documentation**: [API_REFERENCE.md](API_REFERENCE.md)
- **Architecture**: [ARCHITECTURE.md](ARCHITECTURE.md)
- **Testing Guide**: [TESTING.md](TESTING.md)
- **Monitoring**: [MONITORING.md](MONITORING.md)
- **Security**: [SECURITY.md](SECURITY.md)

For issues, create an issue on GitHub or contact: admin@gollamtech.com

---

**SOWKNOW Deployment Guide v3.0.0**
*Last Updated: February 24, 2026*
