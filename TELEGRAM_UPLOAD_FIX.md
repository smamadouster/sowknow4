# Telegram Bot Upload Fix

## Problem
The Telegram bot upload function was hanging indefinitely when users tried to upload documents.

## Root Cause
The `BACKEND_URL` environment variable was not explicitly set in the docker-compose files. While the bot code had a default value of `http://backend:8000`, the environment variable configuration was missing or inconsistent between services.

## Fix Applied

### 1. Updated `docker-compose.yml`
Added explicit `BACKEND_URL` environment variable to the telegram-bot service:
```yaml
environment:
  - DATABASE_URL=postgresql://${DATABASE_USER:-sowknow}:${DATABASE_PASSWORD:?DATABASE_PASSWORD must be set in .env}@postgres:5432/${DATABASE_NAME:-sowknow}
  - TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN:?TELEGRAM_BOT_TOKEN must be set}
  - BOT_API_KEY=${BOT_API_KEY:-}
  - BACKEND_URL=http://backend:8000  # <-- ADDED THIS
```

### 2. Updated `docker-compose.production.yml`
Same fix applied to production configuration:
```yaml
environment:
  - BACKEND_URL=http://backend:8000  # <-- ADDED THIS
```

### 3. Added Diagnostic Script
Created `backend/telegram_bot/diagnostic.py` to help troubleshoot connectivity issues.

### 4. Enhanced Logging
Added detailed logging to the upload function in `bot.py`:
- Log upload attempts with file size
- Log backend URL being used
- Log response status codes

## How to Apply the Fix

### Step 1: Rebuild and Recreate Containers
**Important:** Environment variables only take effect when containers are recreated (not just restarted).

```bash
cd /root/development/src/active/sowknow4

# Stop existing containers
docker-compose down

# Rebuild the telegram-bot image (to include new logging)
docker-compose build telegram-bot

# Start all containers
docker-compose up -d
```

### Step 2: Verify the Fix

#### Check Container Status
```bash
docker-compose ps
```
All containers should show "healthy" status.

#### Check Backend is Reachable
```bash
# Test from the telegram-bot container
docker exec sowknow4-telegram-bot python telegram_bot/diagnostic.py
```

Expected output:
```
============================================================
Telegram Bot Connectivity Diagnostics
============================================================
BACKEND_URL: http://backend:8000

Testing DNS resolution for backend...
  Hostname: backend
  Port: 8000
  DNS Resolution: SUCCESS
    - ('172.20.0.x', 8000)

Testing connection to backend at http://backend:8000...
  Status Code: 200
  Response: {"status":"healthy","timestamp":"..."}
  Connection: SUCCESS

============================================================
All tests PASSED - Bot should be able to connect to backend
============================================================
```

#### Test Upload via Telegram
1. Open Telegram and find your bot
2. Send `/start` to authenticate
3. Send a small test file (PDF, image, etc.)
4. Select "Public" or "Confidential"
5. The upload should complete within a few seconds

### Step 3: Monitor Logs

If upload still hangs, check the logs:

```bash
# Watch bot logs in real-time
docker logs -f sowknow4-telegram-bot

# Watch backend logs
docker logs -f sowknow4-backend
```

Look for these log messages in the bot:
```
Uploading document: filename.pdf (12345 bytes) to bucket: public
Backend URL: http://backend:8000/api/v1/documents/upload
Upload response status: 200
```

## Additional Troubleshooting

### If DNS Resolution Fails
Check that both services are on the same network:
```bash
docker network inspect sowknow-net
```

Both `sowknow4-backend` and `sowknow4-telegram-bot` should be listed as containers.

### If Connection Times Out
1. Check if backend is healthy:
   ```bash
   docker ps | grep backend
   ```

2. Check backend logs for errors:
   ```bash
   docker logs sowknow4-backend | tail -50
   ```

3. Verify backend is listening on port 8000:
   ```bash
   docker exec sowknow4-backend netstat -tlnp | grep 8000
   ```

### If Upload Returns 401/403 Error
The BOT_API_KEY might not be set correctly:

1. Check `.env` file has BOT_API_KEY:
   ```bash
   grep BOT_API_KEY .env
   ```

2. Verify the key is loaded in the container:
   ```bash
   docker exec sowknow4-telegram-bot env | grep BOT
   ```

### Large File Uploads
The default timeout is 60 seconds. For large files:
- The backend has a 100MB file size limit
- The bot client has a 60-second timeout
- Both can be adjusted in the configuration if needed

## Verification Checklist

- [ ] `docker-compose.yml` has `BACKEND_URL=http://backend:8000`
- [ ] Containers were recreated (not just restarted)
- [ ] Both services are on `sowknow-net` network
- [ ] Backend health check returns 200 OK
- [ ] Bot can resolve `backend` hostname
- [ ] Test upload completes successfully
- [ ] Document appears in database/backend storage

## Technical Details

### Docker Networking
- Service name `backend` becomes the hostname in Docker DNS
- Both services must be on the same network (`sowknow-net`)
- Container names don't matter for DNS, service names do

### Authentication Flow
1. User sends `/start` → Bot authenticates via `/api/v1/auth/telegram`
2. Bot receives access_token from backend
3. User uploads file → Bot sends to `/api/v1/documents/upload`
4. Bot includes: `Authorization: Bearer <token>` and `X-Bot-Api-Key: <key>`
5. Backend validates and processes the upload

### Required Environment Variables
```bash
# For telegram-bot service
TELEGRAM_BOT_TOKEN=your_bot_token_from_botfather
BOT_API_KEY=your_secure_random_key
BACKEND_URL=http://backend:8000

# For backend service
BOT_API_KEY=must_match_telegram_bot_value
```
