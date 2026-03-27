# SOWKNOW Gemini Flash Implementation Plan
## Replacing Kimi 2.5 (Moonshot API) with Gemini Flash (Google AI)

**Date:** February 10, 2026
**Status:** Planning Phase
**Version:** 1.0

---

## Executive Summary

This plan details the implementation of **Gemini Flash** as the primary cloud LLM for SOWKNOW, replacing the existing Kimi 2.5 (Moonshot API) integration. The pivot is driven by Gemini's superior capabilities:

| Feature | Kimi 2.5 | Gemini Flash | Impact |
|---------|----------|--------------|--------|
| Context Window | 128K tokens | 1M+ tokens | 8x improvement |
| Context Caching | None | Native support | Up to 80% cost savings |
| Multilingual | Good | Native FR/EN | Better localization |
| API Client | httpx | google-generativeai SDK | Enhanced streaming |

---

## Architecture Overview

### Current State (Kimi 2.5)

```
┌─────────────────────────────────────────────────────────────┐
│                     ChatService                              │
│  ┌─────────────────┐              ┌──────────────────┐      │
│  │  KimiService    │              │  OllamaService   │      │
│  │  (Moonshot API) │              │  (Local VPS)     │      │
│  └─────────────────┘              └──────────────────┘      │
│         ^                                  ^                 │
│         │ has_confidential=false          │ has_confidential=true
└─────────┼──────────────────────────────────┼─────────────────┘
          │                                  │
          ▼                                  ▼
    api.moonshot.cn                   localhost:11434
```

### Target State (Gemini Flash)

```
┌─────────────────────────────────────────────────────────────────┐
│                      ChatService                                 │
│  ┌─────────────────┐              ┌──────────────────┐          │
│  │ GeminiService   │              │  OllamaService   │          │
│  │ (Google AI API) │              │  (Local VPS)     │          │
│  │                 │              │                  │          │
│  │ • Context Cache │              │  • Privacy mode  │          │
│  │ • 1M+ tokens    │              │  • CPU inference │          │
│  │ • Streaming     │              │                  │          │
│  └─────────────────┘              └──────────────────┘          │
│         ^                                  ^                     │
│         │ has_confidential=false          │ has_confidential=true
└─────────┼──────────────────────────────────┼─────────────────────┘
          │                                  │
          ▼                                  ▼
    generativelanguage.googleapis.com  localhost:11434
```

---

## Implementation Tasks

### Phase 1: Foundation (Day 1-2)

#### Task 1.1: Environment Configuration
**Priority:** P0 | **Estimated Time:** 30 minutes

| Step | Action | File |
|------|--------|------|
| 1.1 | Add GEMINI_API_KEY to .env template | `.env.example` |
| 1.2 | Add GEMINI_MODEL configuration | `.env.example` |
| 1.3 | Add GEMINI_CACHE_TTL setting | `.env.example` |
| 1.4 | Add GEMINI_DAILY_BUDGET_CAP setting | `.env.example` |

**Environment Variables to Add:**
```bash
# Gemini Flash Configuration
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-2.0-flash-exp
GEMINI_MAX_TOKENS=1000000
GEMINI_CACHE_TTL=3600  # 1 hour
GEMINI_DAILY_BUDGET_CAP=50.00  # USD
```

#### Task 1.2: Install Dependencies
**Priority:** P0 | **Estimated Time:** 15 minutes

```bash
# backend/requirements.txt
google-generativeai>=0.8.0
```

#### Task 1.3: Update Configuration Module
**Priority:** P0 | **Estimated Time:** 30 minutes

Create `backend/app/core/config.py` (if not exists) or update existing:

```python
# Gemini Configuration
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.0-flash-exp")
GEMINI_MAX_TOKENS: int = int(os.getenv("GEMINI_MAX_TOKENS", "1000000"))
GEMINI_CACHE_TTL: int = int(os.getenv("GEMINI_CACHE_TTL", "3600"))
GEMINI_DAILY_BUDGET_CAP: float = float(os.getenv("GEMINI_DAILY_BUDGET_CAP", "50.00"))
```

---

### Phase 2: Core Service Implementation (Day 2-4)

