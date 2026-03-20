"""
SOWKNOW Agentic Search — Test Suite
Run: pytest backend/tests/test_search_agent.py -v
"""

import pytest
from app.services.search_models import (
    AgenticSearchRequest,
    SearchMode,
)


class TestSearchRequestValidation:
    def test_empty_query_rejected(self):
        with pytest.raises(Exception):
            AgenticSearchRequest(query="")

    def test_whitespace_query_stripped(self):
        req = AgenticSearchRequest(query="  bilan financier  ")
        assert req.query == "bilan financier"

    def test_default_mode_is_auto(self):
        req = AgenticSearchRequest(query="test")
        assert req.mode == SearchMode.AUTO

    def test_top_k_default(self):
        req = AgenticSearchRequest(query="test")
        assert req.top_k == 10

    def test_top_k_max_enforced(self):
        with pytest.raises(Exception):
            AgenticSearchRequest(query="test", top_k=51)


from datetime import datetime
from uuid import uuid4

from app.models.document import DocumentBucket
from app.models.user import UserRole
from app.services.search_models import (
    ParsedIntent,
    QueryIntent,
    RawChunk,
    RelevanceLabel,
)
from app.services.search_agent import (
    _fallback_intent,
    _score_to_label,
    build_citations,
    build_search_queries,
    rerank_and_build_results,
)


def make_chunk(
    bucket: DocumentBucket = DocumentBucket.PUBLIC,
    semantic_score: float = 0.75,
    rrf_score: float = 0.015,
    text: str = "Ceci est un extrait de test sur la finance.",
    doc_id=None,
) -> RawChunk:
    return RawChunk(
        chunk_id=uuid4(),
        document_id=doc_id or uuid4(),
        document_title="Document de test",
        document_bucket=bucket,
        document_type="pdf",
        chunk_index=0,
        page_number=1,
        text=text,
        semantic_score=semantic_score,
        fts_rank=0.3,
        rrf_score=rrf_score,
        created_at=datetime.utcnow(),
        tags=["finance", "test"],
    )


def make_intent(
    intent: QueryIntent = QueryIntent.FACTUAL,
    keywords=None,
    sub_queries=None,
    requires_synthesis: bool = False,
) -> ParsedIntent:
    return ParsedIntent(
        intent=intent,
        confidence=0.9,
        keywords=keywords or ["finance", "bilan"],
        expanded_keywords=["actif", "passif"],
        sub_queries=sub_queries or [],
        detected_language="fr",
        requires_synthesis=requires_synthesis,
    )


class TestRelevanceLabels:
    def test_highly_relevant(self):
        assert _score_to_label(0.85) == RelevanceLabel.HIGHLY_RELEVANT

    def test_highly_relevant_boundary(self):
        assert _score_to_label(0.82) == RelevanceLabel.HIGHLY_RELEVANT

    def test_relevant(self):
        assert _score_to_label(0.72) == RelevanceLabel.RELEVANT

    def test_relevant_lower_boundary(self):
        assert _score_to_label(0.65) == RelevanceLabel.RELEVANT

    def test_partially(self):
        assert _score_to_label(0.55) == RelevanceLabel.PARTIALLY

    def test_marginal(self):
        assert _score_to_label(0.3) == RelevanceLabel.MARGINAL

    def test_zero(self):
        assert _score_to_label(0.0) == RelevanceLabel.MARGINAL


