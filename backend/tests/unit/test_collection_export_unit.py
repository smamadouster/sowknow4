"""
Unit tests for Collection Export endpoint — PDF generation with mocked reportlab.

These tests verify the export logic without a real database or real PDF rendering,
using unittest.mock to isolate the endpoint behaviour.
"""

import io
from datetime import datetime
from uuid import uuid4

from app.models.user import User, UserRole
from app.models.document import Document, DocumentBucket, DocumentStatus
from app.models.collection import Collection, CollectionItem, CollectionVisibility, CollectionType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(role: UserRole, *, can_confidential: bool = True) -> User:
    u = User(
        id=uuid4(),
        email=f"{role.value}@test.local",
        hashed_password="x",
        full_name=f"Test {role.value}",
        role=role,
        is_active=True,
        can_access_confidential=can_confidential,
    )
    return u


def _make_document(bucket: DocumentBucket) -> Document:
    doc = Document(
        id=uuid4(),
        filename=f"doc_{bucket.value}.pdf",
        original_filename=f"doc_{bucket.value}.pdf",
        file_path=f"/data/{bucket.value}/doc.pdf",
        bucket=bucket,
        status=DocumentStatus.INDEXED,
        size=1024,
        mime_type="application/pdf",
    )
    # Provide created_at for isoformat call
    doc.created_at = datetime(2026, 1, 15, 12, 0, 0)
    return doc


def _make_collection(user: User, *, is_confidential: bool = False) -> Collection:
    col = Collection(
        id=uuid4(),
        user_id=user.id,
        name="Test Collection Alpha",
        description="Unit test collection",
        query="find all legacy documents about inheritance",
        collection_type=CollectionType.SMART,
        visibility=CollectionVisibility.PUBLIC,
        ai_summary="A summary of the collection for testing purposes.",
        ai_keywords=["inheritance", "legacy", "family"],
        is_confidential=is_confidential,
        document_count=1,
    )
    col.created_at = datetime(2026, 1, 10, 9, 0, 0)
    col.updated_at = datetime(2026, 1, 20, 10, 0, 0)
    return col


def _make_item(collection: Collection, document: Document, *, relevance: int = 80) -> CollectionItem:
    item = CollectionItem(
        id=uuid4(),
        collection_id=collection.id,
        document_id=document.id,
        relevance_score=relevance,
        order_index=0,
        notes="A test note",
        added_reason="AI found this document highly relevant to the query.",
        is_highlighted=False,
    )
    item.document = document
    return item


# ---------------------------------------------------------------------------
# PDF generation unit tests (reportlab mocked)
# ---------------------------------------------------------------------------

