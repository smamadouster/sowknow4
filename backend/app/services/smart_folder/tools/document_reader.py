"""Document Reader Tool.

Reads full document text by concatenating all chunks, extracts metadata,
and provides structured document content for skills to consume.
"""

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentChunk

logger = logging.getLogger(__name__)


class DocumentReaderTool:
    """Tool: Read full document content and metadata."""

    async def read_document(
        self,
        document_id: UUID,
        db: AsyncSession,
        max_chars: int = 15000,
        allowed_buckets: list[str] | None = None,
    ) -> dict[str, Any] | None:
        """Read a document's full text by concatenating all its chunks.

        Args:
            document_id: The document UUID.
            db: Database session.
            max_chars: Maximum characters to return (truncates if longer).
            allowed_buckets: Optional list of allowed document buckets for RBAC.

        Returns:
            Dict with document metadata and full text, or None if not found
            or bucket not allowed.
        """
        doc = await db.get(Document, document_id)
        if not doc:
            return None

        # SECURITY: Check bucket access
        if allowed_buckets is not None:
            bucket_val = doc.bucket.value if hasattr(doc.bucket, "value") else str(doc.bucket)
            if bucket_val not in allowed_buckets:
                logger.debug("Document %s bucket '%s' not in allowed buckets %s", document_id, bucket_val, allowed_buckets)
                return None

        chunks_result = await db.execute(
            select(DocumentChunk.chunk_text, DocumentChunk.chunk_index)
            .where(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.chunk_index)
        )
        chunks = chunks_result.all()
        full_text = "\n\n".join(c.chunk_text for c in chunks)

        if len(full_text) > max_chars:
            full_text = full_text[:max_chars] + f"\n\n[... {len(full_text) - max_chars} additional characters ...]"

        return {
            "document_id": str(document_id),
            "title": doc.original_filename or doc.filename or "Untitled",
            "filename": doc.filename,
            "bucket": doc.bucket.value if hasattr(doc.bucket, "value") else str(doc.bucket),
            "mime_type": doc.mime_type,
            "created_at": doc.created_at.isoformat() if doc.created_at else None,
            "page_count": doc.page_count,
            "language": doc.language.value if hasattr(doc.language, "value") else str(doc.language) if doc.language else None,
            "full_text": full_text,
            "chunk_count": len(chunks),
            "doc_type": self._detect_doc_type(doc),
        }

    async def read_documents(
        self,
        document_ids: list[UUID],
        db: AsyncSession,
        max_chars: int = 15000,
        allowed_buckets: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Read multiple documents in parallel (sequentially via async).

        SECURITY: Respects allowed_buckets RBAC filter.
        """
        results = []
        for doc_id in document_ids:
            doc = await self.read_document(doc_id, db, max_chars, allowed_buckets)
            if doc:
                results.append(doc)
        return results

    def _detect_doc_type(self, doc: Document) -> str:
        """Heuristic document type classification based on filename and mime type."""
        fname = (doc.original_filename or doc.filename or "").lower()
        mime = (doc.mime_type or "").lower()

        if "contract" in fname or "contrat" in fname or "accord" in fname:
            return "contract"
        if "letter" in fname or "lettre" in fname or "courrier" in fname:
            return "letter"
        if "invoice" in fname or "facture" in fname:
            return "invoice"
        if "balance" in fname or "bilan" in fname or "financial" in fname or "financier" in fname:
            return "financial_statement"
        if "minutes" in fname or "pv" in fname or "procès-verbal" in fname:
            return "meeting_minutes"
        if "report" in fname or "rapport" in fname or "memo" in fname or "mémo" in fname:
            return "report"
        if "email" in fname or "mail" in fname or "courriel" in fname:
            return "email"
        if "legal" in fname or "legal" in fname or "droit" in fname or "avocat" in fname:
            return "legal"
        if "pdf" in mime:
            return "pdf_document"
        return "document"


# Module-level singleton
document_reader = DocumentReaderTool()
