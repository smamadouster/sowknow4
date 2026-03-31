# Metadata-Only Confidential Routing — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Strip confidential search results to metadata-only before LLM prompts, route all chat through cloud LLMs, remove Ollama from the critical path.

**Architecture:** `retrieve_relevant_chunks()` splits results by bucket — public chunks keep full text, confidential chunks get replaced with a metadata summary. `build_rag_context()` labels each source type in the prompt. The `has_confidential` Ollama gate is removed from both streaming and non-streaming paths. All queries go through the public fallback chain (MiniMax → OpenRouter → Ollama).

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.0 async, pytest with SQLite (unit tests)

**Spec:** `docs/superpowers/specs/2026-03-31-metadata-only-confidential-routing-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `backend/app/services/chat_service.py` | Modify | Core changes: retrieve_relevant_chunks, build_rag_context, remove Ollama gates |
| `backend/tests/unit/test_chat_metadata_routing.py` | Create | Unit tests for the new metadata-only flow |

---

### Task 1: Test and implement metadata stripping in `retrieve_relevant_chunks`

**Files:**
- Create: `backend/tests/unit/test_chat_metadata_routing.py`
- Modify: `backend/app/services/chat_service.py:183-230`

- [ ] **Step 1: Write the failing test for confidential metadata stripping**

```python
# backend/tests/unit/test_chat_metadata_routing.py
"""Tests for metadata-only confidential routing in chat service."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from datetime import datetime, timezone


def _make_search_result(bucket="public", chunk_text="Some content", doc_name="test.pdf"):
    """Create a mock SearchResult with the fields used by retrieve_relevant_chunks."""
    r = MagicMock()
    r.document_bucket = bucket
    r.document_id = uuid4()
    r.document_name = doc_name
    r.chunk_id = uuid4()
    r.chunk_text = chunk_text
    r.final_score = 0.85
    return r


def _make_document(doc_id, filename="test.pdf", page_count=3, mime_type="application/pdf",
                   created_at=None, tags=None):
    """Create a mock Document model instance."""
    doc = MagicMock()
    doc.id = doc_id
    doc.filename = filename
    doc.page_count = page_count
    doc.mime_type = mime_type
    doc.created_at = created_at or datetime(2026, 3, 28, tzinfo=timezone.utc)
    doc.tags = tags or []
    return doc


def _make_tag(name, tag_type="topic"):
    tag = MagicMock()
    tag.tag_name = name
    tag.tag_type = tag_type
    return tag


class TestRetrieveRelevantChunksMetadata:
    """Test that confidential results are stripped to metadata only."""

    @pytest.mark.asyncio
    async def test_public_results_keep_full_chunk_text(self):
        """Public search results retain their full chunk text."""
        from app.services.chat_service import ChatService

        svc = ChatService()
        mock_db = AsyncMock()
        mock_user = MagicMock()
        mock_user.email = "test@sowknow.local"
        session_id = uuid4()

        public_result = _make_search_result(bucket="public", chunk_text="Full public content here")

        with patch("app.services.chat_service.search_service") as mock_search, \
             patch("app.services.chat_service.pii_detection_service") as mock_pii:
            mock_pii.detect_pii.return_value = False
            mock_search.hybrid_search = AsyncMock(return_value={
                "results": [public_result],
            })
            # Mock session lookup
            mock_scalar = MagicMock()
            mock_scalar.scalar_one_or_none.return_value = None
            mock_db.execute = AsyncMock(return_value=mock_scalar)

            sources, has_confidential = await svc.retrieve_relevant_chunks(
                query="test", session_id=session_id, db=mock_db, current_user=mock_user
            )

        assert len(sources) == 1
        assert sources[0]["chunk_text"] == "Full public content here"
        assert sources[0]["bucket"] == "public"
        assert has_confidential is False

    @pytest.mark.asyncio
    async def test_confidential_results_stripped_to_metadata(self):
        """Confidential search results have chunk_text replaced with metadata summary."""
        from app.services.chat_service import ChatService

        svc = ChatService()
        mock_db = AsyncMock()
        mock_user = MagicMock()
        mock_user.email = "test@sowknow.local"
        session_id = uuid4()

        conf_result = _make_search_result(
            bucket="confidential",
            chunk_text="SECRET: passport number 12345",
            doc_name="passport_scan.pdf",
        )

        mock_doc = _make_document(
            doc_id=conf_result.document_id,
            filename="passport_scan.pdf",
            page_count=2,
            mime_type="application/pdf",
            tags=[_make_tag("identity"), _make_tag("passport")],
        )

        with patch("app.services.chat_service.search_service") as mock_search, \
             patch("app.services.chat_service.pii_detection_service") as mock_pii:
            mock_pii.detect_pii.return_value = False
            mock_search.hybrid_search = AsyncMock(return_value={
                "results": [conf_result],
            })
            # Mock session lookup (first call) and document metadata fetch (second call)
            mock_session_result = MagicMock()
            mock_session_result.scalar_one_or_none.return_value = None
            mock_doc_result = MagicMock()
            mock_doc_result.scalars.return_value.all.return_value = [mock_doc]
            mock_db.execute = AsyncMock(side_effect=[mock_session_result, mock_doc_result])

            sources, has_confidential = await svc.retrieve_relevant_chunks(
                query="passport", session_id=session_id, db=mock_db, current_user=mock_user
            )

        assert len(sources) == 1
        assert has_confidential is True
        # Chunk text must NOT contain the original content
        assert "SECRET" not in sources[0]["chunk_text"]
        assert "12345" not in sources[0]["chunk_text"]
        # Must contain metadata indicator
        assert "Confidential" in sources[0]["chunk_text"]
        assert sources[0]["bucket"] == "confidential"
        # Metadata fields present
        assert sources[0]["page_count"] == 2
        assert sources[0]["mime_type"] == "application/pdf"
        assert "identity" in sources[0]["tags"]
        assert "passport" in sources[0]["tags"]

    @pytest.mark.asyncio
    async def test_mixed_results_split_correctly(self):
        """Mixed public + confidential results: public keeps text, confidential gets metadata."""
        from app.services.chat_service import ChatService

        svc = ChatService()
        mock_db = AsyncMock()
        mock_user = MagicMock()
        mock_user.email = "test@sowknow.local"
        session_id = uuid4()

        public_result = _make_search_result(bucket="public", chunk_text="Public info about Mansour")
        conf_result = _make_search_result(bucket="confidential", chunk_text="Private letter to Mansour", doc_name="letter.doc")

        mock_doc = _make_document(
            doc_id=conf_result.document_id,
            filename="letter.doc",
            page_count=1,
            mime_type="application/msword",
            tags=[_make_tag("correspondence")],
        )

        with patch("app.services.chat_service.search_service") as mock_search, \
             patch("app.services.chat_service.pii_detection_service") as mock_pii:
            mock_pii.detect_pii.return_value = False
            mock_search.hybrid_search = AsyncMock(return_value={
                "results": [public_result, conf_result],
            })
            mock_session_result = MagicMock()
            mock_session_result.scalar_one_or_none.return_value = None
            mock_doc_result = MagicMock()
            mock_doc_result.scalars.return_value.all.return_value = [mock_doc]
            mock_db.execute = AsyncMock(side_effect=[mock_session_result, mock_doc_result])

            sources, has_confidential = await svc.retrieve_relevant_chunks(
                query="Mansour", session_id=session_id, db=mock_db, current_user=mock_user
            )

        assert len(sources) == 2
        assert has_confidential is True
        # Public result keeps full text
        assert sources[0]["chunk_text"] == "Public info about Mansour"
        assert sources[0]["bucket"] == "public"
        # Confidential result stripped
        assert "Private letter" not in sources[1]["chunk_text"]
        assert sources[1]["bucket"] == "confidential"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/development/src/active/sowknow4/backend && python -m pytest tests/unit/test_chat_metadata_routing.py -v -x 2>&1 | tail -20`

Expected: FAIL — sources don't have `bucket` field, confidential text not stripped.

- [ ] **Step 3: Implement metadata stripping in `retrieve_relevant_chunks`**

In `backend/app/services/chat_service.py`, replace the `retrieve_relevant_chunks` method (lines 183-230) with:

```python
    async def retrieve_relevant_chunks(
        self, query: str, session_id: UUID, db, current_user: User
    ) -> tuple[list[dict], bool]:
        """
        Retrieve relevant document chunks for RAG.

        Confidential results are stripped to metadata only — the actual chunk
        text never reaches the LLM prompt.  Public results keep full text.

        Returns:
            Tuple of (source_documents, has_confidential)
        """
        # Check for PII in query for privacy protection
        has_pii = pii_detection_service.detect_pii(query)
        if has_pii:
            pii_summary = pii_detection_service.get_pii_summary(query)
            logger.warning(f"PII detected in chat query by user {current_user.email}: {pii_summary['detected_types']}")

        # Get session to check document scope
        session = (await db.execute(select(ChatSession).where(ChatSession.id == session_id))).scalar_one_or_none()

        # Perform search
        search_result = await search_service.hybrid_search(query=query, limit=10, offset=0, db=db, user=current_user)

        # Filter by document scope if specified
        if session and session.document_scope:
            scope_set = {str(doc_id) for doc_id in session.document_scope}
            search_result["results"] = [r for r in search_result["results"] if str(r.document_id) in scope_set]

        top_results = search_result["results"][:5]

        # Check for confidential documents OR PII in query
        has_confidential = any(r.document_bucket == "confidential" for r in top_results) or has_pii

        # Batch-fetch metadata for confidential documents
        confidential_doc_ids = [
            r.document_id for r in top_results if r.document_bucket == "confidential"
        ]
        doc_metadata: dict = {}
        if confidential_doc_ids:
            from app.models.document import Document
            result = await db.execute(
                select(Document).where(Document.id.in_(confidential_doc_ids))
            )
            for doc in result.scalars().all():
                doc_metadata[str(doc.id)] = doc

        # Format as source documents
        sources = []
        for r in top_results:
            if r.document_bucket == "confidential":
                # Metadata-only: strip chunk text, include document metadata
                doc = doc_metadata.get(str(r.document_id))
                tags = [t.tag_name for t in doc.tags] if doc and doc.tags else []
                page_count = doc.page_count if doc else None
                mime_type = doc.mime_type if doc else "unknown"
                created_at = doc.created_at.strftime("%Y-%m-%d") if doc and doc.created_at else "unknown"

                metadata_summary = (
                    f"[Confidential document — content not sent to AI] "
                    f"pages: {page_count or 'N/A'} | type: {mime_type} | "
                    f"uploaded: {created_at}"
                )
                if tags:
                    metadata_summary += f" | tags: {', '.join(tags)}"

                sources.append({
                    "document_id": r.document_id,
                    "document_name": r.document_name,
                    "chunk_id": r.chunk_id,
                    "chunk_text": metadata_summary,
                    "relevance_score": r.final_score,
                    "bucket": "confidential",
                    "page_count": page_count,
                    "mime_type": mime_type,
                    "created_at": created_at,
                    "tags": tags,
                })
            else:
                # Public: full chunk text
                chunk_text = r.chunk_text
                if has_pii:
                    chunk_text, _ = pii_detection_service.redact_pii(chunk_text)

                sources.append({
                    "document_id": r.document_id,
                    "document_name": r.document_name,
                    "chunk_id": r.chunk_id,
                    "chunk_text": chunk_text,
                    "relevance_score": r.final_score,
                    "bucket": "public",
                })

        return sources, has_confidential
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/development/src/active/sowknow4/backend && python -m pytest tests/unit/test_chat_metadata_routing.py -v -x 2>&1 | tail -20`

Expected: All 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/unit/test_chat_metadata_routing.py backend/app/services/chat_service.py
git commit -m "feat: strip confidential search results to metadata only

Confidential chunks get their text replaced with a metadata summary
(page count, mime type, upload date, tags). Public chunks keep full
text. Batch-fetches Document model for confidential results only."
```

---

### Task 2: Test and update `build_rag_context` to label sources by bucket

**Files:**
- Modify: `backend/tests/unit/test_chat_metadata_routing.py`
- Modify: `backend/app/services/chat_service.py:232-289`

- [ ] **Step 1: Write the failing test for context formatting**

Append to `backend/tests/unit/test_chat_metadata_routing.py`:

```python
class TestBuildRagContext:
    """Test that build_rag_context labels sources by bucket type."""

    def test_public_source_labeled_with_full_text(self):
        from app.services.chat_service import ChatService

        svc = ChatService()
        sources = [{
            "document_name": "invoice.pdf",
            "chunk_text": "Total amount: $500",
            "bucket": "public",
        }]
        messages = svc.build_rag_context("how much?", sources, [])

        system_content = messages[0]["content"]
        assert "[Document 1 — Public]" in system_content
        assert "Total amount: $500" in system_content

    def test_confidential_source_labeled_metadata_only(self):
        from app.services.chat_service import ChatService

        svc = ChatService()
        sources = [{
            "document_name": "passport.pdf",
            "chunk_text": "[Confidential document — content not sent to AI] pages: 2 | type: application/pdf | uploaded: 2026-03-28",
            "bucket": "confidential",
        }]
        messages = svc.build_rag_context("passport info", sources, [])

        system_content = messages[0]["content"]
        assert "[Document 1 — Confidential, metadata only]" in system_content
        assert "content not sent to AI" in system_content

    def test_system_prompt_includes_confidential_instruction(self):
        from app.services.chat_service import ChatService

        svc = ChatService()
        sources = [{
            "document_name": "secret.pdf",
            "chunk_text": "[Confidential document — content not sent to AI]",
            "bucket": "confidential",
        }]
        messages = svc.build_rag_context("query", sources, [])

        system_content = messages[0]["content"]
        assert "do not fabricate" in system_content.lower() or "Do not fabricate" in system_content

    def test_mixed_sources_both_labeled(self):
        from app.services.chat_service import ChatService

        svc = ChatService()
        sources = [
            {"document_name": "public.pdf", "chunk_text": "Public content", "bucket": "public"},
            {"document_name": "secret.pdf", "chunk_text": "[Confidential document — content not sent to AI]", "bucket": "confidential"},
        ]
        messages = svc.build_rag_context("query", sources, [])

        system_content = messages[0]["content"]
        assert "[Document 1 — Public]" in system_content
        assert "[Document 2 — Confidential, metadata only]" in system_content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/development/src/active/sowknow4/backend && python -m pytest tests/unit/test_chat_metadata_routing.py::TestBuildRagContext -v -x 2>&1 | tail -20`

Expected: FAIL — current code doesn't use bucket labels.

- [ ] **Step 3: Update `build_rag_context` implementation**

In `backend/app/services/chat_service.py`, replace the `build_rag_context` method (lines 232-289) with:

```python
    def build_rag_context(
        self,
        query: str,
        sources: list[dict],
        conversation_history: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        """
        Build RAG context with system prompt and retrieved documents.

        Public sources include full chunk text.
        Confidential sources include metadata only — no document content.
        """
        context_parts = []
        for i, source in enumerate(sources):
            bucket = source.get("bucket", "public")
            if bucket == "confidential":
                label = f"[Document {i + 1} — Confidential, metadata only] {source['document_name']}"
            else:
                label = f"[Document {i + 1} — Public] {source['document_name']}"
            context_parts.append(f"{label}\n{source['chunk_text']}\n")

        context_text = "\n".join(context_parts) if context_parts else "No relevant documents found."

        task_prompt = """Answer questions based on the provided context from documents.
