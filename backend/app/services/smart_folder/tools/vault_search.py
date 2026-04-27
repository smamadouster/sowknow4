"""Vault Search Tool.

Wraps the existing hybrid search service for skill use.
"""

import logging
from typing import Any

from app.services.search_service import search_service

logger = logging.getLogger(__name__)


class VaultSearchTool:
    """Tool: Hybrid Vault Search (keyword + vector + graph)."""

    async def search(
        self,
        query: str,
        user: Any,
        db: Any,
        limit: int = 20,
        regconfig: str = "french",
        rerank: bool = True,
    ) -> dict[str, Any]:
        """Run hybrid search and return normalized results."""
        result = await search_service.hybrid_search(
            query=query,
            limit=limit,
            offset=0,
            db=db,
            user=user,
            timeout=8.0,
            regconfig=regconfig,
            rerank=rerank,
        )
        return {
            "results": [
                {
                    "asset_id": r.document_id,
                    "name": r.document_name,
                    "bucket": r.document_bucket,
                    "text": r.chunk_text,
                    "score": r.final_score,
                }
                for r in result.get("results", [])
            ],
            "total": result.get("total", 0),
        }


vault_search = VaultSearchTool()
