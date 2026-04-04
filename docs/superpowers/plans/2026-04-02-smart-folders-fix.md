# Smart Folders Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix Smart Folders so they actually work — fix the double `/api` URL prefix (404s) and remove Ollama routing so all documents (public + confidential) use MiniMax M2.7 directly.

**Architecture:** Minimal 3-file fix. Frontend URL prefix bug in 3 fetch calls. Backend service removes Ollama routing branch, always uses MiniMax. No new files, no new dependencies.

**Tech Stack:** Next.js (frontend fetch calls), FastAPI + MiniMax API (backend service)

---

### Task 1: Fix double `/api` prefix in frontend smart-folders page

**Files:**
- Modify: `frontend/app/[locale]/smart-folders/page.tsx:52,97`

The bug: `NEXT_PUBLIC_API_URL=/api` + `/api/v1/...` = `/api/api/v1/...` (404).
Fix: change `/api/v1/` to `/v1/` in the fetch URL paths.

- [ ] **Step 1: Fix the generate endpoint URL (line 52)**

Change line 52 from:
```typescript
`${process.env.NEXT_PUBLIC_API_URL}/api/v1/smart-folders/generate`,
```
to:
```typescript
`${process.env.NEXT_PUBLIC_API_URL}/v1/smart-folders/generate`,
```

- [ ] **Step 2: Fix the reports/generate endpoint URL (line 97)**

Change line 97 from:
```typescript
`${process.env.NEXT_PUBLIC_API_URL}/api/v1/smart-folders/reports/generate`,
```
to:
```typescript
`${process.env.NEXT_PUBLIC_API_URL}/v1/smart-folders/reports/generate`,
```

- [ ] **Step 3: Commit**

```bash
git add frontend/app/\[locale\]/smart-folders/page.tsx
git commit -m "fix(smart-folders): remove double /api prefix in fetch URLs"
```

---

### Task 2: Fix double `/api` prefix in collections detail page

**Files:**
- Modify: `frontend/app/[locale]/collections/[id]/page.tsx:111`

Same bug — the export PDF button in collection detail also hits `/api/api/v1/...`.

- [ ] **Step 1: Fix the reports/generate endpoint URL (line 111)**

Change line 111 from:
```typescript
`${process.env.NEXT_PUBLIC_API_URL}/api/v1/smart-folders/reports/generate`,
```
to:
```typescript
`${process.env.NEXT_PUBLIC_API_URL}/v1/smart-folders/reports/generate`,
```

- [ ] **Step 2: Commit**

```bash
git add frontend/app/\[locale\]/collections/\[id\]/page.tsx
git commit -m "fix(collections): remove double /api prefix in report export URL"
```

---

### Task 3: Remove Ollama routing — always use MiniMax in smart folder service

**Files:**
- Modify: `backend/app/services/smart_folder_service.py:82-104`

Remove the `has_confidential` check and Ollama branch. Always call `_generate_with_minimax`. Remove the `_generate_with_ollama` method entirely. Remove the `ollama_service` import and instance.

- [ ] **Step 1: Remove Ollama import and instance**

In `backend/app/services/smart_folder_service.py`, remove line 27:
```python
from app.services.ollama_service import ollama_service
```

And in `__init__` (line 38), remove:
```python
self.ollama_service = ollama_service
```

- [ ] **Step 2: Replace the routing logic (lines 82-104)**

Replace the `has_confidential` check and conditional branches:
```python
        # Check if confidential documents are present
        has_confidential = any(doc.bucket == DocumentBucket.CONFIDENTIAL for doc in documents)

        # Gather document context
        document_context = await self._build_document_context(documents, db)

        # Generate content
        if has_confidential:
            generated = await self._generate_with_ollama(
                topic=topic,
                document_context=document_context,
                style=style,
                length=length,
            )
            llm_used = "ollama"
        else:
            generated = await self._generate_with_minimax(
                topic=topic,
                document_context=document_context,
                style=style,
                length=length,
            )
            llm_used = "minimax"
```

With:
```python
        # Gather document context
        document_context = await self._build_document_context(documents, db)

        # Generate content using MiniMax for all documents
        generated = await self._generate_with_minimax(
            topic=topic,
            document_context=document_context,
            style=style,
            length=length,
        )
        llm_used = "minimax"
```

