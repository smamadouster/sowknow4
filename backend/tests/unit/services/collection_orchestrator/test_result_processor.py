import pytest
@pytest.mark.skip(reason="Ollama removed")
"""Unit tests for ResultProcessor (FR3) — rerank/LLM mocked, no DB."""

import json
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import app.services.collection_orchestrator.result_processor as rp_module
from app.services.collection_orchestrator.result_processor import (
    RANKING_VERSION,
    ResultProcessor,
    content_hash,
    hamming_distance,
    recency_score,
    simhash64,
)


def make_item(text="alpha beta gamma", days_old=100, item_type="pdf", score=0.5, **extra):
    item = {
        "document_id": str(uuid.uuid4()),
        "uri": "/data/doc.pdf",
        "title": "doc.pdf",
        "item_type": item_type,
        "source": "chunk",
        "author": "Jane",
        "item_date": datetime.now(timezone.utc) - timedelta(days=days_old),
        "relevance_score": score,
        "snippet": text,
        "acl_stamp": "public",
        "page_number": 3,
        "status": "ok",
    }
    item.update(extra)
    return item


@pytest.fixture
def processor():
    return ResultProcessor()


class TestDedup:
    def test_exact_duplicates_grouped(self, processor):
        older = make_item(days_old=400)
        newer = make_item(days_old=10)
        canonical, dups = processor.dedup([older, newer])

        assert len(canonical) == 1
        assert canonical[0] is newer  # most recent wins
        assert list(dups.values())[0] == [older]
        assert dups[canonical[0]["content_hash"]][0]["canonical_hash"] == canonical[0]["content_hash"]

    def test_canonical_tiebreak_on_metadata_completeness(self, processor):
        date = datetime(2021, 1, 1, tzinfo=timezone.utc)
        sparse = make_item(item_date=date, author=None, uri=None)
        rich = make_item(item_date=date)
        canonical, _ = processor.dedup([sparse, rich])
        assert canonical[0] is rich

    def test_near_duplicates_via_simhash(self, processor):
        # E-mail thread / re-saved version: long near-identical text, one phrase changed
        sentence = (
            "the annual financial report shows revenue growth across all regional "
            "branches with strong performance in the western division and stable margins "
            "throughout the fiscal year ending december "
        )
        base_text = sentence * 4
        variant_text = base_text.replace("strong performance", "solid performance", 1)
        near_a = make_item(text=base_text, days_old=100)
        near_b = make_item(text=variant_text, days_old=50)

        # Sanity: the simhashes really are within the near-dupe distance
        assert hamming_distance(simhash64(base_text), simhash64(variant_text)) <= 3

        canonical, dups = processor.dedup([near_a, near_b])
        assert len(canonical) == 1
        assert canonical[0] is near_b
        assert len(dups[canonical[0]["content_hash"]]) == 1

    def test_distinct_items_not_merged(self, processor):
        items = [
            make_item(text="quarterly tax filing for the fiscal year"),
            make_item(text="birthday party photos from the lake house"),
            make_item(text="warranty certificate for the washing machine"),
        ]
        canonical, dups = processor.dedup(items)
        assert len(canonical) == 3
        assert dups == {}

    def test_content_hash_is_sha256_of_normalized_text(self, processor):
        assert content_hash("Hello,   WORLD") == content_hash("hello world")


class TestRecency:
    def test_recency_bounds(self):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        assert recency_score(now - timedelta(days=10), now) == 1.0
        assert recency_score(now - timedelta(days=6 * 365), now) == 0.0
        assert recency_score(None, now) == 0.5
        mid = recency_score(now - timedelta(days=2 * 365), now)
        assert 0.0 < mid < 1.0


