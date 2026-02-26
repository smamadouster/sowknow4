"""
OCR Service for text extraction using PaddleOCR (primary) with Tesseract fallback

Implements three processing modes:
- Base (1024x1024): Standard documents, receipts, forms - 1 pass
- Large (1280x1280): High-resolution images, detailed photos - 1 pass
- Gundam: Complex documents, handwriting, degraded text - 3 passes + merging

All processing is done locally - zero PII sent to cloud APIs.
"""

import os
import time
import logging
from enum import Enum
from typing import Optional, Dict, Any, List, Literal
from PIL import Image
import io

logger = logging.getLogger(__name__)

# Local OCR configuration — read from environment (all processing stays on-device)
OCR_ENGINE = os.getenv("OCR_ENGINE", "paddle")
OCR_DEFAULT_MODE = os.getenv("OCR_DEFAULT_MODE", "base")
OCR_FALLBACK_ENABLED = os.getenv("OCR_FALLBACK_ENABLED", "true").lower() == "true"


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

    def _auto_select_mode(self, image_path: str, requested_mode: str) -> str:
        """Auto-upgrade to gundam mode for very large images (> 2000px on either axis)."""
        if requested_mode != "base":
            return requested_mode
        try:
            img = Image.open(image_path)
            w, h = img.size
            if w > 2000 or h > 2000:
                logger.info(
                    f"Auto-upgrading OCR mode to 'gundam' — image {w}×{h}px exceeds 2000px"
                )
                return "gundam"
        except Exception:
            pass
        return requested_mode

    def _count_pages(self, file_path: str, mime_type: Optional[str] = None) -> int:
        """Count document pages. PDFs use PyPDF2; images always return 1."""
        if mime_type and mime_type.startswith("image/"):
            return 1
        try:
            import PyPDF2
            with open(file_path, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                return len(reader.pages)
        except Exception:
            return 1

    async def _extract_full(
        self,
        image_path: str,
        mode: Literal["base", "large", "gundam"] = "base",
        language: str = "french",
    ) -> Dict[str, Any]:
        """Internal extraction returning full metadata dict."""
        start_time = time.time()
        with open(image_path, "rb") as f:
            image_bytes = f.read()

        mode = self._auto_select_mode(image_path, mode)
        ocr_mode = OCRMode(mode)

        try:
            result = await self._extract_with_paddle(image_bytes, language, ocr_mode)
            if result.get("text", "").strip():
                result["processing_time"] = time.time() - start_time
                return result
        except Exception as e:
            logger.warning(f"PaddleOCR failed: {str(e)}, trying Tesseract...")

        result = await self._extract_with_tesseract(image_bytes, language, ocr_mode)
        result["processing_time"] = time.time() - start_time
        return result

    async def extract_text(
        self,
        image_path: str,
        mode: Literal["base", "large", "gundam"] = "base",
        language: str = "french",
    ) -> str:
        """
        Extract text from image file. Returns extracted text as string.

        Args:
            image_path: Path to the image file
            mode: OCR processing mode — "base" (1024×1024), "large" (1280×1280),
                  "gundam" (multi-pass for complex documents)
            language: Language hint ("french", "english", "auto")

        Returns:
            Extracted text as a plain string.
        """
        result = await self._extract_full(image_path, mode=mode, language=language)
        # Wire cost tracking
        try:
            from app.services.monitoring import get_cost_tracker
            pages = self._count_pages(image_path)
            get_cost_tracker().track_ocr_operation(
                method=result.get("engine", "paddle"),
                mode=mode,
                pages=pages,
            )
        except Exception:
            pass  # cost tracking is non-critical
        return result.get("text", "")

    async def _extract_with_paddle(
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
        import cv2  # noqa: PLC0415

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
            "avg_confidence": (
                sum(all_confidences) / len(all_confidences) if all_confidences else 0
            ),
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

    async def _extract_with_tesseract(
        self, image_bytes: bytes, language: str, mode: OCRMode
    ) -> Dict[str, Any]:
        """Fallback OCR using Tesseract with real per-word confidence measurement"""
        try:
            import pytesseract

            img = self._preprocess_image(image_bytes, mode)

            lang_map = {"auto": "eng+fra", "en": "eng", "fr": "fra", "zh": "chi_sim"}
            tess_lang = lang_map.get(language.lower(), "eng+fra")

            # Use image_to_string for layout-preserving text
            text = pytesseract.image_to_string(img, lang=tess_lang)

            # Use image_to_data to get real per-word confidence scores
            data = pytesseract.image_to_data(
                img, lang=tess_lang, output_type=pytesseract.Output.DICT
            )

            # Collect confidence scores for valid words only (conf == -1 means no word)
            word_confidences = []
            word_lengths = []
            for conf, word in zip(data["conf"], data["text"]):
                if conf != -1 and str(word).strip():
                    word_confidences.append(float(conf))
                    word_lengths.append(len(str(word).strip()))

            if word_confidences:
                # Weight confidence by word length so longer words have more influence
                total_weight = sum(word_lengths)
                if total_weight > 0:
                    avg_confidence = (
                        sum(c * w for c, w in zip(word_confidences, word_lengths))
                        / total_weight
                    )
                else:
                    avg_confidence = sum(word_confidences) / len(word_confidences)
                # Tesseract reports 0-100; normalise to 0-1
                avg_confidence = avg_confidence / 100.0
            else:
                avg_confidence = 0.0

            logger.debug(
                f"Tesseract: {len(word_confidences)} words, "
                f"confidence={avg_confidence:.2%}"
            )

            return {
                "text": text.strip(),
                "confidence": avg_confidence,
                "method": OCREngine.TESSERACT.value,
                "engine": OCREngine.TESSERACT.value,
                "mode": mode.value,
                "passes": 1,
                "blocks": len(text.split("\n")),
                "word_count": len(word_confidences),
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

    def should_use_ocr(
        self,
        mime_type: str,
        extracted_text: Optional[str] = None,
        file_path: Optional[str] = None,
    ) -> tuple[bool, str]:
        """
        Determine whether OCR processing is required for a document.

        Args:
            mime_type: MIME type of the document
            extracted_text: Text already extracted by a native parser (e.g. PyPDF2).
                            Pass None or omit when no extraction has been attempted.
            file_path: Optional path to the file (reserved for future use).

        Returns:
            (should_ocr, reason) — True when OCR should run, plus a log-friendly reason.
        """
        # Image files always require OCR — there is no native text layer
        if mime_type.startswith("image/"):
            return True, "image file — no native text layer"

        # Office documents have native text extraction — skip OCR
        OFFICE_MIMES = (
            "application/msword",
            "application/vnd.openxmlformats-officedocument.wordprocessingml",
            "application/vnd.ms-",
        )
        if any(mime_type.startswith(prefix) for prefix in OFFICE_MIMES):
            return False, f"Office document — native text extraction sufficient for {mime_type}"

        # PDFs: run OCR only when native extraction produced no usable text
        if mime_type == "application/pdf":
            if not extracted_text or not extracted_text.strip():
                return True, "scanned PDF — no extractable text found"

            # Short extracted text — likely a scanned PDF with minimal native text
            if len(extracted_text.strip()) < 50:
                return True, "PDF text too short (<50 chars) — likely scanned"

            # High whitespace ratio — likely a scanned PDF
            total_chars = len(extracted_text)
            non_whitespace = len(extracted_text.replace(" ", "").replace("\n", "").replace("\t", ""))
            if total_chars > 0:
                whitespace_ratio = 1.0 - (non_whitespace / total_chars)
                if whitespace_ratio > 0.9:
                    return True, f"high whitespace ratio ({whitespace_ratio:.0%}) — likely scanned PDF"

            return False, "native PDF with extractable text"

        # Everything else has native text extraction
        return False, f"native text extraction sufficient for {mime_type}"

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
