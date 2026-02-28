"""
Collection Performance Benchmark Tests
=======================================
Validates the smart-collection pipeline against hard PRD targets using a
real PostgreSQL / pgvector container (see conftest.py).

Targets (all tests FAIL if exceeded):
  - Intent parsing          < 3 s
  - Document gathering      < 5 s  (hybrid vector + keyword search on 60 docs)
  - AI summary generation   < 20 s (LLM mocked; orchestration overhead only)
  - Full e2e collection     < 30 s (intent + gather + summary + DB writes)

A JSON report is written to tests/performance/benchmark_report.json after
every run so CI can archive it as a build artefact.

CI snippet (GitHub Actions):
----------------------------------------------------------------------
  benchmark-tests:
    runs-on: ubuntu-latest
    services: {}          # Docker socket provided by GHA runner
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install -r backend/requirements.txt
      - name: Run collection benchmarks
        working-directory: backend
        run: |
          pytest tests/performance/test_collection_benchmarks.py \\
            -m benchmark \\
            -v \\
            --tb=short \\
            --timeout=120
      - name: Upload benchmark report
        uses: actions/upload-artifact@v4
        if: always()
        with:
          name: benchmark-report
          path: backend/tests/performance/benchmark_report.json
----------------------------------------------------------------------
"""
from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from app.models.document import Document, DocumentBucket, DocumentStatus
from app.schemas.collection import CollectionCreate
from app.services.collection_service import collection_service
from app.services.intent_parser import ParsedIntent, intent_parser_service

# ---------------------------------------------------------------------------
# All tests in this module carry both markers
# ---------------------------------------------------------------------------
pytestmark = [pytest.mark.benchmark, pytest.mark.performance]

# ---------------------------------------------------------------------------
# Performance report (accumulated in-process, flushed after each test)
# ---------------------------------------------------------------------------
REPORT_PATH = Path(__file__).parent / "benchmark_report.json"

_REPORT: dict[str, Any] = {
    "generated_at": datetime.now(UTC).isoformat(),
    "targets": {
        "intent_parsing_s": 3,
        "document_gathering_s": 5,
        "ai_summary_generation_s": 20,
        "e2e_collection_creation_s": 30,
    },
    "results": [],
}


def _record_result(
    name: str,
    elapsed: float,
    target: float,
    passed: bool,
    **extra: Any,
) -> None:
    """Append a measurement to the in-memory report and flush to disk."""
    _REPORT["results"].append(
        {
            "name": name,
            "elapsed_s": round(elapsed, 3),
            "target_s": target,
            "passed": passed,
            **extra,
        }
    )
    REPORT_PATH.write_text(json.dumps(_REPORT, indent=2))


# ---------------------------------------------------------------------------
# Minimal timer utility
# ---------------------------------------------------------------------------
class _Timer:
    """Inline wall-clock timer used as a context manager."""

    elapsed: float = 0.0

    def __enter__(self) -> _Timer:
        self._start = time.perf_counter()
        return self

    def __exit__(self, *_: Any) -> None:
        self.elapsed = time.perf_counter() - self._start


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def _make_parsed_intent(keywords: list[str]) -> ParsedIntent:
    """Build a deterministic ParsedIntent for document gathering tests."""
    return ParsedIntent(
        query=" ".join(keywords),
        keywords=keywords,
        date_range={},
        entities=[],
        document_types=["all"],
        collection_name="Benchmark Collection",
        confidence=0.95,
    )



# ===========================================================================
# BENCHMARK 1 — Intent Parsing  (target < 3 s)
# ===========================================================================


class TestIntentParsingBenchmark:
    """
    Measures wall-clock time for parse_intent() when the LLM call is
    replaced by an instant local mock that returns valid JSON.

    What this covers:
      - Prompt construction
      - Async generator draining
      - JSON extraction + ParsedIntent hydration
    """

    @pytest.mark.asyncio
    async def test_intent_parsing_perf(self, pg_bench_db: tuple) -> None:
        TARGET = 3.0

        mock_json = json.dumps(
            {
                "keywords": ["solar", "energy", "projects", "2024"],
                "date_range": {
                    "type": "custom",
                    "custom": {"start": "2020-01-01", "end": "2024-12-31"},
                },
                "entities": [],
                "document_types": ["all"],
                "collection_name": "Solar Energy Projects 2020-2024",
                "confidence": 0.95,
            }
        )

        # intent_parser uses openrouter for the public (non-ollama) path
        async def _instant_llm(*_args: Any, **_kwargs: Any):
            yield mock_json

        # Patch via module path so we don't trigger the lazy-loader before
        # the context manager is entered (more robust than patch.object).
        with patch(
            "app.services.openrouter_service.openrouter_service.chat_completion",
            side_effect=_instant_llm,
        ):
            t = _Timer()
            with t:
                result = await intent_parser_service.parse_intent(
                    query="Find all documents about solar energy projects from 2020 to 2024",
                    user_language="en",
                    use_ollama=False,
                )

        elapsed = t.elapsed
        passed = elapsed < TARGET

        _record_result(
            "intent_parsing",
            elapsed,
            TARGET,
            passed,
            keywords_extracted=result.keywords,
            confidence=result.confidence,
        )

        print(
            f"\n  [INTENT PARSING] {elapsed:.3f}s  (target <{TARGET}s) "
            f"— {'PASS ✓' if passed else 'FAIL ✗'}"
        )
        assert passed, (
            f"Intent parsing took {elapsed:.3f}s which exceeds the {TARGET}s target.\n"
            f"Full report: {REPORT_PATH}"
        )


