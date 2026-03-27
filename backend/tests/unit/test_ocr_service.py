"""
Unit tests for OCR Service with three processing modes

Tests cover:
- Base mode (1024x1024 single pass)
- Large mode (1280x1280 single pass)
- Gundam mode (multi-pass with result merging)
- Engine fallback (PaddleOCR -> Tesseract)
- Bilingual FR/EN support
- Audit logging of engine used
"""

import io
import tempfile
import os
from unittest.mock import patch, AsyncMock

import pytest
from PIL import Image


def _make_image_bytes():
    """Create minimal PNG image bytes for testing."""
    img = Image.new("RGB", (100, 100), color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _write_temp_image():
    """Write a minimal PNG to a temp file and return the path."""
    img_bytes = _make_image_bytes()
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp.write(img_bytes)
    tmp.flush()
    tmp.close()
    return tmp.name


class TestOCRMode:
    """Tests for OCRMode enum"""

    def test_ocr_mode_enum_values(self):
        """Verify OCR mode enum values are correct"""
        from app.services.ocr_service import OCRMode

        assert OCRMode.BASE.value == "base"
        assert OCRMode.LARGE.value == "large"
        assert OCRMode.GUNDAM.value == "gundam"

    def test_ocr_engine_enum_values(self):
        """Verify OCR engine enum values are correct"""
        from app.services.ocr_service import OCREngine

        assert OCREngine.PADDLE.value == "paddle"
        assert OCREngine.TESSERACT.value == "tesseract"
        assert OCREngine.NONE.value == "none"


class TestOCRServiceModeConfigs:
    """Tests for OCR mode configurations"""

    def test_mode_configs_exist(self):
        """Verify all mode configurations exist"""
        from app.services.ocr_service import OCRMode, OCRService

        service = OCRService()

        assert OCRMode.BASE in service.MODE_CONFIGS
        assert OCRMode.LARGE in service.MODE_CONFIGS
        assert OCRMode.GUNDAM in service.MODE_CONFIGS

    def test_base_mode_config(self):
        """Verify Base mode configuration"""
        from app.services.ocr_service import OCRMode, OCRService

        service = OCRService()
        config = service.MODE_CONFIGS[OCRMode.BASE]

        assert config["max_size"] == 1024
        assert config["passes"] == 1
        assert config["scales"] == [1.0]

    def test_large_mode_config(self):
        """Verify Large mode configuration"""
        from app.services.ocr_service import OCRMode, OCRService

        service = OCRService()
        config = service.MODE_CONFIGS[OCRMode.LARGE]

        assert config["max_size"] == 1280
        assert config["passes"] == 1
        assert config["scales"] == [1.0]

    def test_gundam_mode_config(self):
        """Verify Gundam mode configuration"""
        from app.services.ocr_service import OCRMode, OCRService

        service = OCRService()
        config = service.MODE_CONFIGS[OCRMode.GUNDAM]

        assert config["max_size"] == 1024
        assert config["passes"] == 3
        assert config["scales"] == [0.5, 1.0, 1.5]


class TestOCRService:
    """Tests for OCRService class"""

    @pytest.fixture
    def ocr_service(self):
        """Create OCR service instance"""
        from app.services.ocr_service import OCRService

        return OCRService()

    def test_get_available_modes(self, ocr_service):
        """Test getting available modes"""
        from app.services.ocr_service import OCRMode  # noqa: PLC0415

        modes = ocr_service.get_available_modes()

        assert "base" in modes or OCRMode.BASE in modes
        assert len(modes) == 3

    def test_get_default_mode(self, ocr_service):
        """Test getting default mode"""
        default = ocr_service.get_default_mode()

        assert default == "base"

    def test_language_mapping_french(self, ocr_service):
        """Test French language mapping"""
        lang = ocr_service._get_language_for_ocr("fr")

        assert lang == "en"

    def test_language_mapping_english(self, ocr_service):
        """Test English language mapping"""
        lang = ocr_service._get_language_for_ocr("en")

        assert lang == "en"

    def test_language_mapping_auto(self, ocr_service):
        """Test auto language mapping"""
        lang = ocr_service._get_language_for_ocr("auto")

        assert lang == "en"

    def test_resize_image_no_change(self, ocr_service):
        """Test image resize when already smaller than max"""
        img = Image.new("RGB", (100, 100), color="white")

        result = ocr_service._resize_image(img, 1024)

        assert result.size == (100, 100)

    def test_resize_image_landscape(self, ocr_service):
        """Test image resize for landscape image"""
        img = Image.new("RGB", (2000, 1000), color="white")

        result = ocr_service._resize_image(img, 1024)

        assert result.size[0] == 1024
        assert result.size[1] == 512

    def test_resize_image_portrait(self, ocr_service):
        """Test image resize for portrait image"""
        img = Image.new("RGB", (1000, 2000), color="white")

        result = ocr_service._resize_image(img, 1024)

        assert result.size[0] == 512
        assert result.size[1] == 1024


class TestOCRModeParameter:
    """Tests for mode parameter handling via _extract_full"""

    @pytest.fixture
    def ocr_service(self):
        from app.services.ocr_service import OCRService

        return OCRService()

    @pytest.fixture
    def temp_image_path(self):
        path = _write_temp_image()
        yield path
        os.unlink(path)

    @pytest.mark.asyncio
    async def test_mode_base(self, ocr_service, temp_image_path):
        """Test Base mode parameter"""
        with patch.object(ocr_service, "_extract_with_tesseract", new_callable=AsyncMock) as mock_tesseract:
            mock_tesseract.return_value = {
                "text": "test",
                "confidence": 0.9,
                "engine": "tesseract",
                "mode": "base",
            }
            with patch.object(ocr_service, "_extract_with_paddle", new_callable=AsyncMock) as mock_paddle:
                mock_paddle.side_effect = Exception("no paddle")

                result = await ocr_service._extract_full(temp_image_path, mode="base")

                assert result["mode"] == "base"

    @pytest.mark.asyncio
    async def test_mode_large(self, ocr_service, temp_image_path):
        """Test Large mode parameter"""
        with patch.object(ocr_service, "_extract_with_tesseract", new_callable=AsyncMock) as mock_tesseract:
            mock_tesseract.return_value = {
                "text": "test",
                "confidence": 0.9,
                "engine": "tesseract",
                "mode": "large",
            }
            with patch.object(ocr_service, "_extract_with_paddle", new_callable=AsyncMock) as mock_paddle:
                mock_paddle.side_effect = Exception("no paddle")

                result = await ocr_service._extract_full(temp_image_path, mode="large")

                assert result["mode"] == "large"

    @pytest.mark.asyncio
    async def test_mode_gundam(self, ocr_service, temp_image_path):
        """Test Gundam mode parameter"""
        with patch.object(ocr_service, "_extract_with_tesseract", new_callable=AsyncMock) as mock_tesseract:
            mock_tesseract.return_value = {
                "text": "test",
                "confidence": 0.9,
                "engine": "tesseract",
                "mode": "gundam",
            }
            with patch.object(ocr_service, "_extract_with_paddle", new_callable=AsyncMock) as mock_paddle:
                mock_paddle.side_effect = Exception("no paddle")

                result = await ocr_service._extract_full(temp_image_path, mode="gundam")

                assert result["mode"] == "gundam"

    @pytest.mark.asyncio
    async def test_default_mode_is_base(self, ocr_service, temp_image_path):
        """Test that default mode is Base when no mode specified"""
        with patch.object(ocr_service, "_extract_with_tesseract", new_callable=AsyncMock) as mock_tesseract:
            mock_tesseract.return_value = {
                "text": "test",
                "confidence": 0.9,
                "engine": "tesseract",
                "mode": "base",
            }
            with patch.object(ocr_service, "_extract_with_paddle", new_callable=AsyncMock) as mock_paddle:
                mock_paddle.side_effect = Exception("no paddle")

                result = await ocr_service._extract_full(temp_image_path)

                assert result["mode"] == "base"


class TestOCREngineFallback:
    """Tests for OCR engine fallback mechanism"""

    @pytest.fixture
    def ocr_service(self):
        from app.services.ocr_service import OCRService

        return OCRService()

    @pytest.fixture
    def temp_image_path(self):
        path = _write_temp_image()
        yield path
        os.unlink(path)

    @pytest.mark.asyncio
    async def test_force_tesseract(self, ocr_service, temp_image_path):
        """Test that tesseract is used when paddle is unavailable"""
        with patch.object(ocr_service, "_extract_with_paddle", new_callable=AsyncMock) as mock_paddle:
            mock_paddle.side_effect = Exception("PaddleOCR not available")

            with patch.object(ocr_service, "_extract_with_tesseract", new_callable=AsyncMock) as mock_tesseract:
                mock_tesseract.return_value = {
                    "text": "test",
                    "confidence": 0.85,
                    "engine": "tesseract",
                    "mode": "base",
                }

                result = await ocr_service._extract_full(temp_image_path)

                mock_tesseract.assert_called_once()
                assert result["engine"] == "tesseract"

    @pytest.mark.asyncio
    async def test_paddle_fallback_to_tesseract(self, ocr_service, temp_image_path):
        """Test PaddleOCR fallback to Tesseract on failure"""
        ocr_service._paddle_model = None

        with patch.object(ocr_service, "_get_paddle_model") as mock_get_paddle:
            mock_get_paddle.side_effect = Exception("PaddleOCR not available")

            with patch.object(ocr_service, "_extract_with_tesseract", new_callable=AsyncMock) as mock_tesseract:
                mock_tesseract.return_value = {
                    "text": "fallback text",
                    "confidence": 0.85,
                    "engine": "tesseract",
                    "mode": "base",
                }

                result = await ocr_service._extract_full(temp_image_path)

                assert result["engine"] == "tesseract"


class TestOCRResultFormat:
    """Tests for OCR result format and audit logging"""

    @pytest.fixture
    def ocr_service(self):
        from app.services.ocr_service import OCRService

        return OCRService()

    @pytest.fixture
    def temp_image_path(self):
        path = _write_temp_image()
        yield path
        os.unlink(path)

    @pytest.mark.asyncio
    async def test_result_contains_engine(self, ocr_service, temp_image_path):
        """Test that result contains engine field for audit"""
        with patch.object(ocr_service, "_extract_with_paddle", new_callable=AsyncMock) as mock_paddle:
            mock_paddle.side_effect = Exception("no paddle")
            with patch.object(ocr_service, "_extract_with_tesseract", new_callable=AsyncMock) as mock_tesseract:
                mock_tesseract.return_value = {
                    "text": "test",
                    "confidence": 0.85,
                    "engine": "tesseract",
                    "mode": "base",
                    "passes": 1,
                }

                result = await ocr_service._extract_full(temp_image_path)

                assert "engine" in result
                assert result["engine"] in ["paddle", "tesseract", "none"]

    @pytest.mark.asyncio
    async def test_result_contains_mode(self, ocr_service, temp_image_path):
        """Test that result contains mode field"""
        with patch.object(ocr_service, "_extract_with_paddle", new_callable=AsyncMock) as mock_paddle:
            mock_paddle.side_effect = Exception("no paddle")
            with patch.object(ocr_service, "_extract_with_tesseract", new_callable=AsyncMock) as mock_tesseract:
                mock_tesseract.return_value = {
                    "text": "test",
                    "confidence": 0.85,
                    "engine": "tesseract",
                    "mode": "base",
                    "passes": 1,
                }

                result = await ocr_service._extract_full(temp_image_path, mode="base")

                assert "mode" in result
                assert result["mode"] in ["base", "large", "gundam"]

    @pytest.mark.asyncio
    async def test_result_contains_processing_time(
        self, ocr_service, temp_image_path
    ):
        """Test that result contains processing_time for monitoring"""
        with patch.object(ocr_service, "_extract_with_paddle", new_callable=AsyncMock) as mock_paddle:
            mock_paddle.side_effect = Exception("no paddle")
            with patch.object(ocr_service, "_extract_with_tesseract", new_callable=AsyncMock) as mock_tesseract:
                mock_tesseract.return_value = {
                    "text": "test",
                    "confidence": 0.85,
                    "engine": "tesseract",
                    "mode": "base",
                }

                result = await ocr_service._extract_full(temp_image_path)

                assert "processing_time" in result
                assert isinstance(result["processing_time"], float)
                assert result["processing_time"] >= 0

    @pytest.mark.asyncio
    async def test_result_contains_confidence(self, ocr_service, temp_image_path):
        """Test that result contains confidence score"""
        with patch.object(ocr_service, "_extract_with_paddle", new_callable=AsyncMock) as mock_paddle:
            mock_paddle.side_effect = Exception("no paddle")
            with patch.object(ocr_service, "_extract_with_tesseract", new_callable=AsyncMock) as mock_tesseract:
                mock_tesseract.return_value = {
                    "text": "test",
                    "confidence": 0.85,
                    "engine": "tesseract",
                    "mode": "base",
                }

                result = await ocr_service._extract_full(temp_image_path)

                assert "confidence" in result
                assert isinstance(result["confidence"], float)
                assert 0 <= result["confidence"] <= 1


class TestOCRPDFExtraction:
    """Tests for PDF text extraction"""

    @pytest.fixture
    def ocr_service(self):
        from app.services.ocr_service import OCRService

        return OCRService()

    @pytest.mark.asyncio
    @pytest.mark.skipif(True, reason="PyPDF2 not available in test environment")
    async def test_pdf_page_not_found(self, ocr_service):
        """Test PDF page extraction with invalid page"""
        result = await ocr_service.extract_from_pdf_page(
            "/fake/path.pdf", page_number=5
        )

        assert "error" in result
        assert result["engine"] == "none"


class TestBilingualSupport:
    """Tests for bilingual FR/EN support"""

    @pytest.fixture
    def ocr_service(self):
        from app.services.ocr_service import OCRService

        return OCRService()

    @pytest.fixture
    def temp_image_path(self):
        path = _write_temp_image()
        yield path
        os.unlink(path)

    @pytest.mark.asyncio
    async def test_french_language_parameter(self, ocr_service, temp_image_path):
        """Test French language parameter"""
        with patch.object(ocr_service, "_extract_with_paddle", new_callable=AsyncMock) as mock_paddle:
            mock_paddle.side_effect = Exception("no paddle")
            with patch.object(ocr_service, "_extract_with_tesseract", new_callable=AsyncMock) as mock_tesseract:
                mock_tesseract.return_value = {
                    "text": "texte français",
                    "confidence": 0.85,
                    "engine": "tesseract",
                    "mode": "base",
                }

                result = await ocr_service._extract_full(
                    temp_image_path, language="fr"
                )

                assert (
                    "français" in result["text"].lower()
                    or "texte" in result["text"].lower()
                )

    @pytest.mark.asyncio
    async def test_english_language_parameter(self, ocr_service, temp_image_path):
        """Test English language parameter"""
        with patch.object(ocr_service, "_extract_with_paddle", new_callable=AsyncMock) as mock_paddle:
            mock_paddle.side_effect = Exception("no paddle")
            with patch.object(ocr_service, "_extract_with_tesseract", new_callable=AsyncMock) as mock_tesseract:
                mock_tesseract.return_value = {
                    "text": "english text",
                    "confidence": 0.85,
                    "engine": "tesseract",
                    "mode": "base",
                }

                result = await ocr_service._extract_full(
                    temp_image_path, language="en"
                )

                assert (
                    "english" in result["text"].lower() or "text" in result["text"].lower()
                )

    @pytest.mark.asyncio
    async def test_auto_language_parameter(self, ocr_service, temp_image_path):
        """Test auto language detection"""
        with patch.object(ocr_service, "_extract_with_paddle", new_callable=AsyncMock) as mock_paddle:
            mock_paddle.side_effect = Exception("no paddle")
            with patch.object(ocr_service, "_extract_with_tesseract", new_callable=AsyncMock) as mock_tesseract:
                mock_tesseract.return_value = {
                    "text": "detected text",
                    "confidence": 0.85,
                    "engine": "tesseract",
                    "mode": "base",
                }

                result = await ocr_service._extract_full(
                    temp_image_path, language="auto"
                )

                assert "text" in result["text"].lower()


class TestOCRServiceIntegration:
    """Integration tests for OCR service"""

    def test_ocr_service_instantiation(self):
        """Test that OCR service can be instantiated"""
        from app.services.ocr_service import OCRService

        service = OCRService()

        assert service is not None
        assert service._paddle_model is None

    def test_ocr_service_singleton(self):
        """Test that ocr_service singleton exists"""
        from app.services.ocr_service import OCRService, ocr_service

        assert ocr_service is not None
        assert isinstance(ocr_service, OCRService)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
