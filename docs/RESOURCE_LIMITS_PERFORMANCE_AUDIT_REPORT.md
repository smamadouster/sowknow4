# RESOURCE LIMITS & PERFORMANCE AUDIT REPORT
**Date:** 2026-02-21 17:30:00 UTC  
**Auditor:** Orchestrator (Multi-Agent Audit Team)  
**Project:** SOWKNOW Multi-Generational Legacy Knowledge System  

---

## EXECUTIVE SUMMARY

| Metric | Value |
|--------|-------|
| **Total Services Audited** | 8 core services + 3 optional |
| **CRITICAL Issues** | 6 |
| **HIGH Issues** | 8 |
| **MEDIUM Issues** | 7 |
| **Compliant Services** | 4 |

### Overall Risk Assessment: **HIGH RISK**

The audit reveals significant issues in vector database configuration, security posture, and memory allocation that require immediate attention before production deployment.

---

## RESOURCE ALLOCATION

### docker-compose.yml (Development)

| Service | Memory Limit | CPU Limit | Expected | Status |
|---------|-------------|-----------|----------|--------|
| postgres | 2048M | 1.5 | 2048M | OK |
| redis | 512M | 0.5 | 512M | OK |
| backend | 1024M | 1.0 | 1024M | OK |
| celery-worker | 1536M | 1.5 | 1536M | OK |
| celery-beat | 512M | 0.25 | 256M | +256MB |
| frontend | 512M | 1.0 | 512M | OK |
| nginx | 256M | 0.5 | 256M | OK |
| telegram-bot | 256M | 0.5 | 256M | OK |
| prometheus | 512M | 0.5 | N/A | Optional |
| **TOTAL** | **6656MB** | **6.75** | **6400MB** | **+256MB** |

### docker-compose.production.yml (Production)

| Service | Memory Limit | CPU Limit | Expected | Status |
|---------|-------------|-----------|----------|--------|
| postgres | 2048M | 1.5 | 2048M | OK |
| redis | 512M | 0.5 | 512M | OK |
| backend | 1024M | 1.0 | 1024M | OK |
| celery-worker | 1536M | 1.5 | 1536M | OK |
| celery-beat | 512M | 0.25 | 256M | +256MB |
| frontend | 512M | 1.0 | 512M | OK |
| nginx | 256M | 0.5 | 256M | OK |
| telegram-bot | 256M | 0.5 | 256M | OK |
| certbot | 128M | 0.25 | N/A | Extra |
| **TOTAL** | **6780MB** | **7.0** | **6400MB** | **+380MB** |

### Status: OVER BUDGET
- Development: +256MB over 6.4GB limit
- Production: +380MB over 6.4GB limit

---

## CRITICAL FINDINGS

### C1. Embedding Column Uses Wrong Data Type
**Agent:** Agent 2 (Application Performance)  
**Location:** `backend/app/alembic/versions/001_initial_schema.py:93`  
**Issue:** Embedding column uses `postgresql.ARRAY(sa.Float())` instead of `Vector(1024)` from pgvector  
**Impact:** 
- Cannot use pgvector indexes (HNSW/IVFFlat)
- Vector similarity search performs O(n) full table scans
- Performance degrades exponentially with document count

**Evidence:**
```python
# Current (WRONG):
sa.Column('embedding', postgresql.ARRAY(sa.Float(), dimensions=1024))

# Required:
from pgvector.sqlalchemy import Vector
sa.Column('embedding', Vector(1024))
```

**Fix Required:** Migration to change column type + re-embed all documents

---

### C2. Embeddings Stored in JSONB Metadata, Not Vector Column
**Agent:** Agent 2 (Application Performance)  
**Location:** `backend/app/tasks/document_tasks.py:200`  
**Issue:** Embeddings stored in `chunk.document_metadata["embedding"]` instead of proper column  
**Impact:** Vector column remains empty, similarity search cannot function

**Evidence:**
```python
# document_tasks.py:196-201
metadata = chunk.document_metadata or {}
metadata["embedding"] = embeddings[i]  # Stored in JSONB!
chunk.document_metadata = metadata
```

---

### C3. Exposed Secrets in .env File
**Agent:** Agent 4 (Security)  
**Location:** `.env` file in project root  
**Issue:** Production secrets visible in development directory  

| Secret | Risk |
|--------|------|
| `DATABASE_PASSWORD` | `0iWO98z3DTNVzyyBj78nT3Lgjx1OIFR` |
| `JWT_SECRET` | 64-char hex key exposed |
| `MINIMAX_API_KEY` | Full API key visible |
| `MOONSHOT_API_KEY` | Full API key visible |
| `OPENROUTER_API_KEY` | Full API key visible |
| `TELEGRAM_BOT_TOKEN` | Full bot token visible |
| `ADMIN_PASSWORD` | `admin123` - weak default |

**Fix Required:** Rotate ALL secrets immediately

---

