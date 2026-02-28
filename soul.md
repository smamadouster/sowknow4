# SOWKNOW — Soul Document

## Mission

SOWKNOW (Sow & Know) transforms a lifetime of scattered digital artifacts — documents,
photos, receipts, handwritten notes, correspondence — into a queryable wisdom system
that preserves multi-generational family knowledge.

## Core Principles

### 1. Privacy Is Non-Negotiable

No personally identifiable information ever leaves the infrastructure boundary.
Confidential documents are processed exclusively by Ollama running on the local VPS.
Cloud LLMs (MiniMax, Kimi) handle only public-bucket content. This is enforced at the
architecture level through the Tri-LLM router, not by policy alone.

### 2. Tri-LLM Intelligence

Three language models serve distinct trust zones:

- **MiniMax** (via OpenRouter): Public document search, summarization, and synthesis.
  Context caching reduces cost by >60%.
- **Kimi** (Moonshot AI): Chatbot conversations, Telegram bot, and interactive search.
- **Ollama** (local): Confidential document processing. Never touches the network.

### 3. Role-Based Access Control

Three tiers enforce the principle of least privilege:

- **Admin**: Full system access — create, read, update, delete, manage users.
- **Super User**: Read-only access to all documents including confidential. Cannot modify.
- **User**: Public documents only. Confidential content is invisible.

### 4. Resource Discipline

SOWKNOW shares a 16 GB VPS with other services. Total container memory must stay
under 6.4 GB. Every container has explicit memory limits. The embedding model
(multilingual-e5-large, 1.3 GB) runs in a single-concurrency Celery worker to
prevent OOM kills.

### 5. Bilingual by Default

French is the primary language. English is fully supported. The AI responds in the
language of the query. All UI strings exist in both locales.

### 6. Graceful Degradation

If Redis is down, rate limiting fails open. If Ollama is unreachable, confidential
queries return a clear error rather than routing to cloud. If OCR (PaddleOCR) fails,
Tesseract takes over. The system bends but does not break.

### 7. Auditable Operations

Every confidential document access is logged with timestamp, user ID, and action.
LLM routing decisions are recorded. Password resets are audited. The system maintains
a verifiable chain of accountability.

## Architecture Identity

SOWKNOW is not a generic document management system. It is a **legacy knowledge vault**
— designed for a family, built for generations. Speed matters less than accuracy.
Features matter less than trust. Scale matters less than privacy.
