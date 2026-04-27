"""Structured Table Parser Tool.

Extracts tables from text / markdown / CSV content into structured dataframes.
"""

import csv
import io
import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


class TableExtractorTool:
    """Tool: Parse structured tables from text, markdown, or CSV."""

    def extract_from_markdown(self, text: str) -> list[dict[str, Any]]:
        """Extract markdown tables into structured dicts."""
        tables = []
        # Find markdown table blocks
        pattern = re.compile(r"((?:\|[^\n]+\|\n)+)")
        for match in pattern.finditer(text):
            block = match.group(1)
            lines = [line.strip() for line in block.strip().split("\n") if line.strip()]
            if len(lines) < 2:
                continue
            # Skip separator line
            if re.match(r"\|?[\s\-\|:]+\|?", lines[1]):
                lines.pop(1)
            headers = [h.strip() for h in lines[0].split("|") if h.strip()]
            rows = []
            for line in lines[1:]:
                cells = [c.strip() for c in line.split("|") if c.strip() or c == ""]
                # Pad or truncate to match headers
                while len(cells) < len(headers):
                    cells.append("")
                cells = cells[: len(headers)]
                rows.append(dict(zip(headers, cells)))
            tables.append({"headers": headers, "rows": rows})
        return tables

    def extract_from_csv(self, text: str) -> list[dict[str, Any]]:
        """Parse CSV text into structured dicts."""
        tables = []
        try:
            reader = csv.DictReader(io.StringIO(text))
            rows = list(reader)
            if rows:
                tables.append({"headers": list(rows[0].keys()), "rows": rows})
        except Exception as exc:
            logger.debug("CSV parse failed: %s", exc)
        return tables

    def extract(self, text: str, mime_hint: str = "text/plain") -> list[dict[str, Any]]:
        """Auto-detect and extract tables from text."""
        if "csv" in mime_hint.lower():
            return self.extract_from_csv(text)
        md_tables = self.extract_from_markdown(text)
        if md_tables:
            return md_tables
        # Fallback: try CSV
        csv_tables = self.extract_from_csv(text)
        if csv_tables:
            return csv_tables
        return []


table_extractor = TableExtractorTool()