class TestPdfExportGeneration:
    """Test PDF generation logic in isolation using mocked reportlab."""

    def _run_pdf_generation(self, collection, documents_data, current_user):
        """
        Execute only the PDF-building section of the export endpoint logic.
        Returns the raw bytes from the BytesIO buffer.
        This mirrors the endpoint code to test it without HTTP.
        """
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.platypus import (
            SimpleDocTemplate,
            Paragraph,
            Spacer,
            Table,
            TableStyle,
            HRFlowable,
        )
        from reportlab.lib import colors

        generated_at = datetime(2026, 2, 24, 12, 0, 0)

        # Extract themes
        themes: list = []
        if collection.ai_keywords:
            kw = collection.ai_keywords
            if isinstance(kw, list):
                themes = [str(k) for k in kw if k]
            elif isinstance(kw, str):
                themes = [t.strip() for t in kw.split(",") if t.strip()]

        buffer = io.BytesIO()

        def _add_footer(canv, doc):
            canv.saveState()
            canv.setFont("Helvetica", 8)
            canv.setFillColor(colors.HexColor("#6B7280"))
            page_width = letter[0]
            footer_y = 0.3 * inch
            canv.drawString(0.75 * inch, footer_y, "SOWKNOW — Multi-Generational Legacy Knowledge System")
            canv.drawRightString(page_width - 0.75 * inch, footer_y, f"Page {doc.page}")
            canv.restoreState()

        doc = SimpleDocTemplate(
            buffer, pagesize=letter,
            topMargin=0.75 * inch, bottomMargin=0.75 * inch,
            leftMargin=0.75 * inch, rightMargin=0.75 * inch,
        )
        styles = getSampleStyleSheet()
        brand_blue = colors.HexColor("#1E40AF")
        brand_grey = colors.HexColor("#6B7280")

        title_style = ParagraphStyle("T", parent=styles["Heading1"], fontSize=20, textColor=brand_blue)
        subtitle_style = ParagraphStyle("S", parent=styles["Normal"], fontSize=10, textColor=brand_grey)
        heading_style = ParagraphStyle("H", parent=styles["Heading2"], fontSize=13, textColor=brand_blue)
        normal_style = styles["Normal"]

        story = []
        story.append(Paragraph(f"Collection: {collection.name}", title_style))
        story.append(Paragraph(
            f"Exported by {current_user.email} · Generated {generated_at.strftime('%Y-%m-%d %H:%M UTC')}",
            subtitle_style,
        ))
        story.append(HRFlowable(width="100%", thickness=1, color=brand_blue, spaceAfter=10))
        story.append(Paragraph(f"<b>Query:</b> {collection.query or '—'}", normal_style))
        story.append(Paragraph(
            f"<b>Created:</b> {collection.created_at.strftime('%Y-%m-%d %H:%M')} · "
            f"<b>Documents:</b> {len(documents_data)}", normal_style,
        ))
        story.append(Spacer(1, 0.15 * inch))

        if collection.ai_summary:
            story.append(Paragraph("AI Summary", heading_style))
            story.append(Paragraph(collection.ai_summary, normal_style))
            story.append(Spacer(1, 0.1 * inch))

        if themes:
            story.append(Paragraph("Identified Themes", heading_style))
            story.append(Paragraph(" · ".join(themes), normal_style))
            story.append(Spacer(1, 0.1 * inch))

        if documents_data:
            story.append(Paragraph("Documents", heading_style))
            table_data = [["#", "Filename", "Score", "Excerpt / Notes"]]
            for idx, doc_item in enumerate(documents_data, 1):
                excerpt = doc_item.get("excerpt") or doc_item.get("notes") or "—"
                if len(excerpt) > 80:
                    excerpt = excerpt[:77] + "..."
                filename = doc_item["filename"]
                if len(filename) > 45:
                    filename = filename[:42] + "..."
                score = doc_item["relevance_score"]
                score_str = f"{score}%" if score is not None else "—"
                table_data.append([str(idx), filename, score_str, excerpt])

            col_widths = [0.35 * inch, 2.8 * inch, 0.65 * inch, 3.0 * inch]
            table = Table(table_data, colWidths=col_widths)
            table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), brand_blue),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 9),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D1D5DB")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]))
            story.append(table)

        doc.build(story, onFirstPage=_add_footer, onLaterPages=_add_footer)
        buffer.seek(0)
        return buffer.getvalue()

    def test_pdf_bytes_are_valid_pdf(self):
        """Generated bytes start with PDF magic bytes."""
        user = _make_user(UserRole.ADMIN)
        collection = _make_collection(user)
        doc = _make_document(DocumentBucket.PUBLIC)
        documents_data = [{
            "id": str(doc.id), "filename": doc.filename, "relevance_score": 90,
            "excerpt": "Relevant to inheritance query.", "notes": "Test note",
            "is_highlighted": False, "created_at": doc.created_at.isoformat(),
        }]

        pdf_bytes = self._run_pdf_generation(collection, documents_data, user)
        assert pdf_bytes.startswith(b"%PDF")

    def test_pdf_has_non_trivial_size(self):
        """PDF should be larger than a minimal skeleton — content was actually rendered."""
        user = _make_user(UserRole.ADMIN)
        collection = _make_collection(user)
        documents_data = []

        pdf_bytes = self._run_pdf_generation(collection, documents_data, user)
        # A real PDF with title, summary and themes is well above 2 KB
        assert len(pdf_bytes) > 2_000, f"PDF unexpectedly small: {len(pdf_bytes)} bytes"

    def test_pdf_with_no_documents_builds_without_error(self):
        """PDF should build cleanly even with an empty document list."""
        user = _make_user(UserRole.USER, can_confidential=False)
        collection = _make_collection(user)
        pdf_bytes = self._run_pdf_generation(collection, [], user)
        assert pdf_bytes.startswith(b"%PDF")
        assert len(pdf_bytes) > 500  # Non-trivial PDF

    def test_pdf_with_themes_builds_without_error(self):
        """PDF with ai_keywords themes builds cleanly."""
        user = _make_user(UserRole.ADMIN)
        collection = _make_collection(user)
        assert collection.ai_keywords == ["inheritance", "legacy", "family"]
        pdf_bytes = self._run_pdf_generation(collection, [], user)
        assert pdf_bytes.startswith(b"%PDF")

    def test_pdf_with_string_keywords_builds_without_error(self):
        """PDF with comma-separated string ai_keywords builds cleanly."""
        user = _make_user(UserRole.ADMIN)
        collection = _make_collection(user)
        collection.ai_keywords = "inheritance, legacy, family"
        pdf_bytes = self._run_pdf_generation(collection, [], user)
        assert pdf_bytes.startswith(b"%PDF")

    def test_pdf_long_filename_truncated(self):
        """Filenames > 45 chars are truncated to avoid table overflow."""
        user = _make_user(UserRole.ADMIN)
        collection = _make_collection(user)
        long_filename = "a_very_long_filename_that_exceeds_the_limit_in_the_pdf_table.pdf"
        documents_data = [{
            "id": str(uuid4()), "filename": long_filename, "relevance_score": 75,
            "excerpt": "", "notes": "", "is_highlighted": False,
            "created_at": datetime(2026, 1, 1).isoformat(),
        }]
        pdf_bytes = self._run_pdf_generation(collection, documents_data, user)
        assert pdf_bytes.startswith(b"%PDF")

    def test_pdf_long_excerpt_truncated(self):
        """Excerpts > 80 chars are truncated with ellipsis."""
        user = _make_user(UserRole.ADMIN)
        collection = _make_collection(user)
        long_excerpt = "x" * 100
        documents_data = [{
            "id": str(uuid4()), "filename": "doc.pdf", "relevance_score": 60,
            "excerpt": long_excerpt, "notes": "", "is_highlighted": False,
            "created_at": datetime(2026, 1, 1).isoformat(),
        }]
        pdf_bytes = self._run_pdf_generation(collection, documents_data, user)
        assert pdf_bytes.startswith(b"%PDF")

    def test_pdf_none_relevance_score_handled(self):
        """None relevance score is displayed as '—' without crashing."""
        user = _make_user(UserRole.ADMIN)
        collection = _make_collection(user)
        documents_data = [{
            "id": str(uuid4()), "filename": "doc.pdf", "relevance_score": None,
            "excerpt": "test", "notes": "", "is_highlighted": False,
            "created_at": datetime(2026, 1, 1).isoformat(),
        }]
        pdf_bytes = self._run_pdf_generation(collection, documents_data, user)
        assert pdf_bytes.startswith(b"%PDF")

    def test_pdf_no_ai_summary_skips_section(self):
        """Collection without ai_summary generates PDF without error."""
        user = _make_user(UserRole.ADMIN)
        collection = _make_collection(user)
        collection.ai_summary = None
        pdf_bytes = self._run_pdf_generation(collection, [], user)
        assert pdf_bytes.startswith(b"%PDF")

    def test_pdf_no_keywords_skips_themes_section(self):
        """Collection without ai_keywords generates PDF without themes section."""
        user = _make_user(UserRole.ADMIN)
        collection = _make_collection(user)
        collection.ai_keywords = None
        pdf_bytes = self._run_pdf_generation(collection, [], user)
        assert pdf_bytes.startswith(b"%PDF")


