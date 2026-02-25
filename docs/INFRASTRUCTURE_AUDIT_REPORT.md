# SOWKNOW Infrastructure Security Audit Report

**Date:** 2026-02-21T00:00:00Z  
**Lead:** Senior App Development Auditor  
**Scope:** Docker Configuration & Environment Security

---

## Executive Summary

| Metric | Value |
|--------|-------|
| **Critical Findings** | 8 |
| **High Risk Findings** | 6 |
| **Medium Risk Findings** | 5 |
| **Overall Risk Level** | 🔴 HIGH |
| **Ready for Production** | ❌ NO |

### Immediate Action Items

1. **ROTATE ALL API KEYS** exposed in .env.example files
2. **Fix memory budget** - exceeds 6.4GB VPS limit by 225MB
3. **Remove hardcoded fallback secrets** in production config
4. **Add Redis authentication** to docker-compose.yml
5. **Remove exposed database ports** from all compose files

---

## Part 1: Docker Configuration Audit

### 1.1 Critical Issues

| ID | Issue | Location | Impact | Fix |
|----|-------|----------|--------|-----|
| D-CRIT-1 | Memory budget exceeded (6.625GB > 6.4GB) | docker-compose.production.yml | OOM crashes on VPS | Reduce celery-worker to 1.25GB |
| D-CRIT-2 | PostgreSQL port exposed to host | docker-compose.yml:38, dev/simple | Direct DB access | Remove port mappings |
| D-CRIT-3 | Redis without authentication | docker-compose.yml, dev/simple | Unauthenticated access | Add --requirepass |
| D-CRIT-4 | Redis port exposed to host | docker-compose.yml:58 | Cache hijacking | Remove port mapping |

### 1.2 Warnings

| ID | Issue | Location | Recommendation |
|----|-------|----------|----------------|
| D-WARN-1 | `:latest` image tags | prometheus, certbot | Pin to specific versions |
| D-WARN-2 | Missing resource limits | simple, dev compose | Add memory/CPU limits |
| D-WARN-3 | Missing health checks | docker-compose.simple.yml | Add comprehensive health checks |
| D-WARN-4 | chmod 777 in Dockerfile | Dockerfile.minimal:40 | Use proper volume permissions |
| D-WARN-5 | Hardcoded DNS in Dockerfiles | All backend Dockerfiles | Use docker-compose DNS config |

### 1.3 Memory Allocation Analysis

| Service | Allocation | Safe? |
|---------|------------|-------|
| postgres | 2GB | ✅ |
| redis | 512MB | ✅ |
| backend | 1GB | ✅ |
| celery-worker | 1.5GB | ⚠️ Reduce to 1.25GB |
| celery-beat | 512MB | ✅ |
| frontend | 512MB | ✅ |
| nginx | 256MB | ✅ |
| telegram-bot | 256MB | ✅ |
| certbot | 128MB | ✅ |
| **TOTAL** | **6.625GB** | ❌ **OVER BUDGET** |

**Required Fix:** Reduce total by 225MB minimum.

### 1.4 Service Readiness Assessment

| Service | Health Check | Resource Limits | Non-root User | Network Isolated |
|---------|--------------|-----------------|---------------|------------------|
| postgres | ✅ | ✅ | ✅ | ⚠️ (port exposed) |
| redis | ✅ | ✅ | ✅ | ⚠️ (port exposed, no auth) |
| backend | ✅ | ✅ | ✅ | ✅ |
| celery-worker | ✅ | ✅ | ✅ | ✅ |
| celery-beat | ✅ | ✅ | ✅ | ✅ |
| frontend | ✅ | ✅ | ❌ | ✅ |
| nginx | ✅ | ✅ | ✅ | ✅ |
| telegram-bot | ✅ | ✅ | ✅ | ✅ |

---

## Part 2: Environment Security Audit

### 2.1 Critical Security Issues

| ID | Issue | Location | Severity |
|----|-------|----------|----------|
| E-CRIT-1 | Real API keys in .env.example | .env.example, backend/.env.example | 🔴 CRITICAL |
| E-CRIT-2 | Multiple Telegram bot tokens | All env files | 🔴 CRITICAL |
| E-CRIT-3 | Hardcoded fallback JWT secrets | backend/.env.production:52-53 | 🔴 CRITICAL |
| E-CRIT-4 | Weak encryption key (pattern-based) | backend/.env.production:30 | 🔴 CRITICAL |

### 2.2 Exposed Secrets Requiring Immediate Rotation