If the context doesn't contain enough information, say so clearly.
Cite specific documents when providing information.
Be conversational and helpful.

For confidential documents, only metadata is provided — the document content is kept private.
Do not fabricate or infer their contents. When referencing confidential documents, direct the
user to review them directly in the vault.

Context from documents:
{context}

Remember: You're helping users access their own knowledge. Be accurate but also conversational."""

        system_prompt = build_service_prompt(
            service_name="SOWKNOW Chat Service",
            mission="Provide intelligent, context-aware conversational responses using RAG over the SOWKNOW vault",
            constraints=(
                "- You MUST cite source documents when referencing vault content\n"
                "- You MUST maintain conversation context across turns\n"
                "- You MUST NOT hallucinate information not in the retrieved documents\n"
                "- For confidential documents, only reference their name and metadata — never invent content"
            ),
            task_prompt=task_prompt,
        )

        messages = [{"role": "system", "content": system_prompt.format(context=context_text)}]

        for msg in conversation_history:
            messages.append({"role": msg["role"], "content": msg["content"]})

        messages.append({"role": "user", "content": query})

        return messages
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/development/src/active/sowknow4/backend && python -m pytest tests/unit/test_chat_metadata_routing.py -v -x 2>&1 | tail -20`

Expected: All tests PASS (Task 1 + Task 2).

- [ ] **Step 5: Commit**

```bash
git add backend/tests/unit/test_chat_metadata_routing.py backend/app/services/chat_service.py
git commit -m "feat: label sources by bucket in RAG context

