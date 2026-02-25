# SOWKNOW API Reference

**Version**: 3.0.0 (Phase 3)
**Base URL**: `https://sowknow.gollamtech.com/api/v1`
**Authentication**: JWT Bearer Token (httpOnly secure cookie)
**Response Format**: JSON

---

## Table of Contents

1. [Authentication](#authentication)
2. [System Status](#system-status)
3. [Collections API](#collections-api)
4. [Documents API](#documents-api)
5. [Search & RAG](#search--rag)
6. [Knowledge Graph](#knowledge-graph)
7. [Chat & Multi-Agent](#chat--multi-agent)
8. [Smart Folders](#smart-folders)
9. [Admin API](#admin-api)
10. [Error Handling](#error-handling)
11. [Rate Limiting](#rate-limiting)

---

## Authentication

### Login

Create a JWT session token.

```http
POST /auth/login
Content-Type: application/json

{
  "email": "user@example.com",
  "password": "secure_password"
}
```

**Response** (200 OK):
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 3600,
  "user": {
    "id": "uuid",
    "email": "user@example.com",
    "role": "user",
    "name": "User Name"
  }
}
```

**cURL Example**:
```bash
curl -X POST https://sowknow.gollamtech.com/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "password": "secure_password"
  }' \
  -c cookies.txt  # Save session cookie
```

### Logout

Revoke JWT token and session.

```http
POST /auth/logout
Authorization: Bearer {token}
```

**Response** (200 OK):
```json
{
  "message": "Successfully logged out"
}
```

### Refresh Token

Get new access token (auto-refresh with httpOnly cookie).

```http
POST /auth/refresh
```

**Response** (200 OK):
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "expires_in": 3600
}
```

---

## System Status

### Health Check (No Auth)

Quick service health check.

```http
GET /health
```

**Response** (200 OK):
```json
{
  "status": "healthy",
  "timestamp": "2026-02-24T10:30:00Z",
  "version": "3.0.0"
}
```

### Detailed Health

Full system health including all services.

```http
GET /health/detailed
Authorization: Bearer {token}
```

**Response** (200 OK):
```json
{
  "status": "healthy",
  "services": {
    "database": {
      "status": "connected",
      "latency_ms": 2,
      "connections": 5
    },
    "redis": {
      "status": "connected",
      "latency_ms": 1,
      "memory_mb": 45.2
    },
    "celery": {
      "status": "connected",
      "workers": 1,
      "queue_depth": 3
    }
  },
  "api": {
    "request_count": 1234,
    "error_rate_percent": 0.2,
    "response_time_ms": 45
  },
  "memory": {
    "used_mb": 512,
    "limit_mb": 1024
  }
}
```

### Status with Feature List

Full API status and available features.

```http
GET /status
Authorization: Bearer {token}
```

**Response** (200 OK):
```json
{
  "status": "operational",
  "version": "3.0.0",
  "features": {
    "collections": true,
    "documents": true,
    "search": true,
    "knowledge_graph": true,
    "graph_rag": true,
    "multi_agent_search": true,
    "smart_folders": true,
    "pdf_export": true,
    "telegram_bot": true
  },
  "llm_providers": {
    "kimi": {
      "available": true,
      "routing": ["chat", "search"]
    },
    "minimax": {
      "available": true,
      "routing": ["public_documents"]
    },
    "ollama": {
      "available": true,
      "routing": ["confidential_documents"]
    }
  }
}
```

---

## Collections API

Collections are dynamic document groups with AI-powered queries.

### Create Collection

```http
POST /collections
Authorization: Bearer {token}
Content-Type: application/json

{
  "name": "Family History",
  "description": "Documents about family genealogy",
  "is_public": false,
  "rules": [
    {
      "field": "title",
      "operator": "contains",
      "value": "family"
    }
  ]
}
```

**Response** (201 Created):
```json
{
  "id": "coll_abc123def456",
  "name": "Family History",
  "description": "Documents about family genealogy",
  "is_public": false,
  "document_count": 42,
  "created_at": "2026-02-24T10:30:00Z",
  "updated_at": "2026-02-24T10:30:00Z"
}
```

**cURL Example**:
```bash
curl -X POST https://sowknow.gollamtech.com/api/v1/collections \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Family History",
    "description": "Documents about family genealogy",
    "is_public": false
  }'
```

### List Collections

```http
GET /collections?skip=0&limit=20&search=family
Authorization: Bearer {token}
```

**Response** (200 OK):
```json
{
  "items": [
    {
      "id": "coll_abc123def456",
      "name": "Family History",
      "description": "Documents about family genealogy",
      "is_public": false,
      "document_count": 42,
      "created_at": "2026-02-24T10:30:00Z"
    }
  ],
  "total": 1,
  "skip": 0,
  "limit": 20
}
```

### Get Collection Details

```http
GET /collections/{collection_id}
Authorization: Bearer {token}
```

**Response** (200 OK):
```json
{
  "id": "coll_abc123def456",
  "name": "Family History",
  "description": "Documents about family genealogy",
  "is_public": false,
  "document_count": 42,
  "documents": [
    {
      "id": "doc_xyz789",
      "title": "Family Tree 2025.pdf",
      "excerpt": "The Smith family originated in Yorkshire...",
      "relevance_score": 0.95
    }
  ],
  "created_at": "2026-02-24T10:30:00Z",
  "updated_at": "2026-02-24T10:30:00Z"
}
```

### Update Collection

```http
PUT /collections/{collection_id}
Authorization: Bearer {token}
Content-Type: application/json

{
  "name": "Smith Family History",
  "description": "Updated description",
  "is_public": true
}
```

**Response** (200 OK): Updated collection object

### Delete Collection

```http
DELETE /collections/{collection_id}
Authorization: Bearer {token}
```

**Response** (204 No Content)

### Export Collection as PDF

```http
POST /collections/{collection_id}/export
Authorization: Bearer {token}
Content-Type: application/json

{
  "format": "pdf",
  "include_excerpts": true,
  "include_metadata": true,
  "theme": "light"
}
```

**Response** (200 OK):
```
Content-Type: application/pdf
Content-Disposition: attachment; filename="Family_History_2026-02-24.pdf"

[Binary PDF content]
```

**cURL Example**:
```bash
curl -X POST https://sowknow.gollamtech.com/api/v1/collections/{collection_id}/export \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"format": "pdf", "theme": "light"}' \
  -o export.pdf
```

---

## Documents API

### Upload Document

Upload individual document or batch.

```http
POST /documents/upload
Authorization: Bearer {token}
Content-Type: multipart/form-data

file: <binary content>
is_confidential: false
tags: ["finance", "2024"]
collection_id: "coll_abc123def456"
```

**Response** (202 Accepted):
```json
{
  "task_id": "task_xyz789",
  "document_id": "doc_abc123def456",
  "filename": "statement.pdf",
  "status": "processing",
  "message": "Document queued for processing",
  "processing_steps": ["ocr", "embedding", "tagging"]
}
```

**cURL Example**:
```bash
curl -X POST https://sowknow.gollamtech.com/api/v1/documents/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@document.pdf" \
  -F "is_confidential=false" \
  -F "tags=finance,2024"
```

### List Documents

```http
GET /documents?skip=0&limit=20&confidential=false&tag=finance
Authorization: Bearer {token}
```

**Response** (200 OK):
```json
{
  "items": [
    {
      "id": "doc_abc123def456",
      "title": "Financial Statement 2024.pdf",
      "filename": "statement.pdf",
      "size_bytes": 2457600,
      "is_confidential": false,
      "tags": ["finance", "2024"],
      "created_at": "2026-02-24T10:30:00Z",
      "ocr_status": "completed",
      "embedding_status": "completed"
    }
  ],
  "total": 150,
  "skip": 0,
  "limit": 20
}
```

### Get Document Details

```http
GET /documents/{document_id}
Authorization: Bearer {token}
```

**Response** (200 OK):
```json
{
  "id": "doc_abc123def456",
  "title": "Financial Statement 2024.pdf",
  "filename": "statement.pdf",
  "size_bytes": 2457600,
  "is_confidential": false,
  "tags": ["finance", "2024"],
  "content_preview": "The financial results for Q4 2024 show...",
  "pages": 45,
  "created_at": "2026-02-24T10:30:00Z",
  "processing": {
    "ocr_status": "completed",
    "ocr_confidence": 0.97,
    "embedding_status": "completed",
    "embedding_model": "multilingual-e5-large",
    "tagging_status": "completed",
    "tags_auto": ["financial_report", "quarterly", "fiscal_2024"]
  },
  "collections": [
    {
      "id": "coll_abc123def456",
      "name": "Finance 2024"
    }
  ]
}
```

### Delete Document

```http
DELETE /documents/{document_id}
Authorization: Bearer {token}
```

**Response** (204 No Content)

### Get Document Content (Full Text)

```http
GET /documents/{document_id}/content
Authorization: Bearer {token}
```

**Response** (200 OK):
```json
{
  "document_id": "doc_abc123def456",
  "content": "The full extracted text from the document...",
  "pages": [
    {
      "page_number": 1,
      "content": "Page 1 content..."
    }
  ]
}
```

---

## Search & RAG

### Hybrid Search

Combined vector + keyword search across documents.

```http
POST /search
Authorization: Bearer {token}
Content-Type: application/json

{
  "query": "What were the family's financial decisions in 2024?",
  "limit": 10,
  "confidential": false,
  "collection_ids": ["coll_abc123def456"],
  "llm_provider": "auto"
}
```

**Response** (200 OK):
```json
{
  "query": "What were the family's financial decisions in 2024?",
  "results": [
    {
      "document_id": "doc_abc123",
      "title": "Financial Statement 2024.pdf",
      "page": 12,
      "excerpt": "In Q4 2024, the family decided to allocate 30% of savings to...",
      "relevance_score": 0.92,
      "source_type": "document"
    },
    {
      "document_id": "doc_def456",
      "title": "Board Meeting Notes 2024.pdf",
      "page": 5,
      "excerpt": "Key financial decisions for the year: real estate investment...",
      "relevance_score": 0.87,
      "source_type": "document"
    }
  ],
  "total": 2,
  "search_time_ms": 1250,
  "llm_provider_used": "kimi"
}
```

**cURL Example**:
```bash
curl -X POST https://sowknow.gollamtech.com/api/v1/search \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "family financial decisions 2024",
    "limit": 10
  }' | jq .
```

### Graph-RAG Search

Knowledge graph-augmented search with synthesis.

```http
POST /graph-rag/search
Authorization: Bearer {token}
Content-Type: application/json

{
  "query": "What are the relationships between family members and their business ventures?",
  "depth": 2,
  "include_synthesis": true,
  "llm_provider": "kimi"
}
```

**Response** (200 OK):
```json
{
  "query": "What are the relationships between family members and their business ventures?",
  "graph_results": {
    "entities": [
      {
        "id": "entity_john_smith",
        "name": "John Smith",
        "type": "person",
        "significance": 0.95
      }
    ],
    "relationships": [
      {
        "source": "entity_john_smith",
        "target": "entity_smith_corp",
        "type": "founder_of",
        "strength": 0.98
      }
    ],
    "paths": [
      {
        "start": "entity_john_smith",
        "end": "entity_smith_corp",
        "length": 1,
        "path": ["entity_john_smith", "entity_smith_corp"]
      }
    ]
  },
  "synthesis": "John Smith founded Smith Corporation in 1995. He was CEO until 2015...",
  "sources": [
    {
      "document_id": "doc_abc123",
      "title": "John Smith Biography"
    }
  ]
}
```

---

## Knowledge Graph

### Get Knowledge Graph

Retrieve current knowledge graph state.

```http
GET /knowledge-graph?limit=100
Authorization: Bearer {token}
```

**Response** (200 OK):
```json
{
  "entities": [
    {
      "id": "entity_john_smith",
      "name": "John Smith",
      "type": "person",
      "mentions": 156,
      "first_mentioned": "2026-01-15",
      "last_mentioned": "2026-02-24",
      "significance_score": 0.95
    }
  ],
  "relationships": [
    {
      "source": "entity_john_smith",
      "target": "entity_jane_smith",
      "type": "spouse_of",
      "strength": 0.99,
      "mentions": 42
    }
  ],
  "statistics": {
    "total_entities": 245,
    "total_relationships": 1203,
    "graph_density": 0.15
  }
}
```

### Get Entity Details

```http
GET /knowledge-graph/entities/{entity_id}
Authorization: Bearer {token}
```

**Response** (200 OK):
```json
{
  "id": "entity_john_smith",
  "name": "John Smith",
  "type": "person",
  "attributes": {
    "birth_year": 1950,
    "nationality": "USA",
    "profession": "Businessman"
  },
  "related_entities": [
    {
      "id": "entity_jane_smith",
      "name": "Jane Smith",
      "relationship": "spouse_of",
      "strength": 0.99
    }
  ],
  "mentions_in_documents": [
    {
      "document_id": "doc_abc123",
      "title": "Family History.pdf",
      "mentions": 15
    }
  ],
  "timeline": [
    {
      "date": "1950-03-15",
      "event": "Birth"
    },
    {
      "date": "1995-06-20",
      "event": "Founded Smith Corporation"
    }
  ]
}
```

### Search Knowledge Graph

```http
POST /knowledge-graph/search
Authorization: Bearer {token}
Content-Type: application/json

{
  "query": "family members",
  "entity_type": "person",
  "limit": 20
}
```

**Response** (200 OK):
```json
{
  "results": [
    {
      "id": "entity_john_smith",
      "name": "John Smith",
      "type": "person",
      "relevance_score": 0.98
    }
  ],
  "total": 1
}
```

### Get Timeline

Entity evolution over time.

```http
GET /knowledge-graph/entities/{entity_id}/timeline
Authorization: Bearer {token}
```

**Response** (200 OK):
```json
{
  "entity_id": "entity_john_smith",
  "name": "John Smith",
  "timeline": [
    {
      "date": "1950-03-15",
      "events": ["Birth"],
      "document_references": []
    },
    {
      "date": "1995-06-20",
      "events": ["Founded Smith Corporation"],
      "document_references": ["doc_abc123", "doc_def456"]
    },
    {
      "date": "2015-01-10",
      "events": ["Retired from CEO role", "Transferred leadership to daughter"],
      "document_references": ["doc_ghi789"]
    }
  ]
}
```

---

## Chat & Multi-Agent

### Start Chat Session

```http
POST /chat/sessions
Authorization: Bearer {token}
Content-Type: application/json

{
  "title": "Questions about Family History",
  "collection_ids": ["coll_abc123def456"]
}
```

**Response** (201 Created):
```json
{
  "session_id": "sess_xyz789abc",
  "title": "Questions about Family History",
  "created_at": "2026-02-24T10:30:00Z",
  "message_count": 0
}
```

### Send Chat Message

```http
POST /chat/sessions/{session_id}/messages
Authorization: Bearer {token}
Content-Type: application/json

{
  "content": "What were the major events in the family's history?",
  "include_sources": true
}
```

**Response** (200 OK):
```json
{
  "message_id": "msg_abc123",
  "session_id": "sess_xyz789abc",
  "role": "user",
  "content": "What were the major events in the family's history?",
  "created_at": "2026-02-24T10:31:00Z"
}
```

Then receives assistant response:

```json
{
  "message_id": "msg_def456",
  "session_id": "sess_xyz789abc",
  "role": "assistant",
  "content": "Based on the documents, the major family events include:\n\n1. **1995** - John Smith founded Smith Corporation...",
  "sources": [
    {
      "document_id": "doc_abc123",
      "title": "Family History.pdf",
      "excerpt": "In 1995, John Smith founded Smith Corporation..."
    }
  ],
  "llm_provider": "kimi",
  "response_time_ms": 2450
}
```

**cURL with Streaming** (WebSocket not shown, use client library):
```bash
curl -X POST https://sowknow.gollamtech.com/api/v1/chat/sessions/{session_id}/messages \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "content": "Tell me about the family history",
    "include_sources": true
  }'
```

### Multi-Agent Search

Advanced research with Clarifier, Researcher, Verifier, and Answerer agents.

```http
POST /multi-agent/search
Authorization: Bearer {token}
Content-Type: application/json

{
  "query": "What were the key business decisions that shaped the family corporation?",
  "depth": "deep",
  "include_verification": true,
  "streaming": true
}
```

**Response** (200 OK - Streaming):
```json
{
  "request_id": "req_abc123",
  "status": "in_progress",

  "clarification": {
    "original_query": "What were the key business decisions that shaped the family corporation?",
    "clarified_query": "What specific business decisions did the founding team of the family corporation make that were pivotal to its growth and success?",
    "key_terms": ["business decisions", "family corporation", "growth", "success"]
  },

  "research": {
    "documents_found": 12,
    "relevant_snippets": 34,
    "search_queries": [
      "family corporation founding decisions",
      "business strategy family company",
      "corporate governance decisions"
    ]
  },

  "verification": {
    "verified_claims": 5,
    "conflicting_claims": 0,
    "uncertain_claims": 1
  },

  "answer": "The family corporation was shaped by three key business decisions:\n\n1. **1995: Expansion Strategy** - John Smith decided to expand from regional to national markets...",

  "confidence_score": 0.92,
  "sources": [
    {
      "document_id": "doc_abc123",
      "title": "Strategic Planning Meeting 1995.pdf",
      "relevance": 0.98
    }
  ]
}
```

### Get Chat History

```http
GET /chat/sessions/{session_id}/messages?limit=50&skip=0
Authorization: Bearer {token}
```

**Response** (200 OK):
```json
{
  "messages": [
    {
      "message_id": "msg_abc123",
      "role": "user",
      "content": "What were the major events?",
      "created_at": "2026-02-24T10:31:00Z"
    },
    {
      "message_id": "msg_def456",
      "role": "assistant",
      "content": "Based on the documents...",
      "llm_provider": "kimi",
      "created_at": "2026-02-24T10:32:15Z"
    }
  ],
  "total": 8,
  "skip": 0,
  "limit": 50
}
```

---

## Smart Folders

AI-generated content folders with contextual analysis.

### Create Smart Folder

```http
POST /smart-folders
Authorization: Bearer {token}
Content-Type: application/json

{
  "name": "2024 Financial Review",
  "description": "AI-generated analysis of 2024 finances",
  "collection_ids": ["coll_abc123def456"],
  "analysis_type": "synthesis"
}
```

**Response** (202 Accepted):
```json
{
  "folder_id": "sf_abc123def456",
  "name": "2024 Financial Review",
  "status": "generating",
  "generation_progress": 0
}
```

### Get Smart Folder

```http
GET /smart-folders/{folder_id}
Authorization: Bearer {token}
```

**Response** (200 OK):
```json
{
  "folder_id": "sf_abc123def456",
  "name": "2024 Financial Review",
  "description": "AI-generated analysis of 2024 finances",
  "status": "completed",
  "content": {
    "executive_summary": "2024 was a strong financial year with 15% revenue growth...",
    "key_findings": [
      "Revenue increased from $5M to $5.75M",
      "Operating costs decreased 8%"
    ],
    "insights": [
      "The company's profitability improved due to efficiency gains"
    ]
  },
  "created_at": "2026-02-24T10:30:00Z",
  "updated_at": "2026-02-24T10:35:00Z"
}
```

### Export Smart Folder as Report

```http
POST /smart-folders/{folder_id}/export
Authorization: Bearer {token}
Content-Type: application/json

{
  "format": "pdf",
  "include_visualizations": true,
  "theme": "professional"
}
```

**Response** (200 OK):
```
Content-Type: application/pdf
Content-Disposition: attachment; filename="2024_Financial_Review.pdf"

[Binary PDF content]
```

---

## Admin API

Administrative endpoints (admin role required).

### List Users

```http
GET /admin/users?skip=0&limit=50
Authorization: Bearer {token}
```

**Response** (200 OK):
```json
{
  "users": [
    {
      "id": "user_abc123",
      "email": "user@example.com",
      "role": "user",
      "created_at": "2026-02-24T10:30:00Z",
      "last_login": "2026-02-24T10:45:00Z",
      "status": "active"
    }
  ],
  "total": 5,
  "skip": 0,
  "limit": 50
}
```

### Reset User Password

```http
POST /admin/users/{user_id}/reset-password
Authorization: Bearer {token}
```

**Response** (200 OK):
```json
{
  "new_password": "TempPassword_123ABC",
  "expires_at": "2026-02-25T10:30:00Z",
  "message": "Temporary password generated. User must change on next login."
}
```

### Get System Statistics

```http
GET /admin/stats
Authorization: Bearer {token}
```

**Response** (200 OK):
```json
{
  "users": {
    "total": 5,
    "active_last_7_days": 4,
    "by_role": {
      "admin": 1,
      "super_user": 1,
      "user": 3
    }
  },
  "documents": {
    "total": 342,
    "public": 250,
    "confidential": 92,
    "by_status": {
      "completed": 340,
      "processing": 2
    }
  },
  "collections": {
    "total": 12,
    "public": 8,
    "private": 4
  },
  "storage": {
    "total_mb": 2450,
    "public_mb": 1850,
    "confidential_mb": 600
  },
  "api_costs": {
    "kimi_daily": 2.35,
    "minimax_daily": 1.80,
    "total_monthly": 125.50,
    "budget_remaining": 374.50
  }
}
```

### Get Anomaly Report

Daily anomaly detection report (sent automatically at 09:00 AM).

```http
GET /admin/anomalies?days=1
Authorization: Bearer {token}
```

**Response** (200 OK):
```json
{
  "generated_at": "2026-02-24T09:00:00Z",
  "anomalies": [
    {
      "type": "slow_response",
      "severity": "warning",
      "description": "Search response time exceeded 8s (actual: 12.5s)",
      "affected_resource": "search_kimi",
      "count": 3,
      "recommendation": "Consider increasing Kimi rate limits or optimizing queries"
    }
  ],
  "health_summary": {
    "error_rate": "0.2%",
    "average_response_time": "45ms",
    "database_connections": 12,
    "memory_usage": "62%"
  }
}
```

### Trigger Cache Clear

```http
POST /admin/cache/clear
Authorization: Bearer {token}
```

**Response** (200 OK):
```json
{
  "status": "success",
  "cleared": "all",
  "timestamp": "2026-02-24T10:30:00Z"
}
```

---

## Error Handling

### Error Response Format

All errors follow this format:

```json
{
  "error": {
    "code": "INVALID_REQUEST",
    "message": "Missing required field: email",
    "details": {
      "field": "email",
      "reason": "required"
    }
  },
  "request_id": "req_abc123",
  "timestamp": "2026-02-24T10:30:00Z"
}
```

### Common Error Codes

| Code | HTTP | Meaning |
|------|------|---------|
| `INVALID_REQUEST` | 400 | Malformed request or missing fields |
| `UNAUTHORIZED` | 401 | Missing or invalid authentication token |
| `FORBIDDEN` | 403 | User lacks permission for resource |
| `NOT_FOUND` | 404 | Resource doesn't exist |
| `CONFLICT` | 409 | Resource already exists (e.g., duplicate email) |
| `UNPROCESSABLE_ENTITY` | 422 | Validation error in request body |
| `RATE_LIMIT_EXCEEDED` | 429 | Too many requests |
| `INTERNAL_SERVER_ERROR` | 500 | Server error (check logs) |
| `SERVICE_UNAVAILABLE` | 503 | Dependent service unavailable (DB/Redis) |

### Example Error Response

```http
HTTP/1.1 401 Unauthorized
Content-Type: application/json

{
  "error": {
    "code": "UNAUTHORIZED",
    "message": "Missing authentication token"
  },
  "request_id": "req_xyz789",
  "timestamp": "2026-02-24T10:30:00Z"
}
```

### Handling Async Operations

For long-running operations (document upload, smart folder generation):

```http
HTTP/1.1 202 Accepted

{
  "task_id": "task_abc123",
  "status": "processing",
  "check_status_url": "/api/v1/tasks/task_abc123"
}
```

Check status with:

```http
GET /tasks/task_abc123
Authorization: Bearer {token}
```

**Response**:
```json
{
  "task_id": "task_abc123",
  "status": "processing",
  "progress_percent": 75,
  "message": "Generating embeddings... (3/4 chunks)",
  "created_at": "2026-02-24T10:30:00Z",
  "started_at": "2026-02-24T10:30:30Z"
}
```

---

## Rate Limiting

### Request Limits

| Endpoint Category | Limit | Window |
|-------------------|-------|--------|
| Authentication | 5 requests | 1 minute |
| Search | 30 requests | 1 minute |
| Chat | Unlimited | - |
| Documents Upload | 10 requests | 1 hour |
| Admin | 10 requests | 1 minute |
| General API | 100 requests | 1 minute |

### Rate Limit Headers

Every response includes rate limit info:

```http
HTTP/1.1 200 OK
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 87
X-RateLimit-Reset: 1645621200
```

### Handling Rate Limits

When limit exceeded (429 Too Many Requests):

```json
{
  "error": {
    "code": "RATE_LIMIT_EXCEEDED",
    "message": "Too many requests. Try again in 45 seconds.",
    "retry_after": 45
  },
  "request_id": "req_abc123"
}
```

**Recommended Retry Strategy**:
```python
import time
import requests

for attempt in range(3):
    response = requests.post(url, headers=headers, json=data)

    if response.status_code == 429:
        retry_after = response.json().get('retry_after', 60)
        print(f"Rate limited. Waiting {retry_after}s...")
        time.sleep(retry_after)
        continue

    break
```

---

## Authentication Scheme

All authenticated endpoints require JWT token in header:

```bash
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

**Token Properties**:
- **Expiration**: 1 hour
- **Refresh**: Automatic with httpOnly secure cookie
- **Format**: JWT (RS256 signing)
- **Scope**: Full user permissions (role-based)

---

## SDK Examples

### JavaScript/TypeScript

```javascript
import { SowknowClient } from '@sowknow/sdk';

const client = new SowknowClient({
  apiUrl: 'https://sowknow.gollamtech.com/api/v1',
  token: 'eyJ...' // From login
});

// Search
const results = await client.search({
  query: 'family history',
  limit: 10
});

// Chat
const response = await client.chat.send({
  sessionId: 'sess_xyz',
  message: 'Tell me about family events'
});

// Collections
const collections = await client.collections.list();
```

### Python

```python
from sowknow import SowknowAPI

api = SowknowAPI(
    api_url='https://sowknow.gollamtech.com/api/v1',
    token='eyJ...'
)

# Search
results = api.search(query='family history', limit=10)

# Chat
response = api.chat.send(session_id='sess_xyz', message='...')

# Collections
collections = api.collections.list()
```

### cURL

```bash
# Login
TOKEN=$(curl -X POST https://sowknow.gollamtech.com/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"pass"}' \
  | jq -r '.access_token')

# Search
curl -X POST https://sowknow.gollamtech.com/api/v1/search \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"family history","limit":10}'
```

---

## Support

For API issues:
- **Documentation**: https://sowknow.gollamtech.com/api/docs
- **Email**: api-support@gollamtech.com
- **GitHub Issues**: https://github.com/anomalyco/sowknow4/issues

---

**SOWKNOW API Reference v3.0.0**
*Last Updated: February 24, 2026*
