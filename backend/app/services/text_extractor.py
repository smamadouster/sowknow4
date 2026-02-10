"""
Text extraction service for various document formats
"""
import os
import logging
from typing import Optional, Dict, Any, List
from pathlib import Path

logger = logging.getLogger(__name__)


class TextExtractor:
    """Service for extracting text from various document formats"""

    def __init__(self):
        self.supported_formats = {
            ".pdf": self._extract_from_pdf,
            ".docx": self._extract_from_docx,
            ".doc": self._extract_from_doc,
            ".pptx": self._extract_from_pptx,
            ".ppt": self._extract_from_ppt,
            ".xlsx": self._extract_from_xlsx,
            ".xls": self._extract_from_xls,
            ".txt": self._extract_from_txt,
            ".md": self._extract_from_txt,
            ".json": self._extract_from_json,
            ".epub": self._extract_from_epub,
        }

    def get_file_extension(self, filename: str) -> str:
        """Get file extension from filename"""
        return Path(filename).suffix.lower()

    async def extract_text(self, file_path: str, filename: str) -> Dict[str, Any]:
        """
        Extract text from a document file

        Args:
            file_path: Path to the file
            filename: Original filename

        Returns:
            dict with extracted text, metadata, and page count
        """
        file_extension = self.get_file_extension(filename)

        if file_extension not in self.supported_formats:
            return {
                "text": "",
                "error": f"Unsupported file format: {file_extension}",
                "pages": 0
            }

        try:
            extractor = self.supported_formats[file_extension]
            result = await extractor(file_path)

            # Add metadata
            result["format"] = file_extension
            result["success"] = "error" not in result

            return result

        except Exception as e:
            logger.error(f"Error extracting text from {filename}: {str(e)}")
            return {
                "text": "",
                "error": str(e),
                "format": file_extension,
                "pages": 0,
                "success": False
            }

    async def _extract_from_pdf(self, file_path: str) -> Dict[str, Any]:
        """Extract text from PDF file"""
        try:
            import PyPDF2

            text_parts = []
            with open(file_path, "rb") as file:
                pdf_reader = PyPDF2.PdfReader(file)
                page_count = len(pdf_reader.pages)

                for page_num, page in enumerate(pdf_reader.pages):
                    page_text = page.extract_text()
                    if page_text.strip():
                        text_parts.append(f"[Page {page_num + 1}]\n{page_text}")

            return {
                "text": "\n\n".join(text_parts),
                "pages": page_count,
                "source": "pypdf2"
            }

        except Exception as e:
            logger.error(f"Error extracting from PDF: {str(e)}")
            return {"text": "", "error": str(e), "pages": 0}

    async def _extract_from_docx(self, file_path: str) -> Dict[str, Any]:
        """Extract text from DOCX file"""
        try:
            from docx import Document

            doc = Document(file_path)
            text_parts = []

            for paragraph in doc.paragraphs:
                if paragraph.text.strip():
                    text_parts.append(paragraph.text)

            # Extract from tables
            for table in doc.tables:
                for row in table.rows:
                    row_text = " | ".join([cell.text.strip() for cell in row.cells])
                    if row_text.strip():
                        text_parts.append(row_text)

            return {
                "text": "\n".join(text_parts),
                "pages": 0,
                "source": "python-docx"
            }

        except Exception as e:
            logger.error(f"Error extracting from DOCX: {str(e)}")
            return {"text": "", "error": str(e), "pages": 0}

    async def _extract_from_doc(self, file_path: str) -> Dict[str, Any]:
        """Extract text from legacy DOC file (requires conversion)"""
        # DOC files require conversion tools - for now return placeholder
        return {
            "text": "",
            "error": "Legacy DOC files require conversion tool",
            "pages": 0,
            "source": "error"
        }

    async def _extract_from_pptx(self, file_path: str) -> Dict[str, Any]:
        """Extract text from PPTX file"""
        try:
            from pptx import Presentation

            prs = Presentation(file_path)
            text_parts = []
            slide_count = len(prs.slides)

            for slide_num, slide in enumerate(prs.slides):
                slide_text_parts = []
                for shape in slide.shapes:
                    if hasattr(shape, "text") and shape.text.strip():
                        slide_text_parts.append(shape.text)

                if slide_text_parts:
                    text_parts.append(f"[Slide {slide_num + 1}]\n" + "\n".join(slide_text_parts))

            return {
                "text": "\n\n".join(text_parts),
                "pages": slide_count,
                "source": "python-pptx"
            }

        except Exception as e:
            logger.error(f"Error extracting from PPTX: {str(e)}")
            return {"text": "", "error": str(e), "pages": 0}

    async def _extract_from_ppt(self, file_path: str) -> Dict[str, Any]:
        """Extract text from legacy PPT file"""
        return {
            "text": "",
            "error": "Legacy PPT files require conversion tool",
            "pages": 0,
            "source": "error"
        }

    async def _extract_from_xlsx(self, file_path: str) -> Dict[str, Any]:
        """Extract text from XLSX file"""
        try:
            from openpyxl import load_workbook

            wb = load_workbook(file_path, read_only=True)
            text_parts = []
            sheet_count = len(wb.sheetnames)

            for sheet_name in wb.sheetnames:
                sheet = wb[sheet_name]
                sheet_text_parts = [f"[Sheet: {sheet_name}]"]

                for row in sheet.iter_rows(values_only=True):
                    row_text = " | ".join([str(cell) if cell is not None else "" for cell in row])
                    if row_text.strip() and row_text != " | ".join([""] * len(row))):
                        sheet_text_parts.append(row_text)

                if len(sheet_text_parts) > 1:
                    text_parts.append("\n".join(sheet_text_parts))

            return {
                "text": "\n\n".join(text_parts),
                "pages": sheet_count,
                "source": "openpyxl"
            }

        except Exception as e:
            logger.error(f"Error extracting from XLSX: {str(e)}")
            return {"text": "", "error": str(e), "pages": 0}

    async def _extract_from_xls(self, file_path: str) -> Dict[str, Any]:
        """Extract text from legacy XLS file"""
        return {
            "text": "",
            "error": "Legacy XLS files require xlrd library",
            "pages": 0,
            "source": "error"
        }

    async def _extract_from_txt(self, file_path: str) -> Dict[str, Any]:
        """Extract text from TXT or MD file"""
        try:
            # Try UTF-8 first, fallback to latin-1
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    text = f.read()
            except UnicodeDecodeError:
                with open(file_path, "r", encoding="latin-1") as f:
                    text = f.read()

            return {
                "text": text,
                "pages": 0,
                "source": "file"
            }

        except Exception as e:
            logger.error(f"Error extracting from TXT: {str(e)}")
            return {"text": "", "error": str(e), "pages": 0}

    async def _extract_from_json(self, file_path: str) -> Dict[str, Any]:
        """Extract text from JSON file"""
        try:
            import json

            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Convert JSON to readable text
            text = json.dumps(data, indent=2, ensure_ascii=False)

            return {
                "text": text,
                "pages": 0,
                "source": "json"
            }

        except Exception as e:
            logger.error(f"Error extracting from JSON: {str(e)}")
            return {"text": "", "error": str(e), "pages": 0}

    async def _extract_from_epub(self, file_path: str) -> Dict[str, Any]:
        """Extract text from EPUB file"""
        try:
            from ebooklib import epub

            book = epub.read_epub(file_path)
            text_parts = []

            for item in book.get_items():
                if item.get_type() == epub.EpubHtml:
                    # Remove HTML tags
                    import re
                    content = item.get_content().decode("utf-8")
                    text = re.sub(r"<[^>]+>", "", content)
                    text = " ".join(text.split())
                    if text.strip():
                        text_parts.append(text)

            return {
                "text": "\n\n".join(text_parts),
                "pages": 0,
                "source": "ebooklib"
            }

        except Exception as e:
            logger.error(f"Error extracting from EPUB: {str(e)}")
            return {"text": "", "error": str(e), "pages": 0}

    async def extract_images_from_pdf(self, file_path: str) -> List[bytes]:
        """
        Extract images from PDF for OCR processing

        Args:
            file_path: Path to PDF file

        Returns:
            List of image bytes
        """
        try:
            import PyPDF2
            from PIL import Image
            import io

            images = []
            with open(file_path, "rb") as file:
                pdf_reader = PyPDF2.PdfReader(file)

                for page_num, page in enumerate(pdf_reader.pages):
                    if "/XObject" in page["/Resources"]:
                        xObject = page["/Resources"]["/XObject"].get_object()

                        for obj_name in xObject:
                            if xObject[obj_name]["/Subtype"] == "/Image":
                                try:
                                    image_data = xObject[obj_name]._data
                                    images.append(image_data)
                                except:
                                    continue

            return images

        except Exception as e:
            logger.error(f"Error extracting images from PDF: {str(e)}")
            return []


# Global text extractor instance
text_extractor = TextExtractor()