Public sources show full text. Confidential sources show metadata only.
System prompt instructs LLM not to fabricate confidential content."
```

---

### Task 3: Test and remove Ollama confidential gate from `generate_chat_response`

**Files:**
- Modify: `backend/tests/unit/test_chat_metadata_routing.py`
- Modify: `backend/app/services/chat_service.py:291-429`

- [ ] **Step 1: Write the failing test for cloud routing of confidential queries**

Append to `backend/tests/unit/test_chat_metadata_routing.py`:

```python
class TestGenerateChatResponseRouting:
    """Test that confidential queries route through cloud LLMs, not Ollama."""

    @pytest.mark.asyncio
    async def test_confidential_query_uses_cloud_llm_not_ollama(self):
        """When search returns confidential docs, the LLM call goes to cloud, not Ollama."""
        from app.services.chat_service import ChatService

        svc = ChatService()
        mock_db = AsyncMock()
        mock_user = MagicMock()
        mock_user.email = "test@sowknow.local"
        mock_user.id = uuid4()
        session_id = uuid4()

        # Mock retrieve_relevant_chunks to return confidential results
        with patch.object(svc, "retrieve_relevant_chunks", new_callable=AsyncMock) as mock_retrieve, \
             patch.object(svc, "get_conversation_history", new_callable=AsyncMock) as mock_history, \
             patch("app.services.chat_service.get_cached_context_block", new_callable=AsyncMock) as mock_ctx, \
             patch("app.services.chat_service.llm_router") as mock_router:

            mock_retrieve.return_value = (
                [{"document_name": "secret.pdf", "chunk_text": "[Confidential document — content not sent to AI]",
                  "bucket": "confidential", "document_id": uuid4(), "chunk_id": uuid4(), "relevance_score": 0.9}],
                True,  # has_confidential
            )
            mock_history.return_value = []
            mock_ctx.return_value = None

            # Mock the LLM router to return a fake cloud service
            mock_llm_service = AsyncMock()

            async def fake_chat_completion(messages, stream=False):
                yield "Here is your answer about the confidential document."

            mock_llm_service.chat_completion = fake_chat_completion
            mock_llm_service.model = "test-model"

            mock_routing = MagicMock()
            mock_routing.service = mock_llm_service
            mock_routing.provider_name = "openrouter"
            mock_routing.reason.value = "public_docs_rag"
            mock_router.select_provider = AsyncMock(return_value=mock_routing)

            result = await svc.generate_chat_response(
                session_id=session_id,
                user_message="show me the passport",
                db=mock_db,
                current_user=mock_user,
            )

        # Verify: cloud LLM was called, NOT Ollama
        mock_router.select_provider.assert_called_once()
        call_kwargs = mock_router.select_provider.call_args
        # has_confidential must be False in the router call (no confidential text reaches LLM)
        assert call_kwargs.kwargs.get("has_confidential") is False or call_kwargs[1].get("has_confidential") is False

        assert result["content"] == "Here is your answer about the confidential document."
        assert result["has_confidential"] is True  # Response still flags it for UI
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/development/src/active/sowknow4/backend && python -m pytest tests/unit/test_chat_metadata_routing.py::TestGenerateChatResponseRouting -v -x 2>&1 | tail -20`

Expected: FAIL — current code hits the Ollama gate when `has_confidential=True`.

- [ ] **Step 3: Remove Ollama gate from `generate_chat_response`**

In `backend/app/services/chat_service.py`, in the `generate_chat_response` method:

**Delete the entire confidential gate block** (the `if has_confidential:` block, approximately lines 323-350 — from `if has_confidential:` through the closing `}` of the return dict).

Then change the `llm_router.select_provider` call to always pass `has_confidential=False`:

Replace:
```python
            routing_decision = await llm_router.select_provider(
                query=user_message,
                context_chunks=sources,
                has_confidential=has_confidential,
            )
