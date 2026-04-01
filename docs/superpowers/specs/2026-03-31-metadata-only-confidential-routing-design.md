# Metadata-Only Confidential Routing

**Date:** 2026-03-31
**Status:** Approved

## Problem

When a search query matches confidential documents, the chat pipeline routes the entire request (including full chunk text) through Ollama for local privacy-preserving inference. Ollama on a CPU-only VPS is fundamentally non-viable for interactive chat: 25-40s latency per request, constant memory pressure, and any background task (entity extraction, health checks) blocks the single-threaded inference queue. This makes confidential search unusable.

## Decision

Strip confidential search results to metadata only before they reach the LLM prompt. Route ALL chat generation through cloud LLMs (OpenRouter/MiniMax fallback chain). Ollama is removed from the critical path.

**Privacy guarantee preserved:** Confidential document text never leaves the server. Only document-level metadata (filename, date, page count, mime type, tags) reaches external APIs.

## Design

### Data Flow

```
User query
  → hybrid_search (respects RBAC bucket filtering)
  → retrieve_relevant_chunks:
      → public results: full chunk text retained
      → confidential results: chunk_text replaced with metadata summary
  → build_rag_context:
      → public sources labeled "[Public]" with full text
      → confidential sources labeled "[Confidential, metadata only]" with metadata
      → system prompt instructs LLM not to fabricate confidential content
  → llm_router.select_provider (always public fallback chain)
  → cloud LLM generates response
  → response references confidential docs by name, directs user to review directly
```

### Changes by File

#### `backend/app/services/chat_service.py` — `retrieve_relevant_chunks()`

After search results return, split by bucket:

- **Public results:** No change. Full `chunk_text` passes through.
- **Confidential results:**
  - Replace `chunk_text` with `"[Confidential document — content not sent to AI]"`
  - Add metadata fields: `created_at`, `page_count`, `mime_type`, `tags`
  - Batch-fetch Document metadata for confidential results only (single query by document IDs)
- `has_confidential` flag still computed (for audit logging and UI badges)
- Add `bucket` field to each source dict

#### `backend/app/services/chat_service.py` — `build_rag_context()`

Update context formatting to distinguish source types:

```
[Document 1 — Public] invoice_2024.pdf
<full chunk text here>

[Document 2 — Confidential, metadata only] passport_scan.pdf | pages: 2 | type: PDF | uploaded: 2024-03-15 | tags: identity, passport
```

Update system prompt to include:

> "Some search results are from confidential documents. For these, only metadata is provided — the document content is kept private. Do not fabricate or infer their contents. When referencing confidential documents, direct the user to review them directly in the vault."

#### `backend/app/services/chat_service.py` — `generate_chat_response()` and `generate_chat_response_stream()`

- Remove the `if has_confidential:` Ollama health check gate
- Remove DeferredQueryService queueing for confidential queries
- Pass `has_confidential=False` to `llm_router.select_provider()` since no confidential text reaches the LLM. The `has_confidential` flag on the response dict is still set truthfully for audit logging and UI display — it just no longer gates LLM routing.
- All queries use the public fallback chain: MiniMax → OpenRouter → Ollama

#### `backend/app/services/llm_router.py`

No structural changes. The confidential routing path becomes dead code. It can be cleaned up or left as-is for future use with better hardware.

### Metadata Fetching Strategy

Batch-fetch from Document model only when confidential results exist:

```python
if confidential_doc_ids:
    docs = await db.execute(
        select(Document).where(Document.id.in_(confidential_doc_ids))
    )
    doc_metadata = {str(d.id): d for d in docs.scalars().all()}
```

Fields used in metadata summary: `filename`, `created_at`, `page_count`, `mime_type`, `tags` (via relationship).

### What Stays the Same

- **RBAC/bucket filtering** — search still respects user roles (admin/superuser see confidential, users don't)
- **Audit logging** — confidential document access still logged
- **PII detection** — InputGuard still flags PII in queries
- **Search layer** — `hybrid_search()`, `SearchResult`, no changes
- **Telegram bot** — no changes needed
- **Frontend** — no changes needed
- **Ollama service** — stays available, just not on the critical chat path

### Mixed Results Handling (Option C)

When a query returns both public and confidential results, the cloud LLM receives:
- Full chunk text from public documents
- Metadata-only summaries from confidential documents
- System prompt labels each source type clearly

The LLM produces a coherent response that synthesizes public content and references confidential documents by name/metadata without fabricating their contents.

### Example Response

User query: "Mansour"

LLM receives:
```
[Document 1 — Confidential, metadata only] 765 courrier du 27 04 09 email à Mr Issa Mansour AFANOU.doc | pages: 1 | type: DOC | uploaded: 2026-03-28 | tags: correspondence
```

LLM responds:
> "I found a confidential document in your vault related to Mansour: a correspondence letter ('765 courrier du 27 04 09 email à Mr Issa Mansour AFANOU.doc') uploaded on March 28, 2026. Since this is a confidential document, I can't show its contents here — you can open it directly from your document list to review it."

### Performance Impact

- Search latency: unchanged
- LLM latency: ~2-5s via OpenRouter (vs 25-60s+ via Ollama)
- No Ollama dependency for interactive chat
- No memory contention with background tasks

### Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| Metadata itself could be sensitive (e.g., filename contains person's name) | Filenames are already visible in the UI to authorized users. The metadata exposure to the cloud LLM is equivalent to what the search API already returns. |
| LLM hallucinates confidential document contents | System prompt explicitly forbids this. Response quality can be monitored. |
| Future need for full confidential RAG | Ollama path preserved as dead code. Can be re-enabled when GPU hardware or a faster local model is available. |
