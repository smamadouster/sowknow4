# 🚀 Map-First Implementation — Migration Guide

This guide documents the architectural improvements implemented after the
Map-First audit was approved.

---

## ✅ Completed Changes

### 1. Unified Map Generation (`generate_all_maps.sh`)

**Path:** `scripts/structural_audit/generate_all_maps.sh`

One command regenerates both backend and frontend architecture maps:

```bash
bash scripts/structural_audit/generate_all_maps.sh
```

### 2. Pre-Commit Hook (`.githooks/pre-commit`)

**Path:** `.githooks/pre-commit`

Auto-regenerates maps when Python or TypeScript files change.

**To install:**
```bash
git config core.hooksPath .githooks
```

The hook is intentionally conservative — it only runs if `backend/*.py` or
`frontend/*.{ts,tsx}` files are staged.

### 3. LLM Gateway (`app/services/llm_gateway.py`)

**Path:** `backend/app/services/llm_gateway.py`

A simplified facade over the existing `LLMRouter`.  Consumers no longer need
to import individual provider services.

**Migration pattern:**

```python
# ❌ OLD — direct provider import + manual fallback
from app.services.minimax_service import minimax_service
from app.services.openrouter_service import openrouter_service

async for chunk in minimax_service.chat_completion(messages):
    ...

# ✅ NEW — single gateway import, automatic routing + fallback
from app.services.llm_gateway import llm_gateway

async for chunk in llm_gateway.chat_completion(messages, tier="simple"):
    ...
```

**Refactored consumer:** `backend/app/services/auto_tagging_service.py`  
The auto-tagging service now uses `llm_gateway` instead of `minimax_service`.

### 4. Document Orchestrator (`app/services/document_orchestrator.py`)

**Path:** `backend/app/services/document_orchestrator.py`

Extracts the core document ingestion pipeline from `api/documents.py`:
- Bucket access validation
- File validation (extension, size, magic bytes)
- Deduplication
- Storage
- Document record creation
- User tag attachment
- Audit logging
- Voice transcription dispatch
- Pipeline queueing

**Integration into `documents.py`:**

Replace the body of `_do_upload_document` with:

```python
from app.services.document_orchestrator import document_orchestrator

async def _do_upload_document(...):
    return await document_orchestrator.ingest_document(
        file=file,
        bucket=bucket,
        title=title,
        tags=tags,
        document_type=document_type,
        transcript=transcript,
        current_user=current_user,
        db=db,
    )
```

This shrinks the 1,441-line router by ~200 lines and removes business logic
from the HTTP layer.

---

## 📋 Remaining Refactoring Tasks

| Task | Effort | Risk | Priority |
|------|--------|------|----------|
| Wire `DocumentOrchestrator` into `api/documents.py` | Small | Low | P1 |
| Migrate remaining 60+ direct LLM service imports to `llm_gateway` | Medium | Medium | P1 |
| Split `api/documents.py` into sub-routers (`upload`, `journal`, `batch`) | Medium | Medium | P2 |
| Add circuit-breakers to `ocr_service`, `embedding_service`, `whisper_service` | Medium | Low | P2 |
| Adopt LSIF for code intelligence | Large | Low | P3 |

---

## 🧪 Verification

Run these commands to verify the new infrastructure:

```bash
# Regenerate maps
bash scripts/structural_audit/generate_all_maps.sh

# Syntax-check new Python modules
cd backend
python3 -m py_compile app/services/llm_gateway.py
python3 -m py_compile app/services/document_orchestrator.py
python3 -m py_compile app/services/auto_tagging_service.py

# Inspect updated backend map
grep -A2 "llm_gateway" scripts/structural_audit/cache.graph.backend.py
grep -A2 "document_orchestrator" scripts/structural_audit/cache.graph.backend.py
```

---

*Generated as part of the Map-First Architecture Audit implementation.*