```

With:
```python
            # Always route through cloud LLMs — confidential chunks have already
            # been stripped to metadata only in retrieve_relevant_chunks().
            routing_decision = await llm_router.select_provider(
                query=user_message,
                context_chunks=sources,
                has_confidential=False,
            )
```

Also update the `except RuntimeError` fallback to use openrouter instead of ollama:

Replace:
```python
        except RuntimeError as routing_err:
            logger.error(f"llm_router.select_provider failed, falling back to Ollama: {routing_err}")
            llm_service = self.ollama_service
            llm_provider = LLMProvider.OLLAMA
            routing_reason = "emergency_fallback"
```

With:
```python
        except RuntimeError as routing_err:
            logger.error(f"llm_router.select_provider failed: {routing_err}")
            if openrouter_service is not None:
                llm_service = openrouter_service
                llm_provider = LLMProvider.OPENROUTER
            else:
                llm_service = self.ollama_service
                llm_provider = LLMProvider.OLLAMA
            routing_reason = "emergency_fallback"
```

- [ ] **Step 4: Run all tests to verify they pass**

Run: `cd /home/development/src/active/sowknow4/backend && python -m pytest tests/unit/test_chat_metadata_routing.py -v -x 2>&1 | tail -30`

Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/unit/test_chat_metadata_routing.py backend/app/services/chat_service.py
git commit -m "feat: remove Ollama gate from non-streaming chat path

Confidential queries now route through cloud LLMs since chunk text is
already stripped to metadata. has_confidential=False passed to router.
Emergency fallback prefers OpenRouter over Ollama."
```