| Secret Type | Files Exposed | Action |
|-------------|---------------|--------|
| Moonshot/Kimi API Key | .env, .env.example, .env.new, backend/.env.example | 🚨 ROTATE NOW |
| Hunyuan API Key | .env.example, .env.new, backend/.env.example | 🚨 ROTATE NOW |
| Telegram Bot Token (v1) | .env, backend/.env.production | 🚨 REVOKE |
| Telegram Bot Token (v2) | .env.example, .env.new | 🚨 REVOKE |
| BOT_API_KEY | .env, backend/.env.production | 🔄 Rotate |
| JWT Secret | All files (inconsistent) | 🔄 Rotate |
| Encryption Key | backend/.env.production | 🔄 Regenerate |
| Database Password | All files (inconsistent) | 🔄 Rotate |
| Redis Password | .env, backend/.env.production | 🔄 Rotate |

### 2.3 High Risk Findings

| ID | Issue | Impact |
|----|-------|--------|
| E-HIGH-1 | Weak admin passwords (admin123, Admin123!) | Brute-force vulnerable |
| E-HIGH-2 | DB password in URL encoding | Visible in connection string |
| E-HIGH-3 | Redis password in multiple URLs | Cache/session hijacking |
| E-HIGH-4 | Inconsistent JWT secrets across files | Auth confusion |

### 2.4 Missing Critical Variables in .env.example

| Variable | Required For |
|----------|--------------|
| REDIS_PASSWORD | Redis authentication |
| MINIMAX_API_KEY | MiniMax LLM integration |
| MINIMAX_MODEL | Model selection |
| OLLAMA_BASE_URL | Ollama integration |
| COOKIE_DOMAIN | Session management |
| EMBEDDING_MODEL | Document embeddings |
| EMBEDDING_DIMENSIONS | Vector dimensions |
| CHUNK_SIZE | Document processing |
| CHUNK_OVERLAP | Document processing |
| GPG_BACKUP_RECIPIENT | Backup encryption |

### 2.5 Security Risk Matrix

| Category | Severity | Exploitability | Impact | Priority |
|----------|----------|----------------|--------|----------|
| Real API keys in examples | CRITICAL | HIGH | Financial loss | P0 |
| Hardcoded fallback secrets | CRITICAL | MEDIUM | Auth bypass | P0 |
| Weak encryption key | CRITICAL | HIGH | Data decryption | P0 |
| Multiple bot tokens | CRITICAL | HIGH | Bot hijacking | P0 |
| Weak admin passwords | HIGH | HIGH | Admin takeover | P1 |
| Exposed DB credentials | HIGH | MEDIUM | Full DB access | P1 |
| Redis auth missing | HIGH | MEDIUM | Cache poisoning | P1 |
| Memory budget exceeded | HIGH | HIGH | Service crash | P1 |

---

## Part 3: Cross-Validation Findings

### 3.1 Consistent Findings (Both Agents)

| Issue | Agent A | Agent B | Confirmed |
|-------|---------|---------|-----------|
| Redis authentication missing | ✅ | ✅ | 🔴 YES |
| Secrets in config files | ✅ | ✅ | 🔴 YES |
| Resource constraints needed | ✅ | - | 🔴 YES |
| Environment variable security | - | ✅ | 🔴 YES |

### 3.2 Configuration Parity Issues

| Config | Production | Development | Simple | Parity Issue |
|--------|------------|-------------|--------|--------------|
| Redis auth | ❌ None | ❌ None | ❌ None | Consistent but INSECURE |
| Memory limits | ✅ Present | ❌ Missing | ❌ Missing | Inconsistent |
| Health checks | ✅ Present | ✅ Partial | ❌ Missing | Inconsistent |
| Port exposure | ✅ Secure | ❌ Exposed | ❌ Exposed | Inconsistent |
| Non-root user | ✅ Backend | ✅ Backend | ✅ Backend | Consistent |

---

## Part 4: Consolidated Recommendations

### Priority 1 - Critical (Fix Immediately)

| # | Action | Files | Effort |
|---|--------|-------|--------|
| 1 | Revoke ALL API keys in .env.example files | All .env* | 30 min |
| 2 | Generate new encryption key with `openssl rand -hex 32` | backend/.env.production | 5 min |
| 3 | Remove hardcoded fallback secrets | backend/.env.production:52-53 | 5 min |
| 4 | Reduce celery-worker memory to 1.25GB | docker-compose.production.yml | 2 min |
| 5 | Add Redis authentication | docker-compose.yml, simple, dev | 10 min |
| 6 | Remove exposed DB/Redis ports | docker-compose.yml, simple, dev | 5 min |

### Priority 2 - Important (Fix This Week)