#### Task 2.1: Create GeminiService
**Priority:** P0 | **Estimated Time:** 4 hours

**File:** `backend/app/services/gemini_service.py`

**Interface Requirements:**
```python
class GeminiService:
    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        stream: bool = False,
        temperature: float = 0.7,
        max_tokens: int = 8192,
        cache_key: Optional[str] = None
    ) -> AsyncGenerator[str, None]
```

**Key Features to Implement:**

1. **Basic Chat Completion**
   - Use google-generativeai SDK
   - Support streaming responses
   - Error handling with retry logic

2. **Context Caching**
   - Implement cache key generation
   - Cache frequently accessed collections
   - Track cache hit/miss metrics
   - Return usage metadata including cache stats

3. **Usage Tracking**
   - Prompt tokens
   - Cached content tokens
   - Completion tokens
   - Total tokens

4. **Health Check**
   - Verify API connectivity
   - Return model info

**Implementation Outline:**

```python
"""
Gemini Flash service for RAG-powered conversations with context caching
"""
import os
import logging
import json
import asyncio
from typing import AsyncGenerator, List, Dict, Any, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass

import google.generativeai as genai
from google.generativeai.types import (
    GenerateContentResponse,
    ContentType,
    CachedContent
)
from tenacity import retry, stop_after_attempt, wait_exponential

from app.models.chat import LLMProvider

logger = logging.getLogger(__name__)

# Configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash-exp")
GEMINI_MAX_TOKENS = int(os.getenv("GEMINI_MAX_TOKENS", "1000000"))
GEMINI_CACHE_TTL = int(os.getenv("GEMINI_CACHE_TTL", "3600"))

# Initialize Gemini API
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)


@dataclass
class GeminiUsageMetadata:
    """Gemini usage metadata with cache information"""
    prompt_tokens: int
    cached_tokens: int
    completion_tokens: int
    total_tokens: int
    cache_hit: bool = False
    cache_key: Optional[str] = None


@dataclass
class GeminiResponse:
    """Gemini response with metadata"""
    content: str
    usage: GeminiUsageMetadata
    model: str
    finish_reason: Optional[str] = None


class GeminiCacheManager:
    """
    Manages context caching for Gemini Flash

    Caching strategy:
    - Pinned Collections: Cache full collection text (60-80% savings)
    - Smart Folders: Cache generated article (80% savings)
    - Follow-up Q&A: Cache conversation context (50-70% savings)
    """

    def __init__(self, ttl: int = GEMINI_CACHE_TTL):
        self.ttl = ttl
        self._cache: Dict[str, tuple[CachedContent, datetime]] = {}

    def _generate_cache_key(self, content: str) -> str:
        """Generate cache key from content"""
        import hashlib
        return hashlib.sha256(content.encode()).hexdigest()[:32]

    async def get_cached_content(
        self,
        content: str,
        model: str = GEMINI_MODEL
    ) -> Optional[CachedContent]:
        """Get cached content if available and not expired"""
        key = self._generate_cache_key(content)

        if key in self._cache:
            cached_content, expiry = self._cache[key]
            if datetime.now() < expiry:
                logger.info(f"Cache HIT for key: {key}")
                return cached_content
            else:
                # Expired, remove
                del self._cache[key]
                logger.info(f"Cache EXPIRED for key: {key}")

        return None

    async def create_cached_content(
        self,
        content: str,
        model: str = GEMINI_MODEL
    ) -> CachedContent:
        """Create new cached content"""
        # Build cached content for large context
        cached_content = genai.caching.CachedContent.create(
            model=model,
            content=content,
            system_instruction=None,
        )

        # Store with expiry
        key = self._generate_cache_key(content)
        expiry = datetime.now() + timedelta(seconds=self.ttl)
        self._cache[key] = (cached_content, expiry)

        logger.info(f"Cache CREATED for key: {key} (TTL: {self.ttl}s)")
        return cached_content

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        total = len(self._cache)
        expired = sum(
            1 for _, expiry in self._cache.values()
            if datetime.now() >= expiry
        )
        return {
            "total_entries": total,
            "active_entries": total - expired,
            "expired_entries": expired,
            "ttl_seconds": self.ttl
        }


class GeminiService:
    """
    Service for interacting with Gemini Flash (Google Generative AI)

    Features:
    - 1M+ token context window
    - Native context caching for cost optimization
    - Streaming responses
    - Bilingual support (FR/EN)
    """

    def __init__(self):
        self.api_key = GEMINI_API_KEY
        self.model_name = GEMINI_MODEL
        self.max_tokens = GEMINI_MAX_TOKENS
        self.cache_manager = GeminiCacheManager()

        if not self.api_key:
            logger.warning("GEMINI_API_KEY not configured")

        # Initialize model
        self.model = genai.GenerativeModel(self.model_name) if self.api_key else None

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        stream: bool = False,
        temperature: float = 0.7,
        max_tokens: int = 8192,
        cache_key: Optional[str] = None
    ) -> AsyncGenerator[str, None]:
        """
        Generate chat completion using Gemini Flash

        Args:
            messages: List of message dicts with role and content
            stream: Whether to stream the response
            temperature: Sampling temperature (0.0 - 1.0)
            max_tokens: Maximum tokens to generate
            cache_key: Optional key for context caching

        Yields:
            Response text chunks if streaming, or full content + usage metadata
        """
        if not self.api_key:
            logger.error("GEMINI_API_KEY not configured")
            yield "Error: Gemini API key not configured"
            return

        try:
            # Convert messages to Gemini format
            gemini_messages = self._convert_messages(messages)

            # Check for cached context
            cached_content = None
            if cache_key:
                cached_content = await self.cache_manager.get_cached_content(cache_key)

            # Configure generation
            generation_config = genai.types.GenerationConfig(
                temperature=temperature,
                max_output_tokens=max_tokens,
            )

            # Start chat or use cached content
            if cached_content:
                logger.info(f"Using cached content for key: {cache_key}")
                response = await self._generate_with_cache(
                    cached_content,
                    gemini_messages[-1]["content"],  # Last message is user query
                    generation_config
                )
            else:
                response = await self._generate_direct(
                    gemini_messages,
                    generation_config,
                    stream=stream
                )

            # Handle response
            if stream:
                async for chunk in self._stream_response(response):
                    yield chunk
            else:
                yield response.content
                # Yield usage metadata
                usage = self._extract_usage_metadata(response, cached_content is not None)
                yield f"\n__USAGE__: {json.dumps({
                    'prompt_tokens': usage.prompt_tokens,
                    'cached_tokens': usage.cached_tokens,
                    'completion_tokens': usage.completion_tokens,
                    'total_tokens': usage.total_tokens,
                    'cache_hit': usage.cache_hit,
                    'cache_key': usage.cache_key
                })}"

        except Exception as e:
            logger.error(f"Gemini API error: {str(e)}")
            yield f"Error: {str(e)}"

    def _convert_messages(self, messages: List[Dict[str, str]]) -> List[Dict]:
        """Convert chat messages to Gemini format"""
        gemini_messages = []

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            # Gemini uses 'user' and 'model' roles
            if role == "assistant":
                role = "model"
            elif role == "system":
                # System messages become part of first user message
                if gemini_messages:
                    gemini_messages[0]["parts"] = [{
                        "text": f"{content}\n\n" + gemini_messages[0]["parts"][0]["text"]
                    }]
                else:
                    gemini_messages.append({
                        "role": "user",
                        "parts": [{"text": content}]
                    })
                continue

            if role == "user":
                if gemini_messages and gemini_messages[-1]["role"] == "user":
                    # Combine consecutive user messages
                    gemini_messages[-1]["parts"][0]["text"] += f"\n\n{content}"
                else:
                    gemini_messages.append({
                        "role": "user",
                        "parts": [{"text": content}]
                    })
            else:  # model
                gemini_messages.append({
                    "role": "model",
                    "parts": [{"text": content}]
                })

        return gemini_messages

    async def _generate_direct(
        self,
        messages: List[Dict],
        config: genai.types.GenerationConfig,
        stream: bool = False
    ):
        """Generate without caching"""
        if stream:
            return self.model.send_message(
                messages,
                generation_config=config,
                stream=True
            )
        else:
            return self.model.send_message(
                messages,
                generation_config=config,
                stream=False
            )

    async def _generate_with_cache(
        self,
        cached_content: CachedContent,
        query: str,
        config: genai.types.GenerationConfig
    ):
        """Generate using cached content"""
        # Create model with cached content
        cached_model = genai.GenerativeModel.from_cached_content(cached_content)
        return cached_model.send_message(
            query,
            generation_config=config
        )

    async def _stream_response(self, response) -> AsyncGenerator[str, None]:
        """Stream response chunks"""
        async for chunk in response:
            if chunk.text:
                yield chunk.text

    def _extract_usage_metadata(
        self,
        response,
        cache_hit: bool
    ) -> GeminiUsageMetadata:
        """Extract usage metadata from response"""
        # Gemini returns usage in response.metadata
        metadata = getattr(response, 'usage_metadata', {})

        return GeminiUsageMetadata(
            prompt_tokens=metadata.get('prompt_token_count', 0),
            cached_tokens=metadata.get('cached_content_token_count', 0),
            completion_tokens=metadata.get('candidates_token_count', 0),
            total_tokens=metadata.get('total_token_count', 0),
            cache_hit=cache_hit,
            cache_key=None  # Will be set by caller
        )

    async def health_check(self) -> Dict[str, Any]:
        """Check Gemini API health"""
        try:
            if not self.api_key:
                return {
                    "status": "error",
                    "message": "GEMINI_API_KEY not configured"
                }

            # Simple test call
            model_info = genai.get_model(self.model_name)

            return {
                "status": "healthy",
                "model": self.model_name,
                "display_name": model_info.display_name,
                "description": model_info.description,
                "cache_stats": self.cache_manager.get_stats()
            }
        except Exception as e:
            return {
                "status": "error",
                "message": str(e)
            }

    async def create_collection_cache(
        self,
        documents: List[str],
        cache_key: str
    ) -> bool:
        """
        Create a cached content for a collection of documents

        This is used for Smart Collections and Smart Folders to enable
        up to 80% cost reduction on recurring queries.
        """
        try:
            # Combine documents into context
            context = "\n\n---\n\n".join(documents)

            # Create cached content
            await self.cache_manager.create_cached_content(
                content=context,
                model=self.model_name
            )

            logger.info(f"Collection cache created: {cache_key}")
            return True
        except Exception as e:
            logger.error(f"Failed to create collection cache: {e}")
            return False

    async def get_cache_hit_rate(self) -> float:
        """Get cache hit rate for monitoring"""
        stats = self.cache_manager.get_stats()
        if stats["total_entries"] == 0:
            return 0.0
        return stats["active_entries"] / stats["total_entries"]


# Global Gemini service instance
gemini_service = GeminiService()
```

