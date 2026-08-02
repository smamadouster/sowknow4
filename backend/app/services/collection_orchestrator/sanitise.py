"""Output sanitisation — FR7.2.

Stdlib-only sanitiser for deliverable rendering (no bleach / markupsafe
dependency). User-controlled text — document titles, filenames, snippets,
annotations, and the generated ``summary_md`` — can carry active content:
a malicious filename like ``"><script>alert(1)</script>.pdf`` or a snippet
containing ``[x](javascript:alert(1))`` must never reach the in-app view
or a PDF/DOCX export as executable markup.

Defences, in order:
1. HTML comments are removed (``<!-- ... -->`` can hide conditional markup).
2. ``<script>`` blocks are removed wholesale, including their content.
3. Event-handler attributes (``onerror=``, ``onclick=``, …) are stripped
   from anything shaped like an HTML tag.
4. ``javascript:`` / ``data:`` / ``vbscript:`` / ``file:`` URIs in markdown
   links and images are neutralised — the link collapses to its label text.
   Scheme detection entity-decodes and strips control/whitespace characters
   first, so ``&#106;avascript:`` and ``java\\tscript:`` are caught too.
5. Every remaining raw HTML tag delimiter is escaped (``<`` → ``&lt;``) so
   tags render as inert text. Only tag-like ``<`` (followed by a letter,
   ``/``, ``!`` or ``?``) is escaped — ``3 < 5`` stays untouched.

The function is idempotent (safe on already-clean or already-sanitised
text) and preserves legitimate markdown: ``**bold**``, tables, and links
with ``http(s)``/``mailto``/relative URIs pass through unchanged.
"""

import html
import re
from typing import Any

_DANGEROUS_SCHEMES = ("javascript:", "data:", "vbscript:", "file:")

_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_SCRIPT_BLOCK_RE = re.compile(r"<script\b[^>]*>.*?</script\s*>", re.IGNORECASE | re.DOTALL)
# Tag-shaped span: <tag ...>, </tag>, <!doctype ...>, <?xml ...>
_TAG_SPAN_RE = re.compile(r"</?[a-zA-Z][^>]*>?|<![^>]*>?|<\?[^>]*\??>")
_EVENT_HANDLER_RE = re.compile(
    r"\s+on[a-zA-Z]+\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s>]+)",
)
# Markdown link or image: [label](uri "optional title")
_MD_LINK_RE = re.compile(
    r"(?P<bang>!)?\[(?P<label>[^\]]*)\]"
    r"\(\s*(?P<uri>[^)\s]+)(?:\s+\"[^\"]*\")?\s*\)"
)
# A "<" that opens something tag-like (letter, /, !, ?) — escaped last.
_TAG_OPEN_RE = re.compile(r"<(?=[a-zA-Z/!?])")
_CONTROL_OR_SPACE_RE = re.compile(r"[\x00-\x20]+")


def _neutralised_scheme(uri: str) -> bool:
    """True when the URI scheme is dangerous (entity/whitespace-obfuscated
    variants included)."""
    decoded = html.unescape(uri)
    compact = _CONTROL_OR_SPACE_RE.sub("", decoded).lower()
    return compact.startswith(_DANGEROUS_SCHEMES)


def _strip_event_handlers(match: re.Match) -> str:
    return _EVENT_HANDLER_RE.sub("", match.group(0))


def _collapse_dangerous_link(match: re.Match) -> str:
    if _neutralised_scheme(match.group("uri")):
        # Drop the link, keep the human-readable label (image alt text for
        # images). The label itself is plain text here; the final escaping
        # pass still applies to any raw tags inside it.
        return match.group("label")
    return match.group(0)


def sanitise_text(text: Any) -> Any:
    """Sanitise one user-content string for deliverable rendering.

    Non-string input (None, numbers) is returned unchanged so callers can
    apply this blanket-style over mixed field values.
    """
    if not isinstance(text, str) or not text:
        return text
    cleaned = _HTML_COMMENT_RE.sub("", text)
    cleaned = _SCRIPT_BLOCK_RE.sub("", cleaned)
    cleaned = _TAG_SPAN_RE.sub(_strip_event_handlers, cleaned)
    cleaned = _MD_LINK_RE.sub(_collapse_dangerous_link, cleaned)
    cleaned = _TAG_OPEN_RE.sub("&lt;", cleaned)
    return cleaned


# Item fields that originate from user-controlled filenames / content.
_ITEM_TEXT_FIELDS = ("title", "annotation", "snippet", "source", "author")
_RELATED_TEXT_FIELDS = ("title",)


def sanitise_item(item: dict[str, Any]) -> dict[str, Any]:
    """Sanitise the user-content fields of one item-view dict in place
    (returns the same dict for chaining)."""
    for field in _ITEM_TEXT_FIELDS:
        if field in item:
            item[field] = sanitise_text(item[field])
    for related in item.get("related_items") or []:
        for field in _RELATED_TEXT_FIELDS:
            if field in related:
                related[field] = sanitise_text(related[field])
    return item


def sanitise_view(view: dict[str, Any]) -> dict[str, Any]:
    """Sanitise every user-content field of a deliverable view in place:
    ``summary_md`` and all item fields. Idempotent, so applying it to an
    already-sanitised view (e.g. from ``build_in_app_view``) is a no-op."""
    if "summary_md" in view:
        view["summary_md"] = sanitise_text(view["summary_md"])
    for item in view.get("items") or []:
        sanitise_item(item)
    return view
