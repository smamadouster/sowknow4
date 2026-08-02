"""Extraction Pipeline — FR4.1 deterministic, LLM-free fact extraction.

Turns retrieved source-item contents into a confidence-scored fact list.
Design follows docs/collection_refactor/EXTRACTION_SPIKE.md: raw regex
over-matches badly (~44 noise "facts"/chunk), so a bare number only becomes
a fact with context — inside a parsed table cell (0.9), adjacent to a label
token (0.75), or as a date (0.8). Everything else is dropped as noise.

The pipeline is pure: no DB, no LLM, no audit writes. Auditing
(stage="extract") is the caller's job (see audit_logger).
"""

import logging
import re
from datetime import date, datetime
from typing import Any

from app.core.config import settings
from app.services.smart_folder.tools.table_extractor import table_extractor

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Regex family (shared shape with grounding_validator — keep in sync)
# ---------------------------------------------------------------------------

_NUM = r"-?\d{1,3}(?:[ ,]\d{3})+(?:[.,]\d+)?|-?\d+(?:\.\d+)?"
NUMBER_RE = re.compile(_NUM)

_CURRENCY_CODES = ("XOF", "FCFA", "EUR", "USD", "GBP")
_SYMBOL_TO_CODE = {"€": "EUR", "$": "USD", "£": "GBP", "FCFA": "XOF"}

# "€1,200" / "$ 50" — symbol prefix
CURRENCY_PREFIX_RE = re.compile(r"([€$£])\s*(" + _NUM + r")")
# "1 200 XOF" / "50 EUR" / "1200€" — code/symbol suffix
CURRENCY_SUFFIX_RE = re.compile(
    r"(" + _NUM + r")\s*(XOF|FCFA|EUR|USD|GBP|€|\$|£)\b"
)
PERCENT_RE = re.compile("(" + _NUM + r")\s*(%|percent\b)")

ISO_DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
DMY_DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b")
_MONTHS = (
    "january|february|march|april|may|june|july|august|september|october|"
    "november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec"
)
MONTH_NAME_RE = re.compile(
    r"\b(?:(\d{1,2})\s+)?(" + _MONTHS + r")[\s,]+(\d{4})\b", re.IGNORECASE
)
BARE_YEAR_RE = re.compile(r"\b((?:19|20)\d{2})\b")

_MD_TABLE_BLOCK_RE = re.compile(r"((?:\|[^\n]+\|\n?)+)")

# Generic "label:" immediately preceding a number, e.g. "Revenue: 1,200"
_GENERIC_LABEL_RE = re.compile(
    r"([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ0-9 _/()'·.-]{1,38}?)\s*[:=]\s*$"
)

# Full-cell numeric parse for table cells: optional currency, optional %
_CELL_NUM_RE = re.compile(
    r"^\s*([€$£])?\s*(-?\d{1,3}(?:[ ,]\d{3})*(?:[.,]\d+)?|-?\d+(?:\.\d+)?)"
    r"\s*(%|XOF|FCFA|EUR|USD|GBP|[€$£])?\s*$"
)

# Confidence levels per spec FR4.1
CONFIDENCE_TABLE = 0.9
CONFIDENCE_LABELED = 0.75
CONFIDENCE_DATE = 0.8
CONFIDENCE_OCR_CAP = 0.6

# Label keywords: a number near one of these (within ~40 chars) is a fact.
# Configurable via the constructor.
DEFAULT_LABEL_KEYWORDS = (
    "revenue", "turnover", "headcount", "profit", "loss", "sales", "cost",
    "costs", "expenses", "expense", "income", "margin", "ebitda",
    "employees", "staff", "budget", "total", "amount", "balance", "debt",
    "cash", "growth", "rate", "price", "volume", "units", "production",
    "dividend", "tax", "capex", "opex", "roi", "npv",
)

