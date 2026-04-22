"""
Lightweight query spelling correction using SymSpell.

Populates the dictionary from indexed document titles and tags.
Provides single-word and multi-word correction with a small memory footprint.
"""

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# Try to import symspellpy; provide fallback if unavailable
try:
    from symspellpy import SymSpell, Verbosity
except ImportError:
    SymSpell = None  # type: ignore[misc, assignment]

    class _VerbosityFallback:
        TOP = 0
        CLOSEST = 1
        ALL = 2

    Verbosity = _VerbosityFallback  # type: ignore[misc, assignment]

# Lazy-loaded corrector
_sym_spell = None


def _get_symspell():
    global _sym_spell
    if _sym_spell is not None:
        return _sym_spell

    if SymSpell is None:
        logger.debug("symspellpy not installed — spell correction disabled")
        return None

    max_edit_distance = int(os.getenv("SPELL_MAX_EDIT_DISTANCE", "2"))
    prefix_length = int(os.getenv("SPELL_PREFIX_LENGTH", "7"))

    _sym_spell = SymSpell(max_dictionary_edit_distance=max_edit_distance, prefix_length=prefix_length)
    logger.info("SymSpell initialized (max_edit_distance=%s)", max_edit_distance)
    return _sym_spell


def load_dictionary_from_terms(terms: list[str]) -> None:
    """Populate SymSpell dictionary with a list of terms."""
    symspell = _get_symspell()
    if symspell is None:
        return
    for term in terms:
        if term and len(term) > 1:
            symspell.create_dictionary_entry(term.lower(), 1)
    logger.info("Spell dictionary loaded with %d terms", len(terms))


def correct_query(query: str) -> tuple[str, bool]:
    """
    Correct a search query.

    Returns (corrected_query, was_corrected).
    If correction fails or dictionary is empty, returns original query.
    """
    symspell = _get_symspell()
    if symspell is None or not query.strip():
        return query, False

    words = query.strip().split()
    corrected_words = []
    changed = False

    for word in words:
        # Don't correct short words or numbers
        if len(word) <= 2 or word.isdigit():
            corrected_words.append(word)
            continue

        suggestions = symspell.lookup(word.lower(), Verbosity.TOP, max_edit_distance=2)
        if suggestions and suggestions[0].distance > 0:
            corrected_words.append(suggestions[0].term)
            changed = True
        else:
            corrected_words.append(word)

    if changed:
        return " ".join(corrected_words), True

    # Try compound correction for multi-word queries
    if len(words) > 1:
        compound = symspell.lookup_compound(query.lower(), max_edit_distance=2)
        if compound and compound[0].distance > 0:
            return compound[0].term, True

    return query, False


def suggest_corrections(query: str, max_suggestions: int = 3) -> list[str]:
    """Return up to N spelling suggestions for a query."""
    symspell = _get_symspell()
    if symspell is None or not query.strip():
        return []

    suggestions = symspell.lookup(query.lower(), Verbosity.CLOSEST, max_edit_distance=2)
    return [s.term for s in suggestions[:max_suggestions] if s.distance > 0]
