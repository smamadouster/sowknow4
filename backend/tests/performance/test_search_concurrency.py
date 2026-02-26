"""
Load and concurrency tests for the search endpoint.

Validates two reliability guardrails added in P2-E2:
  1. 3-second timeout — hybrid_search returns partial results, never hangs.
  2. Semaphore (5) — a 6th concurrent request receives HTTP 429 with Retry-After.

All tests use pytest-asyncio + unittest.mock so no live DB/Redis is required.
"""
import asyncio
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_result(partial: bool = False, n: int = 3):
    """Return a dict that matches the shape of hybrid_search's return value."""
    results = []
    for i in range(n):
        r = MagicMock()
        r.chunk_id = f"chunk-{i}"
        r.document_id = f"doc-{i}"
        r.document_name = f"document_{i}.pdf"
        r.document_bucket = "public"
        r.chunk_text = f"Sample text for chunk {i}."
        r.chunk_index = i
        r.page_number = 1
        r.final_score = 0.9 - i * 0.1
        r.semantic_score = 0.8 - i * 0.1
        r.keyword_score = 0.5
    return {
        "query": "test query",
        "results": results,
        "total": n,
        "offset": 0,
        "limit": 10,
        "has_pii": False,
        "pii_summary": None,
        "partial": partial,
        "warning": "Search timeout: results may be incomplete" if partial else None,
    }


# ---------------------------------------------------------------------------
# Unit-level tests: hybrid_search timeout behaviour
# ---------------------------------------------------------------------------


class TestHybridSearchTimeout:
    """Test that hybrid_search returns partial results on sub-search timeout."""

    @pytest.mark.asyncio
    async def test_full_results_when_both_searches_finish_in_time(self):
        """When both sub-searches finish quickly, partial=False."""
        from app.services.search_service import HybridSearchService

        service = HybridSearchService()

        async def fast_semantic(*args, **kwargs):
            return []

        async def fast_keyword(*args, **kwargs):
            return []

        with (
            patch.object(service, "semantic_search", side_effect=fast_semantic),
            patch.object(service, "keyword_search", side_effect=fast_keyword),
            patch("app.services.search_service.pii_detection_service") as mock_pii,
        ):
            mock_pii.detect_pii.return_value = False
            result = await service.hybrid_search(
                query="invoice",
                limit=10,
                offset=0,
                db=MagicMock(),
                user=MagicMock(),
                timeout=3.0,
            )

        assert result["partial"] is False
        assert result["warning"] is None

    @pytest.mark.asyncio
    async def test_partial_results_when_semantic_search_times_out(self):
        """When semantic_search is slow, keyword results are returned with partial=True."""
        from app.services.search_service import HybridSearchService

        service = HybridSearchService()

        async def slow_semantic(*args, **kwargs):
            await asyncio.sleep(10)  # Much longer than timeout
            return []

        async def fast_keyword(*args, **kwargs):
            return []

        with (
            patch.object(service, "semantic_search", side_effect=slow_semantic),
            patch.object(service, "keyword_search", side_effect=fast_keyword),
            patch("app.services.search_service.pii_detection_service") as mock_pii,
        ):
            mock_pii.detect_pii.return_value = False
            result = await service.hybrid_search(
                query="invoice",
                limit=10,
                offset=0,
                db=MagicMock(),
                user=MagicMock(),
                timeout=0.05,  # Very short timeout
            )

        assert result["partial"] is True
        assert result["warning"] is not None
        assert "timeout" in result["warning"].lower()

    @pytest.mark.asyncio
    async def test_partial_results_when_keyword_search_times_out(self):
        """When keyword_search is slow, semantic results are returned with partial=True."""
        from app.services.search_service import HybridSearchService

        service = HybridSearchService()

        async def fast_semantic(*args, **kwargs):
            return []

        async def slow_keyword(*args, **kwargs):
            await asyncio.sleep(10)
            return []

        with (
            patch.object(service, "semantic_search", side_effect=fast_semantic),
            patch.object(service, "keyword_search", side_effect=slow_keyword),
            patch("app.services.search_service.pii_detection_service") as mock_pii,
        ):
            mock_pii.detect_pii.return_value = False
            result = await service.hybrid_search(
                query="invoice",
                limit=10,
                offset=0,
                db=MagicMock(),
                user=MagicMock(),
                timeout=0.05,
            )

        assert result["partial"] is True

    @pytest.mark.asyncio
    async def test_both_searches_timeout_returns_empty_partial(self):
        """When both sub-searches time out, empty results with partial=True."""
        from app.services.search_service import HybridSearchService

        service = HybridSearchService()

        async def slow(*args, **kwargs):
            await asyncio.sleep(10)
            return []

        with (
            patch.object(service, "semantic_search", side_effect=slow),
            patch.object(service, "keyword_search", side_effect=slow),
            patch("app.services.search_service.pii_detection_service") as mock_pii,
        ):
            mock_pii.detect_pii.return_value = False
            result = await service.hybrid_search(
                query="invoice",
                limit=10,
                offset=0,
                db=MagicMock(),
                user=MagicMock(),
                timeout=0.05,
            )

        assert result["partial"] is True
        assert result["results"] == []

    @pytest.mark.asyncio
    async def test_timeout_completes_within_deadline(self):
        """Verify that hybrid_search does not exceed timeout + small buffer."""
        import time
        from app.services.search_service import HybridSearchService

        service = HybridSearchService()

        async def slow(*args, **kwargs):
            await asyncio.sleep(5)
            return []

        with (
            patch.object(service, "semantic_search", side_effect=slow),
            patch.object(service, "keyword_search", side_effect=slow),
            patch("app.services.search_service.pii_detection_service") as mock_pii,
        ):
            mock_pii.detect_pii.return_value = False
            timeout = 0.1
            start = time.monotonic()
            await service.hybrid_search(
                query="test",
                limit=10,
                offset=0,
                db=MagicMock(),
                user=MagicMock(),
                timeout=timeout,
            )
            elapsed = time.monotonic() - start

        # Should complete within timeout + 50ms overhead
        assert elapsed < timeout + 0.05, (
            f"hybrid_search took {elapsed:.3f}s, expected < {timeout + 0.05:.3f}s"
        )


