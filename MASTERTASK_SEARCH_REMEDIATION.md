# MASTERTASK: Search Remediation Plan

**Status:** Phase 1 In Progress  
**Created:** 2026-05-15  
**Approver:** User  

---

## Rule: Phase Gate Policy

A phase is **COMPLETE** only when ALL of the following are true:
1. All tasks in the phase are coded and saved to disk
2. Any new issues discovered during execution are fixed
3. QA tests are run and pass
4. Code is committed to git
5. Only then does work on the next phase begin

---

## PHASE 1: Stop the Bleeding

**Goal:** Fix the most critical bugs causing missing results.  
**Deployable:** Yes, independently.  

### 1.1 Fix Language Mismatch in Full-Text Search
**File:** `backend/app/services/search_service.py`  
**Problem:** `search_vector` built with document language, query uses query-detected language.  
**Fix:** Change all keyword search paths to use `regconfig = "simple"` (language-agnostic).  
**Status:** ⬜ Pending

### 1.2 Add Filename Search to Hybrid Search
**File:** `backend/app/services/search_service.py`  
**Problem:** Hybrid search only searches chunk content, never filename.  
**Fix:** Add filename ILIKE/tsvector search inside hybrid search and merge with RRF.  
**Status:** ⬜ Pending

### 1.3 Lower Score Thresholds for Short Queries
**File:** `backend/app/services/search_service.py`  
**Problem:** 1-word queries filtered by aggressive 0.25 threshold.  
**Fix:** Lower thresholds to 0.08 (short) / 0.05 (long).  
**Status:** ⬜ Pending

### 1.4 Fix Query Sanitization Inconsistency
**File:** `backend/app/api/search_agent_router.py`  
**Problem:** Streaming search uses raw query; non-streaming sanitizes it.  
**Fix:** Apply `_sanitize_search_query()` in `search_stream()` before `build_search_queries()`.  
**Status:** ⬜ Pending

### 1.5 Add Search-Time Filename Fallback
**File:** `backend/app/api/search_agent_router.py`  
**Problem:** `/search` never finds documents by filename.  
**Fix:** After hybrid search, query `documents.original_filename.ilike()` and append as RawChunk results.  
**Status:** ⬜ Pending

### Phase 1 QA Checklist
- [ ] French query "feuille" finds English-indexed chunks
- [ ] Filename match appears in search results
- [ ] 1-word query returns results even when embed server unavailable
- [ ] Streaming and non-streaming search use same sanitized query
- [ ] All existing backend tests pass
- [ ] Commit made

---

## PHASE 2: Unify Search Architecture

**Goal:** Make `/documents` and `/search` behave consistently.  
**Deployable:** Only after Phase 1 is committed.  

### 2.1 Replace Filename-Only Search in `/documents`
**File:** `backend/app/api/documents.py`  
**Fix:** When `search` param provided, call hybrid search instead of ILIKE-only.  
**Status:** ⬜ Blocked on Phase 1

### 2.2 Add Documents to Global Search on `/search` Page
**File:** `frontend/app/[locale]/search/page.tsx`  
**Fix:** Change `api.searchGlobal` types to include `'document'`.  
**Status:** ⬜ Blocked on Phase 1

### 2.3 Unify Result Limits
**File:** `frontend/app/[locale]/search/page.tsx`, backend defaults  
**Fix:** Increase default `top_k` from 12 to 24.  
**Status:** ⬜ Blocked on Phase 1

### 2.4 Add Match Source Indicators
**Files:** Backend schemas + frontend search page  
**Fix:** Add `match_source` field to results, display badges.  
**Status:** ⬜ Blocked on Phase 1

### Phase 2 QA Checklist
- [ ] `/documents` search finds content matches, not just filenames
- [ ] `/search` page shows documents in global results
- [ ] Same query returns overlapping results on both pages
- [ ] Commit made

---

## PHASE 3: Harden Fallbacks and Edge Cases

**Goal:** Ensure search works when ML services are degraded.  
**Deployable:** Only after Phase 2 is committed.  

### 3.1 Harden Embed Server Fallback
**File:** `backend/app/services/search_service.py`  
**Fix:** Boost keyword weight to 1.0 when semantic_results is empty.  
**Status:** ⬜ Blocked on Phase 2

### 3.2 Add Direct Substring Fallback
**File:** `backend/app/services/search_service.py`  
**Fix:** If total_results < 3, run `chunk_text ILIKE '%query%'` fallback.  
**Status:** ⬜ Blocked on Phase 2

### 3.3 Fix Client-Side Cache
**File:** `frontend/lib/store.ts` (search cache)  
**Fix:** Add 5-minute TTL and cache invalidation on upload.  
**Status:** ⬜ Blocked on Phase 2

### 3.4 Intent Cache TTL and Per-User Isolation
**File:** `backend/app/services/search_agent.py`  
**Fix:** Add TTL and user-scoped keys to `_intent_cache`.  
**Status:** ⬜ Blocked on Phase 2

### 3.5 Surface Unindexed Documents
**Files:** Backend + frontend search page  
**Fix:** Show banner when filename matches exist but documents are not yet indexed.  
**Status:** ⬜ Blocked on Phase 2

### Phase 3 QA Checklist
- [ ] Search works with embed server offline
- [ ] Cache expires after 5 minutes
- [ ] Intent cache respects TTL
- [ ] Commit made

---

## PHASE 4: Monitoring, Testing, and Polish

**Goal:** Prevent regressions and measure improvement.  
**Deployable:** Only after Phase 3 is committed.  

### 4.1 Add Search Quality Metrics
**File:** New or existing analytics  
**Fix:** Track results count, semantic vs keyword ratio, zero-result queries.  
**Status:** ⬜ Blocked on Phase 3

### 4.2 Add A/B Comparison Tool
**File:** New admin debug page  
**Fix:** Internal tool to compare search paths side-by-side.  
**Status:** ⬜ Blocked on Phase 3

### 4.3 Regression Tests
**File:** `backend/tests/`  
**Fix:** Tests for language mismatch, filename search, embed fallback.  
**Status:** ⬜ Blocked on Phase 3

### 4.4 Add Embed Server Health Indicator
**File:** `frontend/app/[locale]/search/page.tsx`  
**Fix:** Show subtle warning when semantic search is unavailable.  
**Status:** ⬜ Blocked on Phase 3

### Phase 4 QA Checklist
- [ ] Metrics are collected
- [ ] Regression tests pass in CI
- [ ] Admin debug tool works
- [ ] Commit made

---

## Current Phase Status

| Phase | Status | Commit Hash |
|-------|--------|-------------|
| 1 | ✅ Complete | 0718521 |
| 2 | 🔴 Blocked | — |
| 3 | 🔴 Blocked | — |
| 4 | 🔴 Blocked | — |
