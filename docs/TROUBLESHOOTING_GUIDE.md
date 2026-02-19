# SOWKNOW Troubleshooting Guide

## Common Issues and Solutions

### Authentication & Authorization

#### Issue: JWT Token Expiration

**Symptoms**: 
- `401 Unauthorized` after ~30 minutes
- Login required repeatedly

**Diagnosis**:
```bash
# Check token expiry in response
curl -X POST http://localhost/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"user@test.com","password":"test123"}' | jq .
```

**Solution**:
1. Refresh tokens are stored in httpOnly cookies
2. Check browser dev tools → Application → Cookies
3. Ensure `JWT_SECRET` is consistent across restarts

---

#### Issue: User Cannot See Confidential Documents

**Symptoms**: 
- Admin/SuperUser queries return no results for confidential docs

**Diagnosis**:
```bash
# Check user role in database
docker exec sowknow-postgres psql -U sowknow -d sowknow -c \
  "SELECT id, email, role FROM users WHERE email='admin@test.com';"
```

**Solution**:
1. Verify user role is set to `ADMIN` or `SUPERUSER`
2. Check document bucket is `confidential`
3. Verify user has `can_access_confidential=true`

---

### Document Processing

#### Issue: Uploaded Documents Not Appearing

**Symptoms**: 
- File uploads succeed but documents don't appear

**Diagnosis**:
```bash
# Check processing queue
docker exec sowknow-redis redis-cli LLEN celery

# Check Celery worker logs
docker logs sowknow-celery-worker --tail 50
```

**Solution**:
1. Check Redis queue has pending tasks
2. Verify Celery worker is running
3. Check for processing errors in logs

---

#### Issue: OCR Not Processing PDFs

**Symptoms**: 
- PDF content shows "Extraction pending"

**Diagnosis**:
```bash
# Check Hunyuan API configuration
docker exec sowknow-backend env | grep HUNYUAN

# Check processing status
curl http://localhost:8000/api/v1/documents | jq '.'
```

**Solution**:
1. Verify `HUNYUAN_API_KEY` and `HUNYUAN_SECRET_ID` are set
2. Check Hunyuan API credits
3. Fallback: Ensure Tesseract is available

---

### AI Services

#### Issue: Chat Returns "Service Unavailable"

**Symptoms**:
- Chat endpoint returns 503 error

**Diagnosis**:
```bash
# Check which LLM service is failing
docker logs sowknow-backend --tail 100 | grep -i "error\|exception"

# Test Ollama connectivity
curl http://host.docker.internal:11434/api/tags
```

**Solution**:
1. If Ollama unavailable: Check Docker extra_hosts configuration
2. If OpenRouter unavailable: Check API key and network
3. If Gemini unavailable: Check API key and quota

---

#### Issue: High API Costs

**Symptoms**: 
- Daily Gemini/OpenRouter costs exceed budget

**Diagnosis**:
```bash
# Check cost tracking
curl http://localhost:8000/api/v1/monitoring/costs | jq .

# Check cache hit rate
curl http://localhost:8000/api/v1/monitoring/system | jq '.cache'
```

**Solution**:
1. Enable stricter caching in configuration
2. Reduce `max_tokens` limits
3. Implement stricter PII detection (more queries → Ollama)

---

#### Issue: Minimax Context Window Exceeded

**Symptoms**:
- Responses truncated or incomplete

**Diagnosis**:
```bash
# Check logs for truncation warnings
docker logs sowknow-backend --tail 100 | grep -i "truncat\|limit\|context"
```

**Solution**:
1. Implement token counting before API calls
2. Reduce chunk size for document retrieval
3. Use summarization for large documents

---

### Database & Storage

#### Issue: Database Connection Failures

**Symptoms**:
- `Connection refused` to PostgreSQL
- Health check shows database unhealthy

**Diagnosis**:
```bash
# Test PostgreSQL directly
docker exec sowknow-postgres pg_isready -U sowknow

# Check connection string
docker exec sowknow-backend env | grep DATABASE
```

**Solution**:
1. Wait for PostgreSQL to fully start (health check)
2. Verify DATABASE_URL format
3. Check PostgreSQL logs: `docker logs sowknow-postgres`

---

#### Issue: File Not Found on Download

**Symptoms**:
- 404 when downloading previously uploaded file

**Diagnosis**:
```bash
# Check volume mounts
docker inspect sowknow-backend | jq '.[0].Mounts'

# Check file exists in volume
docker exec sowknow-backend ls -la /data/public/
docker exec sowknow-backend ls -la /data/confidential/
```

