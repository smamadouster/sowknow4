# Uploader Auth Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow the auto-uploader daemon to upload documents via Tailscale using only an API key — no OAuth2 login, no tokens, no CSRF.

**Architecture:** New `/api/v1/internal/upload` endpoint authenticated by `X-Bot-Api-Key` header only. Looks up a bot user by `BOT_USER_EMAIL` env var for audit attribution. Reuses existing `_do_upload_document()` from `documents.py`. Uploader script gains API-key mode and atomic state file writes.

**Tech Stack:** FastAPI, SQLAlchemy async, Python requests, watchdog

**Spec:** `docs/superpowers/specs/2026-04-02-uploader-auth-fix-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `backend/app/api/internal.py` | Create | Internal upload endpoint (API-key auth only) |
| `backend/app/main_minimal.py` | Modify (line 149-171) | Register the internal router |
| `scripts/sowknow-auto-uploader.py` | Modify | API-key mode + atomic state writes |

---

### Task 1: Create Internal Upload Endpoint

**Files:**
- Create: `backend/app/api/internal.py`

- [ ] **Step 1: Create `backend/app/api/internal.py`**

```python
"""
Internal API endpoints — authenticated by BOT_API_KEY only.

These endpoints are designed for machine-to-machine use over trusted networks
(e.g., Tailscale). No OAuth2, no cookies, no CSRF.
"""

import logging
import os

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.documents import _do_upload_document, _upload_semaphore
from app.database import get_db
from app.models.user import User
from app.schemas.document import DocumentUploadResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal", tags=["internal"])

BOT_API_KEY = os.getenv("BOT_API_KEY", "")
BOT_USER_EMAIL = os.getenv("BOT_USER_EMAIL", "")


async def _get_bot_user(db: AsyncSession) -> User:
    """Look up the bot user by BOT_USER_EMAIL. Raises 500 if not configured or not found."""
    if not BOT_USER_EMAIL:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="BOT_USER_EMAIL not configured",
        )
    result = await db.execute(select(User).where(User.email == BOT_USER_EMAIL))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Bot user not found: {BOT_USER_EMAIL}",
        )
    return user


def _validate_api_key(key: str) -> None:
    """Validate the provided API key against BOT_API_KEY. Raises 401 on mismatch."""
    if not BOT_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="BOT_API_KEY not configured on server",
        )
    if key != BOT_API_KEY:
        logger.warning("Invalid bot API key on internal endpoint")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )


