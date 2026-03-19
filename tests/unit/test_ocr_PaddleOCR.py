"""
Unit tests for local PaddleOCR library integration.
Verifies the local paddleocr library is used correctly (no cloud API calls).

NOTE: These tests mock the PaddleOCR library so they run without a GPU or
the full paddleocr installation. Integration tests requiring a live model
are skipped automatically when the library is unavailable.
"""
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../backend"))


class TestPaddleOCRLocalLibrary:
    """Verify PaddleOCR local library is used — not a cloud API."""

    @pytest.fixture
    def svc(self):
        try:
            from app.services.ocr_service import OCRService
        except ImportError:
            pytest.skip("OCRService not importable in this environment")
        return OCRService()

    def test_no_cloud_api_calls(self, svc):
        """PaddleOCR must not make HTTP calls — local library only."""
        import inspect
        try:
            from app.services.ocr_service import OCRService
        except ImportError:
            pytest.skip("OCRService not importable")
        source = inspect.getsource(OCRService)
        # Ensure no cloud API endpoints are referenced
        assert "paddleocr.com" not in source, "Cloud API URL found in OCRService"
        assert "api.paddleocr" not in source, "Cloud API URL found in OCRService"

    def test_uses_local_paddleocr_library(self, svc):
        """Should import from local paddleocr package, not an HTTP client."""
        import inspect
        try:
            from app.services.ocr_service import OCRService
        except ImportError:
            pytest.skip("OCRService not importable")
        source = inspect.getsource(OCRService)
        assert "from paddleocr import" in source or "import paddleocr" in source, (
            "Local paddleocr library import not found in OCRService"
        )

    def test_paddle_model_is_lazy_loaded(self, svc):
        """PaddleOCR model must be lazy-loaded, not initialised at construction."""
        assert svc._paddle_model is None, (
            "PaddleOCR model should be None at init — lazy-loaded on first use"
        )

    def test_get_paddle_model_method_exists(self, svc):
        """_get_paddle_model() method must exist for lazy loading."""
        assert hasattr(svc, "_get_paddle_model"), "_get_paddle_model method missing"

    def test_mode_configs_all_present(self, svc):
        """MODE_CONFIGS must have base, large, and gundam entries."""
        from app.services.ocr_service import OCRMode
        for mode in (OCRMode.BASE, OCRMode.LARGE, OCRMode.GUNDAM):
            assert mode in svc.MODE_CONFIGS, f"Mode {mode} missing from MODE_CONFIGS"

    def test_base_mode_1024(self, svc):
        """Base mode must use 1024 as max image size."""
        from app.services.ocr_service import OCRMode
        assert svc.MODE_CONFIGS[OCRMode.BASE]["max_size"] == 1024

    def test_large_mode_1280(self, svc):
        """Large mode must use 1280 as max image size."""
        from app.services.ocr_service import OCRMode
        assert svc.MODE_CONFIGS[OCRMode.LARGE]["max_size"] == 1280

    def test_gundam_mode_3_passes(self, svc):
        """Gundam mode must use 3 passes for multi-scale OCR."""
        from app.services.ocr_service import OCRMode
        assert svc.MODE_CONFIGS[OCRMode.GUNDAM]["passes"] == 3

    def test_extract_with_paddle_method_exists(self, svc):
        """_extract_with_paddle (not _extract_text_paddle) must exist."""
        assert hasattr(svc, "_extract_with_paddle"), (
            "_extract_with_paddle missing — check method was renamed from _extract_text_paddle"
        )
        assert not hasattr(svc, "_extract_text_paddle"), (
            "_extract_text_paddle still exists — should have been renamed to _extract_with_paddle"
        )

    def test_extract_with_tesseract_method_exists(self, svc):
        """_extract_with_tesseract (not _extract_text_tesseract) must exist."""
        assert hasattr(svc, "_extract_with_tesseract"), (
            "_extract_with_tesseract missing — check method was renamed from _extract_text_tesseract"
        )
        assert not hasattr(svc, "_extract_text_tesseract"), (
            "_extract_text_tesseract still exists — should have been renamed"
        )

    def test_fallback_chain_tesseract_called_on_paddle_failure(self, svc):
        """When PaddleOCR fails, Tesseract fallback must be invoked."""
        async def fake_tesseract(image_bytes, language, mode):
            return {
                "text": "tesseract fallback",
                "confidence": 0.75,
                "method": "tesseract",
                "engine": "tesseract",
                "mode": "base",
                "passes": 1,
                "word_count": 2,
                "blocks": 1,
            }

        fake_file = MagicMock()
        fake_file.__enter__ = lambda s: MagicMock(read=lambda: b"\x89PNG\r\n\x1a\n")
        fake_file.__exit__ = MagicMock(return_value=False)

        with patch.object(svc, "_extract_with_paddle", side_effect=RuntimeError("GPU OOM")):
            with patch.object(svc, "_extract_with_tesseract", side_effect=fake_tesseract):
                with patch("builtins.open", return_value=fake_file):
                    result = asyncio.get_event_loop().run_until_complete(
                        svc._extract_full("/fake/image.png")
                    )
        assert result["text"] == "tesseract fallback"
        assert result["engine"] == "tesseract"
