"""Tests for pipeline orchestrator — dispatch and backpressure."""
import uuid
from unittest.mock import MagicMock, patch


class TestDispatchDocument:
    @patch("app.tasks.pipeline_orchestrator.redis_client")
    @patch("app.tasks.pipeline_orchestrator.chain")
    def test_dispatches_chain_when_queues_have_capacity(self, mock_chain, mock_redis):
        from app.tasks.pipeline_orchestrator import dispatch_document
        mock_redis.llen.return_value = 5
        mock_pipeline = MagicMock()
        mock_chain.return_value = mock_pipeline
        doc_id = str(uuid.uuid4())
        result = dispatch_document(doc_id)
        assert result == "dispatched"
        mock_pipeline.apply_async.assert_called_once()

    @patch("app.tasks.pipeline_orchestrator.redis_client")
    def test_returns_backpressure_when_embed_queue_full(self, mock_redis):
        from app.models.pipeline import StageEnum
        from app.tasks.pipeline_orchestrator import dispatch_document

        def llen_side_effect(queue_name):
            # Only embed is over limit; keep global total under 1000
            return {
                "pipeline.embed": 301,
                "pipeline.ocr": 10,
                "pipeline.chunk": 10,
                "pipeline.index": 10,
                "pipeline.articles": 10,
                "pipeline.entities": 10,
            }.get(queue_name, 0)

        mock_redis.llen.side_effect = llen_side_effect
        result = dispatch_document(str(uuid.uuid4()), from_stage=StageEnum.EMBEDDED)
        assert result == "backpressure:pipeline.embed"

    @patch("app.tasks.pipeline_orchestrator.redis_client")
    def test_returns_backpressure_when_ocr_queue_full(self, mock_redis):
        from app.tasks.pipeline_orchestrator import dispatch_document

        def llen_side_effect(queue_name):
            # Only OCR is over limit; keep global total under 1000
            return {
                "pipeline.embed": 10,
                "pipeline.ocr": 501,
                "pipeline.chunk": 10,
                "pipeline.index": 10,
                "pipeline.articles": 10,
                "pipeline.entities": 10,
            }.get(queue_name, 0)

        mock_redis.llen.side_effect = llen_side_effect
        result = dispatch_document(str(uuid.uuid4()))
        assert result == "backpressure:pipeline.ocr"


class TestDispatchBatch:
    @patch("app.tasks.pipeline_orchestrator.dispatch_document")
    def test_stops_on_backpressure(self, mock_dispatch):
        from app.tasks.pipeline_orchestrator import dispatch_batch
        mock_dispatch.side_effect = ["dispatched", "dispatched", "backpressure:pipeline.embed", "dispatched"]
        ids = [str(uuid.uuid4()) for _ in range(4)]
        result = dispatch_batch(ids)
        assert result["dispatched"] == 2
        assert result["backpressured"] == 2
        assert mock_dispatch.call_count == 3

    @patch("app.tasks.pipeline_orchestrator.dispatch_document")
    def test_dispatches_all_when_no_backpressure(self, mock_dispatch):
        from app.tasks.pipeline_orchestrator import dispatch_batch
        mock_dispatch.return_value = "dispatched"
        ids = [str(uuid.uuid4()) for _ in range(3)]
        result = dispatch_batch(ids)
        assert result["dispatched"] == 3
        assert result["backpressured"] == 0
