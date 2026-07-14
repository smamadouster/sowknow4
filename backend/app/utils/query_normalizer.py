"""Shared query normalisation utilities for cache keying.

Provides a single source of truth for normalising user queries before they
are hashed into cache keys.  This raises cache hit rates for near-duplicate
queries that differ only in case, whitespace, punctuation, or diacritics.
"""

from __future__ import annotations

import re
import unicodedata


def normalise_query(q: str | None) -> str:
    """Return a canonical form of a query suitable for cache-key generation.

    Normalisation steps:
      1. NFC Unicode normalisation.
      2. Lower-casing.
      3. Strip leading/trailing whitespace.
      4. Collapse internal whitespace.
      5. Remove most punctuation and zero-width characters.
      6. Remove common French/English diacritic alternates by decomposing
         and dropping combining marks (optional, controlled by flag).

    Args:
        q: Raw user query.

    Returns:
        Normalised query string.  ``None`` is treated as empty string.
    """
    if not q:
        return ""

    # Compose characters so identical glyphs share the same byte sequence.
    text = unicodedata.normalize("NFC", q)
    text = text.lower().strip()

    # Collapse whitespace (including non-breaking spaces).
    text = re.sub(r"\s+", " ", text)

    # Remove zero-width and control characters.
    text = "".join(ch for ch in text if unicodedata.category(ch)[0] != "C")

    # Strip punctuation except apostrophes and hyphens inside words.
    text = re.sub(r"[^\w\s'-]", "", text)

    # Collapse whitespace again after punctuation removal.
    text = re.sub(r"\s+", " ", text).strip()

    return text


def normalise_query_fold_diacritics(q: str | None) -> str:
    """Normalise a query and fold diacritics for even broader cache matches.

    This is a stricter normalisation that treats "papier" and "papier" as
    identical.  Use it for cache-key generation where a small loss of
    linguistic precision is acceptable in exchange for higher hit rates.

    Args:
        q: Raw user query.

    Returns:
        Normalised, diacritic-folded query string.
    """
    text = normalise_query(q)
    if not text:
        return ""

    # Decompose characters and drop combining marks.
    decomposed = unicodedata.normalize("NFD", text)
    folded = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")

    # Re-compose to keep the string in a stable form.
    return unicodedata.normalize("NFC", folded)
