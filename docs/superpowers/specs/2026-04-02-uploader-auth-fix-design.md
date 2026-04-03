# Uploader Auth Fix — Tailscale + API Key

**Date:** 2026-04-02
**Status:** Approved
**Scope:** Backend internal endpoint, auto-uploader script, state file reliability

## Problem

The SOWKNOW auto-uploader daemon (macOS) has five interrelated issues:

1. **Token lost on restart** — in-memory token requires re-login on daemon restart
2. **API credentials rejected (401)** — login works in web UI but fails from the uploader; the upload endpoint requires `get_current_user` even when `BOT_API_KEY` is provided
3. **Server 500 errors** — fixed separately (task dispatch verification)
4. **Rate limiting (429)** — auth failures cascade: each file retries login, hitting the 20/min app-level limit
5. **State file corruption** — non-atomic `json.dump` corrupts `~/.sowknow-uploader-state.json` on crash

All devices (macOS local, VPS) are on the same Tailscale mesh network. Daily rsync over Tailscale already works reliably.

## Solution

### 1. New Internal Upload Endpoint

Create `POST /api/v1/internal/upload` that authenticates via `X-Bot-Api-Key` header only — no OAuth2, no cookies, no CSRF.

- Validates `X-Bot-Api-Key` against `BOT_API_KEY` env var
- Looks up the bot user via `BOT_USER_EMAIL` env var for audit/ownership attribution
- Reuses the existing `_do_upload_document()` logic for validation, dedup, processing
- Returns the same `DocumentUploadResponse` schema

**New file:** `backend/app/api/internal.py`

```python
router = APIRouter(prefix="/internal", tags=["internal"])

@router.post("/upload", response_model=DocumentUploadResponse)
async def internal_upload(
    file: UploadFile,
    bucket: str = Form("public"),
    title: str | None = Form(None),
    tags: str | None = Form(None),
    document_type: str | None = Form(None),
    x_bot_api_key: str = Header(..., alias="X-Bot-Api-Key"),
    db: AsyncSession = Depends(get_db),
) -> DocumentUploadResponse:
    # Validate API key
    # Look up bot user by BOT_USER_EMAIL
    # Delegate to _do_upload_document()
```

**Router registration:** Add to `main_minimal.py` (where admin routes live) since this is an internal/privileged endpoint.

### 2. Uploader: API Key Mode

Add a second auth mode to `scripts/sowknow-auto-uploader.py`:

- If `SOWKNOW_BOT_API_KEY` env var is set → use API key mode (hit `/api/v1/internal/upload`, send `X-Bot-Api-Key` header, no login)
- If not set → fall back to existing OAuth2 login mode

API key mode eliminates: login, token refresh, token expiry, CSRF, rate limiting on login.

The uploader's `SOWKNOW_URL` should point to the backend's Tailscale IP directly (e.g., `http://100.x.x.x:8001`) to skip nginx.

### 3. Atomic State File Writes

Replace `json.dump` directly to `STATE_FILE` with:

```python
def save(self):
    tmp = self.path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, self.path)  # atomic on POSIX
```

`os.replace` is atomic on POSIX — a crash mid-write only loses the temp file, never corrupts the real state.

## Environment Variables

### Backend (add to `.env`)

| Variable | Value | Purpose |
|----------|-------|---------|
| `BOT_API_KEY` | (already exists) | API key for internal endpoints |
| `BOT_USER_EMAIL` | `admin@sowknow.local` | User to attribute bot uploads to |

### Uploader (macOS LaunchAgent env)

| Variable | Value | Purpose |
|----------|-------|---------|
| `SOWKNOW_URL` | `http://<tailscale-ip>:8001` | Backend via Tailscale (direct, no nginx) |
| `SOWKNOW_BOT_API_KEY` | same as `BOT_API_KEY` | Authenticate without login |

## Security

- **Tailscale network:** Encrypted, authenticated mesh — traffic never touches the public internet
- **API key gate:** `X-Bot-Api-Key` header required on every request; invalid key → 401
- **Audit trail:** All uploads attributed to `BOT_USER_EMAIL` user with `is_bot=True` flag in logs
- **Defense-in-depth (optional future):** Restrict `/api/v1/internal/*` to Tailscale CIDR (100.64.0.0/10) at nginx level
- **No new attack surface on public internet:** The endpoint is reachable but useless without the API key

## Files Changed

| File | Change |
|------|--------|
| `backend/app/api/internal.py` | New — internal upload endpoint |
| `backend/app/main_minimal.py` | Register internal router |
| `scripts/sowknow-auto-uploader.py` | API key mode, atomic state writes |

## Issues Resolved

| Issue | Resolution |
|-------|------------|
| Token lost on restart | No tokens — API key is static |
| Credentials rejected (401) | No login needed |
| Rate limiting (429) | No login requests to rate-limit |
| State file corruption | Atomic `os.replace` writes |
