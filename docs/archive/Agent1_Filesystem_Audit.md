# SOWKNOW Filesystem Security Audit Report

## SESSION: Agent 1 - Filesystem Security - 2026-02-16T17:14:39Z

### Accomplishments:
1. Mapped all document storage locations in the codebase
2. Analyzed Docker volume configurations for both development and production
3. Verified OS-level permissions and path isolation
4. Checked for symlink and path traversal vulnerabilities
5. Reviewed RBAC implementation for filesystem access control
6. Compared storage paths between development and production configurations

### Decisions Made:
- Focused on `/data/public` and `/data/confidential` as the primary storage paths
- Examined both docker-compose.yml (development) and docker-compose.production.yml
- Analyzed storage_service.py as the single source of truth for file operations
- Reviewed RBAC in deps.py and documents.py API endpoints

### Findings:

#### CRITICAL ISSUE: Production Storage Path Mismatch

**Discovery**: The production docker-compose.yml (lines 100-103, 137-139) has INCORRECT volume mounts:

```
# Production mounts:
- uploads:/app/uploads
- confidential_data:/app/data/confidential

# But storage_service.py expects:
- /data/public
- /data/confidential
```

**Impact**: 
- In production, files uploaded to the "public" bucket would be stored in the container's ephemeral filesystem at `/data/public` (not persisted)
- Files in "confidential" bucket would be stored at `/app/data/confidential` (persisted) but at WRONG path
- The storage service creates `/data/public` and `/data/confidential` using `mkdir(parents=True, exist_ok=True)` but these are NOT mounted to persistent volumes in production
- **Data would be LOST on container restart**

**Evidence**:
- Development docker-compose.yml (lines 95-96): `sowknow-public-data:/data/public` and `sowknow-confidential-data:/data/confidential`
- Production docker-compose.production.yml (lines 100-102): Only `uploads:/app/uploads` and `confidential_data:/app/data/confidential`
- Storage service (storage_service.py lines 17-19): Hardcoded to `/data/public` and `/data/confidential`

#### VERIFIED: Logical Bucket Separation

**Confirmed**: The storage service properly separates buckets:
- `get_bucket_path("public")` returns `/data/public`
- `get_bucket_path("confidential")` returns `/data/confidential`
- Files are stored with UUID-based filenames (timestamp + UUID + extension)
- No user-controlled path input in file naming

#### VERIFIED: No Path Traversal Vulnerabilities

**Search Results**: No instances of `../` or path traversal patterns in file operations
- Files are stored using generated UUIDs, not user-provided filenames as paths
- The `save_file()` method uses `bucket_path / filename` (safe join)
- Database stores `file_path` which is validated against bucket

#### VERIFIED: Docker Volume Physical Separation

**Configuration**:
- `sowknow-public-data` volume (development)
- `sowknow-confidential-data` volume (development)
- Both are separate Docker named volumes
- No symlinks between volumes

#### VERIFIED: RBAC Access Control

**API-Level Protection** (documents.py):
- Line 168-170: Non-admin users only see public documents
- Line 221-222: Returns 404 (not 403) for unauthorized confidential access
- Line 246-248: Same 404 pattern for download endpoint
- Line 272: Update requires admin-only
- Line 302: Delete requires admin-only

**Roles** (user.py):
- USER: Public documents only
- SUPERUSER: View-only access to confidential (cannot modify/delete)
- ADMIN: Full access

#### VERIFIED: Security Tests Present

**Test Coverage**:
- test_confidential_isolation.py: 787 lines of isolation tests
- Tests verify: search isolation, document access, download isolation, enumeration prevention
- Timing attack prevention (line 677-732)

### Critical Vulnerabilities:

| # | Severity | Issue | Location |
|---|----------|-------|----------|
| 1 | CRITICAL | Production storage paths not mounted to persistent volumes | docker-compose.production.yml |
| 2 | HIGH | Path mismatch: storage_service.py uses `/data/*` but production mounts to `/app/*` | storage_service.py vs docker-compose.production.yml |

### Recommendations:

1. **FIX PRODUCTION VOLUMES** (Immediate Action Required):
   ```yaml
   # Add to backend and celery-worker in docker-compose.production.yml:
   volumes:
     - public_data:/data/public      # ADD THIS
     - confidential_data:/app/data/confidential
   ```
   And add volume definition:
   ```yaml
   volumes:
     public_data:
       driver: local
   ```

2. **ADD ENVIRONMENT VARIABLE OVERRIDE** (Best Practice):
   - Modify storage_service.py to accept environment variables for base paths
   - Example: `STORAGE_BASE_PATH=/data` or `PUBLIC_PATH=/data/public`

3. **ADD MOUNT VALIDATION** (Defense in Depth):
   - Add startup check to verify volumes are mounted correctly
   - Log warning if `/data/public` is not a mount point

### Evidence:

**Files Examined**:
- `/root/development/src/active/sowknow4/backend/app/services/storage_service.py` - Lines 17-27 (storage paths)
- `/root/development/src/active/sowknow4/docker-compose.yml` - Lines 94-98 (development volumes)
- `/root/development/src/active/sowknow4/docker-compose.production.yml` - Lines 100-103 (production volumes)
- `/root/development/src/active/sowknow4/backend/app/api/documents.py` - Lines 54-146 (upload endpoint)
- `/root/development/src/active/sowowknow4/backend/app/api/deps.py` - Lines 138-228 (RBAC)
- `/root/development/src/active/sowknow4/backend/tests/security/test_confidential_isolation.py` - Security tests

### Next Steps:

1. **Agent 2 (RBAC Implementation)**: Should verify the RBAC enforcement is complete across all endpoints
2. **Agent 3 (API Security)**: Should check for additional API vulnerabilities
3. **DEPLOYMENT TEAM**: MUST fix production docker-compose before next deployment

### Summary:

The filesystem isolation design is **logically sound** with proper bucket separation and RBAC. However, there is a **CRITICAL deployment misconfiguration** in production where:
- Public documents are NOT persisted (stored in ephemeral container filesystem)
- Confidential documents are stored at an incorrect path

This must be fixed before the system can be safely deployed to production.