# Source precedence for conflict resolution (FR4.1.8), highest first.
# Matched as substrings against "mime item_type". Configurable via constructor.
DEFAULT_SOURCE_PRECEDENCE = (
    ("xlsx", "xls", "csv", "spreadsheet", "excel"),   # finance/system records
    ("pdf", "report"),                                # official reports
    ("eml", "email", "message/rfc822"),               # email
    ("txt", "md", "markdown", "note", "draft"),       # drafts/notes
)

_LABEL_WINDOW = 40  # chars of lookback for label context
_DATE_WINDOW = 300  # chars within which a date annotates a numeric fact

_MONTH_LOOKUP = {
    m: i + 1
    for i, names in enumerate(
        [
            ("january", "jan"), ("february", "feb"), ("march", "mar"),
            ("april", "apr"), ("may",), ("june", "jun"), ("july", "jul"),
            ("august", "aug"), ("september", "sep", "sept"),
            ("october", "oct"), ("november", "nov"), ("december", "dec"),
        ]
    )
    for m in names
}


def _get(item: Any, key: str, default: Any = None) -> Any:
    """Read a field from a dict or a SourceItem-like object."""
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _parse_number(raw: str) -> float:
    """Strip thousands separators (',' or ' ') and parse to float."""
    return float(raw.replace(",", "").replace(" ", "").replace("\u00a0", ""))


def _iso_date(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)[:10] if value else None


