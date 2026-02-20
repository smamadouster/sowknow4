# Production Deployment Guide - SOWKNOW4

## Production Environment

### Server Information
- **Server IP**: 72.62.17.136 (TailScale)
- **Domain**: sowknow.gollamtech.com
- **DNS**: Configured and pointing to server
- **SSH Access**: Via TailScale SSH

### Deployment Strategy
1. **Push code changes to Git repository**
2. **SSH into production server**
3. **Pull latest code**
4. **Stop existing containers** (if any)
5. **Rebuild affected services**
6. **Start services with production configuration**

## Pre-Deployment Checklist

### On Development Machine

- [ ] All code changes committed to Git
- [ ] Docker images pushed to registry (or available for pull)
- [ ] Environment variables documented in `DEPLOYMENT.md`
- [ ] Database backup created (optional)

### On Production Server

- [ ] SSH access verified
- [ ] `.env.production` file created with production values
- [ ] Docker & Docker Compose installed
- [ ] Volume directories created if needed
- [ ] SSL certificates ready (or will be generated)

## Deployment Steps

### Step 1: Push Code Changes

```bash
# On development machine
git add .
git commit -m "chore: prep for production deployment"
git push origin master
```

### Step 2: SSH into Production Server

```bash
# SSH into production server
ssh root@72.62.17.136

# Or via TailScale SSH
# Navigate to project directory
cd /var/docker/sowknow4  # or your deployment path
```

### Step 3: Create Production Environment File

```bash
# On production server
cat > .env.production << 'EOF'
# Database
DATABASE_PASSWORD=your_secure_production_password_here

# Security
JWT_SECRET=your_production_jwt_secret_64_chars_minimum
APP_ENV=production
ALLOWED_ORIGINS=https://sowknow.gollamtech.com,https://www.sowknow.gollamtech.com
ALLOWED_HOSTS=sowknow.gollamtech.com,www.sowknow.gollamtech.com

# AI Services
GEMINI_API_KEY=your_production_gemini_api_key_here
MOONSHOT_API_KEY=your_production_moonshot_api_key_here
HUNYUAN_API_KEY=your_production_hunyuan_api_key_here

# Monitoring
GEMINI_DAILY_BUDGET_USD=5.00

# Optional Services
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
LOCAL_LLM_URL=http://host.docker.internal:11434
EOF

# Secure the file
chmod 600 .env.production
```

### Step 4: Stop Existing Containers

```bash
# Check running containers
docker ps

# Stop all SOWKNOW containers
docker compose down

# Verify no orphan containers
docker ps -a | grep sowknow
```

### Step 5: Pull Latest Code

```bash
# Pull latest changes
git fetch origin
git pull origin master

# Verify you're on correct branch
git branch
```

### Step 6: Rebuild Services

```bash
# Rebuild services with non-root user
docker compose build backend celery-worker telegram-bot

# Verify images
docker images | grep sowknow4
```

### Step 7: Start Production Services

```bash
# Start with production configuration
docker compose --env-file .env.production up -d

# Wait for services to be healthy
sleep 30

# Check status
docker compose ps

# Verify health endpoint
curl http://localhost:8000/health | jq .
```

### Step 8: Verify Deployment

```bash
# Verify all containers are running
docker compose ps

# Check health status
for container in backend celery-worker frontend; do
    docker compose exec $container wget --quiet --tries=1 --spider http://localhost/api/health
done

# Verify non-root user
docker compose exec backend whoami  # Should be "appuser"

# Check logs
docker compose logs -f --tail=100
```

## Production Configuration File Template

```bash
# .env.production template
# Database
DATABASE_PASSWORD=CHANGE_ME_SECURE_PASSWORD

# Security
JWT_SECRET=CHANGE_ME_64_CHAR_SECRET
APP_ENV=production
ALLOWED_ORIGINS=https://sowknow.gollamtech.com,https://www.sowknow.gollamtech.com
ALLOWED_HOSTS=sowknow.gollamtech.com,www.sowknow.gollamtech.com

# AI Services (set these before deployment)
GEMINI_API_KEY=your_gemini_key_here
MOONSHOT_API_KEY=your_moonshot_key_here
HUNYUAN_API_KEY=your_hunyuan_key_here

# Monitoring
GEMINI_DAILY_BUDGET_USD=5.00

# Optional
TELEGRAM_BOT_TOKEN=your_telegram_token
LOCAL_LLM_URL=http://host.docker.internal:11434
```

## SSL Certificate Setup (Caddy)

**Production uses Caddy reverse proxy** (not nginx) to handle SSL termination and reverse proxying. Caddy automatically manages Let's Encrypt certificates.

### How It Works

The shared Caddy instance (`ghostshell-caddy`) handles SSL and reverse proxying for SOWKNOW:

```bash
# View Caddy routes for SOWKNOW
docker exec ghostshell-caddy wget -qO- http://localhost:2019/config/ 2>/dev/null | grep -A10 sowknow

# Traffic routing:
# - sowknow.gollamtech.com/api/* → sowknow4-backend:8000
# - sowknow.gollamtech.com/* → sowknow4-frontend:3000
```

**Important:** Do NOT start the nginx container in production - it conflicts with Caddy on ports 80/443.

### Certificate Management