class TestRank:
    @pytest.mark.asyncio
    async def test_ranking_formula_and_detail(self, monkeypatch, processor):
        monkeypatch.setattr(rp_module, "rerank_passages", AsyncMock(return_value=[(0, 0.9), (1, 0.1)]))
        items = [make_item(score=0.8), make_item(text="other text", score=0.4)]

        ranked = await processor.rank(items, "query")

        detail = ranked[0]["ranking_detail"]
        assert detail["version"] == RANKING_VERSION
        assert detail["weights"] == {"search": 0.55, "rerank": 0.25, "recency": 0.10, "type": 0.10}
        expected = (
            0.55 * detail["components"]["search_score"]
            + 0.25 * detail["components"]["rerank_score"]
            + 0.10 * detail["components"]["recency"]
            + 0.10 * detail["components"]["type_weight"]
        )
        assert detail["final_score"] == pytest.approx(expected)
        assert [i["rank_position"] for i in ranked] == [1, 2]

    @pytest.mark.asyncio
    async def test_weight_override_changes_ordering(self, monkeypatch, processor):
        monkeypatch.setattr(rp_module, "rerank_passages", AsyncMock(return_value=[]))
        old_high_score = make_item(days_old=2000, score=0.99)
        new_low_score = make_item(text="different content", days_old=5, score=0.01)

        ranked = await processor.rank(
            [old_high_score, new_low_score],
            "query",
            weights={"search": 0.0, "rerank": 0.0, "recency": 1.0, "type": 0.0},
        )
        assert ranked[0] is new_low_score
        assert ranked[0]["ranking_detail"]["weights"]["recency"] == 1.0

    @pytest.mark.asyncio
    async def test_rerank_failure_falls_back_to_search_score(self, monkeypatch, processor):
        monkeypatch.setattr(rp_module, "rerank_passages", AsyncMock(return_value=[]))
        item = make_item(score=0.7)
        ranked = await processor.rank([item], "query")
        assert ranked[0]["ranking_detail"]["components"]["rerank_score"] == 0.7

    @pytest.mark.asyncio
    async def test_type_weight_applied(self, monkeypatch, processor):
        monkeypatch.setattr(rp_module, "rerank_passages", AsyncMock(return_value=[]))
        pdf = make_item(score=0.5, item_type="pdf")
        mail = make_item(text="other", score=0.5, item_type="eml")
        ranked = await processor.rank(
            [mail, pdf], "query",
            weights={"search": 0.0, "rerank": 0.0, "recency": 0.0, "type": 1.0},
        )
        assert ranked[0] is pdf


class TestAnnotate:
    @staticmethod
    def llm_yielding(payload):
        async def mock_generate(*args, **kwargs):
            yield payload
        return mock_generate

    @pytest.mark.asyncio
    async def test_llm_annotations_applied(self, monkeypatch, processor):
        payload = json.dumps({"annotations": [
            {"index": 0, "text": "States 2021 revenue of 4.2M, directly evidencing growth."},
            {"index": 1, "text": "Lists board members including the queried person."},
        ]})
        monkeypatch.setattr(rp_module.llm_router, "generate_completion", self.llm_yielding(payload))
        items = [make_item(), make_item(text="other text")]

        annotations = await processor.annotate(items, {"query_text": "q"}, SimpleNamespace(id=1))

        assert annotations[0]["annotation_text"].startswith("States 2021 revenue")
        assert annotations[1]["annotation_text"].startswith("Lists board members")
        assert annotations[0]["category_tags"] == ["pdf", str(datetime.now().year), "chunk"]
        assert items[0]["annotation_text"] == annotations[0]["annotation_text"]

    @pytest.mark.asyncio
    async def test_fallback_on_invalid_llm_output(self, monkeypatch, processor):
        monkeypatch.setattr(rp_module.llm_router, "generate_completion", self.llm_yielding("not json at all"))
        item = make_item(text="the matched passage about revenue")

        annotations = await processor.annotate([item], {"query_text": "q"}, SimpleNamespace(id=1))

        text = annotations[0]["annotation_text"]
        assert "the matched passage about revenue" in text
        assert "page 3" in text  # cites the matched snippet and page

    @pytest.mark.asyncio
    async def test_fallback_on_llm_exception(self, monkeypatch, processor):
        async def failing(*args, **kwargs):
            raise RuntimeError("llm down")
            yield  # pragma: no cover

        monkeypatch.setattr(rp_module.llm_router, "generate_completion", failing)
        annotations = await processor.annotate([make_item()], {"query_text": "q"}, SimpleNamespace(id=1))
        assert "Relevant excerpt" in annotations[0]["annotation_text"]

    @pytest.mark.asyncio
    async def test_batching_bounds_llm_calls(self, monkeypatch, processor):
        calls = []

        async def mock_generate(*args, **kwargs):
            calls.append(1)
            yield "garbage"  # force fallback; we only count calls here

        monkeypatch.setattr(rp_module.llm_router, "generate_completion", mock_generate)
        items = [make_item(text=f"unique text number {i} for item") for i in range(25)]

        await processor.annotate(items, {"query_text": "q"}, SimpleNamespace(id=1), batch_size=10)
        assert len(calls) == 3

    @pytest.mark.asyncio
    async def test_category_tags_deterministic(self, processor):
        item = make_item(days_old=400, item_type="PDF", source="chunk")
        item["item_date"] = datetime(2014, 5, 1, tzinfo=timezone.utc)
        tags = processor._category_tags(item)
        assert tags == ["pdf", "2014", "chunk"]

    @pytest.mark.asyncio
    async def test_confidential_flag_passed_to_llm(self, monkeypatch, processor):
        seen = {}

        async def mock_generate(*args, **kwargs):
            seen["has_confidential"] = kwargs.get("has_confidential")
            yield json.dumps({"annotations": [{"index": 0, "text": "ok evidence"}]})

        monkeypatch.setattr(rp_module.llm_router, "generate_completion", mock_generate)
        await processor.annotate([make_item(acl_stamp="confidential")], {"query_text": "q"}, SimpleNamespace(id=1))
        assert seen["has_confidential"] is True
