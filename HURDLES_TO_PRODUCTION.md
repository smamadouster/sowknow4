# Hurdles to Production

> **Goal**: Production with peace of mind — every barrier identified, tracked, and resolved.

---

## 2026-03-27

### Open Issues

| # | Category | Issue | Severity | Status | Notes |
|---|----------|-------|----------|--------|-------|
| | | | | | |

### Resolved Today

| # | Issue | Resolution |
|---|-------|------------|
| 1 | **Telegram .doc upload fails with "Unknown error"** — Two root causes: (a) `_extract_from_doc()` was a stub returning empty text, so .doc files always produced 0 chunks → ERROR; (b) Telegram bot read `document_metadata.processing_error` instead of the API's actual `error_message` field, masking real errors behind generic "Unknown error" | Implemented antiword-based .doc extraction with python-docx fallback in `text_extractor.py`; added `antiword` to `Dockerfile.worker`; fixed both occurrences in `bot.py` to read `result.get("error_message")`. Commits: `8871076`, `397a4e9`. Worker rebuilt, bot rebuilt, all containers healthy. |

---

## Log Template

<!--
Copy this block for each new day. Add entries as issues are discovered.

## 2026-MM-DD

### Open Issues

| # | Category | Issue | Severity | Status | Notes |
|---|----------|-------|----------|--------|-------|
| 1 | | | | OPEN | |

### Resolved Today

| # | Issue | Resolution |
|---|-------|------------|
| | | |
-->
