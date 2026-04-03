import pytest


class TestSpaceTaskExists:
    def test_sync_space_rules_task_is_importable(self):
        from app.tasks.space_tasks import sync_space_rules_task
        assert callable(sync_space_rules_task)

    def test_task_is_celery_shared_task(self):
        from app.tasks.space_tasks import sync_space_rules_task
        assert hasattr(sync_space_rules_task, "delay")
