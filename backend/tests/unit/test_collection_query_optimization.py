"""Test that collection queries use eager loading."""
import os


class TestCollectionQueryOptimization:
    """Verify selectinload is used for collection relationships."""

    def test_collection_items_query_uses_selectinload(self):
        """The collection items query must include selectinload for documents."""
        # Read the source file directly to avoid triggering the DB engine on import.
        # This is equivalent to inspect.getsource but works in environments where
        # aiosqlite or other optional dependencies are not installed.
        module_path = os.path.join(
            os.path.dirname(__file__),
            "..", "..", "app", "api", "collections.py",
        )
        module_path = os.path.abspath(module_path)
        with open(module_path) as f:
            source = f.read()

        assert "selectinload" in source or "joinedload" in source, (
            "Collection router must use selectinload or joinedload "
            "to prevent N+1 queries on item.document access"
        )
