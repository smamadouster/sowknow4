"""Unit tests for FR7.2 output sanitisation — no DB, no network."""
import pytest
pytest.skip("Disabled during Ollama removal (Sep 4)", allow_module_level=True)

from types import SimpleNamespace

from app.services.collection_orchestrator import packaging_service
from app.services.collection_orchestrator.sanitise import (
    sanitise_item,
    sanitise_text,
    sanitise_view,
)


# ---------------------------------------------------------------------------
# sanitise_text — active-content neutralisation
# ---------------------------------------------------------------------------

class TestScriptNeutralisation:
    def test_script_block_removed_with_content(self):
        out = sanitise_text("hello <script>alert(1)</script> world")
        assert "<script>" not in out
        assert "alert(1)" not in out
        assert "hello" in out and "world" in out

    def test_script_block_case_insensitive(self):
        out = sanitise_text("<SCRIPT SRC=https://evil.example/x.js></SCRIPT>")
        assert "<" not in out or "&lt;" in out
        assert "evil.example" not in out

    def test_unclosed_script_tag_escaped(self):
        out = sanitise_text('<script src="evil.js">')
        assert "<script" not in out
        assert "&lt;script" in out

    def test_malicious_filename_neutralised(self):
        filename = '"><script>alert(1)</script>.pdf'
        out = sanitise_text(filename)
        assert "<script>" not in out
        assert "alert(1)" not in out
        assert out.endswith(".pdf")

    def test_img_onerror_handler_stripped_and_escaped(self):
        out = sanitise_text('<img src=x onerror=alert(1)>')
        assert "onerror=" not in out
        assert "<img" not in out

    def test_event_handler_with_quoted_value(self):
        out = sanitise_text('<a href="#" onclick="evil()">x</a>')
        assert "onclick" not in out
        assert "&lt;a" in out


class TestUriNeutralisation:
    def test_javascript_link_collapses_to_label(self):
        out = sanitise_text("[click me](javascript:alert(1))")
        assert "javascript:" not in out
        assert "click me" in out

    def test_javascript_image_collapses_to_alt(self):
        out = sanitise_text("![alt text](javascript:alert(1))")
        assert "javascript:" not in out
        assert "alt text" in out

    def test_data_uri_image_neutralised(self):
        out = sanitise_text("![x](data:text/html;base64,PHNjcmlwdD4=)")
        assert "data:text/html" not in out

    def test_obfuscated_scheme_caught(self):
        # NUL byte inside the scheme + HTML-entity-encoded first letter.
        out = sanitise_text("[x](java\x00script:alert(1))")
        assert "java" not in out.replace("x", "")
        out = sanitise_text("[y](&#106;avascript:alert(1))")
        assert "avascript:" not in out
        assert "y" in out

    def test_legit_links_preserved(self):
        text = "[docs](https://example.com/a) and [rel](/documents/123) and [mail](mailto:a@b.c)"
        assert sanitise_text(text) == text


class TestHtmlCommentsAndEscaping:
    def test_html_comment_removed(self):
        out = sanitise_text("a <!-- hidden instruction --> b")
        assert "hidden instruction" not in out
        assert out == "a  b"

    def test_raw_tags_escaped(self):
        out = sanitise_text("<b>bold</b> <div class=\"x\">y</div>")
        assert "<b>" not in out and "<div" not in out
        assert "&lt;b>" in out

    def test_comparison_operators_untouched(self):
        text = "3 < 5 and 7 > 2"
        assert sanitise_text(text) == text


class TestIdempotencyAndPreservation:
    def test_idempotent_on_malicious_input(self):
        payload = '"><script>alert(1)</script> [x](javascript:alert(2)) <!-- c --> <i onmouseover=evil()>hi</i>'
        once = sanitise_text(payload)
        assert sanitise_text(once) == once

    def test_legit_markdown_preserved(self):
        md = (
            "## Overview\n\n**Bold** and *italic*.\n\n"
            "| a | b |\n|---|---|\n| 1 | 2 |\n\n"
            "- [link](https://example.com)\n"
        )
        assert sanitise_text(md) == md

    def test_non_string_passthrough(self):
        assert sanitise_text(None) is None
        assert sanitise_text(42) == 42


