# Database Password Change Guide

## Overview

This guide explains how to securely change the SOWKNOW database password in production.

## Why Change Your Database Password?

- **Security**: Regular password rotation prevents unauthorized access
- **Compliance**: Best practice for credential management
- **Breach Response**: Quick response if credentials are compromised

## Production Password Change Procedure

### Step 1: Generate Secure Password

Use a strong password generator or create one manually:

```bash
# Option 1: Use openssl
openssl rand -base64 32

# Option 2: Use Python
python3 -c "import secrets; print(secrets.token_urlsafe(32))"

# Option 3: Use pwgen
pwgen -s 32
```

**Password Requirements:**
- Minimum 16 characters
- At least 3 of: uppercase, lowercase, numbers, special characters
- Not based on dictionary words

### Step 2: Update Application Configuration

```bash
# SSH into production server
ssh root@72.62.17.136

# Navigate to project
cd /root/sowknow4

# Create new environment file (keep old as backup)
cp .env.production .env.production.backup
```

Edit `.env.production` and update the `DATABASE_PASSWORD`:

```bash
# Replace with new secure password
DATABASE_PASSWORD=your_new_secure_password_here_minimum_32_characters
```

### Step 3: Apply Database Password Change

**Option A: Change Password in Running Container** (Zero Downtime)

```bash
# Connect to PostgreSQL
docker exec -it sowknow4-postgres psql -U sowknow

# Alter password
ALTER USER sowknow WITH PASSWORD 'new_secure_password';

# Exit
\q

# Verify - login with new password
docker exec -it sowknow4-postgres psql -U sowknow -c "\conninfo"
```

**Option B: Recreate Container** (Brief Downtime)

```bash
# Stop all services
docker compose down

# Update environment with new password
docker compose --env-file .env.production up -d
```

### Step 4: Verify Change

```bash
# Test database connection
docker exec sowknow4-postgres pg_isready -U sowknow

# Check application logs
docker compose logs backend | grep -i "database\|connection"

# Verify health endpoint
curl http://localhost:8000/health | jq .
```

### Step 5: Update Application Secrets

If your application caches database connections, you may need to restart:

```bash
# Restart backend to pick up new password
docker compose restart backend
```

## Container-Specific Instructions

### Backend (FastAPI)

The backend uses SQLAlchemy connection pooling. After password change:

1. Connections will automatically use the new password
2. No code changes required
3. Verify with health check:
```bash
curl http://localhost:8000/health | jq '.services.database'
# Should return: "connected"
```

### Celery Workers

Celery workers maintain persistent database connections. After password change:

```bash
# Restart celery workers
docker compose restart celery-worker celery-beat
```

### PostgreSQL Details

The PostgreSQL container has the following defaults:

| Setting | Value |
|----------|-------|
| Database | sowknow |
| User | sowknow |
| Password | From DATABASE_PASSWORD env var |
| Encoding | UTF8 |
| Locale | en_US.UTF-8 |

## Rollback Procedure

If the new password causes issues:

```bash
# Restore from backup
cp .env.production.backup .env.production
docker compose down
docker compose --env-file .env.production up -d
```

## Security Considerations

1. **Never commit passwords to Git**
2. **Use environment variables** - Never hardcode credentials
3. **Rotate regularly** - Every 90 days recommended
4. **Use strong passwords** - Minimum 32 characters with mixed types
5. **Monitor access logs** - Check for unauthorized access attempts

## Troubleshooting

### Connection Failed After Password Change

```bash
# Check PostgreSQL logs
docker logs sowknow4-postgres | grep -i "FATAL\|error\|authentication"

# Verify environment variable
docker exec sowknow4-backend env | grep DATABASE_PASSWORD

# Test connection directly
docker exec -it sowknow4-postgres psql -U sowknow -c "SELECT 1;"
```

### Application Won't Start

```bash
# Check if database is the issue
docker compose logs backend | tail -100

# Verify other services
docker compose ps
```

## Best Practices

1. **Change password during low-traffic periods**
2. **Notify users before scheduled changes**
3. **Document password changes** (securely, not in tickets)
4. **Test in staging environment first**
5. **Keep backup of old credentials** (securely delete after 30 days)
