# SOWKNOW Deployment Guide

## Prerequisites

### System Requirements
- Docker 20.10+
- Docker Compose 2.0+
- 16GB VPS (SOWKNOW limited to 6.4GB)
- Domain name configured with DNS pointing to server

### Environment Variables

Create a `.env` file in the project root:

```bash
# Database
DATABASE_PASSWORD=your_secure_password_here

# Security
JWT_SECRET=your_jwt_secret_here_64_chars_minimum
ALLOWED_ORIGINS=https://yourdomain.com,https://www.yourdomain.com
ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com

# Production
APP_ENV=production

# AI Services
GEMINI_API_KEY=your_gemini_api_key_here
OPENROUTER_API_KEY=your_openrouter_api_key_here
OPENROUTER_MODEL=minimax/minimax-01
MOONSHOT_API_KEY=your_moonshot_api_key_here
HUNYUAN_API_KEY=your_hunyuan_api_key_here
LOCAL_LLM_URL=http://host.docker.internal:11434

# Telegram (optional)
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here

# Monitoring
GEMINI_DAILY_BUDGET_USD=5.00
```

## Quick Start

### 1. Clone Repository
```bash
git clone <repository-url>
cd sowknow4
```

### 2. Configure Environment
```bash
cp .env.example .env
# Edit .env with your values
nano .env
```

### 3. Build and Start Services
```bash
# Build with non-root user
docker compose build backend celery-worker telegram-bot

# Start all services
docker compose up -d

# Verify status
docker compose ps
```

### 4. Verify Health
```bash
curl http://localhost:8000/health | jq .
```

Expected response:
```json
{
  "status": "healthy",
  "services": {
    "database": "connected",
    "redis": "connected"
  }
}
```

## SSL Certificate Setup

### Option 1: Automated Setup (Recommended)

```bash
# Set your domain and email
export DOMAIN="yourdomain.com"
export EMAIL="admin@yourdomain.com"

# Run SSL setup
./scripts/setup-ssl-auto.sh
```

This will:
1. Obtain Let's Encrypt certificates
2. Configure reverse proxy (Caddy or nginx) for HTTPS
3. Set up auto-renewal

**Note:** Production uses Caddy reverse proxy (port 80/443). Nginx container is not started in production to avoid port conflicts.

### Option 2: Manual Setup

```bash
# Obtain certificate
docker run --rm -it \
  -p 80:80 \
  -v $(pwd)/certbot-conf:/etc/letsencrypt \
  certbot/certbot certonly --standalone \
  --email admin@yourdomain.com \
  --agree-tos \
  -d yourdomain.com

# Copy certificates
docker run --rm \
  -v $(pwd)/certbot-conf:/letsencrypt:ro \
  -v $(pwd)/nginx/ssl:/ssl \
  alpine sh -c "cp /letsencrypt/live/yourdomain.com/fullchain.pem /ssl/ && \
               cp /letsencrypt/live/yourdomain.com/privkey.pem /ssl/"
```

### Certificate Renewal

```bash
# Manual renewal
./scripts/scripts/renew-ssl.sh

# Check expiry
./scripts/scripts/check-ssl-expiry.sh
```

Add to crontab for automatic renewal:
```bash
0 0,12 * * * /root/development/src/active/sowknow4/scripts/renew-ssl.sh
```

## Monitoring Setup

### 1. Verify Monitoring Endpoints
```bash
# Detailed health
curl http://localhost:8000/api/v1/health/detailed | jq .

# Cost tracking
curl http://localhost:8000/api/v1/monitoring/costs | jq .

# Queue status
curl http://localhost:8000/api/v1/monitoring/queue | jq .

# System resources
curl http://localhost:8000/api/v1/monitoring/system | jq .
```

### 2. Setup Log Rotation
```bash
# Add to crontab
crontab -e
# Add this line:
0 2 * * * /root/development/src/active/sowknow4/scripts/rotate-logs.sh >> /var/log/sowknow-rotate.log 2>&1
```

### 3. Prometheus Scrape (Optional)

Add to `prometheus.yml`:
```yaml
scrape_configs:
  - job_name: 'sowknow'
    static_configs:
      - targets: ['localhost:8000']
    metrics_path: '/metrics'
```

## Production Checklist

### Pre-Deployment

