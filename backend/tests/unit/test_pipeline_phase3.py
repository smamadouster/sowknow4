"""QA tests for Phase 3 architectural hardening."""
import pytest


class TestEmbedTimeLimits:
    """Phase 3.3: Dynamic embed timeouts based on chunk count."""

    def test_small_document_uses_base_timeout(self):
        from app.tasks.pipeline_orchestrator import _get_embed_time_limits

        soft, hard = _get_embed_time_limits(500)
        assert hard == 1980  # 33 minutes
        assert soft == 1800  # 30 minutes

    def test_medium_document_gets_extra_time(self):
        from app.tasks.pipeline_orchestrator import _get_embed_time_limits

        soft, hard = _get_embed_time_limits(1500)
        # 1500 chunks = 1 extra bucket -> +10 min hard, +9 min soft
        assert hard == 1980 + 600
        assert soft == 1800 + 540

    def test_large_document_gets_more_time(self):
        from app.tasks.pipeline_orchestrator import _get_embed_time_limits

        soft, hard = _get_embed_time_limits(2500)
        # 2500 chunks = 2 extra buckets
        assert hard == 1980 + 1200
        assert soft == 1800 + 1080

    def test_timeout_caps_at_2_hours(self):
        from app.tasks.pipeline_orchestrator import _get_embed_time_limits

        soft, hard = _get_embed_time_limits(50_000)
        assert hard == 7200  # 2 hours cap
        assert soft == 6600  # 1h50m cap


class TestSweeperQueueMetrics:
    """Phase 3.4: Sweeper reports all queue depths."""

    def test_metrics_include_queue_depths_key(self):
        from app.tasks.pipeline_sweeper import pipeline_sweeper
        import inspect

        src = inspect.getsource(pipeline_sweeper)
        assert "queue_depths" in src
