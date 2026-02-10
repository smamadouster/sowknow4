# SOWKNOW API Documentation

## Base URL
- **Production**: `https://sowknow.gollamtech.com/api`
- **Development**: `http://localhost:8000/api`

## Authentication

All API endpoints (except `/auth/*` and `/health`) require authentication via JWT bearer token.

### Register a New User
```http
POST /api/v1/auth/register
Content-Type: application/json

{
  "email": "user@example.com",
  "password": "SecurePassword123!",
  "full_name": "John Doe"
}
```

### Login
```http
POST /api/v1/auth/login
Content-Type: application/json

{
  "email": "user@example.com",
  "password": "SecurePassword123!"
}
```

Response:
```json
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "bearer",
  "expires_in": 1800
}
```

### Using the Token
```http
Authorization: Bearer <access_token>
```

---

## Knowledge Graph Endpoints

### Extract Entities from Document
```http
POST /api/v1/knowledge-graph/extract/{document_id}
Authorization: Bearer <token>
```

### List Entities
```http
GET /api/v1/knowledge-graph/entities?entity_type=person&page=1&page_size=50
Authorization: Bearer <token>
```

### Get Entity Details
```http
GET /api/v1/knowledge-graph/entities/{entity_id}
Authorization: Bearer <token>
```

### Get Knowledge Graph Data
```http
GET /api/v1/knowledge-graph/graph?entity_type=organization&limit=100
Authorization: Bearer <token>
```

Response:
```json
{
  "nodes": [
    {
      "id": "uuid",
      "name": "Entity Name",
      "type": "organization",
      "size": 5,
      "color": "#10B981"
    }
  ],
  "edges": [
    {
      "source": "uuid1",
      "target": "uuid2",
      "label": "works_at",
      "weight": 3
    }
  ],
  "entity_count": 50,
  "relationship_count": 75
}
```

### Get Timeline Events
```http
GET /api/v1/knowledge-graph/timeline?start_date=2024-01-01&end_date=2024-12-31
Authorization: Bearer <token>
```

### Get Entity Timeline
```http
GET /api/v1/knowledge-graph/timeline/{entity_name}
Authorization: Bearer <token>
```

---

## Graph-RAG Endpoints

### Graph-Augmented Search
```http
POST /api/v1/graph-rag/search
Authorization: Bearer <token>
Content-Type: application/json

{
  "query": "What are the key features of SOWKNOW?",
  "top_k": 10,
  "expansion_depth": 2
}
```

### Find Entity Paths
```http
GET /api/v1/graph-rag/paths/{source}/{target}
Authorization: Bearer <token>
```

### Get Entity Neighborhood
```http
GET /api/v1/graph-rag/neighborhood/{entity_name}?radius=2
Authorization: Bearer <token>
```

### Synthesize Documents
```http
POST /api/v1/graph-rag/synthesize
Authorization: Bearer <token>
Content-Type: application/json

{
  "topic": "Knowledge Management",
  "document_ids": ["uuid1", "uuid2", "uuid3"],
  "synthesis_type": "comprehensive",
  "style": "informative",
  "language": "en"
}
```

### Temporal Evolution Analysis
```http
GET /api/v1/graph-rag/temporal/evolution/{entity_name}?time_months=12
Authorization: Bearer <token>
```

### Get Family Context
```http
GET /api/v1/graph-rag/family/{focus_person}/context?depth=2
Authorization: Bearer <token>
```

---

## Multi-Agent Search Endpoints

### Full Multi-Agent Search
```http
POST /api/v1/multi-agent/search
Authorization: Bearer <token>
Content-Type: application/json

{
  "query": "How does the knowledge graph work?",
  "require_clarification": true,
  "require_verification": true,
  "answer_style": "comprehensive"
}
```

Response:
```json
{
  "query": "How does the knowledge graph work?",
  "answer": "The knowledge graph...",
  "state": "complete",
  "clarification": {
    "is_clear": true,
    "questions": [],
    "assumptions": []
  },
  "research_summary": {
    "findings_count": 15,
    "entities_count": 8,
    "sources_count": 12
  },
  "verification_summary": {
    "verified_count": 5,
    "total_claims": 5
  },
  "duration_ms": 5234
}
```

### Clarify Query
```http
POST /api/v1/multi-agent/clarify
Authorization: Bearer <token>
Content-Type: application/json

{
  "query": "find information about the project",
  "conversation_history": []
}
```

### Conduct Research
```http
POST /api/v1/multi-agent/research
Authorization: Bearer <token>
Content-Type: application/json

{
  "query": "entity extraction features",
  "max_results": 20,
  "use_graph": true
}
```

### Verify Claim
```http
POST /api/v1/multi-agent/verify
Authorization: Bearer <token>
Content-Type: application/json

{
  "claim": "SOWKNOW uses Gemini Flash for AI processing"
}
```

### Generate Answer
```http
POST /api/v1/multi-agent/answer
Authorization: Bearer <token>
Content-Type: application/json

{
  "query": "What are the main benefits?",
  "answer_style": "comprehensive"
}
```

---

## Smart Collections Endpoints

### List Collections
```http
GET /api/v1/collections?page=1&page_size=20
Authorization: Bearer <token>
```

### Create Collection
```http
POST /api/v1/collections
Authorization: Bearer <token>
Content-Type: application/json

{
  "name": "Project Documents",
  "query": "documents about the project milestones"
}
```

### Get Collection Details
```http
GET /api/v1/collections/{collection_id}
Authorization: Bearer <token>
```

### Chat with Collection
```http
POST /api/v1/collections/{collection_id}/chat
Authorization: Bearer <token>
Content-Type: application/json

{
  "content": "Summarize the key points"
}
```

---

## Smart Folders Endpoints

### Generate Smart Folder Content
```http
POST /api/v1/smart-folders/generate
Authorization: Bearer <token>
Content-Type: application/json

{
  "topic": "Quarterly Report",
  "style": "professional",
  "length": "long",
  "document_ids": ["uuid1", "uuid2"]
}
```

### Generate Report
```http
POST /api/v1/smart-folders/report
Authorization: Bearer <token>
Content-Type: application/json

{
  "topic": "Project Summary",
  "format": "standard",
  "language": "en"
}
```

---

## Rate Limits

- **API endpoints**: 10 requests/second
- **General requests**: 30 requests/second
- **Search endpoints**: 5 requests/second

## Errors

All errors return a JSON response:

```json
{
  "detail": "Error message",
  "status": 400
}
```

Common status codes:
- `400` - Bad Request
- `401` - Unauthorized
- `403` - Forbidden
- `404` - Not Found
- `429` - Rate Limit Exceeded
- `500` - Internal Server Error

## Streaming

Some endpoints support Server-Sent Events (SSE) streaming:

```http
GET /api/v1/multi-agent/stream?query=your+question
Authorization: Bearer <token>
Accept: text/event-stream
```

---

## Interactive API Documentation

Interactive API documentation is available at:
- **Swagger UI**: `https://sowknow.gollamtech.com/api/docs`
- **ReDoc**: `https://sowknow.gollamtech.com/api/redoc`
- **OpenAPI JSON**: `https://sowknow.gollamtech.com/api/openapi.json`