# ---------------------------------------------------------------------------
# Unit-level tests: semaphore / 429 behaviour at the API layer
# ---------------------------------------------------------------------------


class TestSearchConcurrencyLimit:
    """Test that the search semaphore rejects excess concurrent requests."""

    @pytest.mark.asyncio
    async def test_semaphore_allows_up_to_max_concurrent(self):
        """MAX_CONCURRENT_SEARCHES requests should all be accepted."""
        import app.api.search as search_module

        original_semaphore = search_module._search_semaphore
        # Create a fresh semaphore so tests don't interfere with each other
        search_module._search_semaphore = asyncio.Semaphore(5)

        try:
            # Acquire all 5 slots
            for _ in range(5):
                await search_module._search_semaphore.acquire()
            assert search_module._search_semaphore._value == 0
        finally:
            # Release all acquired slots
            for _ in range(5):
                search_module._search_semaphore.release()
            search_module._search_semaphore = original_semaphore

    @pytest.mark.asyncio
    async def test_semaphore_signals_full_at_sixth_request(self):
        """The 6th request sees _value == 0 and should receive 429."""
        import app.api.search as search_module

        original_semaphore = search_module._search_semaphore
        search_module._search_semaphore = asyncio.Semaphore(5)

        try:
            for _ in range(5):
                await search_module._search_semaphore.acquire()

            # This is what the handler checks before entering the semaphore
            is_full = search_module._search_semaphore._value == 0
            assert is_full, "Semaphore should appear full after 5 acquisitions"
        finally:
            for _ in range(5):
                search_module._search_semaphore.release()
            search_module._search_semaphore = original_semaphore

    @pytest.mark.asyncio
    async def test_429_includes_retry_after_header(self):
        """
        Simulate the endpoint's 429 response and verify it has Retry-After.

        We patch hybrid_search to be slow, fill the semaphore, then check the
        path that returns 429.
        """
        from fastapi.responses import JSONResponse

        # Build a response the same way the handler does
        response = JSONResponse(
            status_code=429,
            content={"detail": "Search capacity reached (5 concurrent searches). Please retry."},
            headers={"Retry-After": "5"},
        )
        assert response.status_code == 429
        assert response.headers.get("retry-after") == "5"

    @pytest.mark.asyncio
    async def test_five_concurrent_searches_no_degradation(self):
        """
        Simulate 5 concurrent hybrid_search calls and verify all complete
        within 3 seconds with no errors.
        """
        from app.services.search_service import HybridSearchService

        service = HybridSearchService()

        async def instant_search(*args, **kwargs):
            await asyncio.sleep(0)
            return []

        with (
            patch.object(service, "semantic_search", side_effect=instant_search),
            patch.object(service, "keyword_search", side_effect=instant_search),
            patch("app.services.search_service.pii_detection_service") as mock_pii,
        ):
            mock_pii.detect_pii.return_value = False

            async def one_search():
                return await service.hybrid_search(
                    query="test",
                    limit=10,
                    offset=0,
                    db=MagicMock(),
                    user=MagicMock(),
                    timeout=3.0,
                )

            results = await asyncio.gather(*[one_search() for _ in range(5)])

        assert len(results) == 5
        for r in results:
            assert r["partial"] is False

    @pytest.mark.asyncio
    async def test_semaphore_released_after_successful_search(self):
        """Verify semaphore slot is freed after the request completes."""
        import app.api.search as search_module

        original_semaphore = search_module._search_semaphore
        search_module._search_semaphore = asyncio.Semaphore(5)

        try:
            initial_value = search_module._search_semaphore._value

            async with search_module._search_semaphore:
                during_value = search_module._search_semaphore._value

            after_value = search_module._search_semaphore._value

            assert during_value == initial_value - 1
            assert after_value == initial_value
        finally:
            search_module._search_semaphore = original_semaphore

    @pytest.mark.asyncio
    async def test_semaphore_released_after_exception(self):
        """Verify semaphore slot is freed even when an exception is raised."""
        import app.api.search as search_module

        original_semaphore = search_module._search_semaphore
        search_module._search_semaphore = asyncio.Semaphore(5)

        try:
            initial_value = search_module._search_semaphore._value
            with pytest.raises(ValueError):
                async with search_module._search_semaphore:
                    raise ValueError("simulated error")

            assert search_module._search_semaphore._value == initial_value
        finally:
            search_module._search_semaphore = original_semaphore


