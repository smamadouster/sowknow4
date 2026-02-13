# SOWKNOW Issue Resolution Plan

**Date:** February 13, 2026  
**Goal:** Address all issues from Code Review Assessment Report

---

## Phase 1: Critical Fixes (Immediate)

### 1. Container Stability Issue
**Problem:** nginx container was in stopped state causing Error 521

**Actions:**
1. Investigate nginx logs for crash reason
2. Verify docker-compose restart policy is working
3. Add container health monitoring script
4. Create restart script for emergency recovery

```bash
# Investigate
docker logs sowknow4-nginx --tail 50

# Verify restart policy
grep -A5 "nginx:" docker-compose.production.yml | grep restart
```

**Estimated:** 30 minutes

---

### 2. Fix Failing Tests (26 tests)
**Problem:** SQLAlchemy 2.0 model default behavior causing failures

**Actions:**
1. Review test failures in detail
2. Fix model default configurations
3. Run tests again
4. Target: 85%+ pass rate

```bash
# Run tests to see current state
cd /var/docker/sowknow4/backend
docker exec sowknow-backend pytest -v --tb=short 2>&1 | head -100
```

**Estimated:** 2-3 hours

---

### 3. Configure Git Remote
**Problem:** All code committed locally with no remote

**Actions:**
1. Create GitHub/GitLab repository
2. Add remote origin
3. Push all branches
4. Set up main branch protection

```bash
# In /root/development/src/active/sowknow4
git remote add origin https://github.com/gollamtech/sowknow4.git
git push -u origin main
```

**Estimated:** 30 minutes

---

## Phase 2: High Priority (Within 1 Week)

### 4. Automated Backups
**Problem:** Backup commands documented but not automated

**Actions:**
1. Create backup script
2. Configure cron jobs for daily/weekly backups
3. Set up offsite sync (e.g., rclone to cloud storage)
4. Test restoration procedure

```bash
# Create /root/development/src/active/sowknow4/scripts/backup.sh
#!/bin/bash
# Daily PostgreSQL backup
docker exec sowknow4-postgres pg_dump -U sowknow sowknow > /backups/sowknow_$(date +%Y%m%d).sql

# Add to crontab
# 0 2 * * * /root/development/src/active/sowknow4/scripts/backup.sh
```

**Estimated:** 2 hours

---

### 5. Active Monitoring Setup
**Problem:** No active monitoring despite MONITORING.md

**Actions:**
1. Configure health check alerts (email/webhook)
2. Set up container monitoring
3. Configure API cost tracking
4. Create daily anomaly check script

```bash
# Create /root/development/src/active/sowknow4/scripts/monitor.sh
#!/bin/bash
# Check container health
docker ps --filter "name=sowknow4-" --format "{{.Names}}: {{.Status}}" | grep -v "Up" || echo "All containers running"

# Check memory
docker stats --no-stream --format "table {{.Name}}\t{{.MemUsage}}" | grep sowknow4
```

**Estimated:** 3 hours

---

### 6. Enhance PII Detection
**Problem:** Address and passport patterns need refinement

**Actions:**
1. Review current PII patterns in pii_detection_service.py
2. Add address pattern improvements
3. Add passport/license number patterns
4. Add comprehensive test cases

```python
# Add to backend/app/services/pii_detection_service.py
ADDRESS_PATTERNS = [
    r'\d+\s+[A-Za-z]+\s+(Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr|Court|Ct|Circle|Cir)[,.]?\s*[A-Za-z]{2}\s*\d{5}',
    # ... more patterns
]
```

**Estimated:** 2 hours

---

## Phase 3: Medium Priority (Within 1 Month)

### 7. Frontend Testing Framework
**Problem:** 0% test coverage, no Jest configured

**Actions:**
1. Install Jest and React Testing Library
2. Configure Jest for Next.js
3. Add tests for critical paths:
   - Authentication flow
   - Document upload
   - Search functionality
   - Chat interface

```bash
# Install in /root/development/src/active/sowknow4/frontend
npm install --save-dev jest @testing-library/react @testing-library/jest-dom jest-environment-jsdom
npm install --save-dev @types/jest ts-jest
```

**Estimated:** 4-5 hours

---

### 8. Enable TypeScript Strict Mode
**Problem:** `"strict": false` in tsconfig.json

**Actions:**
1. Enable strict mode in tsconfig.json
2. Fix all resulting type errors
3. Add proper type annotations

```json
// frontend/tsconfig.json
{
  "compilerOptions": {
    "strict": true,
    // ... existing options
  }
}
```

**Estimated:** 3-4 hours

---

### 9. PWA Implementation
**Problem:** No manifest.json or service worker

**Actions:**
1. Create manifest.json
2. Create service worker for offline support
3. Configure next-pwa or custom service worker
4. Test PWA installation on mobile

```bash
# Install PWA plugin
npm install next-pwa
```

**Estimated:** 3-4 hours

---

### 10. Remove Legacy Kimi Code
**Problem:** kimi_service.py still exists after Gemini migration

**Actions:**
1. Identify all Kimi-related code
2. Remove kimi_service.py
3. Remove any Kimi references in other files
4. Update imports/exports

```bash
# Find all Kimi references
grep -r "kimi" --include="*.py" backend/
```

**Estimated:** 1 hour

---

## Implementation Schedule

| Week | Tasks |
|------|-------|
| **Week 1** | Container stability investigation, Fix test failures, Configure Git remote, Set up basic monitoring |
| **Week 2** | Automated backups, Enhance PII detection, Health check script |
| **Week 3** | Frontend testing setup, Enable TypeScript strict mode |
| **Week 4** | PWA implementation, Remove legacy code |

---

## Verification Checklist

After each phase, verify:

- [ ] All Docker containers running with `docker ps`
- [ ] Site accessible at https://sowknow.gollamtech.com
- [ ] Test pass rate > 85%
- [ ] Git remote configured and code pushed
- [ ] Backups running on schedule
- [ ] Monitoring alerts functioning
- [ ] PII detection tested with sample documents
- [ ] Frontend tests passing
- [ ] TypeScript strict mode enabled without errors
- [ ] PWA installable on mobile device

---

## Dependencies

Before starting, ensure you have:
- [ ] Access to production server (`/var/docker/sowknow4`)
- [ ] GitHub/GitLab account for repository
- [ ] Access to cloud storage for offsite backups
- [ ] Email/webhook for monitoring alerts

---

*Plan created: February 13, 2026*