---

### Task 4: Remove Ollama gate from `generate_chat_response_stream`

**Files:**
- Modify: `backend/app/services/chat_service.py:431-561`

- [ ] **Step 1: Write the failing test for streaming path**

Append to `backend/tests/unit/test_chat_metadata_routing.py`:

```python
class TestStreamingConfidentialRouting:
    """Test that streaming path also routes confidential through cloud."""

    @pytest.mark.asyncio
    async def test_streaming_confidential_does_not_hit_ollama_gate(self):
        """Streaming path should not check Ollama health for confidential queries."""
        from app.services.chat_service import ChatService

        svc = ChatService()
        mock_db = AsyncMock()
        mock_user = MagicMock()
        mock_user.email = "test@sowknow.local"
        mock_user.id = uuid4()
        session_id = uuid4()

        with patch.object(svc, "retrieve_relevant_chunks", new_callable=AsyncMock) as mock_retrieve, \
             patch.object(svc, "get_conversation_history", new_callable=AsyncMock) as mock_history, \
             patch("app.services.chat_service.get_cached_context_block", new_callable=AsyncMock) as mock_ctx, \
             patch("app.services.chat_service.llm_router") as mock_router, \
             patch.object(svc, "ollama_service") as mock_ollama:

            mock_retrieve.return_value = (
                [{"document_name": "secret.pdf", "chunk_text": "[Confidential — metadata only]",
                  "bucket": "confidential", "document_id": str(uuid4()), "chunk_id": str(uuid4()),
                  "relevance_score": 0.9}],
                True,
            )
            mock_history.return_value = []
            mock_ctx.return_value = None

            mock_llm_service = MagicMock()

            async def fake_stream(messages, stream=True):
                yield "Streamed answer"

            mock_llm_service.chat_completion = fake_stream
            mock_llm_service.model = "test-model"

            mock_routing = MagicMock()
            mock_routing.service = mock_llm_service
            mock_routing.provider_name = "openrouter"
            mock_routing.reason.value = "public_docs_rag"
            mock_router.select_provider = AsyncMock(return_value=mock_routing)

            chunks = []
            async for chunk in svc.generate_chat_response_stream(
                session_id=session_id,
                user_message="passport",
                db=mock_db,
                current_user=mock_user,
            ):
                chunks.append(chunk)

        # Ollama health check should NOT have been called
        mock_ollama.health_check.assert_not_called()
        # Router called with has_confidential=False
        mock_router.select_provider.assert_called_once()
        call_kwargs = mock_router.select_provider.call_args
        assert call_kwargs.kwargs.get("has_confidential") is False or call_kwargs[1].get("has_confidential") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/development/src/active/sowknow4/backend && python -m pytest tests/unit/test_chat_metadata_routing.py::TestStreamingConfidentialRouting -v -x 2>&1 | tail -20`

