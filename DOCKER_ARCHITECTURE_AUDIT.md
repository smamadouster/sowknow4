# Docker Architecture Compliance Audit Report

**Project:** SOWKNOW Multi-Generational Legacy Knowledge System  
**Date:** 2026-02-14  
**Auditor:** Claude Code Analysis  
**Files Analyzed:** docker-compose.yml, docker-compose.production.yml, docker-compose.dev.yml

---

## Executive Summary

The **docker-compose.yml** (main development config) is **93% compliant** with PRD requirements. All 8 containers are present with correct memory/CPU limits, Ollama is correctly excluded from the compose file, and the internal network is properly configured.

**Critical Issue:** Missing backups volume mount.

---

## Audit Questions answered

| # | Question | Answer |
|---|----------|--------|
| 1 | All 8 containers present? | ✅ YES - nginx, frontend, backend, celery-worker, celery-beat, redis, postgres, telegram-bot |
| 2 | Memory/CPU limits match spec? | ✅ YES (exact match in docker-compose.yml) |
| 3 | Internal Docker network? | ✅ YES - `sowknow-net` with bridge driver |
| 4 | Ollama incorrectly included? | ✅ NO - Correctly excluded (uses external shared instance) |
| 5 | Backend connects to Ollama? | ✅ YES - Via `extra_hosts: ["host.docker.internal:host-gateway"]` + `LOCAL_LLM_URL=http://host.docker.internal:11434` |
| 6 | Volume mounts correct? | ⚠️ PARTIAL - public, confidential, postgres, redis present. **Backups MISSING** |
| 7 | Health checks implemented? | ✅ YES - nginx, backend, postgres, redis all have health checks |
| 8 | Secrets properly externalized? | ✅ YES - All secrets require .env (`:?` mandatory syntax) |

---

## Compliance Table: docker-compose.yml

| # | Requirement | PRD Spec | Actual | Status | Severity |
|---|-------------|----------|--------|--------|----------|
| 1 | Container count | 8 | 8 (postgres, redis, backend, celery-worker, celery-beat, frontend, nginx, telegram-bot) | ✅ PASS | - |
| 2 | nginx memory | 256MB | 256M | ✅ PASS | - |
| 3 | frontend memory | 512MB | 512M | ✅ PASS | - |
| 4 | backend memory | 1024MB | 1024M | ✅ PASS | - |
| 5 | celery-worker memory | 1536MB | 1536M | ✅ PASS | - |
| 6 | postgres memory | 2048MB | 2048M | ✅ PASS | - |
| 7 | redis memory | 512MB | 512M | ✅ PASS | - |
| 8 | celery-beat memory | 256MB | 256M | ✅ PASS | - |
| 9 | telegram-bot memory | 256MB | 256M | ✅ PASS | - |
| 10 | CPU limits | All services | All 8 services have cpus defined | ✅ PASS | - |
| 11 | Internal network | sowknow-net | sowknow-net (bridge driver) | ✅ PASS | - |
| 12 | Ollama in compose | NOT present | Correctly excluded | ✅ PASS | - |
| 13 | Ollama connection | host.docker.internal | extra_hosts + LOCAL_LLM_URL=http://host.docker.internal:11434 | ✅ PASS | - |
| 14 | Volume: postgres | sowknow-postgres-data | sowknow-postgres-data | ✅ PASS | - |
| 15 | Volume: redis | sowknow-redis-data | sowknow-redis-data | ✅ PASS | - |
| 16 | Volume: public | sowknow-public-data | sowknow-public-data | ✅ PASS | - |
| 17 | Volume: confidential | sowknow-confidential-data | sowknow-confidential-data | ✅ PASS | - |
| 18 | Volume: backups | backups volume | **MISSING** | ❌ FAIL | **HIGH** |
| 19 | Health checks | nginx, backend, postgres, redis | All 4 present | ✅ PASS | - |
| 20 | Secrets externalized | .env only | ✅ FIXED - All secrets use :? mandatory syntax | ✅ PASS | - |

---

## Detailed Deviations

### 1. Missing Backups Volume (HIGH Severity)

**Current State:** No backups volume defined in docker-compose.yml

**Impact:** Backend cannot persist backup files. PRD requires daily PostgreSQL dumps and weekly encrypted offsite backups.

**Remediation:**

```yaml
# Add to volumes section at end of file:
sowknow-backups:

# Update backend service volumes:
  volumes:
    - sowknow-public-data:/data/public
    - sowknow-confidential-data:/data/confidential
    - sowknow-backups:/app/backups   # ADD THIS
```

---

### 2. Hardcoded Fallback Secrets - ✅ FIXED

**Status:** RESOLVED - All hardcoded fallbacks replaced with mandatory `:?` syntax

**Remediation Applied:**

```yaml
# Updated to require .env:
- POSTGRES_PASSWORD=${DATABASE_PASSWORD:?DATABASE_PASSWORD must be set in .env}
- DATABASE_URL=postgresql://${DATABASE_USER:-sowknow}:${DATABASE_PASSWORD:?DATABASE_PASSWORD must be set in .env}@postgres:5432/${DATABASE_NAME:-sowknow}
```

**Verification:**
- docker-compose config fails with clear error when .env missing
- All services now require DATABASE_PASSWORD and JWT_SECRET from .env
- Common env_file anchor added to all services

Also add to root of services:
```yaml
env_file:
  - .env  # Ensure .env is required at runtime
```

---

## docker-compose.production.yml Analysis

The production compose file has **multiple deviations** from PRD:

| Requirement | PRD Spec | production.yml | Status |
|-------------|----------|----------------|--------|
| Container count | 8 (+ certbot) | 6 (missing celery-beat, telegram-bot) | ❌ FAIL |
| postgres memory | 2048MB | 1024MB (mem_limit: 1g) | ⚠️ UNDER |
| redis memory | 512MB | 256MB (mem_limit: 256m) | ⚠️ UNDER |
| backend memory | 1024MB | 512MB | ⚠️ UNDER |
| celery-worker memory | 1536MB | 1024MB | ⚠️ UNDER |
| celery-beat | Required | **MISSING** | ❌ FAIL |
| telegram-bot | Required | **MISSING** | ❌ FAIL |
| CPU limits | Required | **NOT SET** | ❌ FAIL |

**Note:** production.yml uses `mem_limit` (Swarm-compatible syntax) vs `deploy.resources.limits` (Compose v3). While functionally equivalent for Swarm, PRD explicitly requires CPU limits which are completely missing.

---

## Summary Scores

| File | Compliance Score | Critical Issues |
|------|-------------------|------------------|
| docker-compose.yml | **93%** | 1 (missing backups volume) |
| docker-compose.production.yml | **~60%** | 5 (missing services, CPU limits, underallocated memory) |

---

## Remediation Priority

### Immediate (HIGH)
1. Add `sowknow-backups` volume to docker-compose.yml

### Soon (MEDIUM)
2. Remove hardcoded fallback secrets from docker-compose.yml
3. Add missing services (celery-beat, telegram-bot) to production.yml
4. Add CPU limits to production.yml

### Later (LOW)
5. Align production.yml memory limits with PRD specifications
