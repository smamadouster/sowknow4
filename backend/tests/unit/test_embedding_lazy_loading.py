"""
Unit test for embedding service lazy loading.

This test verifies that the SentenceTransformer model is NOT loaded at module
import time (which would cause OOM in Celery workers), but is instead loaded
lazily on first use.

This addresses the P0 issue: Celery worker OOM fix.
"""

import pytest
import sys
import importlib
import numpy as np
from unittest.mock import patch, MagicMock


class TestEmbeddingServiceLazyLoading:
    """Test that embedding model is loaded lazily, not at import time."""

    def test_model_not_loaded_at_module_import(self):
        """
        Verify that importing the embedding_service module does NOT
        immediately load the SentenceTransformer model.

        This is critical for Celery workers to avoid OOM issues.
        """
        import app.services.embedding_service as emb_module

        with patch("app.services.embedding_service.SentenceTransformer") as mock_st:
            mock_st.return_value = MagicMock()

            old_instance = emb_module.EmbeddingService._instance
            emb_module.EmbeddingService._instance = None
            try:
                _ = emb_module.EmbeddingService()
                mock_st.assert_not_called()
            finally:
                emb_module.EmbeddingService._instance = old_instance

    def test_model_loaded_on_first_encode_call(self):
        """
        Verify that the model IS loaded when encode() is first called.
        """
        import app.services.embedding_service as emb_module

        with patch("app.services.embedding_service.SentenceTransformer") as mock_st:
            mock_model = MagicMock()
            mock_model.encode.return_value = np.array([[0.1, 0.2, 0.3]])
            mock_st.return_value = mock_model

            old_instance = emb_module.EmbeddingService._instance
            emb_module.EmbeddingService._instance = None
            try:
                service = emb_module.EmbeddingService()
                service._model = None
                service._load_error = None

                result = service.encode(["test text"])

                mock_st.assert_called()
                assert result is not None
            finally:
                emb_module.EmbeddingService._instance = old_instance

    def test_model_singleton_reuse(self):
        """
        Verify that once loaded, the model instance is reused
        rather than creating a new one for each call.
        """
        import app.services.embedding_service as emb_module

        with patch("app.services.embedding_service.SentenceTransformer") as mock_st:
            mock_model = MagicMock()
            mock_model.encode.return_value = np.array([[0.1, 0.2, 0.3]])
            mock_st.return_value = mock_model

            old_instance = emb_module.EmbeddingService._instance
            emb_module.EmbeddingService._instance = None
            try:
                service = emb_module.EmbeddingService()
                service._model = None
                service._load_error = None

                service.encode(["first text"])
                service.encode(["second text"])

                mock_st.assert_called_once()
            finally:
                emb_module.EmbeddingService._instance = old_instance

    def test_no_top_level_model_instantiation(self):
        """
        Static check: Ensure there's no top-level model instantiation
        in the embedding_service.py file.
        """
        import os

        service_path = os.path.join(
            os.path.dirname(__file__), "../../app/services/embedding_service.py"
        )

        with open(service_path, "r") as f:
            content = f.read()

        lines = content.split("\n")
        in_function = False
        in_class = False

        for i, line in enumerate(lines):
            stripped = line.strip()

            if stripped.startswith("def ") or stripped.startswith("async def "):
                in_function = True
            elif stripped.startswith("class "):
                in_class = True
            elif stripped and not line[0].isspace():
                in_function = False
                in_class = False

            if not in_function and not in_class:
                if "SentenceTransformer(" in line and not stripped.startswith("#"):
                    pytest.fail(
                        f"Line {i + 1}: SentenceTransformer instantiated at module level. "
                        f"Use lazy loading instead.\n  {line}"
                    )
