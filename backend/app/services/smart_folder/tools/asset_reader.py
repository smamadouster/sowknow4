"""Asset Content Extractor Tool.

Given a vault asset ID, returns full text, metadata, and any embedded tabular data.
"""

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document

logger = logging.getLogger(__name__)


class AssetReaderTool:
    """Tool: Extract content and metadata from a vault asset."""

    async def read(
        self,
        db: AsyncSession,
        asset_id: str | UUID,
    ) -> dict[str, Any]:
        """Read a document by ID."""
        stmt = select(Document).where(Document.id == asset_id)
        result = await db.execute(stmt)
        doc = result.scalar_one_or_none()

        if not doc:
            return {"error": f"Document {asset_id} not found"}

        return {
            "asset_id": str(doc.id),
            "name": doc.original_filename,
            "mime_type": doc.mime_type,
            "bucket": doc.bucket.value if doc.bucket else None,
            "metadata": doc.document_metadata or {},
            "page_count": doc.page_count,
            "created_at": doc.created_at.isoformat() if doc.created_at else None,
        }


asset_reader = AssetReaderTool()
