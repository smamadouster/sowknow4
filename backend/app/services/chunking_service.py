"""
Text chunking service — lightweight, no ML dependencies.

Extracted from embedding_service.py so it can be imported in the celery
worker without triggering the PyTorch/sentence_transformers import chain
(which crashes with NumPy 2.x due to ABI mismatch).
"""

import logging

logger = logging.getLogger(__name__)


class ChunkingService:
    """Service for chunking text into smaller pieces for embedding"""

    def __init__(
        self,
        chunk_size: int = 512,
        chunk_overlap: int = 50,
        separators: list[str] | None = None,
    ):
        self.chunk_size = chunk_size  # Target token count
        self.chunk_overlap = chunk_overlap  # Overlapping tokens
        self.separators = separators or ["\n\n", "\n", ". ", " ", ""]

    def count_tokens(self, text: str) -> int:
        """Estimate token count (~4 characters per token for English/French)"""
        return len(text) // 4

    def chunk_text(self, text: str, metadata: dict | None = None) -> list[dict]:
        """Split text into chunks for embedding"""
        if not text or not text.strip():
            return []

        chunks = []
        current_position = 0
        chunk_index = 0

        while current_position < len(text):
            end_position = min(
                current_position + self.chunk_size * 4,
                len(text),
            )

            best_break = end_position
            for separator in self.separators:
                break_pos = text.rfind(separator, current_position, end_position)
                if break_pos > current_position:
                    best_break = break_pos + len(separator)
                    break

            chunk_text = text[current_position:best_break].strip()
            # Strip NUL bytes that PostgreSQL rejects in text columns
            chunk_text = chunk_text.replace("\x00", "")

            if chunk_text:
                chunks.append(
                    {
                        "text": chunk_text,
                        "index": chunk_index,
                        "token_count": self.count_tokens(chunk_text),
                        "start_pos": current_position,
                        "end_pos": best_break,
                        "metadata": metadata or {},
                    }
                )
                chunk_index += 1

            # Ensure forward progress — overlap must not move position backwards
            new_position = best_break - (self.chunk_overlap * 4)
            current_position = max(new_position, current_position + 1)

        return chunks

    def chunk_document(self, text: str, document_id: str, metadata: dict | None = None) -> list[dict]:
        """Chunk document text with document metadata"""
        chunk_metadata = {"document_id": document_id, **(metadata or {})}
        return self.chunk_text(text, chunk_metadata)


# Global instance
chunking_service = ChunkingService()
