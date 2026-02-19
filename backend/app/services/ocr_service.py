"""
OCR Service for text extraction using PaddleOCR (primary) with Hunyuan API and Tesseract fallbacks
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


class OCRService:
    """Service for OCR text extraction with PaddleOCR as primary"""

    def __init__(self):
        self.hunyuan_api_key = os.getenv("HUNYUAN_API_KEY")
        self.hunyuan_endpoint = "https://ocr.tencentcloudapi.com"
        self.hunyuan_region = "ap-guangzhou"
        self._paddle_model = None

        if not self.hunyuan_api_key:
            logger.info("HUNYUAN_API_KEY not set, using PaddleOCR")

    def _get_paddle_model(self):
        """Lazy load PaddleOCR model"""
        if self._paddle_model is None:
            try:
                from paddleocr import PaddleOCR
                # Use multilingual model with English and French support
                self._paddle_model = PaddleOCR(
                    use_angle_cls=True,
                    lang='en',  # English base, supports multilingual
                    use_gpu=False,  # CPU mode for container
                    show_log=False,
                    det_db_thresh=0.3,
                    rec_batch_num=6
                )
                logger.info("PaddleOCR initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize PaddleOCR: {str(e)}")
                raise
        return self._paddle_model

    def _encode_image(self, image_bytes: bytes) -> str:
        """Encode image bytes to base64"""
        return base64.b64encode(image_bytes).decode("utf-8")

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
        Extract text from image using PaddleOCR (primary) with fallbacks

        Args:
            image_bytes: Image data as bytes
            language: Language code ("auto", "zh", "en", "fr", etc.)
            mode: Force specific OCR mode if provided ("paddle", "hunyuan", "tesseract")

        Returns:
            dict with extracted text and metadata
        """
        # Force specific mode if requested
        if mode == "hunyuan" and self.hunyuan_api_key:
            return await self._extract_text_hunyuan(image_bytes, language)
        elif mode == "tesseract":
            return await self._extract_text_tesseract(image_bytes, language)

        # Try PaddleOCR first (primary)
        try:
            result = await self._extract_text_paddle(image_bytes, language)
            if result.get("text", "").strip():
                return result
        except Exception as e:
            logger.warning(f"PaddleOCR failed: {str(e)}, trying Hunyuan...")

        # Try Hunyuan as second option
        if self.hunyuan_api_key:
            try:
                result = await self._extract_text_hunyuan(image_bytes, language)
                if result.get("text", "").strip():
                    return result
            except Exception as e:
                logger.warning(f"Hunyuan OCR failed: {str(e)}, trying Tesseract...")

        # Final fallback to Tesseract
        return await self._extract_text_tesseract(image_bytes, language)

    async def _extract_text_paddle(
        self,
        image_bytes: bytes,
        language: str = "auto"
    ) -> Dict[str, Any]:
        """
        Extract text using PaddleOCR

        Args:
            image_bytes: Image data as bytes
            language: Language code

        Returns:
            dict with extracted text and metadata
        """
        try:
            import cv2
            import numpy as np

            # Convert bytes to numpy array
            nparr = np.frombuffer(image_bytes, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

            if img is None:
                raise ValueError("Could not decode image")

            # Run OCR
            ocr = self._get_paddle_model()
            result = ocr.ocr(img, cls=True)

            if not result or not result[0]:
                return {
                    "text": "",
                    "confidence": 0,
                    "mode": "paddle",
                    "blocks": 0,
                    "source": "paddle"
                }

            # Extract text and confidence
            text_lines = []
            confidences = []
            
            for line in result[0]:
                if line:
                    box = line[0]
                    text = line[1][0]
                    conf = line[1][1]
                    text_lines.append(text)
                    confidences.append(conf)

            extracted_text = "\n".join(text_lines)
            avg_confidence = sum(confidences) / len(confidences) if confidences else 0

            return {
                "text": extracted_text,
                "confidence": avg_confidence,
                "mode": "paddle",
                "blocks": len(text_lines),
                "source": "paddle"
            }

        except ImportError as e:
            logger.error(f"PaddleOCR not available: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"Error in PaddleOCR: {str(e)}")
            raise

    async def _extract_text_hunyuan(
        self,
        image_bytes: bytes,
        language: str = "auto"
    ) -> Dict[str, Any]:
        """
        Extract text using Hunyuan-OCR API (cloud)

        Args:
            image_bytes: Image data as bytes
            language: Language code

        Returns:
            dict with extracted text and metadata
        """
        if not self.hunyuan_api_key:
            raise ValueError("HUNYUAN_API_KEY not configured")

        try:
            base64_image = self._encode_image(image_bytes)

            payload = {
                "ImageBase64": base64_image
            }

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.hunyuan_api_key}",
                "X-TC-Action": "GeneralBasicOCR",
                "X-TC-Version": "2020-11-03",
                "X-TC-Region": self.hunyuan_region
            }

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    self.hunyuan_endpoint,
                    json=payload,
                    headers=headers
                )
                response.raise_for_status()

                result = response.json()

                if result.get("Response", {}).get("Error"):
                    error_msg = result["Response"]["Error"].get("Message", "Unknown error")
                    logger.error(f"Hunyuan OCR error: {error_msg}")
                    raise Exception(error_msg)

                text_blocks = result.get("Response", {}).get("TextDetections", [])
                extracted_text = "\n".join([block.get("DetectedText", "") for block in text_blocks])

                return {
                    "text": extracted_text,
                    "confidence": result.get("Response", {}).get("Confidence", 0),
                    "mode": "hunyuan",
                    "blocks": len(text_blocks),
                    "source": "hunyuan"
                }

        except Exception as e:
            logger.error(f"Error in Hunyuan OCR: {str(e)}")
            raise

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

            lang_map = {
                "auto": "eng+fra",
                "en": "eng",
                "fr": "fra",
                "zh": "chi_sim"
            }
            tess_lang = lang_map.get(language, "eng+fra")

            img = Image.open(io.BytesIO(image_bytes))
            text = pytesseract.image_to_string(img, lang=tess_lang)

            return {
                "text": text.strip(),
                "confidence": 0.85,
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
        """Extract text from a specific PDF page"""
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


ocr_service = OCRService()