Expected: FAIL — Ollama health_check is still called.

- [ ] **Step 3: Remove Ollama gate from streaming path**

In `backend/app/services/chat_service.py`, in `generate_chat_response_stream`:

**Delete the entire streaming confidential gate block** (the `if has_confidential:` block that checks Ollama health, enqueues to DeferredQueryService, and yields error SSE events).

Also add isolated search DB session (same fix as non-streaming path). Replace:
```python
        # Retrieve relevant chunks
        sources, has_confidential = await self.retrieve_relevant_chunks(
            query=user_message, session_id=session_id, db=db, current_user=current_user
        )
```

With:
```python
        # Retrieve relevant chunks using separate DB session (search timeouts
        # can corrupt the shared connection via cancelled asyncio tasks).
        from app.database import AsyncSessionLocal

        async with AsyncSessionLocal() as search_db:
            sources, has_confidential = await self.retrieve_relevant_chunks(
                query=user_message, session_id=session_id, db=search_db, current_user=current_user
            )
```

Change the `llm_router.select_provider` call to pass `has_confidential=False`:
```python
            routing_decision = await llm_router.select_provider(
                query=user_message,
                context_chunks=sources,
                has_confidential=False,
            )
```

Update the emergency fallback to prefer OpenRouter (same as non-streaming path):
```python
        except RuntimeError as routing_err:
            logger.error(f"llm_router.select_provider failed (stream): {routing_err}")
            if openrouter_service is not None:
                llm_service = openrouter_service
                llm_provider = LLMProvider.OPENROUTER
            else:
                llm_service = self.ollama_service
                llm_provider = LLMProvider.OLLAMA
            routing_reason = "emergency_fallback"
```

