# LLM Routing Logic - Flowchart Documentation

## Overview

This document describes the LLM routing logic in SOWKNOW, which determines which AI service processes user queries based on document confidentiality and PII detection.

## Routing Flowchart

```
┌─────────────────────────────────────────────────────────────────┐
│                      USER QUERY RECEIVED                        │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│              1. SEARCH DOCUMENTS FROM VECTOR STORE              │
│                                                                 │
│   - Query embedding generated                                   │
│   - Top-K documents retrieved                                   │
│   - RBAC filtering applied (user role)                         │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│              2. CHECK FOR CONFIDENTIAL DOCUMENTS                │
│                                                                 │
│   ┌─────────────────────┐    ┌─────────────────────┐           │
│   │ Any documents from  │    │ All documents are   │           │
│   │ "confidential"     │    │ from "public"      │           │
│   │ bucket?            │    │ bucket?            │           │
│   └─────────┬───────────┘    └─────────┬───────────┘           │
│             │ YES                      │ NO                    │
│             ▼                          ▼                        │
└─────────────┼───────────────────────────┼───────────────────────┘
              │                           │
              ▼                           ▼
┌─────────────────────────┐   ┌───────────────────────────────────┐
│    has_confidential    │   │      3. CHECK FOR PII IN QUERY    │
│         = TRUE        │   │                                   │
└─────────────┬──────────┘   └───────────────┬───────────────────┘
              │                               │
              ▼                               ▼
┌─────────────────────────┐   ┌───────────────────────────────────┐
│                        │   │   ┌─────────────────────────┐    │
│   ROUTE TO OLLAMA      │   │   │ PII detected in query? │    │
│   (Local/Mistral)     │   │   └───────────┬─────────────┘    │
│                        │   │               │                 │
│   - Uses local Ollama  │   │   YES          │ NO              │
│   - Zero cost         │   │   ▼             ▼                │
│   - 100% confidential │   │   ┌────────┐  ┌─────────────┐    │
│                        │   │   │ROUTE TO│  │ROUTE TO    │    │
└────────────────────────┘   │   │OLLAMA  │  │MINIMAX     │    │
                            │   │        │  │(OpenRouter)│    │
                            │   └────────┘  └─────────────┘    │
                            │                                │
                            └────────────────────────────────┘
```

## Detailed Decision Logic

### Step 1: Document Search

```python
# search_service.py - Get user-visible documents
def _get_user_bucket_filter(self, user: User) -> List[str]:
    if user.role == UserRole.ADMIN:
        return ["public", "confidential"]
    elif user.role == UserRole.SUPERUSER:
        return ["public", "confidential"]
    else:
        return ["public"]  # Regular users only see public
```

### Step 2: Confidential Check

```python
# chat_service.py - Check document buckets
has_confidential = any(
    doc.bucket == DocumentBucket.CONFIDENTIAL
    for doc in search_results
)
```

### Step 3: PII Detection

```python
# pii_detection_service.py
def detect_pii(self, text: str) -> Dict[str, Any]:
    # Check for: email, phone, SSN, credit card, IBAN, etc.
    patterns = {
        'email': r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
        'phone': r'\b\d{10,}\b',
        'ssn': r'\b\d{3}-\d{2}-\d{4}\b',
        'credit_card': r'\b\d{13,19}\b',
        'iban': r'\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b',
    }
    # Returns: { 'detected': True/False, 'types': [...], 'count': N }
```

### Step 4: Final Routing Decision

```python
# chat_service.py - Route decision
if has_confidential:
    # Always use Ollama for confidential
    llm_service = self.ollama_service
elif pii_detected:
    # Use Ollama if PII in query
    llm_service = self.ollama_service
else:
    # Use Minimax for public-only queries
    llm_service = self.openrouter_service
```

## Role-Based Access Summary

| User Role | Can See Public | Can See Confidential | Routing |
|-----------|---------------|---------------------|---------|
| **User** | ✅ Yes | ❌ No | Minimax (public) |
| **SuperUser** | ✅ Yes | ✅ Yes (View Only) | Ollama (if contains confidential) |
| **Admin** | ✅ Yes | ✅ Yes | Ollama (if contains confidential) |

## Multi-Agent System (Phase 3) - CURRENTLY BROKEN

The multi-agent system does NOT follow this routing logic:

```
┌─────────────────────────────────────────────────────────────────┐
│           MULTI-AGENT SYSTEM (INCORRECT ROUTING)                │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   Researcher Agent ──▶ Gemini (ALL QUERIES) ❌                 │
│   Answer Agent ──────▶ Gemini (ALL QUERIES) ❌                 │
│   Verification Agent ▶ Gemini (ALL QUERIES) ❌                │
│   Clarification Agent ▶ Gemini (ALL QUERIES) ❌                │
│                                                                 │
│   CRITICAL: Sends confidential docs to Gemini!                 │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Required Fix**: Apply same routing logic to all agents.

## Services Missing Routing

| Service | File | Line | Fix Required |
|---------|------|------|--------------|
| Smart Folder | smart_folder_service.py | 280 | Add has_confidential check |
| Intent Parser | intent_parser.py | 381 | Add has_confidential check |
| Entity Extraction | entity_extraction_service.py | 242 | Add has_confidential check |
| Auto-Tagging | auto_tagging_service.py | 160 | Add has_confidential check |
| Report Service | report_service.py | 255 | Add has_confidential check |
| Progressive Revelation | progressive_revelation_service.py | 405 | Add has_confidential check |
| Synthesis | synthesis_service.py | 263, 465, 503 | Add has_confidential check |

## Caching Behavior

| Cache Type | Storage | TTL | Contents |
|------------|---------|-----|----------|
| Gemini Cache | In-memory | 3600s | Public chat history |
| Redis Cache | Redis | Configurable | Search results |
| Vector Cache | PostgreSQL | Permanent | Document embeddings |

## Testing the Routing

### Test: Public Document Query

```bash
# Login as regular user
# Query about public documents
curl -X POST http://localhost/api/v1/chat \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"message": "What is in my public files?"}'
```

Expected: Routes to Minimax (OpenRouter)

### Test: Confidential Document Query

```bash
# Login as Admin
# Query about confidential documents
curl -X POST http://localhost/api/v1/chat \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d '{"message": "What is in my confidential files?"}'
```

Expected: Routes to Ollama (check logs)

### Test: PII in Query

```bash
# Login as regular user
# Query with PII
curl -X POST http://localhost/api/v1/chat \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"message": "Find my SSN 123-45-6789"}'
```

Expected: Routes to Ollama (due to PII detection)

## Log Verification

```bash
# Check routing decisions in logs
docker logs sowknow-backend 2>&1 | grep -i "routing\|llm\|provider"
```

Expected output examples:
```
Routing to OpenRouter (Minimax) - public docs only
Routing to Ollama - confidential documents detected
Routing to Ollama - PII detected in query
```