**Solution**:
1. Verify production volume mounts in docker-compose
2. Check `public_data` and `confidential_data` volumes exist
3. Restore from backup if file was deleted

---

### Docker & Deployment

#### Issue: Container Out of Memory

**Symptoms**:
- OOMKilled errors in `docker logs`
- Containers restarting unexpectedly

**Diagnosis**:
```bash
# Check memory usage
docker stats --no-stream

# Check container limits
docker inspect sowknow-backend | jq '.[0].HostConfig.Memory'
```

**Solution**:
1. Review memory limits in docker-compose
2. Target: Total SOWKNOW containers ≤ 6.4GB
3. Reduce Celery concurrency if needed

---

#### Issue: Nginx 502 Bad Gateway

**Symptoms**:
- 502 errors when accessing application

**Diagnosis**:
```bash
# Check nginx logs
docker logs sowknow4-nginx --tail 50

# Check backend health
curl http://localhost:8000/health
```

**Solution**:
1. Restart backend: `docker-compose restart backend`
2. Check backend is listening on correct port
3. Verify nginx proxy configuration

---

#### Issue: SSL Certificate Errors

**Symptoms**:
- Certificate expired or invalid

**Diagnosis**:
```bash
# Check certificate expiry
openssl s_client -connect sowknow.gollamtech.com:443 \
  -servername sowknow.gollamtech.com < /dev/null | grep -i "notAfter"

# Check certbot logs
docker logs sowknow-certbot --tail 20
```

**Solution**:
```bash
# Renew certificate
./scripts/setup-ssl-auto.sh
```

---

### LLM Routing Issues

#### Issue: Confidential Docs Sent to Gemini (CRITICAL)

**Symptoms**:
- Admin/SuperUser queries with confidential docs go to Gemini
- PII detected but still uses cloud API

**Diagnosis**:
```bash
# Check routing logs
docker logs sowknow-backend 2>&1 | grep -i "routing"

# Check which provider was used
docker logs sowknow-backend 2>&1 | grep -i "gemini\|ollama\|openrouter"
```

**Solution**:
1. **IMMEDIATE**: Disable multi-agent system for Admin/SuperUser
2. Fix routing in: `chat_service.py`, `collection_chat_service.py`
3. Add routing to all agent services (see Agent 3 findings)

---

#### Issue: Multi-Agent System Leaking Data

**Symptoms**:
- Multi-agent search sends content to Gemini

**Affected Files** (per Agent 3):
- `researcher_agent.py` - lines 256, 353
- `answer_agent.py` - lines 161, 289, 316, 404
- `verification_agent.py` - lines 189, 249, 367
- `clarification_agent.py` - line 121

**Solution**:
1. Add confidential check before Gemini calls
2. Route to Ollama when `has_confidential=True`
3. Apply to all Phase 3 agents

---

### Search & Vector Store

#### Issue: Search Returns No Results

**Symptoms**:
- Queries return empty results despite documents existing

**Diagnosis**:
```bash
# Check vector store
curl http://localhost:8000/api/v1/documents | jq 'length'

# Test embedding service
docker exec sowknow-backend python -c \
  "from app.services.embedding_service import embedding_service; \
   print(embedding_service.encode('test'))"
```

**Solution**:
1. Verify documents are embedded (check status)
2. Check embedding model is loaded
3. Verify pgvector extension is installed

---

## Health Check Commands

### Run All Health Checks

```bash
# Basic health
curl http://localhost:8000/health | jq .

# Detailed health
curl http://localhost:8000/api/v1/health/detailed | jq .

# System monitoring
curl http://localhost:8000/api/v1/monitoring/system | jq .

# Cost tracking
curl http://localhost:8000/api/v1/monitoring/costs | jq .

# Queue status
curl http://localhost:8000/api/v1/monitoring/queue | jq .

# Service status
docker compose ps
```

## Log Locations

| Service | Command |
|---------|---------|
| Backend | `docker logs sowknow-backend --tail 100 -f` |
| Celery | `docker logs sowknow-celery-worker --tail 100 -f` |
| Nginx | `docker logs sowknow4-nginx --tail 100 -f` |
| PostgreSQL | `docker logs sowknow-postgres --tail 100 -f` |
| Redis | `docker logs sowknow-redis --tail 100 -f` |

## Emergency Contacts

For critical issues:
1. Check container status: `docker compose ps`
2. Review recent logs: `docker compose logs --tail=50`
3. Rollback if needed: See ROLLBACK_PLAN.md
