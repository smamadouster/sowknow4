"""Tests for Smart Collections v2 pipeline."""


class TestCollectionQueueRouting:
    """build_smart_collection must be routed to the collections queue."""

    def test_task_routed_to_collections_queue(self):
        from app.celery_app import celery_app

        routes = celery_app.conf.task_routes
        assert "build_smart_collection" in routes
        assert routes["build_smart_collection"]["queue"] == "collections"
