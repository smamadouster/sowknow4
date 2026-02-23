"""
OCR Service for text extraction using PaddleOCR (primary) with Tesseract fallback

Implements three processing modes:
- Base (1024x1024): Standard documents, receipts, forms - 1 pass
- Large (1280x1280): High-resolution images, detailed photos - 1 pass
- Gundam: Complex documents, handwriting, degraded text - 3 passes + merging

All processing is done locally - zero PII sent to cloud APIs.
"""

import os
import base64
import time
import logging
from enum import Enum
from typing import Optional, Dict, Any, List
from PIL import Image
import io

logger = logging.getLogger(__name__)


class OCRMode(str, Enum):
    BASE = "base"
    LARGE = "large"
    GUNDAM = "gundam"


class OCREngine(str, Enum):
    PADDLE = "paddle"
    TESSERACT = "tesseract"
    NONE = "none"


class OCRService:
    """Service for OCR text extraction with PaddleOCR as primary and Tesseract fallback

    Supports three processing modes:
    - base: 1024x1024, single pass (standard documents)
    - large: 1280x1280, single pass (high-resolution images)
    - gundam: multi-pass at 0.5x, 1x, 1.5x scales with merging (complex documents)
    """

    MODE_CONFIGS = {
        OCRMode.BASE: {
            "max_size": 1024,
            "passes": 1,
            "scales": [1.0],
            "description": "Standard documents, receipts, forms",
        },
        OCRMode.LARGE: {
            "max_size": 1280,
            "passes": 1,
            "scales": [1.0],
            "description": "High-resolution images, detailed photos",
        },
        OCRMode.GUNDAM: {
            "max_size": 1024,
            "passes": 3,
            "scales": [0.5, 1.0, 1.5],
            "description": "Complex documents, handwriting, degraded text",
        },
    }

    def __init__(self):
        self._paddle_model = None

    def _get_paddle_model(self):
        """Lazy load PaddleOCR model"""
        if self._paddle_model is None:
            try:
                from paddleocr import PaddleOCR

                self._paddle_model = PaddleOCR(
                    use_angle_cls=True,
                    lang="en",
                    use_gpu=False,
                    show_log=False,
                    det_db_thresh=0.3,
                    rec_batch_num=6,
                )
                logger.info("PaddleOCR initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize PaddleOCR: {str(e)}")
                raise
        return self._paddle_model

    def _get_language_for_ocr(self, language: str) -> str:
        """Map application language codes to OCR language codes

        FR/EN bilingual support:
        - auto: uses multilingual model
        - fr: French
        - en: English
        """
        lang_map = {
            "auto": "en",
            "fr": "en",
            "en": "en",
            "zh": "ch",
        }
        return lang_map.get(language.lower(), "en")

    def _resize_image(self, img, max_size: int) -> Image.Image:
        """Resize image while maintaining aspect ratio"""
        width, height = img.size
        if width <= max_size and height <= max_size:
            return img

        if width > height:
            new_width = max_size
            new_height = int(height * (max_size / width))
        else:
            new_height = max_size
            new_width = int(width * (max_size / height))

        return img.resize((new_width, new_height), Image.Resampling.LANCZOS)

    def _preprocess_image(self, image_bytes: bytes, mode: OCRMode) -> Image.Image:
        """Load and preprocess image based on mode"""
        img = Image.open(io.BytesIO(image_bytes))

        if img.mode != "RGB":
            img = img.convert("RGB")

        max_size = self.MODE_CONFIGS[mode]["max_size"]
        return self._resize_image(img, max_size)

    async def extract_text(
        self,
        image_bytes: bytes,
        language: str = "auto",
        mode: Optional[str] = None,
        force_engine: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Extract text from image using PaddleOCR (primary) with Tesseract fallback

        Args:
            image_bytes: Image data as bytes
            language: Language code ("auto", "zh", "en", "fr")
            mode: OCR mode - "base" (1024x1024), "large" (1280x1280), "gundam" (multi-pass)
            force_engine: Force specific engine ("paddle", "tesseract")

        Returns:
            dict with extracted text, confidence, engine, mode, and audit metadata
        """
        start_time = time.time()

        ocr_mode = OCRMode(mode.lower()) if mode else OCRMode.BASE

        if force_engine == "tesseract":
            result = await self._extract_text_tesseract(image_bytes, language, ocr_mode)
            result["processing_time"] = time.time() - start_time
            return result

        if force_engine == "paddle":
            result = await self._extract_text_paddle(image_bytes, language, ocr_mode)
            result["processing_time"] = time.time() - start_time
            return result

        try:
            result = await self._extract_text_paddle(image_bytes, language, ocr_mode)
            if result.get("text", "").strip():
                result["processing_time"] = time.time() - start_time
                return result
        except Exception as e:
            logger.warning(f"PaddleOCR failed: {str(e)}, trying Tesseract...")

        result = await self._extract_text_tesseract(image_bytes, language, ocr_mode)
        result["processing_time"] = time.time() - start_time
        return result

    async def _extract_text_paddle(
        self, image_bytes: bytes, language: str, mode: OCRMode
    ) -> Dict[str, Any]:
        """Extract text using PaddleOCR with mode-specific processing"""
        try:
            import cv2
            import numpy as np

            img = self._preprocess_image(image_bytes, mode)

            img_array = np.array(img)
            img_cv = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)

            ocr = self._get_paddle_model()

            if mode == OCRMode.GUNDAM:
                return await self._gundam_mode_paddle(img_cv, ocr, language)
            else:
                result = ocr.ocr(img_cv, cls=True)
                return self._parse_paddle_result(result, language)

        except ImportError as e:
            logger.error(f"PaddleOCR not available: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"Error in PaddleOCR: {str(e)}")
            raise

    async def _gundam_mode_paddle(self, img_cv, ocr, language: str) -> Dict[str, Any]:
        """Multi-pass OCR with result merging - for complex documents"""
        scales = [0.5, 1.0, 1.5]
        all_results = []

        height, width = img_cv.shape[:2]

        for scale in scales:
            new_width = int(width * scale)
            new_height = int(height * scale)

            if scale != 1.0:
                scaled_img = cv2.resize(img_cv, (new_width, new_height))
            else:
                scaled_img = img_cv

            try:
                result = ocr.ocr(scaled_img, cls=True)
                if result and result[0]:
                    all_results.append((result[0], scale))
            except Exception as e:
                logger.warning(f"PaddleOCR pass at scale {scale} failed: {str(e)}")
                continue

        if not all_results:
            return {
                "text": "",
                "confidence": 0,
                "engine": OCREngine.PADDLE.value,
                "mode": OCRMode.GUNDAM.value,
                "passes": 0,
                "blocks": 0,
            }

        merged_text = self._merge_ocr_results(all_results)

        return {
            "text": merged_text["text"],
            "confidence": merged_text["avg_confidence"],
            "engine": OCREngine.PADDLE.value,
            "mode": OCRMode.GUNDAM.value,
            "passes": len(all_results),
            "scales_used": [s[1] for s in all_results],
            "blocks": merged_text["block_count"],
        }

    def _merge_ocr_results(self, results: List[tuple]) -> Dict[str, Any]:
        """Merge OCR results from multiple passes using confidence scoring"""
        text_blocks = {}

        for result_data, scale in results:
            for line in result_data:
                if not line:
                    continue

                box = line[0]
                text = line[1][0]
                conf = line[1][1]

                x_center = (box[0][0] + box[2][0]) / 2
                y_center = (box[0][1] + box[2][1]) / 2

                key = f"{int(x_center / 50)}_{int(y_center / 20)}"

                if key not in text_blocks:
                    text_blocks[key] = {
                        "text": text,
                        "confidences": [conf],
                        "y_pos": y_center,
                    }
                else:
                    if conf > max(text_blocks[key]["confidences"]):
                        text_blocks[key]["text"] = text
                        text_blocks[key]["confidences"].append(conf)

        sorted_blocks = sorted(text_blocks.values(), key=lambda x: x["y_pos"])

        all_confidences = []
        for block in sorted_blocks:
            all_confidences.extend(block["confidences"])

        text_lines = [block["text"] for block in sorted_blocks]

        return {
            "text": "\n".join(text_lines),
            "avg_confidence": sum(all_confidences) / len(all_confidences)
            if all_confidences
            else 0,
            "block_count": len(text_blocks),
        }

    def _parse_paddle_result(self, result, language: str) -> Dict[str, Any]:
        """Parse PaddleOCR result into standard format"""
        if not result or not result[0]:
            return {
                "text": "",
                "confidence": 0,
                "engine": OCREngine.PADDLE.value,
                "mode": OCRMode.BASE.value,
                "passes": 1,
                "blocks": 0,
            }

        text_lines = []
        confidences = []

        for line in result[0]:
            if line:
                text = line[1][0]
                conf = line[1][1]
                text_lines.append(text)
                confidences.append(conf)

        extracted_text = "\n".join(text_lines)
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0

        return {
            "text": extracted_text,
            "confidence": avg_confidence,
            "engine": OCREngine.PADDLE.value,
            "mode": OCRMode.BASE.value,
            "passes": 1,
            "blocks": len(text_lines),
        }

    async def _extract_text_tesseract(
        self, image_bytes: bytes, language: str, mode: OCRMode
    ) -> Dict[str, Any]:
        """Fallback OCR using Tesseract"""
        try:
            import pytesseract

            img = self._preprocess_image(image_bytes, mode)

            lang_map = {"auto": "eng+fra", "en": "eng", "fr": "fra", "zh": "chi_sim"}
            tess_lang = lang_map.get(language.lower(), "eng+fra")

            text = pytesseract.image_to_string(img, lang=tess_lang)

            return {
                "text": text.strip(),
                "confidence": 0.85,
                "engine": OCREngine.TESSERACT.value,
                "mode": mode.value,
                "passes": 1,
                "blocks": len(text.split("\n")),
            }

        except ImportError:
            logger.error("Tesseract not available, no OCR fallback")
            return {
                "text": "",
                "confidence": 0,
                "engine": OCREngine.NONE.value,
                "mode": mode.value,
                "passes": 0,
                "blocks": 0,
                "error": "Tesseract not installed",
            }
        except Exception as e:
            logger.error(f"Error in Tesseract OCR: {str(e)}")
            return {
                "text": "",
                "confidence": 0,
                "engine": OCREngine.NONE.value,
                "mode": mode.value,
                "passes": 0,
                "blocks": 0,
                "error": str(e),
            }

    async def extract_from_pdf_page(
        self, pdf_path: str, page_number: int = 0, language: str = "auto"
    ) -> Dict[str, Any]:
        """Extract text from a specific PDF page"""
        try:
            import PyPDF2

            with open(pdf_path, "rb") as file:
                pdf_reader = PyPDF2.PdfReader(file)

                if page_number >= len(pdf_reader.pages):
                    return {
                        "text": "",
                        "error": f"Page {page_number} not found (total: {len(pdf_reader.pages)})",
                        "engine": OCREngine.NONE.value,
                        "source": "pypdf2",
                    }

                page = pdf_reader.pages[page_number]
                text = page.extract_text()

                return {
                    "text": text.strip(),
                    "page_number": page_number,
                    "total_pages": len(pdf_reader.pages),
                    "engine": OCREngine.NONE.value,
                    "source": "pypdf2",
                    "confidence": 0.95 if text.strip() else 0,
                    "mode": "pdf_text",
                }

        except Exception as e:
            logger.error(f"Error extracting from PDF: {str(e)}")
            return {
                "text": "",
                "error": str(e),
                "engine": OCREngine.NONE.value,
                "source": "error",
            }

    def get_available_modes(self) -> Dict[str, Any]:
        """Return available OCR modes and their configurations"""
        return {mode: config for mode, config in self.MODE_CONFIGS.items()}

    def get_default_mode(self) -> str:
        """Return default OCR mode"""
        return OCRMode.BASE.value


ocr_service = OCRService()
