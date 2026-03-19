"""
Unit tests for OCRService.
Tests use mocks to avoid requiring PaddleOCR/Tesseract to be installed.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, mock_open
import pytest
import sys
import os

# Ensure backend is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../backend"))


def _run(coro):
    """Helper to run async coroutines in sync test context."""
    return asyncio.get_event_loop().run_until_complete(coro)


class TestExtractTextSignature:
    """Issue #3: extract_text() signature compliance."""

    def test_extract_text_default_language_is_french(self):
        """Default language parameter must be 'french'."""
        import inspect
        try:
            from app.services.ocr_service import OCRService
        except ImportError:
            pytest.skip("OCRService not importable in this environment")
        sig = inspect.signature(OCRService.extract_text)
        lang_param = sig.parameters.get("language")
        assert lang_param is not None, "language parameter missing"
        assert lang_param.default == "french", (
            f"Expected default 'french', got '{lang_param.default}'"
        )

    def test_extract_text_mode_default_is_base(self):
        """Default mode must be 'base'."""
        import inspect
        try:
            from app.services.ocr_service import OCRService
        except ImportError:
            pytest.skip("OCRService not importable in this environment")
        sig = inspect.signature(OCRService.extract_text)
        mode_param = sig.parameters.get("mode")
        assert mode_param is not None, "mode parameter missing"
        assert mode_param.default == "base"

    def test_extract_text_first_param_is_image_path(self):
        """First positional parameter must be image_path (not image_bytes)."""
        import inspect
        try:
            from app.services.ocr_service import OCRService
        except ImportError:
            pytest.skip("OCRService not importable in this environment")
        sig = inspect.signature(OCRService.extract_text)
        params = list(sig.parameters.keys())
        # params[0] is 'self', params[1] is the first real arg
        assert "image_path" in params, f"image_path not found in {params}"
        assert "image_bytes" not in params, "image_bytes should not be in extract_text params"

    def test_extract_text_mode_accepts_all_three_modes(self):
        """mode param must accept 'base', 'large', 'gundam'."""
        try:
            from app.services.ocr_service import OCRService
        except ImportError:
            pytest.skip("OCRService not importable in this environment")
        # If Literal is used, the annotation string contains all three
        import inspect
        sig = inspect.signature(OCRService.extract_text)
        hints = OCRService.extract_text.__annotations__
        mode_annotation = str(hints.get("mode", ""))
        for mode in ("base", "large", "gundam"):
            assert mode in mode_annotation, f"Mode '{mode}' not in Literal annotation: {mode_annotation}"


class TestShouldUseOcr:
    """Issue #5: should_use_ocr() logic."""

    @pytest.fixture
    def svc(self):
        try:
            from app.services.ocr_service import OCRService
        except ImportError:
            pytest.skip("OCRService not importable")
        return OCRService()

    def test_image_mime_always_ocr(self, svc):
        should, reason = svc.should_use_ocr("image/png")
        assert should is True
        assert "image" in reason.lower()

    def test_image_jpeg_always_ocr(self, svc):
        should, reason = svc.should_use_ocr("image/jpeg", extracted_text="some text")
        assert should is True

    def test_pdf_no_text_needs_ocr(self, svc):
        should, reason = svc.should_use_ocr("application/pdf", extracted_text="")
        assert should is True

    def test_pdf_short_text_needs_ocr(self, svc):
        """PDF with <50 chars of text should trigger OCR."""
        should, reason = svc.should_use_ocr("application/pdf", extracted_text="Hi")
        assert should is True
        assert "50" in reason or "short" in reason.lower()

    def test_pdf_high_whitespace_ratio_needs_ocr(self, svc):
        """PDF where >90% of chars are whitespace should trigger OCR."""
        # 91% whitespace
        text = " " * 910 + "a" * 90
        should, reason = svc.should_use_ocr("application/pdf", extracted_text=text)
        assert should is True

    def test_pdf_good_text_no_ocr(self, svc):
        """PDF with solid extracted text should skip OCR."""
        text = "This is a proper document with plenty of readable text content here."
        should, reason = svc.should_use_ocr("application/pdf", extracted_text=text)
        assert should is False

    def test_office_doc_no_ocr(self, svc):
        """Word documents should skip OCR."""
        should, reason = svc.should_use_ocr(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        assert should is False

    def test_msword_no_ocr(self, svc):
        should, reason = svc.should_use_ocr("application/msword")
        assert should is False

    def test_file_path_param_accepted(self, svc):
        """should_use_ocr must accept optional file_path parameter."""
        import inspect
        sig = inspect.signature(svc.should_use_ocr)
        assert "file_path" in sig.parameters

    def test_returns_tuple_of_bool_and_str(self, svc):
        result = svc.should_use_ocr("image/png")
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], bool)
        assert isinstance(result[1], str)


