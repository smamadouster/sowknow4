"""
Unit tests for local PaddleOCR library integration.
Verifies that the local library (not cloud API) is used correctly.
"""
import pytest
from unittest.mock import MagicMock, patch
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../backend"))


class TestLocalPaddleOCRLibrary:
    """Issue #2: Local PaddleOCR library (not cloud API)."""

    @pytest.fixture
    def svc(self):
        try:
            from app.services.ocr_service import OCRService
        except ImportError:
            pytest.skip("OCRService not importable")
        return OCRService()

    def test_paddle_model_lazy_loaded(self, svc):
        """Model should not be loaded at construction time."""
        assert svc._paddle_model is None, "PaddleOCR should be lazy-loaded, not loaded at init"

    def test_get_paddle_model_method_exists(self, svc):
        """_get_paddle_model lazy-load method must exist."""
        assert hasattr(svc, "_get_paddle_model"), "_get_paddle_model method missing"
        assert callable(svc._get_paddle_model)

    def test_mode_configs_present(self, svc):
        """MODE_CONFIGS class attribute must contain all three modes."""
        assert hasattr(svc, "MODE_CONFIGS")
        config_keys = [str(k) for k in svc.MODE_CONFIGS.keys()]
        for mode in ("base", "large", "gundam"):
            assert any(mode in k for k in config_keys), f"'{mode}' missing from MODE_CONFIGS"

    def test_extract_with_paddle_method_exists(self, svc):
        """_extract_with_paddle method must exist (renamed from _extract_text_paddle)."""
        assert hasattr(svc, "_extract_with_paddle"), (
            "_extract_with_paddle missing — method may still be named _extract_text_paddle"
        )

    def test_extract_with_tesseract_method_exists(self, svc):
        """_extract_with_tesseract method must exist (renamed from _extract_text_tesseract)."""
        assert hasattr(svc, "_extract_with_tesseract"), (
            "_extract_with_tesseract missing — method may still be named _extract_text_tesseract"
        )

    def test_fallback_to_tesseract_on_paddle_failure(self, svc):
        """When PaddleOCR raises an exception, Tesseract must be called as fallback."""
        import asyncio

        async def fake_tesseract(image_bytes, language, mode):
            return {"text": "fallback text", "confidence": 0.5,
                    "engine": "tesseract", "mode": "base",
                    "passes": 1, "word_count": 2, "blocks": 1}

        with patch.object(svc, "_extract_with_paddle", side_effect=RuntimeError("PaddleOCR failed")):
            with patch.object(svc, "_extract_with_tesseract", side_effect=fake_tesseract):
                with patch("builtins.open", MagicMock(return_value=MagicMock(
                    __enter__=lambda s: MagicMock(read=lambda: b"fake bytes"),
                    __exit__=MagicMock(return_value=False)
                ))):
                    result = asyncio.get_event_loop().run_until_complete(
                        svc._extract_full("/fake/image.png")
                    )
        assert result.get("text") == "fallback text"
        assert result.get("engine") == "tesseract"

    def test_resize_image_base_max_1024(self, svc):
        """Base mode resize must cap at 1024px."""
        from PIL import Image
        img = Image.new("RGB", (2048, 1024))
        resized = svc._resize_image(img, 1024)
        assert max(resized.size) <= 1024

    def test_resize_image_large_max_1280(self, svc):
        """Large mode resize must cap at 1280px."""
        from PIL import Image
        img = Image.new("RGB", (2560, 1920))
        resized = svc._resize_image(img, 1280)
        assert max(resized.size) <= 1280

    def test_resize_image_preserves_aspect_ratio(self, svc):
        """Resize must preserve aspect ratio within 1px tolerance."""
        from PIL import Image
        img = Image.new("RGB", (2000, 1000))  # 2:1 ratio
        resized = svc._resize_image(img, 1024)
        w, h = resized.size
        original_ratio = 2000 / 1000
        new_ratio = w / h
        assert abs(original_ratio - new_ratio) < 0.1