class TestRBACEnforcement:
    def test_user_cannot_see_confidential_chunks(self):
        doc_id = uuid4()
        public_chunk = make_chunk(DocumentBucket.PUBLIC, rrf_score=0.01, doc_id=doc_id)
        confidential_chunk = make_chunk(DocumentBucket.CONFIDENTIAL, rrf_score=0.02)
        intent = make_intent()
        results, has_confidential = rerank_and_build_results(
            [public_chunk, confidential_chunk], "test", intent, 10, UserRole.USER,
        )
        for r in results:
            assert r.bucket != DocumentBucket.CONFIDENTIAL
        assert not has_confidential

    def test_admin_can_see_confidential_chunks(self):
        confidential_chunk = make_chunk(DocumentBucket.CONFIDENTIAL, rrf_score=0.9)
        intent = make_intent()
        results, has_confidential = rerank_and_build_results(
            [confidential_chunk], "test", intent, 10, UserRole.ADMIN,
        )
        assert has_confidential
        assert any(r.bucket == DocumentBucket.CONFIDENTIAL for r in results)

    def test_super_user_can_see_confidential_chunks(self):
        confidential_chunk = make_chunk(DocumentBucket.CONFIDENTIAL, rrf_score=0.9)
        intent = make_intent()
        results, has_confidential = rerank_and_build_results(
            [confidential_chunk], "test", intent, 10, UserRole.SUPERUSER,
        )
        assert has_confidential
        assert any(r.bucket == DocumentBucket.CONFIDENTIAL for r in results)

    def test_user_mixed_results_filters_confidential(self):
        doc_pub = uuid4()
        doc_conf = uuid4()
        chunks = [
            make_chunk(DocumentBucket.PUBLIC, rrf_score=0.8, doc_id=doc_pub),
            make_chunk(DocumentBucket.CONFIDENTIAL, rrf_score=0.9, doc_id=doc_conf),
            make_chunk(DocumentBucket.PUBLIC, rrf_score=0.7, doc_id=uuid4()),
        ]
        intent = make_intent()
        results, has_confidential = rerank_and_build_results(
            chunks, "test", intent, 10, UserRole.USER,
        )
        assert all(r.bucket == DocumentBucket.PUBLIC for r in results)
        assert not has_confidential
        assert len(results) == 2

    def test_is_confidential_flag_set_correctly(self):
        doc_id = uuid4()
        conf_chunk = make_chunk(DocumentBucket.CONFIDENTIAL, rrf_score=0.9, doc_id=doc_id)
        intent = make_intent()
        results, _ = rerank_and_build_results(
            [conf_chunk], "test", intent, 10, UserRole.ADMIN,
        )
        assert results[0].is_confidential is True

    def test_public_result_not_flagged_confidential(self):
        doc_id = uuid4()
        pub_chunk = make_chunk(DocumentBucket.PUBLIC, rrf_score=0.9, doc_id=doc_id)
        intent = make_intent()
        results, _ = rerank_and_build_results(
            [pub_chunk], "test", intent, 10, UserRole.ADMIN,
        )
        assert results[0].is_confidential is False


