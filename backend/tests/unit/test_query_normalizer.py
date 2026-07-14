"""Unit tests for the shared query normalisation helper."""

from __future__ import annotations

import pytest

from app.utils.query_normalizer import normalise_query, normalise_query_fold_diacritics


class TestNormaliseQuery:
    """Tests for normalise_query()."""

    def test_lowercases_and_trims(self):
        assert normalise_query("  Hello World  ") == "hello world"

    def test_collapses_whitespace(self):
        assert normalise_query("hello    world") == "hello world"

    def test_removes_punctuation(self):
        assert normalise_query("hello, world!!") == "hello world"

    def test_preserves_apostrophes_and_hyphens(self):
        assert normalise_query("grand-père") == "grand-père"
        assert normalise_query("l'union") == "l'union"

    def test_handles_french_accents(self):
        # NFC normalisation keeps composed accents intact
        assert normalise_query("Papiers de mon Grand-Père") == "papiers de mon grand-père"

    def test_removes_zero_width_chars(self):
        assert normalise_query("hello\u200bworld") == "helloworld"

    def test_empty_and_none(self):
        assert normalise_query("") == ""
        assert normalise_query(None) == ""

    def test_idempotent(self):
        q = "  Documents  about MY Grand-père!! "
        assert normalise_query(normalise_query(q)) == normalise_query(q)


class TestNormaliseQueryFoldDiacritics:
    """Tests for normalise_query_fold_diacritics()."""

    def test_folds_diacritics(self):
        assert normalise_query_fold_diacritics("grand-père") == "grand-pere"
        assert normalise_query_fold_diacritics("café") == "cafe"

    def test_other_normalisation_still_applies(self):
        assert normalise_query_fold_diacritics("  CAFÉ!! ") == "cafe"