#### Task 2.2: Update LLMProvider Enum
**Priority:** P0 | **Estimated Time:** 15 minutes

**File:** `backend/app/models/chat.py`

```python
class LLMProvider(str, enum.Enum):
    """LLM providers used for chat responses"""
    GEMINI = "gemini"       # Google Gemini Flash API
    OLLAMA = "ollama"       # Shared local Ollama instance
```

#### Task 2.3: Update ChatService
**Priority:** P0 | **Estimated Time:** 2 hours

**File:** `backend/app/services/chat_service.py`

**Changes:**
1. Replace `KimiService` import with `GeminiService`
2. Update `self.kimi_service = KimiService()` to `self.gemini_service = GeminiService()`
3. Update all references from `LLMProvider.KIMI` to `LLMProvider.GEMINI`
4. Add cache_key parameter when calling Gemini
5. Update documentation comments

---

### Phase 3: Integration & Testing (Day 4-5)

#### Task 3.1: Update API Endpoints
**Priority:** P1 | **Estimated Time:** 2 hours

**Files to update:**
- `backend/app/api/chat.py`
- `backend/app/api/admin.py` (for stats)

**Changes:**
1. Update streaming endpoint to include cache status
2. Add cache hit-rate to admin stats endpoint
3. Update response schemas to include cache metadata