@router.post("/upload", response_model=DocumentUploadResponse)
async def internal_upload(
    file: UploadFile = File(...),
    bucket: str = Form("public"),
    title: str | None = Form(None),
    tags: str | None = Form(None),
    document_type: str | None = Form(None),
    x_bot_api_key: str = Header(..., alias="X-Bot-Api-Key"),
    db: AsyncSession = Depends(get_db),
) -> DocumentUploadResponse:
    """
    Upload a document via API key only (no user login required).

    Intended for machine-to-machine use over Tailscale.
    Uploads are attributed to the user specified by BOT_USER_EMAIL.
    """
    _validate_api_key(x_bot_api_key)
    bot_user = await _get_bot_user(db)

    logger.info(f"Internal upload: file={file.filename}, bucket={bucket}, bot_user={bot_user.email}")

    if _upload_semaphore._value == 0:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Too many uploads in progress. Please retry shortly.",
        )
    async with _upload_semaphore:
        return await _do_upload_document(
            file=file,
            bucket=bucket,
            title=title,
            tags=tags,
            document_type=document_type,
            x_bot_api_key=x_bot_api_key,
            current_user=bot_user,
            db=db,
        )
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/api/internal.py
git commit -m "feat(internal): add API-key-only upload endpoint for Tailscale uploader"
```

---

### Task 2: Register Internal Router

**Files:**
- Modify: `backend/app/main_minimal.py:149-171`

- [ ] **Step 1: Add the internal import and router registration**

In `backend/app/main_minimal.py`, add the import alongside the other routers (around line 149):

```python
from app.api import (
    admin,
    auth,
    chat,
    collections,
    documents,
    graph_rag,
    internal,
    knowledge_graph,
    multi_agent,
    search,
    smart_folders,
)
```

Then add the router registration after the existing ones (after line 171):

```python
app.include_router(internal.router, prefix="/api/v1")
```

- [ ] **Step 2: Verify the app starts**

Run: `cd /home/development/src/active/sowknow4 && docker compose exec backend python -c "from app.api.internal import router; print('router prefix:', router.prefix)"`

Expected: `router prefix: /internal`

- [ ] **Step 3: Commit**

```bash
git add backend/app/main_minimal.py
git commit -m "feat(internal): register internal router in main app"
```

---

### Task 3: Uploader — Add API Key Mode

**Files:**
- Modify: `scripts/sowknow-auto-uploader.py`

- [ ] **Step 1: Add `SOWKNOW_BOT_API_KEY` config variable**

After line 35 (`SOWKNOW_PASSWORD`), add:

```python
SOWKNOW_BOT_API_KEY = os.getenv("SOWKNOW_BOT_API_KEY", "")  # API key for login-free uploads via Tailscale
```

- [ ] **Step 2: Add `ApiKeyClient` class**

After the `SowknowClient` class (after line 227), add a new client class for API-key mode:

```python
class ApiKeyClient:
    """Upload client using BOT_API_KEY — no login, no tokens, no CSRF."""

    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "SOWKNOW-AutoUploader/2.0",
            "X-Bot-Api-Key": self.api_key,
        })

    def login(self) -> bool:
        """No-op — API key mode doesn't need login."""
        log.info("API key mode: no login required")
        return True

    def ensure_auth(self) -> bool:
        """Always authenticated — API key is static."""
        return True

    def upload(self, filepath: str, bucket: str) -> dict:
        filename = os.path.basename(filepath)
        with open(filepath, "rb") as f:
            resp = self.session.post(
                f"{self.base_url}/api/v1/internal/upload",
                files={"file": (filename, f)},
                data={"bucket": bucket},
                timeout=120,
            )

        if resp.status_code in (200, 201, 202):
            log.info(f"Uploaded: {filename} -> {bucket}")
            return resp.json()

        raise RuntimeError(f"Upload failed ({resp.status_code}): {resp.text[:300]}")
```

- [ ] **Step 3: Update `main()` to select the right client**

Replace the client initialization block in `main()` (lines 414-424) with:

```python
    state = UploadState(STATE_FILE)

    # Select auth mode: API key (Tailscale) or OAuth2 login
    if SOWKNOW_BOT_API_KEY:
        log.info("Using API key mode (Tailscale / no login)")
        client = ApiKeyClient(SOWKNOW_URL, SOWKNOW_BOT_API_KEY)
    else:
        if not SOWKNOW_EMAIL or not SOWKNOW_PASSWORD:
            log.error("Set SOWKNOW_BOT_API_KEY (preferred) or SOWKNOW_EMAIL + SOWKNOW_PASSWORD")
            sys.exit(1)
        log.info("Using OAuth2 login mode")
        client = SowknowClient(SOWKNOW_URL, SOWKNOW_EMAIL, SOWKNOW_PASSWORD)

    log.info(f"SOWKNOW Auto-Uploader starting")
    log.info(f"  API:          {SOWKNOW_URL}")
    log.info(f"  Auth mode:    {'API key' if SOWKNOW_BOT_API_KEY else 'OAuth2 login'}")
    log.info(f"  Public dir:   {PUBLIC_DIR}")
    log.info(f"  Confid. dir:  {CONFIDENTIAL_DIR}")
    log.info(f"  State file:   {STATE_FILE}")

    # Initial login (no-op in API key mode)
    if not client.login():
        log.error("Initial login failed — will retry on first upload")
