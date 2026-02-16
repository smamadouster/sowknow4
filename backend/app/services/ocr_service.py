"""
OCR Service for text extraction using Hunyuan-OCR API
"""
import os
import base64
import httpx
from typing import Optional, Dict, Any
from PIL import Image
import io
from tenacity import retry, stop_after_attempt, wait_exponential
import logging

logger = logging.getLogger(__name__)


class HunyuanOCRMode:
    """Hunyuan-OCR processing modes"""
    BASE = "Base"         # 1024x1024 - Standard documents
    LARGE = "Large"       # 1280x1280 - Complex layouts, tables
    GUNDAM = "Gundam"     # Variable - Handwriting, detailed illustrations


class OCRService:
    """Service for OCR text extraction using Hunyuan API"""

    def __init__(self):
        self.api_key = os.getenv("HUNYUAN_API_KEY")
        self.endpoint = "https://ocr.tencentcloudapi.com"
        self.region = "ap-guangzhou"

        if not self.api_key:
            logger.warning("HUNYUAN_API_KEY not set, OCR will use fallback")

    def _encode_image(self, image_bytes: bytes) -> str:
        """Encode image bytes to base64"""
        return base64.b64encode(image_bytes).decode("utf-8")

    def _get_image_dimensions(self, image_bytes: bytes) -> tuple:
        """Get image dimensions (width, height)"""
        try:
            img = Image.open(io.BytesIO(image_bytes))
            return img.size
        except Exception as e:
            logger.error(f"Error getting image dimensions: {str(e)}")
            return (0, 0)

    def _select_ocr_mode(self, image_bytes: bytes, force_mode: Optional[str] = None) -> str:
        """
        Select appropriate OCR mode based on image characteristics

        Args:
            image_bytes: Image data as bytes
            force_mode: Force specific mode if provided

        Returns:
            OCR mode to use
        """
        if force_mode:
            return force_mode

        width, height = self._get_image_dimensions(image_bytes)

        # Determine mode based on image size and complexity
        max_dimension = max(width, height)

        if max_dimension > 1280:
            return HunyuanOCRMode.GUNDAM
        elif max_dimension > 1024:
            return HunyuanOCRMode.LARGE
        else:
            return HunyuanOCRMode.BASE

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    async def extract_text(
        self,
        image_bytes: bytes,
        language: str = "auto",
        mode: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Extract text from image using Hunyuan-OCR API

        Args:
            image_bytes: Image data as bytes
            language: Language code ("auto", "zh", "en", "fr", etc.)
            mode: OCR mode to use (None for auto-detection)

        Returns:
            dict with extracted text and metadata
        """
        if not self.api_key:
            # Fallback to Tesseract
            return await self._extract_text_tesseract(image_bytes, language)

        try:
            # Select OCR mode
            ocr_mode = self._select_ocr_mode(image_bytes, mode)

            # Prepare request
            base64_image = self._encode_image(image_bytes)

            payload = {
                "ImageBase64": base64_image
            }

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
                "X-TC-Action": "GeneralBasicOCR",
                "X-TC-Version": "2020-11-03",
                "X-TC-Region": self.region
            }

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    self.endpoint,
                    json=payload,
                    headers=headers
                )
                response.raise_for_status()

                result = response.json()

                # Parse response
                if result.get("Response", {}).get("Error"):
                    error_msg = result["Response"]["Error"].get("Message", "Unknown error")
                    logger.error(f"Hunyuan OCR error: {error_msg}")
                    # Fallback to Tesseract
                    return await self._extract_text_tesseract(image_bytes, language)

                text_blocks = result.get("Response", {}).get("TextDetections", [])
                extracted_text = "\n".join([block.get("DetectedText", "") for block in text_blocks])

                return {
                    "text": extracted_text,
                    "confidence": result.get("Response", {}).get("Confidence", 0),
                    "mode": ocr_mode,
                    "blocks": len(text_blocks),
                    "source": "hunyuan"
                }

        except httpx.HTTPError as e:
            logger.error(f"HTTP error calling Hunyuan OCR: {str(e)}")
            # Fallback to Tesseract
            return await self._extract_text_tesseract(image_bytes, language)
        except Exception as e:
            logger.error(f"Error in Hunyuan OCR: {str(e)}")
            # Fallback to Tesseract
            return await self._extract_text_tesseract(image_bytes, language)

    async def _extract_text_tesseract(
        self,
        image_bytes: bytes,
        language: str = "auto"
    ) -> Dict[str, Any]:
        """
        Fallback OCR using Tesseract

        Args:
            image_bytes: Image data as bytes
            language: Language code

        Returns:
            dict with extracted text and metadata
        """
        try:
            import pytesseract
            from PIL import Image

            # Map language codes
            lang_map = {
                "auto": "eng+fra",
                "en": "eng",
                "fr": "fra",
                "zh": "chi_sim"
            }
            tess_lang = lang_map.get(language, "eng+fra")

            # Open image and extract text
            img = Image.open(io.BytesIO(image_bytes))
            text = pytesseract.image_to_string(img, lang=tess_lang)

            return {
                "text": text.strip(),
                "confidence": 0.85,  # Tesseract doesn't provide confidence
                "mode": "tesseract",
                "blocks": len(text.split("\n")),
                "source": "tesseract"
            }

        except ImportError:
            logger.error("Tesseract not available, no OCR fallback")
            return {
                "text": "",
                "confidence": 0,
                "mode": "none",
                "blocks": 0,
                "source": "error",
                "error": "Tesseract not installed"
            }
        except Exception as e:
            logger.error(f"Error in Tesseract OCR: {str(e)}")
            return {
                "text": "",
                "confidence": 0,
                "mode": "error",
                "blocks": 0,
                "source": "error",
                "error": str(e)
            }

    async def extract_from_pdf_page(
        self,
        pdf_path: str,
        page_number: int = 0
    ) -> Dict[str, Any]:
        """
        Extract text from a specific PDF page

        Args:
            pdf_path: Path to PDF file
            page_number: Page number (0-indexed)

        Returns:
            dict with extracted text and metadata
        """
        try:
            import PyPDF2

            with open(pdf_path, "rb") as file:
                pdf_reader = PyPDF2.PdfReader(file)

                if page_number >= len(pdf_reader.pages):
                    return {
                        "text": "",
                        "error": f"Page {page_number} not found (total: {len(pdf_reader.pages)})"
                    }

                page = pdf_reader.pages[page_number]
                text = page.extract_text()

                return {
                    "text": text.strip(),
                    "page_number": page_number,
                    "total_pages": len(pdf_reader.pages),
                    "source": "pypdf2"
                }

        except Exception as e:
            logger.error(f"Error extracting from PDF: {str(e)}")
            return {
                "text": "",
                "error": str(e),
                "source": "error"
            }


# Global OCR service instance
ocr_service = OCRService()