class TestAutoSelectMode:
    """Issue #4: Gundam auto-detect for large images."""

    @pytest.fixture
    def svc(self):
        try:
            from app.services.ocr_service import OCRService
        except ImportError:
            pytest.skip("OCRService not importable")
        return OCRService()

    def test_small_image_stays_base(self, svc):
        """Images <=2000px should stay as base mode."""
        mock_img = MagicMock()
        mock_img.size = (800, 600)
        with patch("PIL.Image.open", return_value=mock_img):
            result = svc._auto_select_mode("/fake/path.png", "base")
        assert result == "base"

    def test_large_image_upgrades_to_gundam(self, svc):
        """Images >2000px on either axis should auto-upgrade to gundam."""
        mock_img = MagicMock()
        mock_img.size = (2400, 1800)
        with patch("PIL.Image.open", return_value=mock_img):
            result = svc._auto_select_mode("/fake/path.png", "base")
        assert result == "gundam"

    def test_explicit_large_mode_not_overridden(self, svc):
        """Explicit 'large' mode should not be overridden."""
        mock_img = MagicMock()
        mock_img.size = (3000, 3000)
        with patch("PIL.Image.open", return_value=mock_img):
            result = svc._auto_select_mode("/fake/path.png", "large")
        assert result == "large"


class TestCountPages:
    """Issue #7: _count_pages() helper."""

    @pytest.fixture
    def svc(self):
        try:
            from app.services.ocr_service import OCRService
        except ImportError:
            pytest.skip("OCRService not importable")
        return OCRService()

    def test_image_returns_one(self, svc):
        result = svc._count_pages("/fake/image.png", mime_type="image/png")
        assert result == 1

    def test_image_jpeg_returns_one(self, svc):
        result = svc._count_pages("/fake/image.jpg", mime_type="image/jpeg")
        assert result == 1

    def test_pdf_uses_pypdf2(self, svc):
        mock_reader = MagicMock()
        mock_reader.pages = [MagicMock()] * 5
        with patch("builtins.open", mock_open(read_data=b"")):
            with patch("PyPDF2.PdfReader", return_value=mock_reader):
                result = svc._count_pages("/fake/doc.pdf")
        assert result == 5

    def test_fallback_returns_one(self, svc):
        """When PyPDF2 fails, should return 1."""
        with patch("builtins.open", side_effect=FileNotFoundError):
            result = svc._count_pages("/nonexistent/file.pdf")
        assert result == 1


class TestModeConfigs:
    """Issue #4: Resolution mode configurations."""

    def test_mode_configs_has_all_three_modes(self):
        try:
            from app.services.ocr_service import OCRService
        except ImportError:
            pytest.skip("OCRService not importable")
        assert hasattr(OCRService, "MODE_CONFIGS")
        configs = OCRService.MODE_CONFIGS
        modes = [str(k) for k in configs.keys()]
        for expected in ("base", "large", "gundam"):
            assert any(expected in m for m in modes), f"Mode '{expected}' missing from MODE_CONFIGS"

    def test_base_mode_max_size_1024(self):
        try:
            from app.services.ocr_service import OCRService, OCRMode
        except ImportError:
            pytest.skip("OCRService not importable")
        assert OCRService.MODE_CONFIGS[OCRMode.BASE]["max_size"] == 1024

    def test_large_mode_max_size_1280(self):
        try:
            from app.services.ocr_service import OCRService, OCRMode
        except ImportError:
            pytest.skip("OCRService not importable")
        assert OCRService.MODE_CONFIGS[OCRMode.LARGE]["max_size"] == 1280

    def test_gundam_mode_multipass(self):
        try:
            from app.services.ocr_service import OCRService, OCRMode
        except ImportError:
            pytest.skip("OCRService not importable")
        assert OCRService.MODE_CONFIGS[OCRMode.GUNDAM]["passes"] == 3
