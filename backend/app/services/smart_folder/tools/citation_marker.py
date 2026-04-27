"""Citation Linker Tool.

Tags each piece of evidence with the exact asset ID and cell/section reference.
"""

import logging
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)


class CitationMarkerTool:
    """Tool: Wrap raw evidence with citation metadata."""

    def tag(
        self,
        asset_id: str | UUID,
        text: str,
        cell_ref: str | None = None,
        page_number: int | None = None,
        section: str | None = None,
    ) -> dict[str, Any]:
        """Create a citation marker entry."""
        return {
            "asset_id": str(asset_id),
            "text": text,
            "cell_ref": cell_ref,
            "page_number": page_number,
            "section": section,
            "citation_key": f"[{asset_id}]" if not cell_ref else f"[{asset_id}:{cell_ref}]",
        }

    def bulk_tag(
        self,
        entries: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Tag multiple evidence entries at once."""
        return [self.tag(**e) for e in entries]


citation_marker = CitationMarkerTool()
