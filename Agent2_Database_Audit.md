## SESSION: Agent 2 - Database & Query Layer - 2026-02-16T17:15:03Z

- **Accomplished:**
  - Analyzed database schema for Document and User models
  - Reviewed query builders and ORM filtering logic
  - Examined API endpoints for document listing, search, and collections
  - Checked for enumeration vulnerabilities
  - Verified timing attack resistance

- **Decisions Made:**
  - Focused on endpoints that could expose confidential document metadata to unauthorized users
  - Analyzed role-based filtering at multiple layers (API, Service, Database)
  - Prioritized findings based on severity and exploitability

- **Findings:**

### CRITICAL FINDINGS

#### 1. Bucket Parameter Enumeration in Document List (LOW-MEDIUM SEVERITY)
**Location:** `/root/development/src/active/sowknow4/backend/app/api/documents.py` lines 165-174

**Issue:** When a regular (non-admin) user queries `/api/v1/documents?bucket=confidential`, the bucket parameter is silently ignored and the query still filters to PUBLIC only. While this prevents enumeration (user gets public docs, not an error), it could confuse users about whether confidential docs exist.

```python
# Lines 167-174
if current_user.role not in [UserRole.ADMIN, UserRole.SUPERUSER]:
    # Non-admins and non-superusers only see public documents
    query = query.filter(Document.bucket == DocumentBucket.PUBLIC)
elif bucket:
    # Admin can filter by bucket
    if bucket in ["public", "confidential"]:
        query = query.filter(Document.bucket == DocumentBucket(bucket))
```

**Risk:** Low - The filter correctly prevents access, but returns public count instead of error.

---

#### 2. Collection Item Reveals Document Bucket (MEDIUM SEVERITY)
**Location:** `/root/development/src/active/sowknow4/backend/app/api/collections.py` line 218

**Issue:** When retrieving collection details, the document bucket is exposed in the response:

```python
item_dict["document"] = {
    "id": str(item.document.id),
    "filename": item.document.filename,
    "bucket": item.document.bucket.value,  # EXPOSES BUCKET
    "created_at": item.document.created_at.isoformat()
}
```

**Risk:** If a regular user somehow gains access to a collection containing confidential documents (e.g., shared by admin), they would see the bucket type. However, this requires the collection to already be shared with them, limiting the exploitability.

---

#### 3. Admin Statistics Exposes Confidential Counts (ADMIN ONLY - LOW RISK)
**Location:** `/root/development/src/active/sowknow4/backend/app/api/admin.py` lines 527-533

**Issue:** The `/admin/stats` endpoint returns confidential document counts:
```python
confidential_documents = db.query(func.count(Document.id)).filter(
    Document.bucket == DocumentBucket.CONFIDENTIAL
).scalar()
```

**Risk:** This is mitigated by `require_admin_only` dependency - only admins can access this endpoint. Acceptable for admin dashboard functionality.

---

### POSITIVE SECURITY CONTROLS

#### 1. Proper 404 vs 403 Handling (EXCELLENT)
**Location:** `/root/development/src/active/sowknow4/backend/app/api/documents.py` lines 212-222, 236-248

The code intentionally returns 404 (not 403) for confidential documents accessed by non-privileged users:

```python
# SECURITY: Returns 404 (not 403) for confidential documents accessed by
# regular users to prevent document enumeration.
if document.bucket == DocumentBucket.CONFIDENTIAL and current_user.role not in [UserRole.ADMIN, UserRole.SUPERUSER]:
    raise HTTPException(status_code=404, detail="Document not found")
```

**Assessment:** Excellent - Prevents attackers from enumerating document IDs to discover confidential documents.

---

#### 2. Role-Based Query Filtering (EXCELLENT)
**Location:** `/root/development/src/active/sowknow4/backend/app/services/search_service.py` lines 59-98

The `_get_user_bucket_filter()` method correctly implements RBAC:

```python
def _get_user_bucket_filter(self, user: User) -> List[str]:
    if user.role == UserRole.ADMIN:
        return [DocumentBucket.PUBLIC.value, DocumentBucket.CONFIDENTIAL.value]
    elif user.role == UserRole.SUPERUSER:
        return [DocumentBucket.PUBLIC.value, DocumentBucket.CONFIDENTIAL.value]
    else:
        return [DocumentBucket.PUBLIC.value]
```

**Assessment:** Excellent - Properly filters at the query level.

---

#### 3. Superuser View-Only Enforcement (EXCELLENT)
**Location:** `/root/development/src/active/sowknow4/backend/app/api/deps.py` lines 199-228

The `require_admin_only` dependency ensures SuperUsers cannot modify documents:

```python
async def require_admin_only(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, ...)
```

**Assessment:** Correctly implements CLAUDE.md requirement that SuperUsers have VIEW-ONLY access.

---

#### 4. Document List Filtering (EXCELLENT)
**Location:** `/root/development/src/active/sowknow4/backend/app/api/documents.py` lines 165-174

Regular users only see PUBLIC documents in list endpoint:

```python
if current_user.role not in [UserRole.ADMIN, UserRole.SUPERUSER]:
    query = query.filter(Document.bucket == DocumentBucket.PUBLIC)
```

**Assessment:** Correctly implemented.

---

### TIMING ATTACK ANALYSIS

**Finding:** No significant timing attack vectors detected.

- All database queries have consistent execution paths based on role
- 404 responses are identical in timing for both missing docs and unauthorized access
- No conditional branching that could leak information via response timing

---

### ENUMERATION TESTING SUMMARY

| Endpoint | Non-Admin | SuperUser | Admin |
|----------|-----------|-----------|-------|
| GET /documents | Sees PUBLIC only | Sees all | Sees all |
| GET /documents/{id} | 404 for confidential | Can access | Can access |
| GET /documents?bucket=confidential | Silently returns PUBLIC | Filters correctly | Filters correctly |
| POST /documents/upload | 403 | 403 | Can upload |
| DELETE /documents/{id} | 403 | 403 | Can delete |
| GET /admin/stats | 403 | 403 | Full stats |
| Search /hybrid_search | Sees PUBLIC only | Sees all | Sees all |

---

- **Next Steps:**
  1. Fix the collection item bucket exposure (line 218 in collections.py) - remove bucket field from response for non-admin users
  2. Consider adding explicit error message when regular user tries to filter by confidential bucket
  3. Consider adding rate limiting on document listing to prevent bulk enumeration via pagination

- **Evidence:**
  - Schema files: `/root/development/src/active/sowknow4/backend/app/models/document.py`, `/root/development/src/active/sowknow4/backend/app/models/user.py`
  - Document API: `/root/development/src/active/sowknow4/backend/app/api/documents.py`
  - Search service: `/root/development/src/active/sowknow4/backend/app/services/search_service.py`
  - Collections API: `/root/development/src/active/sowknow4/backend/app/api/collections.py`
  - Admin API: `/root/development/src/active/sowknow4/backend/app/api/admin.py`
  - Dependencies: `/root/development/src/active/sowknow4/backend/app/api/deps.py`