class ExtractionPipeline:
    """FR4.1: context-gated, confidence-scored fact extraction."""

    def __init__(
        self,
        label_keywords: tuple[str, ...] = DEFAULT_LABEL_KEYWORDS,
        source_precedence: tuple[tuple[str, ...], ...] = DEFAULT_SOURCE_PRECEDENCE,
        confidence_threshold: float | None = None,
    ) -> None:
        self.label_keywords = tuple(k.lower() for k in label_keywords)
        self.source_precedence = source_precedence
        self.confidence_threshold = (
            confidence_threshold
            if confidence_threshold is not None
            else settings.COLLECTION_FACT_CONFIDENCE_THRESHOLD
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract(
        self,
        items: list[Any],
        contents: dict[Any, Any],
    ) -> dict[str, Any]:
        """Extract facts from item contents.

        Args:
            items: SourceItem objects or dicts (id, document_id, title,
                item_type, mime_type/mime, item_date, page).
            contents: item_id -> chunk text. Values may be a plain string,
                a dict {text, chunk_id, page}, or a list of such dicts.

        Returns:
            {facts, low_confidence, unparseable, normalization_notes,
             conflicts}
        """
        facts: list[dict] = []
        low_confidence: list[dict] = []
        unparseable: list[Any] = []
        notes: list[str] = []

        for item in items:
            item_id = _get(item, "id", _get(item, "item_id"))
            chunks = self._normalize_chunks(contents.get(item_id))
            if not chunks:
                unparseable.append(item_id)
                continue

            item_facts: list[dict] = []
            for chunk in chunks:
                item_facts.extend(self._extract_from_chunk(item, chunk, notes))

            if not item_facts:
                # Content existed but yielded nothing (e.g. scanned images
                # whose OCR text is empty) — FR6.6 content_unavailable.
                unparseable.append(item_id)
                continue

            for fact in item_facts:
                if fact["confidence"] < self.confidence_threshold:
                    low_confidence.append(fact)  # FR4.1.6 — appendix only
                else:
                    facts.append(fact)

        notes.extend(self._flag_mixed_currencies(facts))
        facts, conflicts = self._resolve_conflicts(facts)
        for fact in facts + low_confidence:
            fact.pop("_source_hint", None)  # internal precedence scratch field
            fact.pop("_item_date", None)    # internal recency scratch field

        return {
            "facts": facts,
            "low_confidence": low_confidence,
            "unparseable": unparseable,
            "normalization_notes": notes,
            "conflicts": conflicts,
        }

    # ------------------------------------------------------------------
    # Chunk handling
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_chunks(raw: Any) -> list[dict]:
        """Normalize a contents value to [{text, chunk_id, page}]."""
        if raw is None:
            return []
        if isinstance(raw, str):
            raw = [{"text": raw}]
        elif isinstance(raw, dict):
            raw = [raw]
        chunks = []
        for entry in raw:
            if isinstance(entry, str):
                entry = {"text": entry}
            text = (entry.get("text") or "").strip()
            if not text:
                continue
            chunks.append(
                {
                    "text": entry["text"],
                    "chunk_id": entry.get("chunk_id"),
                    "page": entry.get("page"),
                }
            )
        return chunks

    def _is_ocr(self, item: Any) -> bool:
        mime = str(_get(item, "mime_type", _get(item, "mime", "")) or "").lower()
        item_type = str(_get(item, "item_type", "") or "").lower()
        hint = f"{mime} {item_type}"
        return mime.startswith("image/") or "scanned" in hint or "ocr" in hint

    def _source_ref(self, item: Any, chunk: dict) -> dict:
        return {
            "document_id": (
                str(_get(item, "document_id")) if _get(item, "document_id") else None
            ),
            "chunk_id": (
                str(chunk.get("chunk_id")) if chunk.get("chunk_id") else None
            ),
            "page": chunk.get("page", _get(item, "page")),
        }

    def _extract_from_chunk(
        self, item: Any, chunk: dict, notes: list[str]
    ) -> list[dict]:
        text = chunk["text"]
        ocr = self._is_ocr(item)
        mime_hint = str(_get(item, "mime_type", _get(item, "mime", "text/plain")))
        is_csv = "csv" in mime_hint.lower()

        dates = self._find_dates(text)
        fallback_date = _iso_date(_get(item, "item_date"))

        facts: list[dict] = []
        # Date spans are claimed up front so a year inside a date is never
        # re-extracted as a labelled number (spike: years are top noise).
        consumed: list[tuple[int, int]] = [span for _dt, _raw, span in dates]

        # 1. Tables — high-confidence path (0.9). Markdown blocks are
        #    removed from the prose text below to avoid double-counting;
        #    for CSV the whole text IS the table, so prose is skipped.
        #    CSV parsing is delegated to the smart_folder table_extractor;
        #    markdown tables are parsed locally because the tool's row split
        #    keeps the empty artefacts of leading/trailing pipes, which
        #    shifts every row one column left and drops the last column
        #    (smart_folder files may not be modified — worked around here).
        prose_text = text
        if is_csv:
            tables = table_extractor.extract(text, mime_hint)
        else:
            tables = self._extract_markdown_tables(text)
        for table in tables:
            facts.extend(self._facts_from_table(item, chunk, table, fallback_date, notes))
        if is_csv and tables:
            prose_text = ""
        else:
            # Blank out table blocks WITHOUT shifting offsets (whitespace-
            # preserving) so span bookkeeping stays valid for prose passes.
            prose_text = _MD_TABLE_BLOCK_RE.sub(
                lambda m: "".join("\n" if c == "\n" else " " for c in m.group(0)),
                text,
            )

        # 2. Currency amounts (unit = context) — 0.75 class
        for match, raw_num, symbol in self._iter_currency(prose_text):
            span = match.span()
            if self._overlaps(span, consumed):
                continue
            consumed.append(span)
            value = _parse_number(raw_num)
            code = _SYMBOL_TO_CODE.get(symbol, symbol)
            if symbol == "FCFA":
                notes.append(
                    f"normalised currency 'FCFA' -> 'XOF' for '{match.group(0)}'"
                )
            notes.append(
                f"kept currency unit {code} for '{match.group(0).strip()}' "
                "(no conversion)"
            )
            label = self._find_label(prose_text, span[0])
            facts.append(
                self._make_fact(
                    item, chunk, name=label or "amount", value=value,
                    unit=code, raw=match.group(0),
                    confidence=CONFIDENCE_LABELED, origin="text",
                    date=self._nearest_date(dates, span[0]) or fallback_date,
                    ocr=ocr,
                )
            )

        # 3. Percentages (unit = context) — 0.75 class, kept on 0-100 base
        for match in PERCENT_RE.finditer(prose_text):
            span = match.span(1)
            if self._overlaps(span, consumed) or self._overlaps(match.span(), consumed):
                continue
            consumed.append(match.span())
            value = _parse_number(match.group(1))
            notes.append(f"kept percent on 0-100 base: {value}%")
            label = self._find_label(prose_text, span[0])
            facts.append(
                self._make_fact(
                    item, chunk, name=label or "percentage", value=value,
                    unit="%", raw=match.group(0),
                    confidence=CONFIDENCE_LABELED, origin="text",
                    date=self._nearest_date(dates, span[0]) or fallback_date,
                    ocr=ocr,
                )
            )

        # 4. Labeled bare numbers — 0.75; unlabeled numbers are noise (spike)
        for match in NUMBER_RE.finditer(prose_text):
            span = match.span()
            if self._overlaps(span, consumed):
                continue
            label = self._find_label(prose_text, span[0])
            if label is None:
                continue  # bare number without context -> dropped
            consumed.append(span)
            raw = match.group(0)
            value = _parse_number(raw)
            if "," in raw or " " in raw:
                notes.append(f"stripped thousands separators: '{raw}' -> {value}")
            facts.append(
                self._make_fact(
                    item, chunk, name=label, value=value, unit=None, raw=raw,
                    confidence=CONFIDENCE_LABELED, origin="text",
                    date=self._nearest_date(dates, span[0]) or fallback_date,
                    ocr=ocr,
                )
            )

        # 5. Dates — 0.8 (value-less period facts). Dates inside table
        #    blocks (blanked out of prose_text) are already represented by
        #    the table facts themselves, so they are skipped here.
        for dt, raw, span in dates:
            if not prose_text or not prose_text[span[0]:span[1]].strip():
                continue
            facts.append(
                self._make_fact(
                    item, chunk, name="date", value=None, unit=None, raw=raw,
                    confidence=CONFIDENCE_DATE, origin="text",
                    date=dt, ocr=ocr,
                )
            )

        return facts

    # ------------------------------------------------------------------
    # Tables
    # ------------------------------------------------------------------

    # Headers naming a period column: its cells annotate the row's facts
    # instead of becoming facts themselves.
    _PERIOD_HEADER_RE = re.compile(r"\b(year|date|period|ann[eé]e|month|quarter)\b", re.IGNORECASE)

    @staticmethod
    def _extract_markdown_tables(text: str) -> list[dict]:
        """Correctly-aligned markdown table parse ({headers, rows}).

        Mirrors ``table_extractor.extract_from_markdown`` but splits rows on
        the pipes with the outer pipes stripped first, so leading-pipe rows
        keep every column in the right position.
        """
        tables = []
        for match in _MD_TABLE_BLOCK_RE.finditer(text):
            block = match.group(1)
            lines = [ln.strip() for ln in block.strip().split("\n") if ln.strip()]
            if len(lines) < 2:
                continue
            if re.match(r"\|?[\s\-|:]+\|?", lines[1]):
                lines.pop(1)  # separator line
            headers = [
                h.strip() for h in lines[0].strip("|").split("|")
            ]
            headers = [h for h in headers if h]
            rows = []
            for line in lines[1:]:
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                while len(cells) < len(headers):
                    cells.append("")
                rows.append(dict(zip(headers, cells[: len(headers)])))
            if headers and rows:
                tables.append({"headers": headers, "rows": rows})
        return tables

    def _facts_from_table(
        self, item: Any, chunk: dict, table: dict, fallback_date: str | None,
        notes: list[str],
    ) -> list[dict]:
        facts = []
        headers = table.get("headers") or []
        ocr = self._is_ocr(item)
        period_col = next(
            (i for i, h in enumerate(headers) if self._PERIOD_HEADER_RE.search(h)),
            None,
        )
        for row in table.get("rows") or []:
            cells = [row.get(h, "") for h in headers]
            row_date = None
            if period_col is not None and period_col < len(cells):
                row_date = self._date_from_text(str(cells[period_col]))
            row_label = None
            if cells and not _CELL_NUM_RE.match(str(cells[0]).strip() or "x"):
                row_label = str(cells[0]).strip() or None
            for col, (header, cell) in enumerate(zip(headers, cells)):
                if col == period_col:
                    continue  # period column annotates, never a fact
                cell_text = str(cell).strip()
                m = _CELL_NUM_RE.match(cell_text)
                if not m:
                    continue
                raw_num = m.group(2)
                value = _parse_number(raw_num)
                unit = None
                symbol = m.group(1) or m.group(3)
                if symbol:
                    if symbol == "%":
                        unit = "%"
                        notes.append(f"kept percent on 0-100 base: {value}%")
                    else:
                        unit = _SYMBOL_TO_CODE.get(symbol, symbol)
                        notes.append(
                            f"kept currency unit {unit} for '{cell_text}' "
                            "(no conversion)"
                        )
                elif "%" in header:
                    unit = "%"
                    notes.append(f"kept percent on 0-100 base: {value}% (header)")
                else:
                    for code in _CURRENCY_CODES + tuple(_SYMBOL_TO_CODE):
                        if code.lower() in header.lower():
                            unit = _SYMBOL_TO_CODE.get(code, code)
                            notes.append(
                                f"unit {unit} inferred from column header "
                                f"'{header}'"
                            )
                            break
                if ("," in raw_num or " " in raw_num) and len(raw_num) > 4:
                    notes.append(
                        f"stripped thousands separators: '{raw_num}' -> {value}"
                    )
                # Period: row's period column, else a date-like header,
                # else the item date.
                header_date = self._date_from_text(header)
                name = self._metric_name(row_label, header)
                facts.append(
                    self._make_fact(
                        item, chunk, name=name, value=value, unit=unit,
                        raw=cell_text, confidence=CONFIDENCE_TABLE,
                        origin="table",
                        date=row_date or header_date or fallback_date, ocr=ocr,
                    )
                )
        return facts

    @staticmethod
    def _metric_name(row_label: str | None, header: str) -> str:
        """Metric name from row label or header, with unit tokens stripped."""
        base = (row_label or header).lower()
        base = re.sub(r"\b(xof|fcfa|eur|usd|gbp)\b", "", base)
        base = base.replace("%", "").replace("€", "").replace("$", "").replace("£", "")
        base = re.sub(r"\s+", " ", base).strip(" -:/")
        return base or "value"

    # ------------------------------------------------------------------
    # Dates & labels
    # ------------------------------------------------------------------

    @staticmethod
    def _date_from_text(text: str) -> str | None:
        m = ISO_DATE_RE.search(text)
        if m:
            return m.group(0)
        m = BARE_YEAR_RE.search(text)
        if m:
            return m.group(1)
        return None

    def _find_dates(self, text: str) -> list[tuple[str, str, tuple[int, int]]]:
        """Return [(iso_date_or_year, raw, span)] for all date forms."""
        found: list[tuple[str, str, tuple[int, int]]] = []
        claimed: list[tuple[int, int]] = []

        def free(span: tuple[int, int]) -> bool:
            return not self._overlaps(span, claimed)

        for m in ISO_DATE_RE.finditer(text):
            try:
                dt = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                continue
            found.append((dt.isoformat(), m.group(0), m.span()))
            claimed.append(m.span())
        for m in DMY_DATE_RE.finditer(text):
            if not free(m.span()):
                continue
            day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if year < 100:
                year += 2000
            try:
                dt = date(year, month, day)
            except ValueError:
                continue
            found.append((dt.isoformat(), m.group(0), m.span()))
            claimed.append(m.span())
        for m in MONTH_NAME_RE.finditer(text):
            if not free(m.span()):
                continue
            month = _MONTH_LOOKUP.get(m.group(2).lower())
            if month is None:
                continue
            day = int(m.group(1)) if m.group(1) else 1
            try:
                dt = date(int(m.group(3)), month, day)
            except ValueError:
                continue
            found.append((dt.isoformat(), m.group(0), m.span()))
            claimed.append(m.span())
        for m in BARE_YEAR_RE.finditer(text):
            if not free(m.span()):
                continue
            found.append((m.group(1), m.group(0), m.span()))
            claimed.append(m.span())
        return found

    def _nearest_date(
        self, dates: list[tuple[str, str, tuple[int, int]]], pos: int
    ) -> str | None:
        best = None
        best_dist = _DATE_WINDOW + 1
        for dt, _raw, span in dates:
            dist = min(abs(pos - span[0]), abs(pos - span[1]))
            if dist < best_dist:
                best, best_dist = dt, dist
        return best if best_dist <= _DATE_WINDOW else None

    def _find_label(self, text: str, pos: int) -> str | None:
        """Find a context label within ~40 chars before the number.

        The lookback window is cut at the last sentence boundary so a label
        never leaks across sentences (spike finding: over-matching noise).
        """
        window = text[max(0, pos - _LABEL_WINDOW - 5):pos]
        # Cut at the last sentence/line boundary.
        window = re.split(r"[.!?;\n]", window)[-1]
        m = _GENERIC_LABEL_RE.search(window)
        if m:
            label = m.group(1).strip(" .,-").lower()
            if label:
                return label
        lowered = window.lower()
        for kw in self.label_keywords:
            if re.search(r"\b" + re.escape(kw) + r"\b", lowered):
                return kw
        return None

    # ------------------------------------------------------------------
    # Currency iterator (prefix + suffix forms, deduped by span)
    # ------------------------------------------------------------------

    def _iter_currency(self, text: str):
        seen: list[tuple[int, int]] = []
        for m in CURRENCY_PREFIX_RE.finditer(text):
            if not self._overlaps(m.span(), seen):
                seen.append(m.span())
                yield m, m.group(2), m.group(1)
        for m in CURRENCY_SUFFIX_RE.finditer(text):
            if not self._overlaps(m.span(), seen):
                seen.append(m.span())
                yield m, m.group(1), m.group(2)

    @staticmethod
    def _overlaps(span: tuple[int, int], spans: list[tuple[int, int]]) -> bool:
        return any(span[0] < s[1] and s[0] < span[1] for s in spans)

    # ------------------------------------------------------------------
    # Fact construction, mixed currencies, conflicts
    # ------------------------------------------------------------------

    def _make_fact(
        self, item: Any, chunk: dict, *, name: str, value: float | None,
        unit: str | None, raw: str, confidence: float, origin: str,
        date: str | None, ocr: bool,
    ) -> dict:
        if ocr:
            # FR4.1.6: OCR/image-origin facts are capped and excluded from
            # computation (they land below the 0.7 default threshold).
            confidence = min(confidence, CONFIDENCE_OCR_CAP)
            origin = "ocr"
        fact = {
            "name": name,
            "value": value,
            "unit": unit,
            "date": date,
            "source_ref": self._source_ref(item, chunk),
            "confidence": round(confidence, 4),
            "origin": origin,
            "raw": raw,
        }
        return self._attach_hint(item, fact)

    @staticmethod
    def _flag_mixed_currencies(facts: list[dict]) -> list[str]:
        """FR4.1.7: no rate source — mixed currencies are flagged, never
        converted."""
        by_name: dict[str, set[str]] = {}
        for f in facts:
            if f.get("unit") in _SYMBOL_TO_CODE.values() or f.get("unit") in _CURRENCY_CODES:
                by_name.setdefault(f["name"], set()).add(f["unit"])
        notes = []
        for name, units in sorted(by_name.items()):
            if len(units) > 1:
                notes.append(
                    f"mixed currencies for metric '{name}': {sorted(units)} — "
                    "not converted (no rate source)"
                )
        return notes

    def _source_rank(self, item_hint: str) -> int:
        for rank, tokens in enumerate(self.source_precedence):
            if any(t in item_hint for t in tokens):
                return rank
        return len(self.source_precedence)

    def _resolve_conflicts(
        self, facts: list[dict]
    ) -> tuple[list[dict], list[dict]]:
        """FR4.1.8: same (name, period, unit) with differing values.

        Winner by source precedence (configurable); every conflict is
        recorded with both values, both source_refs and the rule applied —
        never silently picked.
        """
        groups: dict[tuple, list[dict]] = {}
        for f in facts:
            if f.get("value") is None:
                continue
            key = (f["name"], f.get("date") or "unknown", f.get("unit"))
            groups.setdefault(key, []).append(f)

        drop_ids: set[int] = set()
        conflicts: list[dict] = []
        for (name, period, unit), group in groups.items():
            distinct = {round(f["value"], 6) for f in group}
            if len(distinct) <= 1:
                continue
            winner = min(
                group,
                key=lambda f: (
                    self._source_rank(self._fact_hint(f)),
                    -self._fact_recency(f),
                    -f["confidence"],
                ),
            )
            for loser in group:
                if loser is winner:
                    continue
                if round(loser["value"], 6) == round(winner["value"], 6):
                    continue
                drop_ids.add(id(loser))
                winner_hint = (self._fact_hint(winner) or "unknown").strip() or "unknown"
                loser_hint = (self._fact_hint(loser) or "unknown").strip() or "unknown"
                if self._source_rank(self._fact_hint(winner)) == self._source_rank(
                    self._fact_hint(loser)
                ):
                    # Same precedence class (e.g. pdf vs pdf): precedence
                    # says nothing — the most recent item wins.
                    rule = (
                        f"same source class '{winner_hint}': "
                        "most recent item_date preferred"
                    )
                else:
                    rule = f"source_precedence: {winner_hint} preferred over {loser_hint}"
                conflicts.append(
                    {
                        "name": name,
                        "date": None if period == "unknown" else period,
                        "unit": unit,
                        "winner": {
                            "value": winner["value"],
                            "source_ref": winner["source_ref"],
                        },
                        "loser": {
                            "value": loser["value"],
                            "source_ref": loser["source_ref"],
                        },
                        "rule": rule,
                    }
                )

        kept = [f for f in facts if id(f) not in drop_ids]
        return kept, conflicts

    @staticmethod
    def _fact_hint(fact: dict) -> str:
        """Precedence hint stashed on the fact at extraction time."""
        return fact.get("_source_hint", "")

    @staticmethod
    def _fact_recency(fact: dict) -> float:
        """Item-date epoch for same-class conflict resolution (0 = unknown)."""
        value = fact.get("_item_date")
        if isinstance(value, datetime):
            try:
                return value.timestamp()
            except (ValueError, OSError):
                return 0.0
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(
                    value.replace("Z", "+00:00")
                ).timestamp()
            except ValueError:
                return 0.0
        return 0.0

    # Items carry their mime/type into each fact for precedence resolution.
    def _attach_hint(self, item: Any, fact: dict) -> dict:
        mime = str(_get(item, "mime_type", _get(item, "mime", "")) or "")
        item_type = str(_get(item, "item_type", "") or "")
        fact["_source_hint"] = f"{mime} {item_type}".lower().strip()
        fact["_item_date"] = _get(item, "item_date")
        return fact