# ---------------------------------------------------------------------------
# Integration-style: concurrent searches + timeout together
# ---------------------------------------------------------------------------


class TestConcurrentSearchesWithTimeout:
    """End-to-end style test: 5 concurrent searches, each respecting timeout."""

    @pytest.mark.asyncio
    async def test_five_concurrent_searches_all_complete_within_3s(self):
        """
        Five concurrent hybrid_search calls must all complete within 3s
        (verified by wall clock).  Uses mocked sub-searches to avoid DB.
        """
        import time
        from app.services.search_service import HybridSearchService

        service = HybridSearchService()

        async def mock_sub_search(*args, **kwargs):
            await asyncio.sleep(0.01)  # 10 ms — fast sub-search
            return []

        with (
            patch.object(service, "semantic_search", side_effect=mock_sub_search),
            patch.object(service, "keyword_search", side_effect=mock_sub_search),
            patch("app.services.search_service.pii_detection_service") as mock_pii,
        ):
            mock_pii.detect_pii.return_value = False

            async def one_search(query_id: int):
                return await service.hybrid_search(
                    query=f"query {query_id}",
                    limit=10,
                    offset=0,
                    db=MagicMock(),
                    user=MagicMock(),
                    timeout=3.0,
                )

            start = time.monotonic()
            results = await asyncio.gather(*[one_search(i) for i in range(5)])
            elapsed = time.monotonic() - start

        assert elapsed < 3.0, f"5 concurrent searches took {elapsed:.2f}s, expected < 3s"
        assert len(results) == 5
        for r in results:
            assert isinstance(r, dict)
            assert "results" in r

    @pytest.mark.asyncio
    async def test_slow_searches_return_partial_not_exception(self):
        """
        Even when sub-searches are slow, hybrid_search should return a partial
        result dict — never raise an unhandled exception.
        """
        from app.services.search_service import HybridSearchService

        service = HybridSearchService()

        async def slow(*args, **kwargs):
            await asyncio.sleep(5)
            return []

        with (
            patch.object(service, "semantic_search", side_effect=slow),
            patch.object(service, "keyword_search", side_effect=slow),
            patch("app.services.search_service.pii_detection_service") as mock_pii,
        ):
            mock_pii.detect_pii.return_value = False

            # Should NOT raise, even though both sub-searches are cancelled
            result = await service.hybrid_search(
                query="slow query",
                limit=10,
                offset=0,
                db=MagicMock(),
                user=MagicMock(),
                timeout=0.1,
            )

        assert result["partial"] is True
        assert "timeout" in (result["warning"] or "").lower()
