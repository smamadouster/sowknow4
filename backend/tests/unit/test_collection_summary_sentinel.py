"""Regression tests (2026-08-02): the "__USAGE__" stream sentinel must never
leak into stored collection summaries, and collection relevance scores must
stay ABSOLUTE (no relative max-normalization inflating the top doc to 100%).

Root cause of the leak: providers yield the sentinel as a trailing
"\\n__USAGE__: {...}" chunk, so ``chunk.startswith("__USAGE__")`` misses it.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.collection_service import CollectionService
from app.services.collection_orchestrator import summary_generator
from app.services.collection_orchestrator.summary_generator import SummaryGenerator


USAGE_CHUNK = '\n__USAGE__: {"prompt_tokens": 10, "completion_tokens": 5}'


def _svc():
    service = CollectionService()
    service.llm = MagicMock()
    service.search_service = MagicMock()
    return service


class TestLegacySynthesizeSummary:
    @pytest.mark.asyncio
    async def test_usage_sentinel_stripped(self):
        service = _svc()
        service.llm.chat_completion_non_stream = AsyncMock(
            return_value="Résumé utile de la collection." + USAGE_CHUNK
        )
        intent = MagicMock(entities=[])
        summary = await service._synthesize_summary(
            "dossier salaires", "faire un dossier sur les salaires", [], intent
        )
        assert summary == "Résumé utile de la collection."
        assert "__USAGE__" not in summary

    @pytest.mark.asyncio
    async def test_prompt_requires_query_language(self):
        service = _svc()
        captured = {}

        async def _capture(messages, **kwargs):
            captured["messages"] = messages
            return "ok"

        service.llm.chat_completion_non_stream = _capture
        intent = MagicMock(entities=[])
        await service._synthesize_summary("dossier", "les salaires", [], intent)
        system = captured["messages"][0]["content"]
        user = captured["messages"][1]["content"]
        assert "same language" in system.lower()
        assert "same language" in user.lower()


class TestLegacyGenerateCollectionSummary:
    @pytest.mark.asyncio
    async def test_usage_sentinel_chunk_stripped(self):
        service = _svc()

        async def fake_chat(**kwargs):
            yield "Voici "
            yield "le résumé."
            yield USAGE_CHUNK  # leading newline defeats startswith()

        service.llm.chat_completion = fake_chat
        intent = MagicMock(entities=[])
        doc = MagicMock(filename="salaires.pdf", bucket=None)
        summary = await service._generate_collection_summary(
            "dossier", "les salaires", [doc], intent
        )
        assert summary == "Voici le résumé."


class TestGatewayNonStreamFallback:
    @pytest.mark.asyncio
    async def test_fallback_collector_strips_sentinel(self):
        from app.services.llm_gateway import LLMGateway

        class FakeSvc:
            # no chat_completion_non_stream -> gateway uses the fallback
            async def chat_completion(self, **kwargs):
                yield "Réponse."
                yield USAGE_CHUNK

        gateway = LLMGateway.__new__(LLMGateway)
        gateway._router = MagicMock()
        gateway._router._minimax = None
        gateway._router._openrouter = FakeSvc()

        result = await gateway.chat_completion_non_stream(
            messages=[{"role": "user", "content": "hi"}]
        )
        assert result == "Réponse."


class TestOrchestratorSummaryGenerator:
    @pytest.mark.asyncio
    async def test_usage_sentinel_stripped(self, monkeypatch):
        async def mock_generate(messages, **kwargs):
            yield "narrative text"
            yield USAGE_CHUNK

        monkeypatch.setattr(
            summary_generator.llm_router, "generate_completion", mock_generate
        )
        generator = SummaryGenerator()
        result = await generator.generate(
            [{"statement": "s", "source_refs": [], "validation_status": "validated"}],
            [],
            {"query": "q"},
            {},
        )
        assert result == "narrative text"


class TestGatherQueryText:
    """2026-08-02: the intent parser may return raw query tokens as keywords
    (["faire","dossier","sur","les","salaires",...]); plainto_tsquery ANDs
    every term, so unfiltered keywords silently kill recall."""

    def test_french_stopwords_filtered(self):
        from app.services.collection_service import gather_query_text

        intent = MagicMock(
            keywords=["faire", "dossier", "sur", "les", "salaires",
                      "tout", "qui", "rapproche", "mot", "salaire"],
            query="faire un dossier sur les salaires",
        )
        assert gather_query_text(intent) == "salaires salaire"

    def test_meaningful_keywords_kept_in_order(self):
        from app.services.collection_service import gather_query_text

        intent = MagicMock(keywords=["MATFORCE", "mali", "contrats"], query="q")
        assert gather_query_text(intent) == "MATFORCE mali contrats"

    def test_fallback_to_raw_query_when_all_stopwords(self):
        from app.services.collection_service import gather_query_text

        intent = MagicMock(keywords=["le", "la", "les"], query="raw query")
        assert gather_query_text(intent) == "raw query"

    def test_no_keywords_uses_raw_query(self):
        from app.services.collection_service import gather_query_text

        intent = MagicMock(keywords=[], query="raw query")
        assert gather_query_text(intent) == "raw query"


class TestGatherAbsoluteScores:
    """Scores must stay absolute: the best doc keeps its blended score, it is
    NOT re-inflated to 1.0 by relative normalization."""

    @staticmethod
    def _result(doc_id, score, result_type="chunk"):
        r = MagicMock()
        r.document_id = doc_id
        r.result_type = result_type
        r.final_score = score
        r.semantic_score = score
        r.keyword_score = score
        r.article_id = None
        r.article_title = None
        r.article_summary = None
        r.document_name = f"doc-{doc_id}.pdf"
        r.chunk_text = "le salaire brut et net"
        return r

    @pytest.mark.asyncio
    async def test_scores_not_normalized_to_max(self):
        service = _svc()
        hits = [self._result("d1", 0.50), self._result("d2", 0.40)]
        for name in (
            "article_semantic_search",
            "article_keyword_search",
        ):
            setattr(service.search_service, name, AsyncMock(return_value=[]))
        service.search_service.semantic_search = AsyncMock(return_value=hits)
        service.search_service.keyword_search = AsyncMock(return_value=[])
        service.search_service.tag_search = AsyncMock(return_value=[])

        intent = MagicMock(keywords=["salaire"], query="les salaires")
        user = MagicMock()
        user.role.value = "user"

        # rerank returns (position, score) pairs over the top candidates
        rerank = AsyncMock(return_value=[(0, 0.60), (1, 0.50)])
        with patch(
            "app.services.rerank_service.rerank_passages", rerank
        ), patch(
            "app.services.collection_service.SearchCache"
        ) as cache:
            cache.get_collection_gather.return_value = None
            results = await service._gather_and_verify(
                intent, "broad_hybrid", user, MagicMock()
            )

        assert len(results) == 2
        by_doc = {r["document_id"]: r["relevance_score"] for r in results}
        # absolute blend 0.3*raw + 0.7*rerank — NOT normalized to 1.0
        assert by_doc["d1"] == pytest.approx(0.3 * 0.50 + 0.7 * 0.60)
        assert by_doc["d2"] == pytest.approx(0.3 * 0.40 + 0.7 * 0.50)
        assert max(by_doc.values()) < 1.0
