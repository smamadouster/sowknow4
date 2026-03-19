"""
Integration tests for the full OCR chain.
Tests the complete path from image file -> extracted text.
Requires PaddleOCR or Tesseract to be installed.
"""
import os
import pytest
import asyncio
import tempfile
from pathlib import Path

pytestmark = pytest.mark.integration

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


def ocr_available():
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        pass
    try:
        from paddleocr import PaddleOCR  # noqa: F401
        return True
    except Exception:
        pass
    return False


def create_test_image():
    """Create a small test PNG with text for OCR testing."""
    try:
        from PIL import Image, ImageDraw, ImageFont
        img = Image.new("RGB", (400, 100), color="white")
        draw = ImageDraw.Draw(img)
        draw.text((10, 30), "Hello OCR Test", fill="black")
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            img.save(f.name)
            return f.name
    except Exception:
        return None


@pytest.fixture(scope="module")
def test_image_path():
    if not ocr_available():
        pytest.skip("No OCR engine available (PaddleOCR or Tesseract required)")
    path = create_test_image()
    if path is None:
        pytest.skip("Could not create test image (PIL/Pillow required)")
    yield path
    try:
        os.unlink(path)
    except Exception:
        pass


class TestOCRFullChain:
    """Full OCR chain: image_path -> extract_text() -> str."""

    def test_extract_text_returns_string(self, test_image_path):
        """extract_text() must return a str."""
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../backend"))
        try:
            from app.services.ocr_service import OCRService
        except ImportError:
            pytest.skip("OCRService not importable")

        svc = OCRService()
        result = asyncio.get_event_loop().run_until_complete(
            svc.extract_text(test_image_path)
        )
        assert isinstance(result, str), f"Expected str, got {type(result)}"

    def test_confidence_in_valid_range(self, test_image_path):
        """Internal confidence metric must be in [0, 1]."""
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../backend"))
        try:
            from app.services.ocr_service import OCRService
        except ImportError:
            pytest.skip("OCRService not importable")

        svc = OCRService()
        result = asyncio.get_event_loop().run_until_complete(
            svc._extract_full(test_image_path)
        )
        confidence = result.get("confidence", 0)
        assert 0.0 <= confidence <= 1.0, f"Confidence {confidence} out of [0, 1] range"

    def test_should_use_ocr_with_file_path(self, test_image_path):
        """should_use_ocr() must accept file_path as an optional kwarg."""
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../backend"))
        try:
            from app.services.ocr_service import OCRService
        except ImportError:
            pytest.skip("OCRService not importable")

        svc = OCRService()
        should, reason = svc.should_use_ocr("image/png", file_path=test_image_path)
        assert should is True
        assert isinstance(reason, str)
