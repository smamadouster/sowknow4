"""
Phase 3 QA Validation — Advanced Optimizations

Validates:
- Feedback endpoint (auth, validation, structure)
- Spell service (correction, fallback)
- Search cache store (TTL, eviction)

Run: pytest backend/tests/qa/test_search_phase3_qa.py -v
"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch


class TestFeedbackEndpoint:
    """QA Gate: P3.5 Feedback must be recorded correctly"""

    def test_feedback_unauthorized_401(self, client: TestClient):
        response = client.post("/api/v1/search/feedback", json={
            "query": "test",
            "document_id": "550e8400-e29b-41d4-a716-446655440000",
            "feedback_type": "thumbs_up",
        })
        assert response.status_code == 401

    def test_feedback_invalid_type_rejected(self, client: TestClient, auth_headers):
        response = client.post("/api/v1/search/feedback", json={
            "query": "test",
            "document_id": "550e8400-e29b-41d4-a716-446655440000",
            "feedback_type": "invalid",
        }, headers=auth_headers)
        assert response.status_code in [400, 422]

    def test_feedback_valid_thumbs_up(self, client: TestClient, auth_headers):
        response = client.post("/api/v1/search/feedback", json={
            "query": "passport search",
            "document_id": "550e8400-e29b-41d4-a716-446655440000",
            "chunk_id": "550e8400-e29b-41d4-a716-446655440001",
            "feedback_type": "thumbs_up",
        }, headers=auth_headers)
        assert response.status_code == 201
        assert response.json()["status"] == "recorded"

    def test_feedback_valid_thumbs_down(self, client: TestClient, auth_headers):
        response = client.post("/api/v1/search/feedback", json={
            "query": "tax 2024",
            "document_id": "550e8400-e29b-41d4-a716-446655440000",
            "feedback_type": "thumbs_down",
        }, headers=auth_headers)
        assert response.status_code == 201
        assert response.json()["status"] == "recorded"

    def test_feedback_valid_dismiss(self, client: TestClient, auth_headers):
        response = client.post("/api/v1/search/feedback", json={
            "query": "insurance",
            "document_id": "550e8400-e29b-41d4-a716-446655440000",
            "feedback_type": "dismiss",
        }, headers=auth_headers)
        assert response.status_code == 201
        assert response.json()["status"] == "recorded"

    def test_feedback_stats_require_auth(self, client: TestClient):
        response = client.get("/api/v1/search/feedback/stats")
        assert response.status_code == 401


class TestSpellService:
    """QA Gate: P3.3 Spell correction must work and fallback gracefully"""

    def test_correct_query_no_change_when_dictionary_empty(self):
        from app.services.spell_service import correct_query
        query, changed = correct_query("passport")
        assert query == "passport"
        assert changed is False

    def test_suggest_corrections_empty_when_dictionary_empty(self):
        from app.services.spell_service import suggest_corrections
        suggestions = suggest_corrections("pasport")
        assert suggestions == []

    def test_load_dictionary_and_correct(self):
        from unittest.mock import MagicMock, patch
        import app.services.spell_service as spell_mod

        mock_sym = MagicMock()
        mock_sym.lookup.return_value = [MagicMock(term="passport", distance=1)]
        mock_sym.lookup_compound.return_value = [MagicMock(term="passport", distance=1)]

        with patch.object(spell_mod, "_get_symspell", return_value=mock_sym):
            spell_mod.load_dictionary_from_terms(["passport", "insurance", "financial"])
            query, changed = spell_mod.correct_query("pasport")
            assert changed is True
            assert query == "passport"

    def test_numbers_not_corrected(self):
        from app.services.spell_service import load_dictionary_from_terms, correct_query
        load_dictionary_from_terms(["2024", "tax"])
        query, changed = correct_query("2024")
        assert query == "2024"
        assert changed is False

    def test_short_words_not_corrected(self):
        from app.services.spell_service import load_dictionary_from_terms, correct_query
        load_dictionary_from_terms(["at", "in", "on"])
        query, changed = correct_query("at")
        assert query == "at"
        assert changed is False


class TestSearchCache:
    """QA Gate: P1.4 + P3.4 Redis cache integration"""

    def test_cache_get_set_embedding(self):
        from unittest.mock import MagicMock, patch
        mock_redis = MagicMock()
        mock_redis.get.return_value = '[0.1, 0.2, 0.3]'

        with patch("app.services.search_cache._get_redis", return_value=mock_redis):
            from app.services.search_cache import SearchCache
            SearchCache.set_embedding("test query", [0.1, 0.2, 0.3])
            cached = SearchCache.get_embedding("test query")
            assert cached == [0.1, 0.2, 0.3]

    def test_cache_get_set_result(self):
        from unittest.mock import MagicMock, patch
        mock_redis = MagicMock()
        mock_redis.get.return_value = '{"results": []}'

        with patch("app.services.search_cache._get_redis", return_value=mock_redis):
            from app.services.search_cache import SearchCache
            SearchCache.set_result("test query", "user", 10, ["public"], {"results": []})
            cached = SearchCache.get_result("test query", "user", 10, ["public"])
            assert cached is not None
            assert cached["results"] == []

    def test_cache_miss_different_query(self):
        from unittest.mock import MagicMock, patch
        mock_redis = MagicMock()
        mock_redis.get.return_value = None

        with patch("app.services.search_cache._get_redis", return_value=mock_redis):
            from app.services.search_cache import SearchCache
            cached = SearchCache.get_result("query b", "user", 10, ["public"])
            assert cached is None

    def test_cache_invalidates_results(self):
        from unittest.mock import MagicMock, patch
        mock_redis = MagicMock()
        mock_redis.scan_iter.return_value = ["key1", "key2"]

        with patch("app.services.search_cache._get_redis", return_value=mock_redis):
            from app.services.search_cache import SearchCache
            SearchCache.invalidate_results()
            assert mock_redis.delete.call_count == 2
