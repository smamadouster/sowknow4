# SOWKNOW Deployment Checklist

## Pre-Deployment Verification

### Environment Configuration

| # | Item | Command | Expected Result |
|---|------|---------|-----------------|
| 1 | `.env.production` exists | `ls -la backend/.env.production` | File exists |
| 2 | Database password set | `grep DATABASE_PASSWORD backend/.env.production` | Non-empty value |
| 3 | JWT secret set (64+ chars) | `grep JWT_SECRET backend/.env.production` | 64+ character string |
| 4 | Allowed origins configured | `grep ALLOWED_ORIGINS backend/.env.production` | Specific HTTPS domains |
| 5 | Allowed hosts configured | `grep ALLOWED_HOSTS backend/.env.production` | Specific hostnames |
| 6 | APP_ENV=production | `grep APP_ENV backend/.env.production` | `production` |

### API Keys

| # | Service | Variable | Verification |
|---|---------|----------|--------------|
| 1 | Gemini | `GEMINI_API_KEY` | Key starts with `AIza...` |
| 2 | OpenRouter | `OPENROUTER_API_KEY` | Key starts with `sk-or-v1-...` |
| 3 | Hunyuan OCR | `HUNYUAN_API_KEY` | Non-empty |
| 4 | Ollama | `OLLAMA_BASE_URL` | `http://host.docker.internal:11434` |

### Docker Configuration

```bash
# Verify production compose
docker compose -f docker-compose.production.yml config --quiet

# Check volumes are defined
grep -A 10 "^volumes:" docker-compose.production.yml
# Expected: public_data, confidential_data, postgres_data, redis_data, backups
```

### SSL/TLS

```bash
# Verify certificates exist
ls -la certbot-conf/live/sowknow.gollamtech.com/

# Test SSL
openssl s_client -connect sowknow.gollamtech.com:443 \
  -servername sowknow.gollamtech.com < /dev/null | grep -E "Verify|Protocol"
# Expected: Protocol = TLSv1.2 or TLSv1.3, Verify return: OK
```

### Security Settings

| # | Check | Command | Expected |
|---|-------|---------|----------|
| 1 | No CORS wildcards | `grep ALLOWED_ORIGINS backend/.env.production` | No `*` |
| 2 | Trusted hosts set | `grep TRUSTED_HOSTS backend/.env.production` | Specific hosts |
| 3 | Rate limiting active | `grep rate_limit nginx/nginx.conf` | Configured |
| 4 | Non-root users | `grep "USER " backend/Dockerfile` | `appuser` not `root` |

## Pre-Deployment Tests

### Database

```bash
# Verify PostgreSQL is ready
docker exec sowknow-postgres pg_isready -U sowknow

# Check migrations applied
docker exec sowknow-postgres psql -U sowknow -d sowknow -c \
  "SELECT * FROM alembic_version;"
```

### Backend Services

```bash
# Test health endpoint
curl http://localhost:8000/health | jq .

# Test API docs accessible
curl -I http://localhost:8000/api/docs | head -1

# Test authentication
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@test.com","password":"test123"}' | jq '.access_token'
```

### Storage

```bash
# Verify volume mounts
docker inspect sowknow-backend | jq '.[0].Mounts'

# Test write permissions
docker exec sowknow-backend touch /data/public/test.txt
docker exec sowknow-backend rm /data/public/test.txt
```

## Deployment Steps

### Step 1: Backup

```bash
# Create timestamped backup
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Database backup
docker exec sowknow-postgres pg_dump -U sowknow sowknow > \
  backups/sowknow_db_$TIMESTAMP.sql

# Configuration backup
cp -r nginx nginx.backup.$TIMESTAMP
cp backend/.env.production backend/.env.production.backup.$TIMESTAMP
```

### Step 2: Pull Latest Code

```bash
# If using git
git pull origin master

# Or rebuild containers
docker compose -f docker-compose.production.yml build
```

### Step 3: Stop Services

```bash
# Graceful shutdown
docker compose -f docker-compose.production.yml down
```

### Step 4: Start Services

```bash
# Start infrastructure first
docker compose -f docker-compose.production.yml up -d postgres redis

# Wait for health
sleep 30

# Start application services
docker compose -f docker-compose.production.yml up -d backend celery-worker

# Wait for backend health
sleep 20

# Start nginx
docker compose -f docker-compose.production.yml up -d nginx

# Start optional services
docker compose -f docker-compose.production.yml up -d telegram-bot
```

### Step 5: Verify

```bash
# Check all containers
docker compose ps

# Health checks
for endpoint in health api/v1/health/detailed api/v1/monitoring/system; do
  echo "Testing: $endpoint"
  curl -sf http://localhost:8000/$endpoint > /dev/null && echo "OK" || echo "FAILED"
done

# Test authenticated endpoint
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@test.com","password":"test123"}' | jq -r '.access_token')

curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/documents | jq '.total'
```

## Post-Deployment

### Monitoring Setup

```bash
# Add to crontab for log rotation
crontab -e
# Add: 0 2 * * * /root/development/src/active/sowknow4/scripts/rotate-logs.sh

# Add to crontab for SSL renewal check
# Add: 0 0,12 * * * /root/development/src/active/sowknow4/scripts/renew-ssl.sh
```

### Documentation Updates

- [ ] Update deployment date in DEPLOYMENT.md
- [ ] Record any configuration changes
- [ ] Update API documentation if changed
- [ ] Notify users of deployment

## Rollback Triggers

Immediately rollback if:
- [ ] Health checks fail for >5 minutes
- [ ] >10% of requests return 5xx errors
- [ ] Database connection failures
- [ ] Confidential data routing to wrong LLM (CRITICAL)

See ROLLBACK_PLAN.md for detailed procedures.

## Sign-Off

| Role | Name | Date | Signature |
|------|------|------|-----------|
| Deployer | | | |
| QA Reviewer | | | |
| Security Reviewer | | | |