- [ ] **Step 3: Delete `_generate_with_ollama` method (lines 289-332)**

Remove the entire `_generate_with_ollama` method.

- [ ] **Step 4: Update module docstring (line 4)**

Change:
```python
Uses MiniMax (public documents) or Ollama (confidential documents) to
```
to:
```python
Uses MiniMax M2.7 directly for all documents to
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/smart_folder_service.py
git commit -m "fix(smart-folders): use MiniMax directly for all docs, remove Ollama routing"
```

---

### Task 4: Remove confidential access gate in API endpoint

**Files:**
- Modify: `backend/app/api/smart_folders.py:75-79`

The endpoint currently blocks non-admin users from setting `include_confidential=true`. Since we're now using MiniMax for everything, simplify: always include all documents the user has access to based on their RBAC role (the `_search_documents_for_topic` method already handles role-based filtering).

- [ ] **Step 1: Remove the include_confidential permission check (lines 75-79)**

Remove:
```python
    # Check confidential access
    if request.include_confidential and not current_user.can_access_confidential:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="You don't have permission to access confidential documents"
        )
```

- [ ] **Step 2: Auto-set include_confidential based on user role**

After removing the check, add before the `try:` block:
```python
    # Auto-include confidential docs based on user's RBAC role
    include_confidential = current_user.can_access_confidential
```

And change the service call to use this variable instead of `request.include_confidential`:
```python
        result = await smart_folder_service.generate_smart_folder(
            topic=request.topic,
            style=request.style,
            length=request.length,
            include_confidential=include_confidential,
            user=current_user,
            db=db,
        )
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/api/smart_folders.py
git commit -m "fix(smart-folders): auto-set confidential access based on user RBAC role"
```

---

### Task 5: Remove confidential toggle from frontend UI

**Files:**
- Modify: `frontend/app/[locale]/smart-folders/page.tsx:36,60-64,264-287`

Since confidential inclusion is now automatic server-side, remove the toggle and the `include_confidential` field from the request body.

- [ ] **Step 1: Remove the includeConfidential state (line 36)**

Remove:
```typescript
const [includeConfidential, setIncludeConfidential] = useState(false);
```

- [ ] **Step 2: Remove include_confidential from request body (lines 60-64)**

Change the body from:
```typescript
body: JSON.stringify({
  topic,
  style,
  length,
  include_confidential: includeConfidential,
}),
```
to:
```typescript
body: JSON.stringify({
  topic,
  style,
  length,
}),
```

- [ ] **Step 3: Remove the confidential toggle UI block (lines 264-287)**

Remove the entire `{/* Confidential Toggle */}` div block:
```tsx
{/* Confidential Toggle */}
<div className="flex items-center justify-between p-3 bg-gray-50 dark:bg-gray-700 rounded-lg">
  ...entire toggle block...
</div>
```

- [ ] **Step 4: Commit**

```bash
git add frontend/app/\[locale\]/smart-folders/page.tsx
git commit -m "fix(smart-folders): remove confidential toggle, now automatic server-side"
```

---

### Task 6: Build and test end-to-end

**Files:** None (testing only)

- [ ] **Step 1: Rebuild frontend container**

```bash
cd /var/docker/sowknow4
docker compose build frontend
docker compose up -d frontend
```

- [ ] **Step 2: Rebuild backend container**

```bash
docker compose build backend
docker compose up -d backend
```

- [ ] **Step 3: Verify containers are healthy**

```bash
docker compose ps
# All containers should show (healthy)
```

- [ ] **Step 4: Test smart folder generation via curl**

```bash
# Get auth token first, then:
curl -X POST https://sowknow.gollamtech.com/api/v1/smart-folders/generate \
  -H "Content-Type: application/json" \
  -H "Cookie: <auth-cookie>" \
  -d '{"topic": "test topic", "style": "informative", "length": "short"}'
```

Expected: 200 response with `generated_content`, `llm_used: "minimax"`, `sources_used` array.

- [ ] **Step 5: Test in browser**

Navigate to `https://sowknow.gollamtech.com/smart-folders`, enter a topic, click generate. Verify:
- No 404 errors in browser console
- Content generates successfully
- Sources are displayed
- `llm_used` shows "minimax" (not "ollama")
