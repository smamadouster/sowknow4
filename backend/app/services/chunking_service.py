"""
Text chunking service — lightweight tokenizer-aware chunking.

Extracted from embedding_service.py so it can be imported in the celery
worker without triggering the PyTorch/sentence_transformers import chain
(which crashes with NumPy 2.x due to ABI mismatch).

Token counting now uses the real SentencePiece tokenizer for the
intfloat/multilingual-e5-large model, ensuring no chunk ever exceeds
the model's 512-token limit.
"""

import logging

logger = logging.getLogger(__name__)

# Lazy-loaded tokenizer — only instantiated on first use.
# AutoTokenizer does NOT pull in torch, so this stays lightweight.
_tokenizer = None


def _get_tokenizer():
    global _tokenizer
    if _tokenizer is None:
        from transformers import AutoTokenizer

        _tokenizer = AutoTokenizer.from_pretrained("intfloat/multilingual-e5-large")
    return _tokenizer


def _count_tokens(text: str) -> int:
    """Return the real token count for e5-large."""
    if not text:
        return 0
    return len(_get_tokenizer().encode(text, add_special_tokens=False))


def _truncate_to_max_tokens(text: str, max_tokens: int = 512) -> str:
    """Truncate text so it never exceeds ``max_tokens`` for e5-large."""
    tokenizer = _get_tokenizer()
    tokens = tokenizer.encode(text, add_special_tokens=False)
    if len(tokens) <= max_tokens:
        return text
    truncated = tokenizer.decode(tokens[:max_tokens], skip_special_tokens=True)
    return truncated


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
        """Real token count using the e5-large tokenizer."""
        return _count_tokens(text)

    def chunk_text(self, text: str, metadata: dict | None = None) -> list[dict]:
        """Split text into chunks for embedding.

        Each chunk is guaranteed to be ≤ 512 tokens for the
        intfloat/multilingual-e5-large model.
        """
        if not text or not text.strip():
            return []

        chunks = []
        current_position = 0
        chunk_index = 0

        # Character window: use 2.5 chars/token as a conservative estimate
        # (empirically dense French/English text averages ~2.4 chars/token).
        char_multiplier = 2.5

        while current_position < len(text):
            end_position = min(
                current_position + int(self.chunk_size * char_multiplier),
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
                # Enforce the hard 512-token ceiling
                if _count_tokens(chunk_text) > self.chunk_size:
                    chunk_text = _truncate_to_max_tokens(
                        chunk_text, max_tokens=self.chunk_size
                    )

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
            new_position = best_break - int(self.chunk_overlap * char_multiplier)
            current_position = max(new_position, current_position + 1)

        return chunks

    def chunk_document(self, text: str, document_id: str, metadata: dict | None = None) -> list[dict]:
        """Chunk document text with document metadata"""
        chunk_metadata = {"document_id": document_id, **(metadata or {})}
        return self.chunk_text(text, chunk_metadata)


# Global instance
chunking_service = ChunkingService()