# ---------------------------------------------------------------------------
# item / view level
# ---------------------------------------------------------------------------

class TestItemAndView:
    def test_item_fields_sanitised(self):
        item = {
            "title": '"><script>alert(1)</script>.pdf',
            "snippet": "revenue [x](javascript:alert(1))",
            "annotation": "<i onclick=evil()>note</i>",
            "author": "<b>Mallory</b>",
            "source": "upload",
            "related_items": [{"title": "<img src=x onerror=alert(1)>"}],
        }
        out = sanitise_item(item)
        assert "<script>" not in out["title"]
        assert "javascript:" not in out["snippet"]
        assert "onclick" not in out["annotation"]
        assert "&lt;b>" in out["author"]
        assert "onerror" not in out["related_items"][0]["title"]
        assert out["source"] == "upload"

    def test_view_sanitises_summary_and_items(self):
        view = {
            "summary_md": "## Overview\n\n<script>alert(1)</script>Clean 1,000.",
            "items": [{"title": '"><script>alert(2)</script>.pdf'}],
        }
        out = sanitise_view(view)
        assert "<script>" not in out["summary_md"]
        assert "Clean 1,000." in out["summary_md"]
        assert "<script>" not in out["items"][0]["title"]

    def test_view_idempotent(self):
        view = {
            "summary_md": "x <script>a()</script> [l](javascript:b())",
            "items": [{"title": "<u onfocus=evil()>t</u>"}],
        }
        once = sanitise_view(dict(view, items=[dict(view["items"][0])]))
        twice = sanitise_view(once)
        assert twice == once


# ---------------------------------------------------------------------------
# packaging integration
# ---------------------------------------------------------------------------

class TestPackagingIntegration:
    def test_build_in_app_view_sanitises_user_content(self):
        deliverable = SimpleNamespace(
            id="d-1",
            request_id="r-1",
            version=1,
            summary_md="## Overview\n\n<script>alert(1)</script>Revenue 1,000.",
            appendix={},
            disclosures=[],
            created_at=None,
        )
        items = [{
            "id": "i-1",
            "document_id": None,
            "title": '"><script>alert(1)</script>.pdf',
            "annotation": "ok",
            "snippet": "[x](javascript:alert(1))",
            "rank_position": 1,
        }]
        view = packaging_service.build_in_app_view(deliverable, items, [])
        assert "<script>" not in view["summary_md"]
        assert "<script>" not in view["items"][0]["title"]
        assert "javascript:" not in view["items"][0]["snippet"]

    def test_export_pdf_survives_malicious_content(self):
        pytest = __import__("pytest")
        pytest.importorskip("reportlab")
        deliverable = SimpleNamespace(id="d-1", request_id="r-1", version=1)
        view = {
            "version": 1,
            "summary_md": "## Overview\n\n<script>alert(1)</script>Revenue 1,000.",
            "items": [{
                "title": '"><script>alert(1)</script>.pdf',
                "date": None,
                "annotation": "<i onerror=evil()>n</i>",
                "rank_position": 1,
            }],
            "appendix": {},
            "disclosures": [],
            "data_as_of": None,
        }
        payload = packaging_service.export_pdf(deliverable, view)
        assert payload.startswith(b"%PDF")

    def test_export_docx_survives_malicious_content(self):
        pytest = __import__("pytest")
        pytest.importorskip("docx")
        deliverable = SimpleNamespace(id="d-1", request_id="r-1", version=1)
        view = {
            "version": 1,
            "summary_md": "## Overview\n\n<script>alert(1)</script>Text.",
            "items": [{
                "title": '"><script>alert(1)</script>.pdf',
                "date": None,
                "annotation": "note",
                "rank_position": 1,
            }],
            "appendix": {},
            "disclosures": [],
            "data_as_of": None,
        }
        payload = packaging_service.export_docx(deliverable, view)
        assert payload[:2] == b"PK"  # docx is a zip