#### Task 3.2: Update Health Check
**Priority:** P0 | **Estimated Time:** 1 hour

**File:** `backend/app/api/health.py` (or main.py)

```python
@router.get("/health")
async def health_check():
    """Comprehensive health check"""
    health_status = {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "services": {
            "postgres": await check_postgres(),
            "redis": await check_redis(),
            "gemini": await gemini_service.health_check(),
            "ollama": await check_ollama(),
        }
    }
    return health_status
```

#### Task 3.3: Add Monitoring Metrics
**Priority:** P1 | **Estimated Time:** 2 hours

**New File:** `backend/app/services/cache_monitor.py`

```python
"""
Cache monitoring service for Gemini Flash context caching
Tracks cache hit-rate, cost savings, and performance metrics
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, Any
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class CacheMonitor:
    """Monitor Gemini Flash context caching performance"""

    def __init__(self):
        self._daily_stats: Dict[str, Dict] = {}

    async def record_cache_hit(
        self,
        cache_key: str,
        tokens_saved: int,
        user_id: str
    ):
        """Record a cache hit event"""
        today = datetime.now().strftime("%Y-%m-%d")
        if today not in self._daily_stats:
            self._daily_stats[today] = {
                "hits": 0,
                "misses": 0,
                "tokens_saved": 0,
                "queries": 0
            }

        self._daily_stats[today]["hits"] += 1
        self._daily_stats[today]["tokens_saved"] += tokens_saved
        self._daily_stats[today]["queries"] += 1

    async def record_cache_miss(self, cache_key: str, user_id: str):
        """Record a cache miss event"""
        today = datetime.now().strftime("%Y-%m-%d")
        if today not in self._daily_stats:
            self._daily_stats[today] = {
                "hits": 0,
                "misses": 0,
                "tokens_saved": 0,
                "queries": 0
            }

        self._daily_stats[today]["misses"] += 1
        self._daily_stats[today]["queries"] += 1

    def get_hit_rate(self, days: int = 1) -> float:
        """Get cache hit rate for recent days"""
        total_hits = 0
        total_queries = 0

        cutoff_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

        for date, stats in self._daily_stats.items():
            if date >= cutoff_date:
                total_hits += stats["hits"]
                total_queries += stats["queries"]

        if total_queries == 0:
            return 0.0
        return total_hits / total_queries

    def get_stats_summary(self) -> Dict[str, Any]:
        """Get comprehensive cache statistics"""
        return {
            "daily_stats": self._daily_stats,
            "hit_rate_1day": self.get_hit_rate(1),
            "hit_rate_7day": self.get_hit_rate(7),
            "total_tokens_saved": sum(
                s["tokens_saved"] for s in self._daily_stats.values()
            )
        }


# Global cache monitor instance
cache_monitor = CacheMonitor()
```

