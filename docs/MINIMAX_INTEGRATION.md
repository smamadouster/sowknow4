# Minimax 2.5 Integration Documentation

## Overview

SOWKNOW uses OpenRouter as the primary API gateway to access Minimax models, specifically `minimax/minimax-01`. This provides cost-effective AI processing for public documents while maintaining privacy compliance.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        SOWKNOW System                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐    ┌─────────────────┐    ┌──────────────┐  │
│  │   User       │───▶│   Chat Service   │───▶│   Routing    │  │
│  │   Query      │    │                 │    │   Logic      │  │
│  └──────────────┘    └─────────────────┘    └──────┬───────┘  │
│                                                    │           │
│              ┌─────────────────────────────────────┼────────┐  │
│              │                                     │        │  │
│              ▼                                     ▼        ▼  │
│     ┌─────────────────┐              ┌──────────────────┐     │
│     │ Public Docs     │              │ Confidential    │     │
│     │ (No PII)       │              │ Docs OR PII     │     │
│     └────────┬────────┘              └────────┬─────────┘     │
│              │                                │               │
│              ▼                                ▼               │
│     ┌─────────────────┐              ┌──────────────────┐     │
│     │ OpenRouter     │              │ Ollama           │     │
│     │ (Minimax-01)  │              │ (Local/Mistral)  │     │
│     │ Cost: $0.25/M  │              │ Cost: $0.00      │     │
│     └─────────────────┘              └──────────────────┘     │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## Routing Decision Matrix

| Document Type | PII Detected | User Role | LLM Provider |
|---------------|--------------|-----------|--------------|
| Public        | No           | Any       | Minimax      |
| Public        | Yes          | Any       | Ollama       |
| Confidential  | No           | Admin     | Ollama       |
| Confidential  | No           | SuperUser | Ollama       |
| Confidential  | Any          | User      | (Hidden)     |
| Any           | Any          | Any       | Ollama       |

## API Configuration

### Environment Variables

```bash
# OpenRouter (Minimax)
OPENROUTER_API_KEY=sk-or-v1-xxxxx  # Required for Minimax access
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_MODEL=minimax/minimax-01
OPENROUTER_SITE_URL=https://sowknow.gollamtech.com
OPENROUTER_SITE_NAME=SOWKNOW

# Ollama (Local - for confidential)
OLLAMA_BASE_URL=http://host.docker.internal:11434
OLLAMA_MODEL=mistral
```

### Model Specifications

| Model | Context Window | Input Cost | Output Cost |
|-------|---------------|------------|-------------|
| minimax/minimax-01 | 32K tokens | $0.10/1M | $0.25/1M |
| mistral (Ollama) | 8K tokens | $0.00 | $0.00 |

## Services Using Minimax

### Primary Services

1. **Chat Service** (`chat_service.py`)
   - Public document RAG: Uses Minimax
   - Confidential/PII: Routes to Ollama

2. **Collection Chat** (`collection_chat_service.py`)
   - Public collections: Uses Minimax
   - Confidential collections: Uses Ollama

3. **Search Service** (`search_service.py`)
   - Document retrieval with RBAC filtering
   - Returns context for LLM processing

### Secondary Services (Require Routing Fixes)

| Service | File | Current Behavior | Risk |
|---------|------|-----------------|------|
| Smart Folder | smart_folder_service.py | Uses Gemini | HIGH |
| Intent Parser | intent_parser.py | Uses Gemini | HIGH |
| Entity Extraction | entity_extraction_service.py | Uses Gemini | HIGH |
| Auto-Tagging | auto_tagging_service.py | Uses Gemini | HIGH |
| Report Generation | report_service.py | Uses Gemini | HIGH |
| Progressive Revelation | progressive_revelation_service.py | Uses Gemini | HIGH |
| Synthesis | synthesis_service.py | Uses Gemini | HIGH |
| Multi-Agent | All agents | Uses Gemini | CRITICAL |

## Token Consumption Optimization

### Caching Strategy

The system implements context caching for repeated queries:

```python
# Gemini caching (public docs only)
cache_key = hash(message.content)
if cache_key in cache:
    return cache[cache_key]
```

### Cost Optimization Rules

1. **Minimax for Public**: Use for all public document queries
2. **Ollama for Confidential**: Free local processing
3. **Cache Repeated Queries**: Reduces API calls by up to 80%
4. **Chunk Size Optimization**: 500-token chunks balance context/performance

### Cost Tracking

```bash
# Check daily costs
curl http://localhost:8000/api/v1/monitoring/costs | jq .
```

Response:
```json
{
  "date": "2026-02-16",
  "gemini": {
    "requests": 150,
    "input_tokens": 250000,
    "output_tokens": 75000,
    "cost_usd": 2.45
  },
  "openrouter": {
    "requests": 89,
    "input_tokens": 180000,
    "output_tokens": 42000,
    "cost_usd": 12.30
  },
  "total_cost_usd": 14.75,
  "budget_usd": 50.00,
  "remaining_usd": 35.25
}
```

## Known Issues

### FAIL: Context Window Enforcement

**Issue**: Minimax context window (32K tokens) is not enforced
**Impact**: Large queries may be truncated silently
**Status**: Requires implementation
**Fix Required**: Add token counting before API calls

### FAIL: Secondary Services Routing

**Issue**: 6+ services bypass routing and send data to Gemini
**Impact**: Potential PII leakage for Admin/SuperUser queries
**Status**: Documented in Agent 3 findings

## Testing

### Unit Tests

```bash
# Run LLM routing tests
pytest backend/tests/unit/test_llm_routing.py -v
```

### Integration Tests

```bash
# Run OpenRouter streaming tests
pytest backend/tests/integration/test_openrouter_streaming.py -v
```

## Troubleshooting

### Issue: OpenRouter API Errors

**Symptoms**: `Error: OpenRouter API key not configured`

**Solution**:
1. Check `OPENROUTER_API_KEY` is set in environment
2. Verify API key has sufficient credits
3. Check network connectivity to openrouter.ai

### Issue: High Costs

**Symptoms**: Daily cost exceeds budget

**Solutions**:
1. Enable stricter caching
2. Reduce max_tokens limit
3. Implement stricter PII detection thresholds

### Issue: Slow Responses

**Symptoms**: API timeouts

**Solutions**:
1. Check Ollama is running: `docker ps | grep ollama`
2. Verify network to OpenRouter
3. Add timeout configuration

## References

- OpenRouter API: https://openrouter.ai/docs
- Minimax Models: https://minimax.chat
- Pricing: https://openrouter.ai/docs/providers/minimax
