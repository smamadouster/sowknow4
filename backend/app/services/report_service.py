"""
Report Generation Service for Smart Collections

Generates PDF reports in Short/Standard/Comprehensive formats
from collection data using Gemini Flash for analysis and synthesis.
"""
import logging
import uuid
from typing import List, Dict, Any, Optional
from datetime import datetime
from sqlalchemy.orm import Session
from io import BytesIO

from app.models.collection import Collection, CollectionItem
from app.models.document import Document
from app.models.user import User
from app.services.gemini_service import gemini_service
from app.services.ollama_service import ollama_service

logger = logging.getLogger(__name__)


class ReportFormat:
    SHORT = "short"
    STANDARD = "standard"
    COMPREHENSIVE = "comprehensive"


class ReportService:
    """Service for generating reports from collections"""

    def __init__(self):
        self.gemini_service = gemini_service
        self.ollama_service = ollama_service

    async def generate_report(
        self,
        collection_id: uuid.UUID,
        format: str = ReportFormat.STANDARD,
        include_citations: bool = True,
        language: str = "en",
        user: User = None,
        db: Session = None
    ) -> Dict[str, Any]:
        """
        Generate a report from a collection

        Args:
            collection_id: Collection to generate report from
            format: Report format (short/standard/comprehensive)
            include_citations: Whether to include document citations
            language: Report language (en/fr)
            user: Current user
            db: Database session

        Returns:
            Dictionary with report content, metadata, and file info
        """
        # Get collection
        collection = db.query(Collection).filter(
            Collection.id == collection_id
        ).first()

        if not collection:
            raise ValueError(f"Collection {collection_id} not found")

        # Get collection items with documents
        items = db.query(CollectionItem).filter(
            CollectionItem.collection_id == collection_id
        ).join(Document).order_by(
            CollectionItem.relevance_score.desc()
        ).all()

        # Build document context
        document_context = await self._build_document_context(items, db)

        # Check for confidential documents
        has_confidential = any(
            item.document.bucket.value == "confidential"
            for item in items
            if item.document
        )

        # Generate report content
        if has_confidential:
            report_content = await self._generate_report_with_ollama(
                collection=collection,
                document_context=document_context,
                format=format,
                include_citations=include_citations,
                language=language
            )
            llm_used = "ollama"
        else:
            report_content = await self._generate_report_with_gemini(
                collection=collection,
                document_context=document_context,
                format=format,
                include_citations=include_citations,
                language=language
            )
            llm_used = "gemini"

        # Extract citations
        citations = []
        if include_citations:
            citations = [
                {
                    "filename": item.document.filename,
                    "id": str(item.document.id),
                    "relevance": item.relevance_score,
                    "added_reason": item.added_reason
                }
                for item in items[:10]
                if item.document
            ]

        # Generate report metadata
        report_metadata = {
            "report_id": str(uuid.uuid4()),
            "collection_id": str(collection_id),
            "collection_name": collection.name,
            "format": format,
            "language": language,
            "generated_at": datetime.utcnow().isoformat(),
            "llm_used": llm_used,
            "document_count": len(items),
            "word_count": len(report_content.split()),
            "citations": citations
        }

        # Generate PDF (if available)
        file_url = None
        try:
            file_url = await self._generate_pdf_report(
                content=report_content,
                metadata=report_metadata,
                collection=collection
            )
        except Exception as e:
            logger.error(f"PDF generation failed: {e}")

        return {
            **report_metadata,
            "content": report_content,
            "file_url": file_url
        }

    async def _build_document_context(
        self,
        items: List[CollectionItem],
        db: Session
    ) -> List[Dict[str, Any]]:
        """Build document context from collection items"""
        context = []

        for item in items[:15]:  # Top 15 documents
            if not item.document:
                continue

            from app.models.document import DocumentChunk

            chunks = db.query(DocumentChunk).filter(
                DocumentChunk.document_id == item.document_id
            ).order_by(DocumentChunk.chunk_index).limit(3).all()

            doc_info = {
                "filename": item.document.filename,
                "bucket": item.document.bucket.value,
                "created_at": item.document.created_at.isoformat(),
                "relevance": item.relevance_score,
                "chunks": [
                    {
                        "text": chunk.chunk_text[:400],
                        "page": chunk.page_number
                    }
                    for chunk in chunks
                ]
            }
            context.append(doc_info)

        return context

    async def _generate_report_with_gemini(
        self,
        collection: Collection,
        document_context: List[Dict[str, Any]],
        format: str,
        include_citations: bool,
        language: str
    ) -> str:
        """Generate report using Gemini Flash"""

        # Build format guidelines
        format_guides = {
            ReportFormat.SHORT: {
                "length": "1-2 pages",
                "sections": ["Executive Summary", "Key Findings", "Recommendations"],
                "detail": "Concise, high-level overview"
            },
            ReportFormat.STANDARD: {
                "length": "3-5 pages",
                "sections": ["Executive Summary", "Introduction", "Analysis", "Key Findings", "Recommendations", "Conclusion"],
                "detail": "Balanced overview with supporting details"
            },
            ReportFormat.COMPREHENSIVE: {
                "length": "6-10 pages",
                "sections": ["Executive Summary", "Introduction", "Background", "Detailed Analysis", "Key Findings", "Supporting Evidence", "Recommendations", "Implementation Notes", "Conclusion", "Appendices"],
                "detail": "In-depth analysis with extensive supporting evidence"
            }
        }

        guide = format_guides.get(format, format_guides[ReportFormat.STANDARD])

        # Language instruction
        lang_instruction = "Write the report in English." if language == "en" else "Rédigez le rapport en français."

        # Build document list
        doc_list = "\n".join([
            f"- {doc['filename']} (relevance: {doc['relevance']}%)"
            for doc in document_context[:10]
        ])

        system_prompt = f"""You are SOWKNOW, a professional report generator. Create a {guide['length']} report in {language} about the collection: "{collection.name}"

Collection Query: {collection.query}
AI Summary: {collection.ai_summary or 'Not available'}

FORMAT REQUIREMENTS:
{lang_instruction}
Length: {guide['length']}
Style: Professional business report
Sections: {', '.join(guide['sections'])}
Detail Level: {guide['detail']}

AVAILABLE DOCUMENTS ({len(document_context)} files):
{doc_list}

REPORT GUIDELINES:
1. Use clear section headings
2. Provide data-driven insights when possible
3. Include specific document references in brackets [filename]
4. Maintain professional, objective tone
5. Structure for executive audience
6. Highlight actionable insights

Generate the complete report now:"""

        messages = [
            {"role": "system", "content": "You are SOWKNOW, a professional report generator that creates well-structured business reports."},
            {"role": "user", "content": system_prompt}
        ]

        response_parts = []
        async for chunk in self.gemini_service.chat_completion(
            messages=messages,
            stream=False,
            temperature=0.5,
            max_tokens=8192
        ):
            if chunk and not chunk.startswith("Error:") and not chunk.startswith("__USAGE__"):
                response_parts.append(chunk)

        return "".join(response_parts).strip()

    async def _generate_report_with_ollama(
        self,
        collection: Collection,
        document_context: List[Dict[str, Any]],
        format: str,
        include_citations: bool,
        language: str
    ) -> str:
        """Generate report using Ollama for confidential collections"""

        doc_list = "\n".join([f"- {doc['filename']}" for doc in document_context[:10]])

        length_desc = {
            ReportFormat.SHORT: "concise 1-2 page",
            ReportFormat.STANDARD: "standard 3-5 page",
            ReportFormat.COMPREHENSIVE: "detailed 6-10 page"
        }.get(format, "standard 3-5 page")

        prompt = f"""Generate a {length_desc} report about: {collection.name}

Collection Query: {collection.query}
Summary: {collection.ai_summary or 'N/A'}

Documents:
{doc_list}

Create a professional report with:
- Executive Summary
- Key Findings
- Recommendations

{'' if language == 'en' else 'Rédigez le rapport en français.'}"""

        try:
            response = await self.ollama_service.generate(
                prompt=prompt,
                system="You are a professional report generator. Create structured, insightful business reports.",
                temperature=0.5
            )
            return response
        except Exception as e:
            logger.error(f"Ollama report generation error: {e}")
            return f"Report generation failed: {str(e)}"

    async def _generate_pdf_report(
        self,
        content: str,
        metadata: Dict[str, Any],
        collection: Collection
    ) -> Optional[str]:
        """
        Generate PDF report

        Returns file URL or None if generation fails
        """
        try:
            # Import reportlab here to avoid dependency issues
            from reportlab.lib.pagesizes import letter, A4
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.units import inch
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle
            from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
            from reportlab.lib import colors
            import os

            # Create buffer
            buffer = BytesIO()

            # Create PDF
            doc = SimpleDocTemplate(
                buffer,
                pagesize=A4,
                rightMargin=72,
                leftMargin=72,
                topMargin=72,
                bottomMargin=18
            )

            # Build PDF story
            story = []
            styles = getSampleStyleSheet()

            # Title style
            title_style = ParagraphStyle(
                'CustomTitle',
                parent=styles['Heading1'],
                fontSize=24,
                textColor=colors.HexColor('#1e40af'),
                alignment=TA_CENTER,
                spaceAfter=30
            )

            # Add title
            story.append(Paragraph(collection.name, title_style))
            story.append(Spacer(1, 12))

            # Add metadata
            meta_style = ParagraphStyle(
                'MetaData',
                parent=styles['Normal'],
                fontSize=10,
                textColor=colors.gray,
                alignment=TA_CENTER
            )

            generated_date = datetime.fromisoformat(metadata['generated_at']).strftime('%B %d, %Y')
            story.append(Paragraph(f"Generated: {generated_date} | Documents: {metadata['document_count']}", meta_style))
            story.append(Spacer(1, 24))

            # Parse content into paragraphs
            lines = content.split('\n')
            current_style = styles['Normal']

            for line in lines:
                line = line.strip()
                if not line:
                    story.append(Spacer(1, 6))
                    continue

                # Handle headings
                if line.startswith('# ') or line.upper() == line and len(line) < 50:
                    heading_style = ParagraphStyle(
                        'Heading',
                        parent=styles['Heading2'],
                        fontSize=14,
                        textColor=colors.HexColor('#1e3a8a'),
                        spaceAfter=12
                    )
                    clean_line = line.lstrip('#').strip()
                    story.append(Paragraph(clean_line, heading_style))
                elif line.startswith('- '):
                    # Bullet point
                    bullet_style = ParagraphStyle(
                        'Bullet',
                        parent=styles['Normal'],
                        leftIndent=20,
                        bulletIndent=10
                    )
                    story.append(Paragraph(line, bullet_style))
                else:
                    story.append(Paragraph(line, styles['BodyText']))

                story.append(Spacer(1, 6))

            # Add citations if available
            if metadata.get('citations'):
                story.append(PageBreak())
                story.append(Paragraph("References", styles['Heading2']))
                story.append(Spacer(1, 12))

                for citation in metadata['citations'][:10]:
                    citation_text = f"{citation['filename']} (Relevance: {citation['relevance']}%)"
                    story.append(Paragraph(f"• {citation_text}", styles['Normal']))

            # Build PDF
            doc.build(story)

            # Get PDF bytes
            pdf_bytes = buffer.getvalue()
            buffer.close()

            # Save to file (in a real implementation, this would upload to storage)
            # For now, we'll simulate and return a placeholder URL
            report_filename = f"report_{collection.id}_{metadata['report_id'][:8]}.pdf"

            # In production: upload to S3/storage and return URL
            # For now, return a placeholder
            return f"/api/v1/reports/download/{metadata['report_id']}"

        except ImportError:
            logger.warning("reportlab not installed, PDF generation skipped")
            return None
        except Exception as e:
            logger.error(f"PDF generation error: {e}")
            return None


# Global report service instance
report_service = ReportService()