# ===========================================================================
# BENCHMARK 2 — Document Gathering via Hybrid Search  (target < 5 s)
# ===========================================================================


class TestDocumentGatheringBenchmark:
    """
    Measures real PostgreSQL query time: keyword (ILIKE) search across
    60 pre-seeded documents (50 public + 10 confidential).

    Semantic search is naturally bypassed because the embedding model is not
    loaded in the benchmark environment — identical to the production backend
    container which runs requirements-minimal.txt (per CLAUDE.md).
    """

    @pytest.mark.asyncio
    async def test_document_gathering_perf(self, pg_bench_db: tuple) -> None:
        TARGET = 5.0
        session, admin = pg_bench_db

        intent = _make_parsed_intent(["solar", "energy", "projects"])

        # Semantic search is naturally skipped when the embedding model is not
        # loaded (can_embed returns False — the production backend container
        # runs without sentence_transformers per CLAUDE.md).  The benchmark
        # therefore exercises the real keyword (ILIKE) search path against
        # the seeded PostgreSQL data.
        t = _Timer()
        with t:
            docs = await collection_service._gather_documents_for_intent(
                intent=intent,
                user=admin,
                db=session,
            )

        elapsed = t.elapsed
        passed = elapsed < TARGET

        public_cnt = sum(1 for d in docs if d.bucket == DocumentBucket.PUBLIC)
        conf_cnt = sum(1 for d in docs if d.bucket == DocumentBucket.CONFIDENTIAL)

        _record_result(
            "document_gathering",
            elapsed,
            TARGET,
            passed,
            docs_returned=len(docs),
            public_count=public_cnt,
            confidential_count=conf_cnt,
        )

        print(
            f"\n  [DOC GATHERING] {elapsed:.3f}s  (target <{TARGET}s) "
            f"— {'PASS ✓' if passed else 'FAIL ✗'}\n"
            f"  Documents: {len(docs)} total ({public_cnt} public, {conf_cnt} confidential)"
        )
        assert passed, (
            f"Document gathering took {elapsed:.3f}s which exceeds the {TARGET}s target.\n"
            f"Full report: {REPORT_PATH}"
        )


# ===========================================================================
# BENCHMARK 3 — AI Summary Generation  (target < 20 s)
# ===========================================================================


class TestAISummaryBenchmark:
    """
    Measures orchestration overhead for _generate_collection_summary():
      - Confidentiality routing decision (has_confidential flag)
      - Prompt assembly
      - Async stream drain from mocked LLM
      - Response concatenation and strip

    The LLM call itself is replaced by an instant in-process generator.
    """

    @pytest.mark.asyncio
    async def test_ai_summary_generation_perf(self, pg_bench_db: tuple) -> None:
        TARGET = 20.0
        session, admin = pg_bench_db

        # Use real documents from the seeded DB so routing logic fires properly
        docs = (
            session.query(Document)
            .filter(Document.status == DocumentStatus.INDEXED)
            .limit(10)
            .all()
        )
        assert len(docs) > 0, "Seeded documents missing — check seeded_db fixture"

        intent = _make_parsed_intent(["solar", "energy"])

        canned_summary = (
            "This collection gathers solar and energy documents spanning 2020-2024. "
            "Key themes include renewable energy policy, project management, and "
            "sustainability metrics across the legacy archive."
        )

        async def _instant_summary(*_args: Any, **_kwargs: Any):
            # Yield in a few chunks to exercise the streaming drain loop
            for part in canned_summary.split(". "):
                yield part + ". "

        with patch(
            "app.services.openrouter_service.openrouter_service.chat_completion",
            side_effect=_instant_summary,
        ):
            t = _Timer()
            with t:
                summary = await collection_service._generate_collection_summary(
                    collection_name="Solar Energy Benchmark Collection",
                    query="Find solar energy project documents",
                    documents=docs,
                    parsed_intent=intent,
                )

        elapsed = t.elapsed
        passed = elapsed < TARGET
        summary_len = len(summary) if summary else 0

        _record_result(
            "ai_summary_generation",
            elapsed,
            TARGET,
            passed,
            summary_length_chars=summary_len,
            docs_input=len(docs),
        )

        print(
            f"\n  [AI SUMMARY] {elapsed:.3f}s  (target <{TARGET}s) "
            f"— {'PASS ✓' if passed else 'FAIL ✗'}\n"
            f"  Summary ({summary_len} chars): {summary[:80]}…"
        )
        assert passed, (
            f"AI summary generation took {elapsed:.3f}s which exceeds the {TARGET}s target.\n"
            f"Full report: {REPORT_PATH}"
        )