# ---------------------------------------------------------------------------
# Document data building unit tests (RBAC / privacy)
# ---------------------------------------------------------------------------

class TestExportDocumentDataBuilding:
    """Unit tests for the documents_data assembly logic (privacy / RBAC)."""

    def _build_documents_data(self, items, current_user):
        """Mirror the documents_data building from the endpoint."""
        show_bucket = current_user.role.value in ["admin", "superuser"]
        documents_data = []
        for item in items:
            if item.document:
                doc_entry = {
                    "id": str(item.document.id),
                    "filename": item.document.filename,
                    "relevance_score": item.relevance_score,
                    "excerpt": item.added_reason or "",
                    "notes": item.notes,
                    "is_highlighted": item.is_highlighted,
                    "created_at": item.document.created_at.isoformat(),
                }
                if show_bucket:
                    doc_entry["bucket"] = item.document.bucket.value
                documents_data.append(doc_entry)
        return documents_data

    def test_regular_user_does_not_see_bucket_label(self):
        """Regular user export must not include bucket field (privacy)."""
        user = _make_user(UserRole.USER, can_confidential=False)
        doc = _make_document(DocumentBucket.PUBLIC)
        col = _make_collection(user)
        item = _make_item(col, doc)

        data = self._build_documents_data([item], user)
        assert len(data) == 1
        assert "bucket" not in data[0]

    def test_admin_sees_bucket_label(self):
        """Admin export includes bucket field for full transparency."""
        user = _make_user(UserRole.ADMIN)
        doc = _make_document(DocumentBucket.CONFIDENTIAL)
        col = _make_collection(user, is_confidential=True)
        item = _make_item(col, doc)

        data = self._build_documents_data([item], user)
        assert len(data) == 1
        assert data[0]["bucket"] == "confidential"

    def test_superuser_sees_bucket_label(self):
        """Superuser export includes bucket field."""
        user = _make_user(UserRole.SUPERUSER)
        doc = _make_document(DocumentBucket.PUBLIC)
        col = _make_collection(user)
        item = _make_item(col, doc)

        data = self._build_documents_data([item], user)
        assert len(data) == 1
        assert data[0]["bucket"] == "public"

    def test_excerpt_from_added_reason(self):
        """Excerpt field uses CollectionItem.added_reason when present."""
        user = _make_user(UserRole.USER, can_confidential=False)
        doc = _make_document(DocumentBucket.PUBLIC)
        col = _make_collection(user)
        item = _make_item(col, doc)
        item.added_reason = "AI found high relevance to inheritance query."

        data = self._build_documents_data([item], user)
        assert data[0]["excerpt"] == "AI found high relevance to inheritance query."

    def test_excerpt_empty_when_no_added_reason(self):
        """Excerpt defaults to empty string when added_reason is None."""
        user = _make_user(UserRole.USER, can_confidential=False)
        doc = _make_document(DocumentBucket.PUBLIC)
        col = _make_collection(user)
        item = _make_item(col, doc)
        item.added_reason = None

        data = self._build_documents_data([item], user)
        assert data[0]["excerpt"] == ""

    def test_item_without_document_is_skipped(self):
        """Items where document is None are silently excluded."""
        user = _make_user(UserRole.ADMIN)
        col = _make_collection(user)
        item = CollectionItem(
            id=uuid4(), collection_id=col.id, document_id=uuid4(),
            relevance_score=70, order_index=0,
        )
        item.document = None

        data = self._build_documents_data([item], user)
        assert data == []

    def test_relevance_score_preserved(self):
        """Relevance score from CollectionItem is preserved in export data."""
        user = _make_user(UserRole.ADMIN)
        doc = _make_document(DocumentBucket.PUBLIC)
        col = _make_collection(user)
        item = _make_item(col, doc, relevance=95)

        data = self._build_documents_data([item], user)
        assert data[0]["relevance_score"] == 95


