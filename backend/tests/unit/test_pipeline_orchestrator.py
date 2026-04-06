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
        from app.tasks.pipeline_orchestrator import dispatch_document
        mock_redis.llen.return_value = 25
        result = dispatch_document(str(uuid.uuid4()))
        assert result == "backpressure:pipeline.embed"

    @patch("app.tasks.pipeline_orchestrator.redis_client")
    def test_returns_backpressure_when_ocr_queue_full(self, mock_redis):
        from app.tasks.pipeline_orchestrator import dispatch_document
        def llen_side_effect(key):
            if key == "pipeline.embed":
                return 5
            if key == "pipeline.ocr":
                return 45
            return 0
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
