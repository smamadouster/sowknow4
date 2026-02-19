# SOWKNOW Rollback Plan

## When to Rollback

Execute rollback immediately if:
1. **Critical**: Multi-agent system leaking confidential data
2. **Critical**: Health checks failing for >10 minutes
3. **Critical**: Database connection failures
4. **High**: >20% error rate on API endpoints
5. **High**: Storage volumes not mounting correctly

## Rollback Levels

### Level 1: Quick Container Restart (Fastest)

Used for: Minor issues, temporary glitches

```bash
# Restart specific service
docker compose -f docker-compose.production.yml restart backend

# Or restart all
docker compose -f docker-compose.production.yml restart
```

**Downtime**: ~30 seconds

---

### Level 2: Restore Previous Image

Used for: Code bugs introduced in latest build

```bash
# List available images
docker images | grep sowknow

# Tag previous working image (example: using last known good)
docker tag sowknow4/backend:previous sowknow4/backend:latest

# Restart backend
docker compose -f docker-compose.production.yml up -d backend
```

**Downtime**: ~2-3 minutes

---

### Level 3: Restore Database

Used for: Migration failures, data corruption

```bash
# STOP services first (prevent new writes)
docker compose -f docker-compose.production.yml down

# List available backups
ls -la backups/

# Restore from backup (choose recent backup)
TIMESTAMP="20260215_120000"  # Example
docker exec -i sowknow-postgres psql -U sowknow sowknow < \
  backups/sowknow_db_$TIMESTAMP.sql

# Restart services
docker compose -f docker-compose.production.yml up -d
```

**Downtime**: ~10-15 minutes

---

### Level 4: Full System Restore

Used for: Catastrophic failure, wrong configuration

```bash
# 1. Stop all services
docker compose -f docker-compose.production.yml down

# 2. Remove volumes (WARNING: Deletes ALL data)
docker compose -f docker-compose.production.yml down -v

# 3. Restore configuration from backup
TIMESTAMP="20260215_120000"
cp backend/.env.production.backup.$TIMESTAMP backend/.env.production
cp -r nginx.backup.$TIMESTAMP nginx

# 4. Restore database from backup
docker compose -f docker-compose.production.yml up -d postgres
sleep 30
docker exec -i sowknow-postgres psql -U sowknow sowknow < \
  backups/sowknow_db_$TIMESTAMP.sql

# 5. Start all services
docker compose -f docker-compose.production.yml up -d
```

**Downtime**: ~30 minutes

## Emergency Contacts

| Role | Contact | Phone |
|------|---------|-------|
| Dev Lead | | |
| DBA | | |
| Ops | | |

## Post-Rollback Actions

1. **Document incident**: What went wrong?
2. **Notify stakeholders**: Email/chat about downtime
3. **Fix root cause**: Don't deploy broken code again
4. **Test thoroughly**: Verify fix before next deployment
5. **Update runbook**: Add this issue to troubleshooting guide

## Quick Reference Commands

```bash
# Check current status
docker compose -f docker-compose.production.yml ps

# View recent errors
docker logs sowknow-backend --tail 100

# Health check
curl http://localhost:8000/health

# Restore configuration
ls backups/*.sql

# Restart everything
docker compose -f docker-compose.production.yml down && \
  docker compose -f docker-compose.production.yml up -d
```
