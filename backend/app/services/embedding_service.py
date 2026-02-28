"""
Embedding service using multilingual-e5-large model
"""

import logging
import os
from typing import Any

import numpy as np

try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    SentenceTransformer = None

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Service for generating text embeddings using multilingual-e5-large"""

    _instance = None
    _model_loaded = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized") and self._initialized:
            return
        self.model_name = "intfloat/multilingual-e5-large"
        self.embedding_dim = 1024
        self._model = None
        self._device = "cpu"
        self._load_error = None
        self._initialized = True

    @property
    def model(self) -> object:
        """Return the loaded SentenceTransformer model, loading it lazily if needed."""
        if self._model is None:
            self._load_model()
        return self._model

    @property
    def is_loaded(self) -> bool:
        """True when the embedding model has been loaded into memory."""
        return self._model is not None

    @property
    def can_embed(self) -> bool:
        """True only when the model is loaded and ready."""
        return self._model is not None and self._load_error is None

    def _load_model(self):
        try:
            if SentenceTransformer is None:
                raise ImportError("sentence_transformers is not installed")

            try:
                import torch

                if torch.cuda.is_available():
                    self._device = "cuda"
                    logger.info("Using CUDA for embeddings")
                else:
                    logger.info("Using CPU for embeddings")
            except ImportError:
                self._device = "cpu"
                logger.info("torch not available, using CPU for embeddings")

            logger.info(f"Loading embedding model: {self.model_name}")
            self._model = SentenceTransformer(self.model_name, device=self._device)
            self._model_loaded = True
            self._load_error = None
            logger.info("Embedding model loaded successfully")

        except Exception as e:
            self._load_error = str(e)
            # Do NOT re-raise: graceful degradation — backend container runs without
            # sentence_transformers (requirements-minimal.txt).  Semantic search will
            # be skipped and keyword-only results returned.
            logger.warning(
                f"Embedding model unavailable (sentence_transformers not installed or "
                f"model download failed): {str(e)}. "
                f"Semantic search disabled; keyword search will still work."
            )

    def get_memory_stats(self) -> dict[str, Any]:
        """Return memory usage statistics for the embedding service process."""
        try:
            import psutil

            process = psutil.Process(os.getpid())
            mem_info = process.memory_info()
            return {
                "model_loaded": self.is_loaded,
                "model_name": self.model_name if self.is_loaded else None,
                "rss_mb": round(mem_info.rss / 1024 / 1024, 2),
                "vms_mb": round(mem_info.vms / 1024 / 1024, 2),
                "percent": round(process.memory_percent(), 2),
                "device": self._device,
                "load_error": self._load_error,
            }
        except ImportError:
            return {
                "model_loaded": self.is_loaded,
                "model_name": self.model_name if self.is_loaded else None,
                "device": self._device,
                "psutil_available": False,
                "load_error": self._load_error,
            }
        except Exception as e:
            return {
                "model_loaded": self.is_loaded,
                "error": str(e),
                "load_error": self._load_error,
            }

    def health_check(self) -> dict[str, Any]:
        """Return a health status dict including memory stats and load error if any."""
        stats = self.get_memory_stats()
        stats["status"] = "healthy" if self.is_loaded else "model_not_loaded"
        if self._load_error:
            stats["status"] = "error"
        return stats

    def encode(self, texts: list[str], batch_size: int = 32, show_progress: bool = False) -> list[list[float]]:
        """
        Generate embeddings for a list of texts.

        Returns zero vectors when the model is unavailable (graceful degradation for
        the backend container which runs without sentence_transformers).  Callers
        should check ``can_embed`` before using results for vector similarity.

        Args:
            texts: List of text strings to encode
            batch_size: Batch size for encoding
            show_progress: Show progress bar

        Returns:
            List of embedding vectors (each is a list of floats)
        """
        if not texts:
            return []

        # Trigger lazy model loading if not yet attempted
        if self._model is None and self._load_error is None:
            self._load_model()

        # Graceful degradation: model not available in backend container
        if not self.can_embed:
            logger.debug("Embedding model not available; returning zero vectors (semantic search disabled).")
            return [[0.0] * self.embedding_dim for _ in texts]

        try:
            # Preprocess texts - add prefix for e5 model
            # The e5 model expects "query:" prefix for queries and "passage:" for passages
            processed_texts = [f"passage: {text}" for text in texts]

            # Generate embeddings
            embeddings = self.model.encode(
                processed_texts,
                batch_size=batch_size,
                show_progress_bar=show_progress,
                convert_to_numpy=True,
                normalize_embeddings=True,  # L2 normalization
            )

            # Convert to list of lists
            return embeddings.tolist()

        except Exception as e:
            logger.error(f"Error generating embeddings: {str(e)}")
            raise

    def encode_single(self, text: str) -> list[float]:
        """Generate embedding for a single text"""
        if not text or not text.strip():
            return [0.0] * self.embedding_dim

        result = self.encode([text])
        return result[0] if result else [0.0] * self.embedding_dim

    async def encode_async(self, texts: list[str], batch_size: int = 32) -> list[list[float]]:
        """Async wrapper for encoding (runs in thread pool)"""
        import asyncio

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.encode, texts, batch_size)

    def calculate_similarity(self, embedding1: list[float], embedding2: list[float]) -> float:
        """
        Calculate cosine similarity between two embeddings

        Args:
            embedding1: First embedding vector
            embedding2: Second embedding vector

        Returns:
            Similarity score between -1 and 1
        """
        try:
            vec1 = np.array(embedding1)
            vec2 = np.array(embedding2)

            # Cosine similarity
            dot_product = np.dot(vec1, vec2)
            norm1 = np.linalg.norm(vec1)
            norm2 = np.linalg.norm(vec2)

            if norm1 == 0 or norm2 == 0:
                return 0.0

            return float(dot_product / (norm1 * norm2))

        except Exception as e:
            logger.error(f"Error calculating similarity: {str(e)}")
            return 0.0

    def get_average_embedding(self, embeddings: list[list[float]]) -> list[float]:
        """
        Calculate the average (centroid) of multiple embeddings

        Args:
            embeddings: List of embedding vectors

        Returns:
            Average embedding vector
        """
        if not embeddings:
            return [0.0] * self.embedding_dim

        try:
            embeddings_array = np.array(embeddings)
            average = np.mean(embeddings_array, axis=0)
            return average.tolist()

        except Exception as e:
            logger.error(f"Error calculating average embedding: {str(e)}")
            return [0.0] * self.embedding_dim


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
        """
        Estimate token count (rough approximation)

        Args:
            text: Text to count tokens for

        Returns:
            Estimated token count
        """
        # Rough approximation: ~4 characters per token for English/French
        return len(text) // 4

    def chunk_text(self, text: str, metadata: dict | None = None) -> list[dict]:
        """
        Split text into chunks for embedding

        Args:
            text: Text to chunk
            metadata: Optional metadata to attach to each chunk

        Returns:
            List of chunk dictionaries with text and metadata
        """
        if not text or not text.strip():
            return []

        chunks = []
        current_position = 0
        chunk_index = 0

        while current_position < len(text):
            # Calculate end position for this chunk
            end_position = min(
                current_position + self.chunk_size * 4,  # Convert tokens to chars
                len(text),
            )

            # Try to find a good break point
            best_break = end_position
            for separator in self.separators:
                break_pos = text.rfind(separator, current_position, end_position)
                if break_pos > current_position:
                    best_break = break_pos + len(separator)
                    break

            chunk_text = text[current_position:best_break].strip()

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

            # Move to next position with overlap
            current_position = best_break - (self.chunk_overlap * 4)

        return chunks

    def chunk_document(self, text: str, document_id: str, metadata: dict | None = None) -> list[dict]:
        """
        Chunk document text with document metadata

        Args:
            text: Document text
            document_id: Document UUID
            metadata: Additional metadata

        Returns:
            List of chunk dictionaries
        """
        chunk_metadata = {"document_id": document_id, **(metadata or {})}

        return self.chunk_text(text, chunk_metadata)


# Global service instances
embedding_service = EmbeddingService()
chunking_service = ChunkingService()