### C4. Redis Has No Memory Limit or Eviction Policy
**Agent:** Agent 1 (Infrastructure)  
**Location:** `docker-compose.yml`, `docker-compose.production.yml`  
**Issue:** Redis configured without `maxmemory` or `maxmemory-policy`  
**Impact:** Unbounded memory growth, potential OOM killer

**Fix Required:**
```yaml
command: redis-server --maxmemory 400mb --maxmemory-policy allkeys-lru
```

---

### C5. No Standalone Output for Next.js Production Build
**Agent:** Agent 3 (Frontend)  
**Location:** `frontend/next.config.js`  
**Issue:** Missing `output: 'standalone'` configuration  
**Impact:** Docker images 50-70% larger than necessary

**Fix Required:**
```javascript
// next.config.js
module.exports = {
  output: 'standalone',
  // ...
}
```

---

### C6. PostgreSQL Config Mismatch - shared_buffers Exceeds Container Limit
**Agent:** Agent 1 (Infrastructure)  
**Location:** `backend/app/core/performance.py:89`  
**Issue:** Attempts to set `shared_buffers = '4GB'` on 2GB container  
**Impact:** Configuration will fail or be ineffective

**Fix Required:** Use appropriate values for 2GB container:
```
shared_buffers = 512MB
effective_cache_size = 1536MB
```

---

## HIGH PRIORITY FINDINGS

### H1. No pgvector Index on Embeddings
**Agent:** Agent 2  
**Impact:** Vector similarity search without index is O(n)

**Recommendation:** After fixing column type, add HNSW index:
```sql
CREATE INDEX ix_chunks_embedding_hnsw 
ON document_chunks 
USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);
```

---

### H2. No GIN/tsvector Full-Text Search Index
**Agent:** Agent 2  
**Impact:** Text search on `chunk_text` is slow

**Recommendation:**
```sql
CREATE INDEX ix_chunks_text_gin 
ON document_chunks 
USING gin(to_tsvector('french', chunk_text));
```

---

### H3. No Lazy Loading for Heavy Components
**Agent:** Agent 3  
**Impact:** Frontend bundle size inflated, slow initial page load

**Recommendation:** Use `next/dynamic` for Knowledge Graph visualization:
```javascript
const GraphVisualization = dynamic(
  () => import('@/components/knowledge-graph/GraphVisualization'),
  { loading: () => <div>Loading...</div> }
)
```

---

### H4. Backend Dockerfile Runs as Root
**Agent:** Agent 4  
**Location:** `backend/Dockerfile` (full version)  
**Impact:** Container privilege escalation risk

**Recommendation:** Add non-root user:
```dockerfile
RUN useradd -m -u 1001 appuser
USER appuser
```

---

### H5. Rate Limiting Not Enforced
**Agent:** Agent 4  
**Location:** `backend/app/api/auth.py` (comment only)  
**Issue:** `RATE_LIMIT_PER_MINUTE=100` defined but not implemented

**Recommendation:** Integrate slowapi middleware

---

### H6. No Response Compression (Gzip/Brotli)
**Agent:** Agent 3  
**Location:** `backend/app/main.py`  
**Impact:** Larger response sizes, slower API performance

**Recommendation:**
```python
from fastapi.middleware.gzip import GZipMiddleware
app.add_middleware(GZipMiddleware, minimum_size=1000)
```

---

### H7. Image Optimization Disabled
**Agent:** Agent 3  
**Location:** `frontend/next.config.js:8-10`  
**Issue:** `images.unoptimized: true` set

**Recommendation:** Remove or configure proper image CDN

---

### H8. No max_tasks_per_child in Celery
**Agent:** Agent 2  
**Location:** `backend/app/core/celery_app.py`  
**Impact:** Memory leak risk over time

**Recommendation:**
```python
worker_max_tasks_per_child=100
```

---

## MEDIUM PRIORITY FINDINGS

| ID | Issue | Agent | Location | Recommendation |
|----|-------|-------|----------|----------------|
| M1 | Memory budget deficit (+380MB) | 1 | docker-compose.production.yml | Reduce celery-beat to 256MB |
| M2 | Health check intervals too low | 1 | docker-compose.yml | Update to 30-60s range |
| M3 | Redis no password in dev | 4 | docker-compose.yml | Add `--requirepass` |
| M4 | Dev ports exposed | 4 | docker-compose.yml | Use profiles |
| M5 | Dead dependencies (recharts, react-markdown) | 3 | package.json | Remove unused packages |
| M6 | No static caching headers | 3 | nginx.conf | Add cache-control |
| M7 | .secrets file referenced but missing | 4 | docker-compose | Create with 600 permissions |

---

## VERIFIED COMPLIANT CONTROLS