---

### Phase 4: Frontend Updates (Day 5)

#### Task 4.1: Update Chat UI
**Priority:** P1 | **Estimated Time:** 2 hours

**File:** `frontend/components/chat/ChatMessage.tsx`

**Changes:**
1. Add cache hit/miss indicator
2. Update model display to show "Gemini Flash" instead of "Kimi 2.5"
3. Add "Local LLM is thinking..." for Ollama

```typescript
interface ChatMessageProps {
  content: string;
  llmUsed: 'gemini' | 'ollama';
  cacheHit?: boolean;
  sources?: Source[];
}

// Add cache indicator badge
{llmUsed === 'gemini' && (
  <Tooltip content={cacheHit ? "Response from cached context" : "New query"}>
    <Badge variant={cacheHit ? "success" : "neutral"}>
      {cacheHit ? "Cached" : "Gemini Flash"}
    </Badge>
  </Tooltip>
)}
```

#### Task 4.2: Update Admin Dashboard
**Priority:** P2 | **Estimated Time:** 2 hours

**File:** `frontend/app/dashboard/page.tsx`

**Add:**
- Cache hit-rate metric card
- Daily token cost tracking
- Cache efficiency chart

---

### Phase 5: Cleanup & Documentation (Day 6)

#### Task 5.1: Remove Legacy Code
**Priority:** P1 | **Estimated Time:** 2 hours

**Files to clean:**
1. Remove any remaining `kimi_service.py` references
2. Remove `MOONSHOT_API_KEY` from config
3. Update all imports and documentation