class TestResultRanking:
    def test_results_sorted_by_relevance_descending(self):
        chunks = [
            make_chunk(rrf_score=0.005, doc_id=uuid4()),
            make_chunk(rrf_score=0.020, doc_id=uuid4()),
            make_chunk(rrf_score=0.012, doc_id=uuid4()),
        ]
        intent = make_intent()
        results, _ = rerank_and_build_results(chunks, "test", intent, 10, UserRole.ADMIN)
        scores = [r.relevance_score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_ranks_sequential(self):
        chunks = [make_chunk(rrf_score=0.02 - i * 0.003, doc_id=uuid4()) for i in range(5)]
        intent = make_intent()
        results, _ = rerank_and_build_results(chunks, "test", intent, 10, UserRole.ADMIN)
        assert [r.rank for r in results] == list(range(1, len(results) + 1))

    def test_top_k_respected(self):
        chunks = [make_chunk(rrf_score=0.02 - i * 0.001, doc_id=uuid4()) for i in range(20)]
        intent = make_intent()
        results, _ = rerank_and_build_results(chunks, "test", intent, top_k=5, user_role=UserRole.ADMIN)
        assert len(results) <= 5

    def test_chunks_collapsed_per_document(self):
        doc_id = uuid4()
        chunks = [
            make_chunk(rrf_score=0.02, doc_id=doc_id),
            make_chunk(rrf_score=0.015, doc_id=doc_id),
            make_chunk(rrf_score=0.01, doc_id=doc_id),
        ]
        intent = make_intent()
        results, _ = rerank_and_build_results(chunks, "test", intent, 10, UserRole.ADMIN)
        doc_ids = [r.document_id for r in results]
        assert len(doc_ids) == len(set(doc_ids))


class TestQueryExpansion:
    def test_simple_query_no_sub_queries(self):
        intent = make_intent(sub_queries=[])
        queries = build_search_queries(intent, "bilan financier 2023")
        assert "bilan financier 2023" in queries
        assert len(queries) >= 1

    def test_complex_query_with_sub_queries(self):
        intent = make_intent(
            sub_queries=["bilan actif 2022", "bilan passif 2022"],
            keywords=["bilan", "actif"],
        )
        queries = build_search_queries(intent, "analyse complete du bilan 2022")
        assert "analyse complete du bilan 2022" in queries
        assert "bilan actif 2022" in queries
        assert "bilan passif 2022" in queries

    def test_no_duplicate_queries(self):
        intent = make_intent(sub_queries=["bilan financier"])
        queries = build_search_queries(intent, "bilan financier")
        assert queries.count("bilan financier") == 1

    def test_keyword_variant_added(self):
        intent = make_intent(keywords=["bilan", "actif", "passif", "2022", "annuel"])
        queries = build_search_queries(intent, "bilan financier annuel")
        assert len(queries) >= 2


class TestCitations:
    def test_citations_match_results(self):
        doc_id = uuid4()
        chunk = make_chunk(doc_id=doc_id, rrf_score=0.9)
        intent = make_intent()
        results, _ = rerank_and_build_results([chunk], "test", intent, 10, UserRole.ADMIN)
        citations = build_citations(results, [chunk])
        assert len(citations) == 1
        assert citations[0].document_id == doc_id

    def test_one_citation_per_document(self):
        doc_id = uuid4()
        chunks = [make_chunk(doc_id=doc_id, rrf_score=0.9 - i * 0.1) for i in range(3)]
        intent = make_intent()
        results, _ = rerank_and_build_results(chunks, "test", intent, 10, UserRole.ADMIN)
        citations = build_citations(results, chunks)
        cit_doc_ids = [c.document_id for c in citations]
        assert len(cit_doc_ids) == len(set(cit_doc_ids))

    def test_citations_max_ten(self):
        chunks = [make_chunk(doc_id=uuid4(), rrf_score=0.02 - i * 0.001) for i in range(15)]
        intent = make_intent()
        results, _ = rerank_and_build_results(chunks, "test", intent, 15, UserRole.ADMIN)
        citations = build_citations(results, chunks)
        assert len(citations) <= 10

    def test_citation_excerpt_length(self):
        doc_id = uuid4()
        chunk = make_chunk(doc_id=doc_id, text="A" * 300)
        intent = make_intent()
        results, _ = rerank_and_build_results([chunk], "test", intent, 10, UserRole.ADMIN)
        citations = build_citations(results, [chunk])
        assert len(citations[0].chunk_excerpt) <= 205


class TestFallbackIntent:
    def test_temporal_query_detected(self):
        intent = _fallback_intent("Comment a evolue mon portefeuille en 2022 ?")
        assert intent.intent == QueryIntent.TEMPORAL

    def test_financial_query_detected(self):
        intent = _fallback_intent("Analyse du bilan financier annuel")
        assert intent.intent == QueryIntent.FINANCIAL

    def test_french_language_detected(self):
        intent = _fallback_intent("Quels sont les documents relatifs a la famille ?")
        assert intent.detected_language == "fr"

    def test_english_language_detected(self):
        intent = _fallback_intent("What are the main assets on the balance sheet?")
        assert intent.detected_language == "en"

    def test_keywords_extracted(self):
        intent = _fallback_intent("bilan financier actif passif 2023")
        assert len(intent.keywords) > 0

    def test_stop_words_removed_from_keywords(self):
        intent = _fallback_intent("les documents de la famille")
        assert "les" not in intent.keywords
        assert "la" not in intent.keywords