- [ ] Environment variables configured in `.env`
- [ ] DATABASE_PASSWORD is strong and unique
- [ ] JWT_SECRET is 64+ characters
- [ ] ALLOWED_ORIGINS matches production domain
- [ ] ALLOWED_HOSTS matches production domain
- [ ] APP_ENV=production

### Security

- [ ] Non-root user configured (all containers)
- [ ] Health checks enabled (all 8 services)
- [ ] Restart policies set (unless-stopped)
- [ ] SSL certificates installed
- [ ] CORS restricted to production origins
- [ ] TrustedHost middleware enabled

### Monitoring

- [ ] Log rotation cron configured
- [ ] SSL auto-renewal cron configured
- [ ] GEMINI_DAILY_BUDGET_USD set
- [ ] Daily anomaly report scheduled (09:00 AM)
- [ ] Prometheus metrics accessible

### Verification

```bash
# 1. Check all containers healthy
docker compose ps | grep healthy

# 2. Verify non-root user
docker exec sowknow4-backend whoami  # Should be "appuser"

# 3. Test HTTPS (after SSL setup)
curl https://yourdomain.com/health | jq .

# 4. Verify all monitoring endpoints
for endpoint in health/detailed monitoring/costs monitoring/queue monitoring/system monitoring/alerts; do
  echo "Testing: $endpoint"
  curl -s "http://localhost:8000/api/v1/$endpoint" | jq '.status // .'
done
```

## Service Management

### Start All Services
```bash
docker compose up -d
```

### Stop All Services
```bash
docker compose down
```

### Restart Specific Service
```bash
docker compose restart backend
# Note: nginx not used in production - Caddy handles reverse proxy
```

### View Logs
```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f backend

# Last 100 lines
docker compose logs --tail=100 backend
```

### Rebuild After Code Changes
```bash
# Rebuild specific service
docker compose build backend
docker compose up -d backend

# Rebuild all
docker compose build
docker compose up -d
```

## Troubleshooting

### Backend Won't Start
```bash
# Check logs
docker logs sowknow4-backend

# Verify database is ready
docker logs sowknow4-postgres

# Check environment variables
docker exec sowknow4-backend env | grep DATABASE
```

### Health Check Failing
```bash
# Test database connection
docker exec sowknow4-postgres pg_isready -U sowknow

# Test Redis connection
docker exec sowknow4-redis redis-cli ping

# Check service dependencies
docker compose ps
```

### SSL Certificate Issues
```bash
# Check certificate expiry
./scripts/scripts/check-ssl-expiry.sh

# Test SSL manually
openssl s_client -connect yourdomain.com:443 -servername yourdomain.com
```

### High Memory Usage
```bash
# Check memory limits
docker stats --no-stream

# Verify container limits
docker inspect sowknow4-backend | jq '.[0].HostConfig.Memory'

# Adjust if needed (in docker-compose.yml)
deploy:
  resources:
    limits:
      memory: 1024M
```

## Backup & Recovery

### Database Backup
```bash
# Create backup
docker exec sowknow4-postgres pg_dump -U sowknow sowknow > backup_$(date +%Y%m%d).sql

# Restore backup
docker exec -i sowknow4-postgres psql -U sowknow sowknow < backup_20240211.sql
```

### Volume Backup
```bash
# Backup all volumes
docker run --rm -v sowknow4_sowknow-postgres-data:/data -v $(pwd):/backup \
  alpine tar czf /backup/postgres_$(date +%Y%m%d).tar.gz -C /data .

# Restore volume
docker run --rm -v sowknow4_sowknow-postgres-data:/data -v $(pwd):/backup \
  alpine tar xzf /backup/postgres_20240211.tar.gz -C /data
```

## Updates & Maintenance

### Apply Code Updates
```bash
# Pull latest code
git pull origin master

# Rebuild affected services
docker compose build backend celery-worker telegram-bot

# Restart services
docker compose up -d
```

### Database Migrations
```bash
# Run Alembic migrations
docker exec sowknow4-backend alembic upgrade head
```

### Clear Cache
```bash
# Clear Redis cache
docker exec sowknow4-redis redis-cli FLUSHALL

# Clear application cache (if implemented)
curl -X POST http://localhost:8000/api/v1/admin/cache/clear
```

## Support

For issues or questions:
1. Check logs: `docker compose logs -f`
2. Verify configuration: Check `.env` file
3. Review monitoring: `curl http://localhost:8000/api/v1/health/detailed`
4. Consult: See MONITORING.md for detailed monitoring guide