```

Also remove the early credential check at lines 405-407 (`if not SOWKNOW_EMAIL or not SOWKNOW_PASSWORD`) since that's now handled inside the else branch above.

- [ ] **Step 4: Commit**

```bash
git add scripts/sowknow-auto-uploader.py
git commit -m "feat(uploader): add API key mode for login-free uploads over Tailscale"
```

---

### Task 4: Uploader — Atomic State File Writes

**Files:**
- Modify: `scripts/sowknow-auto-uploader.py`

- [ ] **Step 1: Update `UploadState.save()` method**

Replace the `save` method (lines 96-102) with:

```python
    def save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump({
                "uploaded": self.uploaded,
                "daily_uploads": self.daily_uploads,
                "daily_errors": self.daily_errors,
            }, f, indent=2)
        os.replace(tmp, self.path)  # atomic on POSIX
```

- [ ] **Step 2: Update `_load()` to clean up stale temp files**

Replace the `_load` method (lines 85-94) with:

```python
    def _load(self):
        # Clean up any stale temp file from a prior crash
        tmp = self.path + ".tmp"
        if os.path.exists(tmp):
            os.remove(tmp)
        if os.path.exists(self.path):
            try:
                with open(self.path) as f:
                    data = json.load(f)
                self.uploaded = data.get("uploaded", {})
                self.daily_uploads = data.get("daily_uploads", [])
                self.daily_errors = data.get("daily_errors", [])
            except (json.JSONDecodeError, KeyError):
                log.warning("Corrupt state file, starting fresh")
```

- [ ] **Step 3: Commit**

```bash
git add scripts/sowknow-auto-uploader.py
git commit -m "fix(uploader): atomic state file writes to prevent corruption"
```

---

### Task 5: CSRF Exemption for Internal Endpoint

**Files:**
- Modify: `backend/app/middleware/csrf.py:33-43`

- [ ] **Step 1: Add internal prefix to CSRF exempt paths**

The internal endpoint uses a `X-Bot-Api-Key` header (not a Bearer token), so the existing Bearer-token CSRF bypass won't apply. Add the internal prefix to `EXEMPT_PREFIXES` in `backend/app/middleware/csrf.py`:

Replace line 46:
```python
EXEMPT_PREFIXES = ("/api/v1/auth/verify-email/",)
```

With:
```python
EXEMPT_PREFIXES = ("/api/v1/auth/verify-email/", "/api/v1/internal/")
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/middleware/csrf.py
git commit -m "fix(csrf): exempt internal API endpoints from CSRF validation"
```

---

### Task 6: Smoke Test

- [ ] **Step 1: Rebuild and verify backend starts**

```bash
cd /var/docker/sowknow4
docker compose up -d --build backend
docker compose logs --tail=20 backend | grep -i "internal\|error"
```

Expected: No import errors. Internal router registered.

- [ ] **Step 2: Test internal upload endpoint with curl**

```bash
# Get the BOT_API_KEY from the .env file
source /var/docker/sowknow4/.env

# Create a test file
echo "test upload via internal endpoint" > /tmp/test-internal-upload.txt

# Upload via internal endpoint
curl -s -X POST http://localhost:8001/api/v1/internal/upload \
  -H "X-Bot-Api-Key: $BOT_API_KEY" \
  -F "file=@/tmp/test-internal-upload.txt" \
  -F "bucket=public" | python3 -m json.tool
```

Expected: 200 response with `DocumentUploadResponse` JSON (document id, filename, status).

- [ ] **Step 3: Test invalid API key is rejected**

```bash
curl -s -X POST http://localhost:8001/api/v1/internal/upload \
  -H "X-Bot-Api-Key: wrong-key" \
  -F "file=@/tmp/test-internal-upload.txt" \
  -F "bucket=public"
```

Expected: 401 response with `{"detail": "Invalid API key"}`

- [ ] **Step 4: Test missing API key is rejected**

```bash
curl -s -X POST http://localhost:8001/api/v1/internal/upload \
  -F "file=@/tmp/test-internal-upload.txt" \
  -F "bucket=public"
```

Expected: 422 response (missing required header)

- [ ] **Step 5: Clean up test file and delete test document**

```bash
rm /tmp/test-internal-upload.txt
```

- [ ] **Step 6: Commit all remaining changes (if any)**

```bash
git add -A
git status
# Only commit if there are changes
```
