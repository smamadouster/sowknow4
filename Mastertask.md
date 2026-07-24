# Master Task: SOWKNOW Project Tracker
Started: 2026-02-16 | Lead: Orchestrator
Full history: `docs/archive/Mastertask_full_history.md`

---

## Completed Phases (Summary)

| Phase | What | Date | Key Outcome |
|-------|------|------|-------------|
| 1 | Parallel Agent Execution | 2026-02 | Security audit with 6 agents |
| 2 | QA & Testing | 2026-02 | Test infrastructure established |
| 3 | LLM Routing & MiniMax Audit | 2026-02 | Tri-LLM routing verified |
| 4 | Critical Vulnerability Remediation | 2026-02 | 6 agents fixed backend/security/compliance |
| 6 | Frontend Auth Flow Audit | 2026-02 | JWT + cookie auth secured |
| 8 | Hunyuan Cleanup & OCR | 2026-02-23 | PaddleOCR + Tesseract, 29 tests |
| 9 | 500MB Batch Upload | 2026-02-23 | Server-side size enforcement |
| 10 | pgvector Migration | 2026-02-23 | JSONB -> vector(1024), IVFFlat index |
| 10b | At-Rest Encryption | 2026-02-23 | Fernet encryption for confidential docs |
| 12 | E2E User Testing | 2026-02 | Auth, search, Telegram, chat tested |
| 13 | PDF Export | 2026-02-23 | Collections + Smart Folders export |
| 14 | OCR Modernization | 2026-02-23 | PaddleOCR 3-mode (Base/Large/Gundam) |
| 14b | JWT Token Refresh | 2026-02 | Role propagation fix |
| -- | Codebase Remediation | 2026-03-27 | 10 tasks, 21 commits, 422 unit tests pass |
| -- | Upload Pipeline & Guardian Remediation | 2026-07-24 | 10 commits. Guardian restart loops stopped (jwt probe: 2-consecutive-failure gate + RestartTracker gating). Guardian pipeline probes repaired (dead for months: wrong PG role, enum case, schema, swallowed errors). Sweeper self-block fixed (force dispatch); stage timeouts aligned with Celery limits; MaxRetriesExceeded handled; 4,325 duplicate chunk pairs deduped + unique constraint (mig 033). Upload hardening: unified validation (150MB), rate limits, per-user dedup, compare_digest, pause on /internal/upload, orphan cleanup. **Crypto: STORAGE_ENCRYPTION_KEY was never wired to any container — entire confidential bucket (7,111 docs / 12,611 files) was plaintext; now enforced no-key-no-write, all files re-encrypted, OCR decrypt-to-temp.** Alerting restored (Telegram + email) + 30min flood throttle. bcrypt off event loop; nginx login rate limit; guardian MetricsDB reconnect. 40+3 historical stage failures recovered; 7,333 docs enriched. |
| -- | Drag-and-Drop Upload | 2026-02 | Frontend batch upload |
| -- | Context Caching | 2026-02 | OpenRouter Redis cache + confidential bypass |
| -- | Telegram Sessions | 2026-02 | Redis-backed persistent sessions |

## Production Readiness: READY

All P0/P1 security issues resolved. Tri-LLM routing enforced. 100% audit coverage. PDF export. Batch upload. At-rest encryption **actually live since 2026-07-24** — Phase 10b shipped the code but the key was never provisioned; the bucket was plaintext until the 2026-07-24 remediation.

---

## Open Items

### User-Action Items (2026-07-24)
- ~~Gmail app password for guardian email alerts~~ — DONE 2026-07-24 (email channel verified live)
- **TailscaleUploader on MacBook**: loops login→403→login when active (no cookies/CSRF sent). Fix on the Mac: use Bearer header or SOWKNOW_BOT_API_KEY mode (see `scripts/macos-uploader/`). Server-side impact now contained (bcrypt threadpool + nginx 10r/m login limit).
- **Rotate telegram-bot ADMIN_PASSWORD** (was exposed in a debug session 2026-07-24).
- **Old-layout documents** (`storage/documents/...` paths): files missing on disk — decide cleanup vs restore from backup.
- **`.env` backup coverage**: STORAGE_ENCRYPTION_KEY + TELEGRAM_CHAT_ID exist only in `.env` on this host. Losing the key = confidential bucket unreadable.
- Pre-existing: 2 test collection errors (`testcontainers` package missing from backend venv).
- Pre-existing: notes audio stored unencrypted in `/data/audio/` (no pipeline, capped 10MB since 2026-07-24).

### 175 Integration Test Failures (PostgreSQL suite)

Real integration bugs requiring code changes. Unit suite is green (422 pass / 0 fail).

| Priority | Issue | ~Tests | Root Cause |
|----------|-------|--------|------------|
| P1 | Sync/Async session mismatch | ~95 | `client` fixture injects sync Session, endpoints use AsyncSession. Fix: async-compatible test fixtures |
| P2 | Auth status code mismatches | ~23 | 403 vs 401 confusion. Fix: audit each test's expected code |
| P3 | Stale mock targets | ~20 | Mocking deleted/renamed modules. Fix: update mock targets |
| P4 | Root tests/ import errors | 9 | `from backend.app...` imports. Fix: use `from app...` |
| P5 | PostgreSQL-specific failures | 6 | greenlet_spawn, ARRAY casting. Fix: correct engine type in fixtures |

**Key files:** `backend/tests/conftest.py` (db + client fixtures), integration/e2e/security tests.

### VPS Memory Budget

```
postgres: 2048M | redis: 512M | backend: 512M | celery-worker: 2048M
celery-beat: 256M | frontend: 512M | nginx: 256M | telegram-bot: 256M
TOTAL: 6400M (6.4GB limit)
```

### Non-Blocking Items
- Frontend testing infrastructure (Phase 8 audit: 15/100)
- Database migration fixes (Phase 9 audit)
- TypeScript strict mode disabled (Phase 11 audit)
