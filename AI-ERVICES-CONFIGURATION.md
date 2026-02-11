# AI Services Configuration Guide

## Overview

SOWKNOW uses a tiered AI service architecture with automatic fallback:

1. **Primary**: Gemini 2.0 Flash (Google Generative AI)
2. **Secondary**: Kimi 2.5 (Moonshot AI) - Used as fallback
3. **Tertiary**: Ollama (local LLM for confidential docs)

## Service Priority Flow

```
Incoming Request
       │
       ├── Is document confidential?
       │    │
       ├── NO ──→ Use Gemini 2.0 Flash (Primary)
       │    │
       └── YES ──→ Use Ollama (Local/Tertiary)
       │
       └── Is Gemini API available?
            │
            ├── YES ──── Use Gemini 2.0 Flash
            │
            └── NO ──── Use Kimi 2.5 (Secondary/Fallback)
```

## Service Descriptions

### Gemini 2.0 Flash (Primary)

**Purpose**: Main AI service for public documents

**Features**:
- Context caching for up to 80% cost reduction
- Fast responses (~2-3 seconds)
- 128K context window
- Multimodal capabilities (text, images, code)

**Use Cases**:
- Public document chat
- RAG search responses
- Document summarization
- Collection generation
- Smart folder management

**Configuration**:
```bash
GEMINI_API_KEY=your_gemini_api_key_here
```

**Pricing**:
- Input: $0.00001 per 1K tokens
- Cache read: $0.000001 per 1K tokens
- Output: $0.00005 per 1K tokens

**Status Monitoring**: `GET /api/v1/health/detailed` returns gemini service status

### Kimi 2.5 (Secondary/Fallback)

**Purpose**: Secondary AI service when Gemini is unavailable

**Features**:
- Moonshot 2.5 foundation model
- Chat completion
- Strong reasoning capabilities
- Web search integration

**Use Cases**:
- Backup chat when Gemini API is down
- Overflow traffic handling
- Development/testing queries

**Configuration**:
```bash
KIMI_API_KEY=your_kimi_api_key_here
```

**Pricing**: Free tier available with API key

**Status Monitoring**: Automatically selected when Gemini API returns error

### Ollama (Tertiary/Local)

**Purpose**: Local LLM for confidential documents only

**Features**:
- Runs on same server (host.docker.internal:11434)
- Zero data egress
- Complete privacy
- Supports multiple models (llama3, mistral, etc.)

**Use Cases**:
- Confidential document processing
- Private knowledge graph queries
- Local RAG without external API calls

**Configuration**:
```bash
LOCAL_LLM_URL=http://host.docker.internal:11434
```

**Model**: multilingual-e5-large (embeddings)

## Document Classification Logic

Documents are automatically classified when uploaded:

**Public Documents** (non-confidential):
- User bucket only
- Processed by Gemini 2.0 Flash
- Stored in `sowknow-public-data` volume
- Searchable by all users

**Confidential Documents**:
- User and Confidential buckets
- Processed by Ollama (local)
- Stored in `sowknow-confidential-data` volume
- Searchable only by Admin and Super User

## API Routing Logic

The routing logic is implemented in `backend/app/main.py`:

```python
def determine_llm_service(document_confidential: bool, gemini_available: bool) -> str:
    """
    Determine which LLM service to use based on:
    1. Document confidentiality
    2. Gemini API availability

    Returns: 'gemini', 'ollama', or 'kimi'
    """

    if document_confidential:
        # Confidential documents ALWAYS use Ollama (privacy-first)
        return 'ollama'

    elif gemini_available:
        # Gemini API is available - use it (primary choice)
        return 'gemini'

    else:
        # Fallback to Kimi 2.5
        return 'kimi'
```

## Cost Tracking

All API calls are tracked with cost monitoring:

```python
# Usage in code
from app.services.monitoring import get_cost_tracker

cost_tracker = get_cost_tracker()

# Record API call
cost_tracker.record_api_call(
    service="gemini",  # or 'kimi' or 'ollama'
    operation="chat",
    model="gemini-2.0-flash-exp",
    input_tokens=1000,
    output_tokens=500,
    cached_tokens=0
)

# Check daily cost
daily_cost = cost_tracker.get_daily_cost()
remaining_budget = cost_tracker.get_remaining_budget()

if cost_tracker.is_over_budget():
    # Send alert!
    logger.warning(f"API cost over budget: ${daily_cost:.2f}")
```