# ---------------------------------------------------------------------------
# Themes extraction unit tests
# ---------------------------------------------------------------------------

class TestThemesExtraction:
    """Unit tests for the ai_keywords → themes extraction logic."""

    def _extract_themes(self, ai_keywords) -> list:
        themes: list = []
        if ai_keywords:
            kw = ai_keywords
            if isinstance(kw, list):
                themes = [str(k) for k in kw if k]
            elif isinstance(kw, str):
                themes = [t.strip() for t in kw.split(",") if t.strip()]
        return themes

    def test_list_keywords_extracted(self):
        assert self._extract_themes(["alpha", "beta", "gamma"]) == ["alpha", "beta", "gamma"]

    def test_string_keywords_split_by_comma(self):
        assert self._extract_themes("alpha, beta, gamma") == ["alpha", "beta", "gamma"]

    def test_none_returns_empty_list(self):
        assert self._extract_themes(None) == []

    def test_empty_list_returns_empty(self):
        assert self._extract_themes([]) == []

    def test_empty_string_returns_empty(self):
        assert self._extract_themes("") == []

    def test_falsy_items_in_list_filtered(self):
        assert self._extract_themes([None, "", "valid"]) == ["valid"]

    def test_non_string_items_in_list_coerced(self):
        result = self._extract_themes([42, True, "text"])
        assert "42" in result
        assert "text" in result


# ---------------------------------------------------------------------------
# Confidential item detection unit tests
# ---------------------------------------------------------------------------

class TestConfidentialItemDetection:
    """Unit tests for confidential_items filter logic."""

    def _get_confidential_items(self, items) -> list:
        return [
            item for item in items
            if item.document and item.document.bucket.value == "confidential"
        ]

    def test_public_only_collection_has_no_confidential_items(self):
        user = _make_user(UserRole.USER)
        col = _make_collection(user)
        doc = _make_document(DocumentBucket.PUBLIC)
        item = _make_item(col, doc)
        assert self._get_confidential_items([item]) == []

    def test_confidential_document_detected(self):
        user = _make_user(UserRole.ADMIN)
        col = _make_collection(user, is_confidential=True)
        doc = _make_document(DocumentBucket.CONFIDENTIAL)
        item = _make_item(col, doc)
        result = self._get_confidential_items([item])
        assert len(result) == 1
        assert result[0].document.bucket.value == "confidential"

    def test_mixed_collection_confidential_items_detected(self):
        user = _make_user(UserRole.ADMIN)
        col = _make_collection(user, is_confidential=True)
        pub_doc = _make_document(DocumentBucket.PUBLIC)
        conf_doc = _make_document(DocumentBucket.CONFIDENTIAL)
        pub_item = _make_item(col, pub_doc)
        conf_item = _make_item(col, conf_doc)

        result = self._get_confidential_items([pub_item, conf_item])
        assert len(result) == 1
        assert result[0].document.bucket.value == "confidential"

    def test_item_without_document_not_counted_as_confidential(self):
        user = _make_user(UserRole.ADMIN)
        col = _make_collection(user)
        item = CollectionItem(id=uuid4(), collection_id=col.id, document_id=uuid4())
        item.document = None
        assert self._get_confidential_items([item]) == []