Caddy automatically handles certificate renewal. No manual action required.

To verify certificate status:

## Rollback Procedure

If deployment fails:

```bash
# 1. Revert to previous working state
git checkout HEAD~1

# 2. Restart previous containers
docker compose up -d

# 3. Verify health
curl http://localhost:8000/health | jq .
```

## Post-Deployment Verification

### Health Checks

```bash
# Basic health
curl http://localhost:8000/health | jq .

# Detailed health
curl http://localhost:8000/api/v1/health/detailed | jq .

# Expected responses
# {"status": "healthy"} for basic health
# Full monitoring data for detailed health
```

### Monitoring Endpoints

```bash
# Test all monitoring endpoints
for endpoint in health/detailed monitoring/costs monitoring/queue monitoring/system monitoring/alerts; do
    echo "Testing: /api/v1/$endpoint"
    curl -s "http://localhost:8000/api/v1/$endpoint" | jq '.status'
done

# Test Prometheus metrics
curl http://localhost:8000/metrics | head -20
```

### Log Verification

```bash
# Check recent logs for errors
docker compose logs --tail=100 backend | grep -i "error\|exception\|traceback"

# Check for security issues
docker compose logs --tail=100 backend | grep -i "permission denied\|unauthorized\|forbidden"

# View container stats
docker stats --no-stream
```

## Troubleshooting

### Service Won't Start

```bash
# Check logs
docker compose logs backend

# Verify configuration
docker compose config

# Check port conflicts
netstat -tulpn | grep ':8000\|:3000\|:80\|:443'

# Check resource limits
docker inspect backend | jq '.[0].HostConfig.Memory'
```

### SSL Issues

```bash
# Check certificate status (via Caddy)
./scripts/ssl-auto-renewal.sh status

# View Caddy configuration
docker exec ghostshell-caddy wget -qO- http://localhost:2019/config/ 2>/dev/null | grep -A5 sowknow

# Test SSL manually
openssl s_client -connect sowknow.gollamtech.com:443 -servername sowknow.gollamtech.com
```

**Note:** SSL is handled by Caddy, not nginx. Do not start the nginx container.

### Database Issues

```bash
# Check database connection
docker compose exec backend python -c "from app.database import engine; print(engine.connect())"

# Run migrations
docker compose exec backend alembic upgrade head

# Check database size
docker compose exec postgres psql -U sowknow -d sowknow -c "SELECT pg_size('sowknow');"
```

### Memory Issues

```bash
# Check container memory usage
docker stats --no-stream | grep -E "sowknow4-backend|sowknow4-celery-worker"

# Verify container limits
docker inspect sowknow4-backend | jq '.[0].HostConfig.Memory'

# Check system memory
free -h
```

## Security Checklist

- [ ] All passwords changed from defaults
- [ ] JWT_SECRET is 64+ characters
- [ ] ALLOWED_ORIGINS is set to production domain only
- [ ] ALLOWED_HOSTS is set to production domain only
- [ ] APP_ENV=production
- [ ] DATABASE_PASSWORD is strong (16+ characters)
- [ ] API keys are set
- [ ] Non-root user configured (appuser)
- [ ] SSL certificates are valid (30+ days)
- [ ] HTTPS enforced (no HTTP on production domain)

## Monitoring Alerts Configuration

### Alert Thresholds (Production)

| Alert | Threshold | Action |
|--------|-----------|--------|
| Memory > 80% | Email + Stop container |
| Disk > 85% | Email + Cleanup required |
| Queue depth > 100 | Email + Scale workers |
| API cost > daily budget | Email + Alert |
| SSL < 14 days | Email + Renew immediately |
| 5xx error rate > 5% | Email + Investigate |

### Set Alert Email

```python
# In backend/app/services/monitoring.py
# Configure email alerts for production
```

## Support Contacts

| Issue Type | Contact | Email |
|------------|---------|--------|
| Deployment | ops-team@example.com | ops-team@example.com |
| Database Issues | dba@example.com | dba@example.com |
| SSL/Certificates | ssl-admin@example.com | ssl-admin@example.com |
| Security Issues | security@example.com | security@example.com |
| API/LLM Issues | api-support@example.com | api-support@example.com |

## Quick Reference

### Common Commands

```bash
# SSH to production
ssh root@72.62.17.136

# Check container status
docker compose ps

# View logs
docker compose logs -f --tail=100 backend

# Restart specific service
docker compose restart backend

# Rebuild service
docker compose build backend && docker compose up -d backend

# Stop all services
docker compose down

# Start all services
docker compose --env-file .env.production up -d

# Check system resources
free -h
df -h
docker stats --no-stream
```

### Important Files

- `docker-compose.yml` - Service definitions
- `.env.production` - Production environment
- `DEPLOYMENT.md` - This guide
- `MONITORING.md` - Monitoring guide
- `scripts/` - Utility scripts

## Deployment Best Practices

1. **Always test in development first** - Verify changes locally
2. **Use .env.production** - Never commit secrets to Git
3. **Tag releases** - Use git tags for production deployments
4. **Keep backups** - Database and file backups before major changes
5. **Monitor health** - Check health endpoints after deployment
6. **Rollback ready** - Know how to revert if needed
7. **Document changes** - Update this file with lessons learned