## Environment Variables

```bash
# Primary AI Service (Gemini)
GEMINI_API_KEY=your_gemini_api_key_here
# Optional: GEMINI_DAILY_BUDGET_USD=5.00

# Secondary AI Service (Kimi Fallback)
KIMI_API_KEY=your_kimi_api_key_here
# Optional: KIMI_API_BASE_URL=https://api.moonshot.cn/v1

# Tertiary AI Service (Ollama for confidential docs)
LOCAL_LLM_URL=http://host.docker.internal:11434
# Optional: OLLAMA_MODEL=llama3
```

## Testing the Fallback

To test Kimi fallback when Gemini is unavailable:

```bash
# 1. Set Kimi as primary (uncomment Gemini key)
export GEMINI_API_KEY=""
export KIMI_API_KEY=your_kimi_api_key_here

# 2. Restart services
docker compose restart backend celery-worker

# 3. Test Kimi response
curl http://localhost:8000/api/v1/graph-rag/answer \
  -H "Content-Type: application/json" \
  -d '{"query": "test query"}' \
  | jq .

# Expected: Kimi service responds instead of Gemini
```

## Monitoring AI Service Health

Each AI service's health is monitored via `GET /api/v1/health/detailed`:

```json
{
  "services": {
    "gemini": {
      "status": "healthy" | "unhealthy" | "unavailable",
      "api_configured": true | false,
      "model": "gemini-2.0-flash-exp"
    },
    "kimi": {
      "status": "configured" | "unused"
    },
    "ollama": {
      "status": "connected" | "disconnected",
      "model": "multilingual-e5-large"
    }
  }
}
```

## Cost Optimization Tips

1. **Enable Context Caching**: Gemini supports automatic caching of prompts
   - Reduces costs by up to 80% for repeated queries
   - Automatically used when same query is asked multiple times

2. **Batch Processing**: Process multiple documents together
   - Reduces per-document overhead

3. **Use Kimi for Development**: Kimi is free
   - Save Gemini API costs for production
   - Kimi 2.5 performs comparably to Gemini for most tasks

4. **Monitor Daily Budget**: Set alerts at 80% of budget
   - `GEMINI_DAILY_BUDGET_USD=5.00`
   - Alert when exceeded via `GET /api/v1/monitoring/alerts`

## Troubleshooting

### Issue: All Requests Using Kimi (Fallback Active)

If Kimi is being used when it shouldn't be:

```bash
# Check current AI service configuration
curl http://localhost:8000/api/v1/health/detailed | jq '.services.gemini.status'

# If returns "unavailable", check your Gemini API key
# If Gemini key is valid but service still uses Kimi, check routing logic
```

### Issue: High API Costs

If daily budget is exceeded:

```bash
# Check current costs
curl http://localhost:8000/api/v1/monitoring/costs | jq .

# Reset cost tracking for testing (development only!)
docker exec backend python -c "
from app.services.monitoring import get_cost_tracker
ct = get_cost_tracker()
ct._cost_records.clear()
print('Cost tracker reset')
"

# Increase budget temporarily
export GEMINI_DAILY_BUDGET_USD=10.00
```

### Issue: Ollama Not Responding

```bash
# Check Ollama connection
curl http://host.docker.internal:11434/api/tags

# Restart Ollama (if using shared instance)
# Contact server administrator
```

## Service Status Codes

| Status | Description |
|---------|-------------|
| `healthy` | Service is fully operational |
| `unhealthy` | Service is responding but with errors |
| `unavailable` | Service cannot be reached |
| `connected` | Connection established |
| `configured` | Service is enabled and configured |
| `unused` | Service is configured but not currently in use |

## Migration Guide

### Migrating from Gemini to Kimi

No code changes required! The fallback is automatic.

To test Kimi fallback:
1. Set `GEMINI_API_KEY=""` (unset) to disable Gemini
2. Set `KIMI_API_KEY=your_key_here` to enable Kimi
3. Restart services: `docker compose restart backend celery-worker`

### Migrating from Development to Production

No changes required - the routing logic automatically handles Gemini availability!

Simply set the `GEMINI_API_KEY` in your `.env.production` file.

## Summary

- **3 AI Services** with automatic fallback and privacy-first routing
- **Cost Tracking** for all API calls with daily budget enforcement
- **Zero Configuration** fallback for high availability
- **Document Classification** automatically handled based on bucket
- **Monitoring** via `/api/v1/health/detailed` endpoint