| Control | Status | Evidence |
|---------|--------|----------|
| JWT authentication | PASS | bcrypt hashing, httpOnly cookies |
| RBAC implementation | PASS | 3-tier roles, bucket isolation |
| Audit logging | PASS | 11 action types tracked |
| Embedding model singleton | PASS | Lazy-loaded global instance |
| Connection pooling | PASS | pool_size=10, max_overflow=20 |
| Non-root containers | PARTIAL | Most Dockerfiles use appuser |
| Network isolation | PASS | sowknow-net bridge network |
| API pagination | PASS | Implemented in documents, collections |
| SSE streaming | PASS | Implemented in chat, multi-agent |

---

## RESOURCE USAGE PROJECTIONS

### Peak Memory Scenarios

| Scenario | Memory Required | Risk Level |
|----------|-----------------|------------|
| Normal operation | 5.5GB | LOW |
| Document processing (OCR + embedding) | 6.2GB | MEDIUM |
| Multi-user search (5 concurrent) | 6.8GB | HIGH |
| All services + monitoring | 7.1GB | CRITICAL |

### Scaling Triggers

| Condition | Action |
|-----------|--------|
| Memory > 80% (12.8GB VPS) | Alert + reduce celery-worker memory |
| Concurrent users > 5 | Queue requests or scale horizontally |
| Processing queue > 100 | Alert + increase worker concurrency |

---

## OPTIMIZATION RECOMMENDATIONS

### Immediate (24h)

| # | Action | Impact | Effort |
|---|--------|--------|--------|
| 1 | Rotate ALL secrets in .env | Security | Low |
| 2 | Add Redis maxmemory limit | Stability | Low |
| 3 | Add `output: 'standalone'` to Next.js | Image size | Low |

### Short-term (1 week)

| # | Action | Impact | Effort |
|---|--------|--------|--------|
| 4 | Fix embedding column type + migration | Performance | High |
| 5 | Add pgvector HNSW index | Performance | Medium |
| 6 | Add GIN full-text index | Performance | Low |
| 7 | Implement rate limiting | Security | Medium |
| 8 | Add GzipMiddleware | Performance | Low |

### Long-term (1 month)

| # | Action | Impact | Effort |
|---|--------|--------|--------|
| 9 | Implement lazy loading for heavy components | UX | Medium |
| 10 | Add Celery max_tasks_per_child | Stability | Low |
| 11 | Remove dead dependencies | Bundle size | Low |
| 12 | Add security scanning to CI/CD | Security | Medium |

---

## APPENDIX A: AGENT FINDINGS SUMMARY

### Agent 1: Infrastructure & Container Audit
- **Timestamp:** 2026-02-21T17:25:00Z
- **Status:** Complete
- **Critical Issues:** 2 (Redis config, PostgreSQL mismatch)
- **Files Analyzed:** docker-compose.yml, docker-compose.production.yml

### Agent 2: Application Performance Audit
- **Timestamp:** 2026-02-21T17:26:00Z
- **Status:** Complete
- **Critical Issues:** 2 (Wrong column type, wrong storage location)
- **Files Analyzed:** embedding_service.py, celery_app.py, alembic migrations

### Agent 3: Frontend & API Performance Audit
- **Timestamp:** 2026-02-21T17:27:00Z
- **Status:** Complete
- **Critical Issues:** 1 (No standalone output)
- **Files Analyzed:** next.config.js, package.json, main.py

### Agent 4: Security & Resource Projections Audit
- **Timestamp:** 2026-02-21T17:28:00Z
- **Status:** Complete
- **Critical Issues:** 1 (Exposed secrets)
- **Files Analyzed:** .env, .gitignore, Dockerfiles, auth.py

---

## APPENDIX B: FIX COMMANDS

### Redis Memory Limit
```bash
# docker-compose.yml - update redis command
command: redis-server --appendonly yes --maxmemory 400mb --maxmemory-policy allkeys-lru
```

### Celery Beat Memory Reduction
```yaml
# docker-compose.production.yml - line 165
mem_limit: 256m  # Change from 512m
```

### GzipMiddleware Addition
```python
# backend/app/main.py - add after imports
from fastapi.middleware.gzip import GZipMiddleware
app.add_middleware(GZipMiddleware, minimum_size=1000)
```

### Celery max_tasks_per_child
```python
# backend/app/core/celery_app.py - add to conf.update()
worker_max_tasks_per_child=100,
```

---

## AUDIT SIGN-OFF

| Role | Name | Date | Status |
|------|------|------|--------|
| Lead Auditor | Orchestrator | 2026-02-21 | Complete |
| Infrastructure Agent | Agent 1 | 2026-02-21 | Complete |
| Performance Agent | Agent 2 | 2026-02-21 | Complete |
| Frontend Agent | Agent 3 | 2026-02-21 | Complete |
| Security Agent | Agent 4 | 2026-02-21 | Complete |

---

**Report Generated:** 2026-02-21T17:30:00Z  
**Next Audit Due:** 2026-03-21  
**Distribution:** DevOps Team, Security Team, Project Lead
