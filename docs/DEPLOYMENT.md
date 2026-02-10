# SOWKNOW Deployment Guide

## Production Deployment
**Domain**: sowknow.gollamtech.com

### Prerequisites

- Docker and Docker Compose
- A server with at least 16GB RAM and 100GB storage
- SSL certificate (Let's Encrypt)
- Gemini Flash API key
- Hunyuan OCR API credentials

### Quick Start

1. **Clone the repository**
```bash
git clone <repository-url>
cd sowknow4
```

2. **Generate secrets**
```bash
# The deploy script will generate secrets automatically
# Or manually create .secrets file:
cat > .secrets <<EOF
POSTGRES_PASSWORD=$(openssl rand -base64 32)
REDIS_PASSWORD=$(openssl rand -base64 32)
SECRET_KEY=$(openssl rand -hex 32)
JWT_SECRET_KEY=$(openssl rand -hex 32)
EOF
```

3. **Set up SSL certificates**
```bash
# First time setup
./scripts/setup-ssl.sh

# Make sure to update the email in the script first
```

4. **Configure API keys**
```bash
# Add your API keys to backend/.env.production:
GEMINI_API_KEY=your_gemini_api_key_here
HUNYUAN_API_KEY=your_hunyuan_api_key_here
HUNYUAN_SECRET_ID=your_hunyuan_secret_id_here
```

5. **Deploy**
```bash
./scripts/deploy-production.sh
```

### Manual Deployment Steps

If you prefer manual deployment:

1. **Create environment files**
```bash
cp backend/.env.production.example backend/.env.production
cp frontend/.env.production.example frontend/.env.production
```

2. **Update environment files** with your actual values

3. **Build and start services**
```bash
docker-compose -f docker-compose.production.yml build
docker-compose -f docker-compose.production.yml up -d
```

4. **Run database migrations**
```bash
docker-compose -f docker-compose.production.yml run --rm backend alembic upgrade head
```

5. **Check health**
```bash
curl https://sowknow.gollamtech.com/health
```

### Docker Services

The production setup includes:

- **backend**: FastAPI application on port 8000
- **frontend**: Next.js application on port 3000
- **postgres**: PostgreSQL with pgvector extension
- **redis**: Redis for caching and Celery
- **celery-worker**: Background task processor
- **nginx**: Reverse proxy with SSL
- **certbot**: Automatic SSL renewal

### SSL Certificate Management

SSL certificates are automatically renewed by the certbot container.

Manual renewal (if needed):
```bash
docker-compose -f docker-compose.production.yml run --rm certbot renew
docker-compose -f docker-compose.production.yml restart nginx
```

### Database Backups

Automated backups are scheduled daily at 2 AM.

Manual backup:
```bash
docker-compose -f docker-compose.production.yml exec postgres \
  pg_dump -U sowknow sowknow > backup_$(date +%Y%m%d).sql
```

Restore from backup:
```bash
cat backup_20250101.sql | docker-compose -f docker-compose.production.yml exec -T postgres \
  psql -U sowknow sowknow
```

### Monitoring

Check service status:
```bash
docker-compose -f docker-compose.production.yml ps
```

View logs:
```bash
# All services
docker-compose -f docker-compose.production.yml logs -f

# Specific service
docker-compose -f docker-compose.production.yml logs -f backend
```

Health checks:
```bash
# Backend health
curl https://sowknow.gollamtech.com/health

# API status
curl https://sowknow.gollamtech.com/api/v1/status
```

### Performance Tuning

Run the performance tuning script:
```bash
./scripts/tune-performance.sh
```

This will:
- Create optimized database indexes
- Configure PostgreSQL settings
- Create materialized views
- Run VACUUM ANALYZE

### Scaling

To handle more traffic:

1. **Increase worker counts** in docker-compose.production.yml:
```yaml
backend:
  command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

2. **Add more Celery workers**:
```bash
docker-compose -f docker-compose.production.yml up -d --scale celery-worker=4
```

3. **Enable connection pooling** (consider PgBouncer for high traffic)

### Troubleshooting

**Service won't start:**
```bash
# Check logs
docker-compose -f docker-compose.production.yml logs [service-name]

# Restart service
docker-compose -f docker-compose.production.yml restart [service-name]
```

**Database connection issues:**
```bash
# Check postgres is healthy
docker-compose -f docker-compose.production.yml exec postgres pg_isready

# Restart backend
docker-compose -f docker-compose.production.yml restart backend
```

**SSL certificate errors:**
```bash
# Check certificate expiry
docker-compose -f docker-compose.production.yml exec certbot \
  certificates

# Force renew
docker-compose -f docker-compose.production.yml run --rm certbot renew --force-renewal
```

**High memory usage:**
```bash
# Check container stats
docker stats

# Restart services
docker-compose -f docker-compose.production.yml restart
```

### Updates

To update the application:

1. **Pull latest code**
```bash
git pull origin main
```

2. **Rebuild and restart**
```bash
docker-compose -f docker-compose.production.yml build
docker-compose -f docker-compose.production.yml up -d
```

3. **Run migrations**
```bash
docker-compose -f docker-compose.production.yml run --rm backend alembic upgrade head
```

### Rollback

If something goes wrong:

1. **Revert code changes**
```bash
git checkout [previous-commit]
```

2. **Rebuild**
```bash
docker-compose -f docker-compose.production.yml build
docker-compose -f docker-compose.production.yml up -d
```

3. **Or restore from database backup** if needed

### Security Checklist

- [ ] Strong passwords in .secrets file
- [ ] SSL certificates valid
- [ ] Firewall configured (only ports 80, 443 exposed)
- [ ] API keys not committed to git
- [ ] Rate limiting enabled
- [ ] CORS configured correctly
- [ ] Database not exposed externally
- [ ] Redis password protected
- [ ] Regular backups scheduled
- [ ] Log monitoring enabled

### Support

For issues or questions:
- Check logs: `docker-compose -f docker-compose.production.yml logs -f`
- Review API docs: `https://sowknow.gollamtech.com/api/docs`
- Health check: `https://sowknow.gollamtech.com/health`
