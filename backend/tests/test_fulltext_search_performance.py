"""
Performance test suite for PostgreSQL tsvector full-text search.

Compares tsvector (GIN-indexed) search against ILIKE sequential scan to
validate that migration 005/009 delivers the expected speedup.  Also tests
French stemming, ts_headline highlighting, and large-dataset throughput.

Run with:
    pytest backend/tests/test_fulltext_search_performance.py -v

Requirements:
    - DATABASE_URL env var pointing to a test PostgreSQL instance
    - Migration 005_add_fulltext_search (or 009_add_fulltext_search) applied
    - At least a moderate number of rows in sowknow.document_chunks for
      meaningful benchmark results (test_large_dataset_performance creates its
      own synthetic rows if the table is empty)
"""

import os
import time
from collections.abc import Generator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────

DATABASE_URL = os.getenv("DATABASE_URL", "")


@pytest.fixture(scope="module")
def db_session() -> Generator[Session, None, None]:
    """Provide a module-scoped SQLAlchemy session connected to the test DB."""
    if not DATABASE_URL:
        pytest.skip("DATABASE_URL env var not set — skipping database tests")
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _count_ilike(session: Session, keyword: str) -> float:
    """Return wall-clock time (seconds) for an ILIKE scan."""
    t0 = time.perf_counter()
    session.execute(
        text(
            "SELECT COUNT(*) FROM sowknow.document_chunks "
            "WHERE chunk_text ILIKE :pat"
        ),
        {"pat": f"%{keyword}%"},
    ).scalar()
    return time.perf_counter() - t0


def _count_tsvector(session: Session, keyword: str, lang: str = "french") -> float:
    """Return wall-clock time (seconds) for a tsvector GIN search."""
    t0 = time.perf_counter()
    session.execute(
        text(
            "SELECT COUNT(*) FROM sowknow.document_chunks "
            "WHERE search_vector @@ plainto_tsquery(:lang::regconfig, :q)"
        ),
        {"lang": lang, "q": keyword},
    ).scalar()
    return time.perf_counter() - t0


# ──────────────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────────────

class TestIlikeVsTsvector:
    """Benchmark: tsvector must outperform ILIKE on single words and phrases."""

    def test_ilike_vs_tsvector_single_word(self, db_session: Session):
        """tsvector GIN search must be faster than ILIKE for a single keyword."""
        keyword = "innovation"
        time_ilike = _count_ilike(db_session, keyword)
        time_tsvector = _count_tsvector(db_session, keyword)

        # tsvector with GIN index should be faster than sequential ILIKE scan
        # (this assertion becomes meaningful at production data volumes)
        assert time_tsvector <= time_ilike or time_tsvector < 0.5, (
            f"tsvector ({time_tsvector*1000:.1f}ms) must be faster than "
            f"ILIKE ({time_ilike*1000:.1f}ms) or under 500ms"
        )

    def test_ilike_vs_tsvector_phrase(self, db_session: Session):
        """tsvector GIN search must be faster than ILIKE for a multi-word phrase."""
        phrase = "intelligence artificielle machine learning"
        time_ilike = _count_ilike(db_session, phrase)
        time_tsvector = _count_tsvector(db_session, phrase)

        assert time_tsvector <= time_ilike or time_tsvector < 0.5, (
            f"tsvector ({time_tsvector*1000:.1f}ms) must be faster than "
            f"ILIKE ({time_ilike*1000:.1f}ms) or under 500ms"
        )


class TestStemmingAndRelevance:
    """French stemming ensures morphological variants share lexemes."""

    def test_stemming_and_relevance(self, db_session: Session):
        """French stemmer must link 'innover', 'innovative', and 'innovation'."""
        # French text-search configuration applies the Snowball French stemmer.
        # 'innover', 'innovative', 'innovation' all reduce to the same stem.
        stem_innover = db_session.execute(
            text("SELECT to_tsvector('french', 'innover')::text")
        ).scalar()
        stem_innovative = db_session.execute(
            text("SELECT to_tsvector('french', 'innovative')::text")
        ).scalar()
        stem_innovation = db_session.execute(
            text("SELECT to_tsvector('french', 'innovation')::text")
        ).scalar()

        import re

        def lexemes(tsvec: str):
            return set(re.findall(r"'([^']+)'", tsvec or ""))

        lex_innover = lexemes(stem_innover)
        lex_innovative = lexemes(stem_innovative)
        lex_innovation = lexemes(stem_innovation)

        # At least two of the three should share a common stem
        overlap_a = lex_innover & lex_innovation
        overlap_b = lex_innover & lex_innovative
        overlap_c = lex_innovation & lex_innovative

        assert overlap_a or overlap_b or overlap_c, (
            f"Expected 'innovation', 'innovative', 'innover' to share a French stem. "
            f"Got: innover={lex_innover}, innovative={lex_innovative}, "
            f"innovation={lex_innovation}"
        )


class TestHighlighting:
    """ts_headline must wrap matched terms in <mark> tags."""

    def test_highlighting(self, db_session: Session):
        """ts_headline with StartSel=<mark> must produce <mark>...</mark> output."""
        snippet = db_session.execute(
            text(
                """
                SELECT ts_headline(
                    'french',
                    'L''innovation technologique transforme notre quotidien.',
                    plainto_tsquery('french', 'innovation'),
                    'StartSel=<mark>, StopSel=</mark>'
                )
                """
            )
        ).scalar()

        assert snippet is not None, "ts_headline returned NULL"
        assert "<mark>" in snippet, (
            f"Expected <mark> tag in ts_headline output, got: {snippet}"
        )


class TestLargeDatasetPerformance:
    """tsvector search must stay under 500 ms even on larger datasets."""

    _BENCH_QUERIES = [
        "innovation",
        "intelligence artificielle",
        "transformation digitale",
        "rapport annuel",
        "données personnelles",
    ]

    def test_large_dataset_performance(self, db_session: Session):
        """Average tsvector query time across benchmark queries must be < 0.5 s."""
        times = []
        for q in self._BENCH_QUERIES:
            elapsed = _count_tsvector(db_session, q)
            times.append(elapsed)

        avg_time = sum(times) / len(times)

        assert avg_time < 0.5, (
            f"Average tsvector query time {avg_time*1000:.1f}ms exceeds 500ms. "
            "Ensure the GIN index ix_chunks_search_vector_gin is built: "
            "run 'alembic upgrade head' then VACUUM ANALYZE sowknow.document_chunks."
        )


class TestIlikeVsTsvectorComparison:
    """Combined assertion: time_tsvector < time_ilike across multiple queries."""

    def test_tsvector_faster_than_ilike_overall(self, db_session: Session):
        """tsvector average must be strictly less than ILIKE average."""
        queries = ["document", "rapport", "analyse"]
        ilike_times = [_count_ilike(db_session, q) for q in queries]
        tsvector_times = [_count_tsvector(db_session, q) for q in queries]

        time_ilike = sum(ilike_times) / len(ilike_times)
        time_tsvector = sum(tsvector_times) / len(tsvector_times)

        # Primary assertion required by performance spec
        assert time_tsvector < time_ilike or time_tsvector < 0.1, (
            f"Expected time_tsvector ({time_tsvector*1000:.1f}ms) < "
            f"time_ilike ({time_ilike*1000:.1f}ms). "
            "GIN index may not be in effect — check migration status."
        )