- [ ] **Step 4: Run all tests**

Run: `cd /home/development/src/active/sowknow4/backend && python -m pytest tests/unit/test_chat_metadata_routing.py -v 2>&1 | tail -30`

Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/unit/test_chat_metadata_routing.py backend/app/services/chat_service.py
git commit -m "feat: remove Ollama gate from streaming chat path

Same metadata-only routing for streaming. Isolated search DB session
to prevent connection corruption from search timeouts."
```

---

### Task 5: Run full test suite and deploy

**Files:**
- No new files

- [ ] **Step 1: Run the full unit test suite**

Run: `cd /home/development/src/active/sowknow4/backend && python -m pytest tests/unit/ -v --timeout=30 2>&1 | tail -40`

Expected: All tests pass (or pre-existing failures only — no new failures).

- [ ] **Step 2: Copy changed files to production**

```bash
cp /home/development/src/active/sowknow4/backend/app/services/chat_service.py /var/docker/sowknow4/backend/app/services/chat_service.py
```

- [ ] **Step 3: Restart backend**

```bash
cd /var/docker/sowknow4 && docker compose restart backend
```

Wait for healthy:
```bash
sleep 20 && docker compose ps backend
```

Expected: `(healthy)` status.

- [ ] **Step 4: Test via Telegram**

Send a search query via Telegram bot (e.g., "Mansour") and verify:
- Response arrives within 5-10 seconds (not 60s timeout)
- Response mentions the confidential document by name
- Response does NOT contain confidential document text
- Response directs user to review the document directly

- [ ] **Step 5: Final commit with deployment note**

```bash
git add -A
git commit -m "feat: metadata-only confidential routing — complete

Confidential search results stripped to metadata before LLM prompt.
All chat routes through cloud LLMs. Ollama removed from critical path.
Tested and deployed to production."
```
