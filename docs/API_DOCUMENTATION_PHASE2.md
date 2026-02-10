# SOWKNOW API Documentation - Phase 2 Endpoints

**Version:** 2.0.0
**Base URL:** `http://localhost:8000/api/v1`

---

## Authentication

All endpoints require a valid JWT token in the Authorization header:

```
Authorization: Bearer <your_token>
```

---

## Collections API

### Create Collection

```http
POST /collections
```

Create a new Smart Collection from a natural language query.

**Request Body:**
```json
{
  "name": "Financial Documents 2023",
  "description": "All financial documents from last year",
  "query": "Show me all financial documents from 2023",
  "collection_type": "smart",
  "visibility": "private",
  "save": true
}
```

**Response:** `201 Created`
```json
{
  "id": "uuid",
  "name": "Financial Documents 2023",
  "query": "Show me all financial documents from 2023",
  "ai_summary": "This collection contains financial documents...",
  "document_count": 15,
  "created_at": "2026-02-10T10:00:00Z"
}
```

### List Collections

```http
GET /collections?page=1&page_size=20&visibility=private
```

**Query Parameters:**
- `page` (int): Page number
- `page_size` (int): Items per page (max 100)
- `visibility` (string): Filter by visibility
- `pinned_only` (boolean): Only pinned collections
- `favorites_only` (boolean): Only favorite collections

**Response:**
```json
{
  "collections": [...],
  "total": 42,
  "page": 1,
  "page_size": 20
}
```

### Get Collection Details

```http
GET /collections/{collection_id}
```

**Response:**
```json
{
  "id": "uuid",
  "name": "Financial Documents 2023",
  "query": "...",
  "ai_summary": "...",
  "document_count": 15,
  "items": [
    {
      "id": "uuid",
      "document_id": "uuid",
      "relevance_score": 95,
      "notes": null,
      "is_highlighted": false
    }
  ]
}
```

### Refresh Collection

```http
POST /collections/{collection_id}/refresh
```

Re-run the collection query to find new/updated documents.

**Request Body:**
```json
{
  "include_new_documents": true,
  "update_summary": true
}
```

### Update Collection

```http
PATCH /collections/{collection_id}
```

**Request Body:**
```json
{
  "name": "Updated Name",
  "description": "Updated description",
  "is_pinned": true,
  "is_favorite": false
}
```

### Delete Collection

```http
DELETE /collections/{collection_id}
```

### Pin/Unpin Collection

```http
POST /collections/{collection_id}/pin
```

### Favorite/Unfavorite Collection

```http
POST /collections/{collection_id}/favorite
```

---

## Smart Folders API

### Generate Smart Folder

```http
POST /smart-folders/generate
```

Generate AI-created content from documents.

**Request Body:**
```json
{
  "topic": "Annual performance summary",
  "style": "professional",
  "length": "medium",
  "include_confidential": false
}
```

**Parameters:**
- `topic` (string): Subject to generate content about
- `style` (string): `informative`, `creative`, `professional`, `casual`
- `length` (string): `short`, `medium`, `long`
- `include_confidential` (boolean): Include confidential docs (admin only)

**Response:**
```json
{
  "collection_id": "uuid",
  "topic": "Annual performance summary",
  "generated_content": "Full generated article text...",
  "sources_used": [
    {
      "id": "uuid",
      "filename": "report.pdf",
      "bucket": "public",
      "created_at": "2026-02-10T10:00:00Z"
    }
  ],
  "word_count": 850,
  "llm_used": "gemini"
}
```

---

## Reports API

### Generate Report

```http
POST /smart-folders/reports/generate
```

Generate a PDF report from a collection.

**Request Body:**
```json
{
  "collection_id": "uuid",
  "format": "standard",
  "include_citations": true,
  "language": "en"
}
```

**Parameters:**
- `collection_id` (UUID): Collection to report on
- `format` (string): `short`, `standard`, `comprehensive`
- `include_citations` (boolean): Include document references
- `language` (string): `en`, `fr`

**Response:**
```json
{
  "report_id": "uuid",
  "collection_id": "uuid",
  "format": "standard",
  "content": "Full report text...",
  "citations": [...],
  "generated_at": "2026-02-10T10:00:00Z",
  "file_url": "/api/v1/reports/download/uuid"
}
```

### Get Report Templates

```http
GET /smart-folders/reports/templates
```

Returns available report formats and their specifications.

---

## Collection Chat API

### Chat with Collection

```http
POST /collections/{collection_id}/chat
```

Send a message to a collection-scoped chat with context caching.

**Request Body:**
```json
{
  "message": "What are the key findings in these documents?",
  "session_name": "Q&A Session 1"
}
```

**Response:**
```json
{
  "session_id": "uuid",
  "collection_id": "uuid",
  "response": "Based on the documents...",
  "sources": [...],
  "llm_used": "gemini",
  "cache_hit": true
}
```

---

## Preview API

### Preview Collection

```http
POST /collections/preview
```

Preview a collection without saving it.

**Request Body:**
```json
{
  "query": "Financial documents from last quarter"
}
```

**Response:**
```json
{
  "intent": {...},
  "documents": [...],
  "estimated_count": 12,
  "ai_summary": "...",
  "suggested_name": "Q1 Financial Documents"
}
```

---

## Collection Stats API

### Get Collection Statistics

```http
GET /collections/stats
```

Get statistics about user's collections.

**Response:**
```json
{
  "total_collections": 15,
  "pinned_collections": 3,
  "favorite_collections": 5,
  "total_documents_in_collections": 245,
  "average_documents_per_collection": 16.3,
  "collections_by_type": {
    "smart": 12,
    "manual": 3
  },
  "recent_activity": [...]
}
```

---

## Collection Items API

### Add Item to Collection

```http
POST /collections/{collection_id}/items
```

Manually add a document to a collection.

**Request Body:**
```json
{
  "document_id": "uuid",
  "relevance_score": 80,
  "notes": "Important for Q3 review",
  "is_highlighted": false
}
```

### Update Collection Item

```http
PATCH /collections/{collection_id}/items/{item_id}
```

**Request Body:**
```json
{
  "relevance_score": 90,
  "notes": "Updated notes",
  "is_highlighted": true
}
```

### Remove Collection Item

```http
DELETE /collections/{collection_id}/items/{item_id}
```

---

## Performance API

### Get System Performance

```http
GET /admin/performance
```

Get system performance metrics (admin only).

**Response:**
```json
{
  "timestamp": "2026-02-10T10:00:00Z",
  "memory": {
    "used_mb": 1250,
    "percent": 65,
    "available_mb": 4096
  },
  "embeddings": {...},
  "cache": {
    "hit_rate": 0.65
  },
  "gemini": {...},
  "recommendations": [...]
}
```

---

## Error Codes

| Code | Description |
|------|-------------|
| 400 | Bad Request - Invalid input |
| 401 | Unauthorized - Missing or invalid token |
| 403 | Forbidden - Insufficient permissions |
| 404 | Not Found - Resource doesn't exist |
| 500 | Internal Server Error |

**Error Response Format:**
```json
{
  "detail": "Error message description"
}
```

---

## Rate Limits

- Standard users: 100 requests/minute
- Power users: 300 requests/minute
- Admins: 1000 requests/minute

---

## Webhooks

Webhooks are supported for real-time notifications on collection events.

### Webhook Events

- `collection.created`
- `collection.refreshed`
- `report.generated`

### Webhook Configuration

Contact your administrator to configure webhook endpoints.

---

**Version:** 2.0.0 | **Last Updated:** February 10, 2026