#### Task 5.2: Update Documentation
**Priority:** P1 | **Estimated Time:** 2 hours

**Documents to update:**
1. `CLAUDE.md` - Update LLM references
2. `SOWKNOW_TechStack_v1.1.md` - Update to v1.2 with Gemini
3. API documentation
4. Deployment runbook

#### Task 5.3: Update Requirements.txt
**Priority:** P0 | **Estimated Time:** 15 minutes

**File:** `backend/requirements.txt`

```
# Remove:
# httpx>=0.25.0 (keep for Ollama, just remove Moonshot dependency)

# Add:
google-generativeai>=0.8.0
```

---

## File Structure Summary

### New Files
```
backend/app/services/
├── gemini_service.py          # NEW: Gemini Flash integration
├── cache_monitor.py           # NEW: Cache performance monitoring
└── gemini_cache.py            # NEW: Context caching manager (optional separate)
```

### Modified Files
```
backend/app/
├── models/chat.py             # UPDATE: LLMProvider enum
├── services/chat_service.py   # UPDATE: Use GeminiService
├── api/chat.py                # UPDATE: Cache metadata in responses
├── api/admin.py               # UPDATE: Cache stats in dashboard
├── api/health.py              # UPDATE: Gemini health check
├── core/config.py             # UPDATE: Gemini config vars
└── requirements.txt           # UPDATE: Add google-generativeai

frontend/
├── components/chat/ChatMessage.tsx  # UPDATE: Cache indicators
├── app/dashboard/page.tsx           # UPDATE: Cache stats
└── lib/api.ts                       # UPDATE: Response types
```

### Files to Remove
```
backend/app/services/kimi_service.py  # DELETE: Replaced by gemini_service.py
```

---

## Testing Checklist

### Unit Tests
- [ ] GeminiService.chat_completion (streaming)
- [ ] GeminiService.chat_completion (non-streaming)
- [ ] GeminiCacheManager.get_cached_content
- [ ] GeminiCacheManager.create_cached_content
- [ ] GeminiService.health_check
- [ ] CacheMonitor.record_cache_hit/miss
- [ ] CacheMonitor.get_hit_rate

### Integration Tests
- [ ] End-to-end chat flow with Gemini
- [ ] Confidential routing (Gemini → Ollama switch)
- [ ] Cache creation for collections
- [ ] Cache hit on subsequent queries
- [ ] Health check endpoint
- [ ] Admin dashboard cache stats

### Manual Tests
- [ ] Verify GEMINI_API_KEY works
- [ ] Test streaming responses
- [ ] Test cache hit/miss indicators in UI
- [ ] Verify confidential documents route to Ollama
- [ ] Check token usage tracking
- [ ] Verify cost cap alerts

---

## Rollback Plan

If issues arise with Gemini Flash integration:

1. **Immediate Rollback** (5 minutes):
   - Revert `chat_service.py` to use `KimiService`
   - Restore `MOONSHOT_API_KEY` environment variable

2. **Full Rollback** (30 minutes):
   - Restore all files from git commit before migration
   - Restart all containers
   - Verify Kimi 2.5 works

3. **Fallback Option**:
   - Configure OpenRouter as backup cloud LLM
   - Update `GeminiService` to support multiple providers

---

## Success Criteria

| Metric | Target | Measurement |
|--------|--------|-------------|
| API Response Time | <3s (p95) | Monitoring |
| Cache Hit Rate | >30% (Day 1), >50% (Week 1) | Cache stats |
| Cost Reduction | >40% vs Kimi 2.5 | Token tracking |
| Uptime | >99.5% | Health checks |
| Error Rate | <5% | Error monitoring |

---

## Next Steps

Once approved, execute in order:

1. **Day 1 Morning:** Acquire GEMINI_API_KEY from Google Cloud Console
2. **Day 1 Mid:** Install dependencies, update config
3. **Day 2:** Create `gemini_service.py`
4. **Day 3:** Update `chat_service.py` and models
5. **Day 4:** Integrate and test
6. **Day 5:** Frontend updates
7. **Day 6:** Cleanup and documentation

---

**Document Version:** 1.0
**Author:** Claude Code
**Status:** Ready for Review
