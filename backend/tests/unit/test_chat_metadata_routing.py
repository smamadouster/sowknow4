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
        assert "SECRET" not in sources[0]["chunk_text"]
        assert "12345" not in sources[0]["chunk_text"]
        assert "Confidential" in sources[0]["chunk_text"]
        assert sources[0]["bucket"] == "confidential"
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
        assert sources[0]["chunk_text"] == "Public info about Mansour"
        assert sources[0]["bucket"] == "public"
        assert "Private letter" not in sources[1]["chunk_text"]
        assert sources[1]["bucket"] == "confidential"


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