| # | Action | Files | Effort |
|---|--------|-------|--------|
| 7 | Rotate ALL secrets and keys | All .env files | 1 hour |
| 8 | Fix admin passwords (16+ chars) | All .env files | 10 min |
| 9 | Delete stale .env.new file | .env.new | 1 min |
| 10 | Add missing variables to .env.example | .env.example | 15 min |
| 11 | Add resource limits to dev/simple compose | docker-compose.dev/simple.yml | 15 min |
| 12 | Pin :latest image tags to versions | docker-compose*.yml | 5 min |

### Priority 3 - Nice to Have

| # | Action | Files | Effort |
|---|--------|-------|--------|
| 13 | Implement Docker Secrets for sensitive values | All | 2 hours |
| 14 | Add pre-commit hook for secret detection | .git/hooks | 30 min |
| 15 | Create separate monitoring compose file | docker-compose.monitoring.yml | 30 min |
| 16 | Consolidate Dockerfile variants | Dockerfile* | 2 hours |
| 17 | Fix chmod 777 in Dockerfile.minimal | Dockerfile.minimal:40 | 10 min |

---

## Part 5: Security Scores

| Category | Score | Notes |
|----------|-------|-------|
| Docker Network Isolation | 7/10 | sowknow-net used, but ports exposed |
| Docker Authentication | 5/10 | Redis unauthenticated |
| Docker Resource Management | 6/10 | Limits present but budget exceeded |
| Secret Management | 2/10 | Real secrets in example files |
| Configuration Consistency | 4/10 | Multiple env files with different values |
| Image Security | 7/10 | Mostly pinned, 2 :latest tags |

### Overall Security Score: 5.2/10 🔴

---

## Part 6: Pre-Deployment Checklist

Before deploying to production, complete ALL of the following:

### Environment Security
- [ ] All API keys rotated (Moonshot, Hunyuan, OpenRouter, MiniMax)
- [ ] Telegram bot tokens revoked and new ones created
- [ ] New encryption key generated (32-byte hex)
- [ ] JWT secret regenerated and consistent across all files
- [ ] Database password rotated
- [ ] Redis password configured and rotated
- [ ] Admin password changed to 16+ character random
- [ ] .env.example contains ONLY placeholders
- [ ] Hardcoded fallback secrets removed
- [ ] .env.new deleted

### Docker Configuration
- [ ] Memory budget ≤ 6.4GB total
- [ ] Redis authentication enabled (--requirepass)
- [ ] PostgreSQL port NOT exposed to host
- [ ] Redis port NOT exposed to host
- [ ] All images pinned to specific versions
- [ ] Health checks on all services
- [ ] Resource limits on all services

### Verification
- [ ] `docker-compose config` validates successfully
- [ ] All services start without errors
- [ ] Health checks pass for all services
- [ ] No secrets in `docker inspect` output
- [ ] Redis requires password to connect

---

## Part 7: Quick Fix Commands

```bash
# Generate new secrets
openssl rand -hex 32  # Encryption key
openssl rand -base64 32  # JWT secret
openssl rand -base64 24  # Admin password

# Fix Redis authentication (add to docker-compose.yml)
# command: redis-server --requirepass ${REDIS_PASSWORD} --appendonly yes

# Fix memory budget (edit docker-compose.production.yml)
# Change celery-worker from 1536m to 1280m (1.25GB)

# Remove exposed ports (edit docker-compose.yml)
# Delete lines: "5432:5432" and "6379:6379"

# Delete stale file
rm .env.new
```

---

## Report Metadata

| Field | Value |
|-------|-------|
| Generated | 2026-02-21T00:00:00Z |
| Agent A (Docker) | Task ses_37f5d1ca9ffeorALrN7NAeLX0R |
| Agent B (Env) | Task ses_37f5d1c9fffeGpNsmVGrqACx4c |
| Files Analyzed | 22 |
| Critical Issues | 8 |
| Recommendations | 17 |
| Estimated Remediation Time | 4-6 hours |

---

## Appendix: Files Analyzed

### Docker Files
- docker-compose.yml
- docker-compose.production.yml
- docker-compose.dev.yml
- docker-compose.simple.yml
- docker-compose.prebuilt.yml
- frontend/Dockerfile
- frontend/Dockerfile.dev
- backend/Dockerfile
- backend/Dockerfile.dev
- backend/Dockerfile.minimal
- backend/Dockerfile.worker
- backend/Dockerfile.telegram

### Environment Files
- .env
- .env.example
- .env.new
- backend/.env.example
- backend/.env.production
- frontend/.env.production

---

*End of Report*