# ===========================================================================
# BENCHMARK 4 — Full End-to-End Collection Creation  (target < 30 s)
# ===========================================================================


class TestCollectionCreationE2EBenchmark:
    """
    Full pipeline:
      parse_intent() → _gather_documents_for_intent() → _generate_collection_summary()
      → Collection INSERT + CollectionItem INSERTs

    LLM calls are mocked; all PostgreSQL operations (search, writes) are real.
    Fails if wall-clock time exceeds 30 s.
    """

    @pytest.mark.asyncio
    async def test_e2e_collection_creation_perf(self, pg_bench_db: tuple) -> None:
        TARGET = 30.0
        session, admin = pg_bench_db

        # --- Responses: intent JSON first, summary second ---
        intent_json = json.dumps(
            {
                "keywords": ["energy", "solar"],
                "date_range": {},
                "entities": [],
                "document_types": ["all"],
                "collection_name": "E2E Benchmark Collection",
                "confidence": 0.92,
            }
        )
        _responses = [
            intent_json,
            "E2E benchmark collection covering solar and energy documents.",
        ]
        _call_idx: list[int] = [0]   # mutable cell for nonlocal update

        async def _stateful_llm(*_args: Any, **_kwargs: Any):
            """Return the next canned response in sequence."""
            response = _responses[_call_idx[0] % len(_responses)]
            _call_idx[0] += 1
            yield response

        collection_data = CollectionCreate(
            name="E2E Perf Benchmark Collection",
            query="Find all solar energy documents",
            collection_type="smart",
            visibility="private",
        )

        # Embedding model is not loaded in benchmark env → semantic search is
        # naturally skipped; keyword search runs against real PostgreSQL.
        with patch(
            "app.services.openrouter_service.openrouter_service.chat_completion",
            side_effect=_stateful_llm,
        ):
            t = _Timer()
            with t:
                collection = await collection_service.create_collection(
                    collection_data=collection_data,
                    user=admin,
                    db=session,
                )

        elapsed = t.elapsed
        passed = elapsed < TARGET

        _record_result(
            "e2e_collection_creation",
            elapsed,
            TARGET,
            passed,
            collection_id=str(collection.id),
            document_count=collection.document_count,
            has_ai_summary=bool(collection.ai_summary),
            is_confidential=collection.is_confidential,
        )

        print(
            f"\n  [E2E CREATION] {elapsed:.3f}s  (target <{TARGET}s) "
            f"— {'PASS ✓' if passed else 'FAIL ✗'}\n"
            f"  Collection '{collection.name}' — {collection.document_count} docs"
        )
        assert passed, (
            f"End-to-end collection creation took {elapsed:.3f}s "
            f"which exceeds the {TARGET}s target.\n"
            f"Full report: {REPORT_PATH}"
        )

    def test_benchmark_report_artifact_written(self) -> None:
        """
        Verify that the JSON benchmark report was written by at least one of
        the timing tests in this session.  Skips gracefully if the report
        was not yet created (e.g. when this test is run in isolation).
        """
        if not REPORT_PATH.exists():
            pytest.skip(
                f"Benchmark report not found at {REPORT_PATH}. "
                "Run the timing tests first (test_intent_parsing_perf etc.)."
            )

        data = json.loads(REPORT_PATH.read_text())
        assert "results" in data, "Report has no 'results' key"
        assert len(data["results"]) >= 1, "Report has no measurement entries"

        # Print a human-readable summary table
        print(f"\n  Benchmark report: {REPORT_PATH}")
        print(f"  {'Name':<35} {'Elapsed':>9} {'Target':>8} {'Status':>7}")
        print(f"  {'-'*35} {'-'*9} {'-'*8} {'-'*7}")
        for r in data["results"]:
            status = "PASS ✓" if r["passed"] else "FAIL ✗"
            print(
                f"  {r['name']:<35} {r['elapsed_s']:>8.3f}s "
                f"{r['target_s']:>7}s {status:>7}"
            )
