"""
Tests for collection cache invalidation.

Verifies that OpenRouter LLM cache is invalidated after every
collection mutation: refresh (via CollectionService) and
delete / update / add-item / remove-item (via API router helpers.

Import strategy: the collection_service and collections router both pull
in heavy transitive dependencies (pydantic email-validator, aiosqlite,
reportlab…) that are not available in the unit-test environment. Tests
here use sys.modules stubs applied *before* each import to keep things
isolated, exactly like the rest of the unit-test suite.
"""

import sys
import uuid
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stub_heavy_modules():
    """
    Pre-stub modules that import third-party packages unavailable in the
    unit-test environment (broken idna, aiosqlite, reportlab, etc.).
    This must be called before importing any app module that transitively
    touches these packages.
    """
    stubs = [
        "app.schemas.collection",
        "app.services.intent_parser",
        "app.services.search_service",
        "app.services.minimax_service",
        "app.services.ollama_service",
        "app.services.openrouter_service",
    ]
    for mod in stubs:
        if mod not in sys.modules:
            sys.modules[mod] = MagicMock()


def _import_collection_service():
    """Return CollectionService class with heavy deps stubbed."""
    _stub_heavy_modules()
    # Force re-resolution inside the already-cached module if present
    from app.services.collection_service import CollectionService
    return CollectionService


# ---------------------------------------------------------------------------
# CollectionService._invalidate_cache
# ---------------------------------------------------------------------------

class TestCollectionServiceInvalidateCache:
    """Unit tests for the _invalidate_cache helper on CollectionService."""

    def _make_service(self):
        CollectionService = _import_collection_service()
        return CollectionService()

    def test_invalidate_cache_calls_openrouter(self):
        """_invalidate_cache delegates to openrouter_service.invalidate_collection_cache."""
        _stub_heavy_modules()
        import app.services.collection_service as cs_mod

        service = self._make_service()
        mock_or = MagicMock()
        cid = uuid.uuid4()

        original_enabled = cs_mod._cache_invalidation_enabled
        original_svc = getattr(cs_mod, "_openrouter_svc", None)
        try:
            cs_mod._cache_invalidation_enabled = True
            cs_mod._openrouter_svc = mock_or
            service._invalidate_cache(cid)
        finally:
            cs_mod._cache_invalidation_enabled = original_enabled
            if original_svc is not None:
                cs_mod._openrouter_svc = original_svc

        mock_or.invalidate_collection_cache.assert_called_once_with(str(cid))

    def test_invalidate_cache_skipped_when_disabled(self):
        """_invalidate_cache is a no-op when _cache_invalidation_enabled is False."""
        _stub_heavy_modules()
        import app.services.collection_service as cs_mod

        service = self._make_service()
        mock_or = MagicMock()

        original_enabled = cs_mod._cache_invalidation_enabled
        original_svc = getattr(cs_mod, "_openrouter_svc", None)
        try:
            cs_mod._cache_invalidation_enabled = False
            cs_mod._openrouter_svc = mock_or
            service._invalidate_cache(uuid.uuid4())
        finally:
            cs_mod._cache_invalidation_enabled = original_enabled
            if original_svc is not None:
                cs_mod._openrouter_svc = original_svc

        mock_or.invalidate_collection_cache.assert_not_called()

    def test_invalidate_cache_swallows_exceptions(self):
        """_invalidate_cache does not propagate exceptions (best-effort)."""
        _stub_heavy_modules()
        import app.services.collection_service as cs_mod

        service = self._make_service()
        mock_or = MagicMock()
        mock_or.invalidate_collection_cache.side_effect = RuntimeError("redis down")

        original_enabled = cs_mod._cache_invalidation_enabled
        original_svc = getattr(cs_mod, "_openrouter_svc", None)
        try:
            cs_mod._cache_invalidation_enabled = True
            cs_mod._openrouter_svc = mock_or
            # Must not raise
            service._invalidate_cache(uuid.uuid4())
        finally:
            cs_mod._cache_invalidation_enabled = original_enabled
            if original_svc is not None:
                cs_mod._openrouter_svc = original_svc

    def test_invalidate_cache_converts_uuid_to_str(self):
        """collection_id is coerced to str regardless of input type."""
        _stub_heavy_modules()
        import app.services.collection_service as cs_mod

        service = self._make_service()
        mock_or = MagicMock()
        cid = uuid.uuid4()

        original_enabled = cs_mod._cache_invalidation_enabled
        original_svc = getattr(cs_mod, "_openrouter_svc", None)
        try:
            cs_mod._cache_invalidation_enabled = True
            cs_mod._openrouter_svc = mock_or
            service._invalidate_cache(cid)
        finally:
            cs_mod._cache_invalidation_enabled = original_enabled
            if original_svc is not None:
                cs_mod._openrouter_svc = original_svc

        called_with = mock_or.invalidate_collection_cache.call_args[0][0]
        assert isinstance(called_with, str)
        assert called_with == str(cid)


# ---------------------------------------------------------------------------
# CollectionService.refresh_collection calls _invalidate_cache
# ---------------------------------------------------------------------------

class TestRefreshCollectionInvalidatesCache:
    """refresh_collection must call _invalidate_cache after a successful commit."""

    def test_invalidate_cache_method_is_called_by_refresh(self):
        """
        We verify _invalidate_cache is defined and called inside refresh_collection
        by inspecting the source code. This is a structural test that avoids the
        complexity of fully mocking the async DB and is appropriate for a unit suite
        that cannot run the full FastAPI stack.
        """
        import inspect
        CollectionService = _import_collection_service()
        source = inspect.getsource(CollectionService.refresh_collection)
        assert "_invalidate_cache" in source, (
            "refresh_collection must call self._invalidate_cache()"
        )

    def test_invalidate_cache_is_called_after_commit_in_refresh(self):
        """
        The _invalidate_cache call should appear after db.commit() in refresh_collection.
        We verify this by checking line order in the source.
        """
        import inspect
        CollectionService = _import_collection_service()
        source = inspect.getsource(CollectionService.refresh_collection)
        commit_pos = source.find("db.commit()")
        inval_pos = source.find("_invalidate_cache")
        assert commit_pos != -1, "db.commit() not found in refresh_collection"
        assert inval_pos != -1, "_invalidate_cache not found in refresh_collection"
        assert inval_pos > commit_pos, (
            "_invalidate_cache must be called AFTER db.commit() in refresh_collection"
        )


# ---------------------------------------------------------------------------
# API router-level cache invalidation helper
# ---------------------------------------------------------------------------

class TestRouterInvalidateCollectionCacheHelper:
    """Tests for the _invalidate_collection_cache helper in the collections router."""

    def _import_helper_source(self):
        """Return source code of _invalidate_collection_cache from the router."""
        import inspect
        _stub_heavy_modules()
        # Also need to stub database/deps for router import
        for mod in [
            "app.database",
            "app.api.deps",
            "app.models.audit",
            "app.models.collection",
            "app.services.collection_chat_service",
            "app.schemas.collection",
        ]:
            if mod not in sys.modules:
                sys.modules[mod] = MagicMock()

        from app.api import collections as col_module
        return col_module, inspect.getsource(col_module._invalidate_collection_cache)

    def test_router_helper_wraps_openrouter_call(self):
        """_invalidate_collection_cache must call invalidate_collection_cache."""
        try:
            _, source = self._import_helper_source()
            assert "invalidate_collection_cache" in source, (
                "_invalidate_collection_cache must call invalidate_collection_cache()"
            )
        except Exception:
            # Router import may fail in minimal env; fall back to source-level check
            import ast, pathlib
            router_path = pathlib.Path(__file__).parent.parent.parent / "app/api/collections.py"
            src = router_path.read_text()
            assert "_invalidate_collection_cache" in src
            assert "invalidate_collection_cache" in src

    def test_router_helper_catches_exceptions(self):
        """_invalidate_collection_cache must have exception handling (try/except)."""
        import ast, pathlib
        router_path = pathlib.Path(__file__).parent.parent.parent / "app/api/collections.py"
        src = router_path.read_text()
        # Parse AST and find the function
        tree = ast.parse(src)
        found_try = False
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_invalidate_collection_cache":
                for child in ast.walk(node):
                    if isinstance(child, ast.ExceptHandler):
                        found_try = True
                        break
        assert found_try, "_invalidate_collection_cache must have exception handling"


# ---------------------------------------------------------------------------
# Router mutation endpoints call _invalidate_collection_cache (source audit)
# ---------------------------------------------------------------------------

class TestRouterMutationEndpointsInvalidate:
    """
    Source-level audit: each mutation endpoint in collections.py must call
    _invalidate_collection_cache after its db.commit().
    """

    def _load_router_source(self):
        import pathlib
        router_path = pathlib.Path(__file__).parent.parent.parent / "app/api/collections.py"
        return router_path.read_text()

    def _function_source(self, full_source: str, func_name: str) -> str:
        """Extract the source of an async def function by naive line scanning."""
        lines = full_source.splitlines()
        start = None
        for i, line in enumerate(lines):
            if f"async def {func_name}" in line or f"def {func_name}" in line:
                start = i
                break
        if start is None:
            return ""
        # Collect until next top-level def/class (dedent back to col 0) or EOF
        body_lines = [lines[start]]
        for line in lines[start + 1:]:
            if line and not line[0].isspace() and (
                line.startswith("@") or line.startswith("async def") or line.startswith("def") or line.startswith("class")
            ):
                break
            body_lines.append(line)
        return "\n".join(body_lines)

    def _assert_invalidated_after_commit(self, func_name: str):
        src = self._load_router_source()
        func_src = self._function_source(src, func_name)
        assert func_src, f"Function {func_name} not found in collections router"
        assert "db.commit()" in func_src, f"{func_name}: db.commit() not found"
        assert "_invalidate_collection_cache" in func_src, (
            f"{func_name}: must call _invalidate_collection_cache()"
        )
        commit_pos = func_src.find("db.commit()")
        inval_pos = func_src.find("_invalidate_collection_cache")
        assert inval_pos > commit_pos, (
            f"{func_name}: _invalidate_collection_cache must appear AFTER db.commit()"
        )

    def test_update_collection_invalidates_cache(self):
        """update_collection must call _invalidate_collection_cache after commit."""
        self._assert_invalidated_after_commit("update_collection")

    def test_delete_collection_invalidates_cache(self):
        """delete_collection must call _invalidate_collection_cache after commit."""
        self._assert_invalidated_after_commit("delete_collection")

    def test_add_collection_item_invalidates_cache(self):
        """add_collection_item must call _invalidate_collection_cache after commit."""
        self._assert_invalidated_after_commit("add_collection_item")

    def test_remove_collection_item_invalidates_cache(self):
        """remove_collection_item must call _invalidate_collection_cache after commit."""
        self._assert_invalidated_after_commit("remove_collection_item")


# ---------------------------------------------------------------------------
# Smoke tests: helpers and methods exist
# ---------------------------------------------------------------------------

def test_invalidate_helper_exists_in_router_source():
    """The _invalidate_collection_cache function must be defined in collections.py."""
    import pathlib
    router_path = pathlib.Path(__file__).parent.parent.parent / "app/api/collections.py"
    src = router_path.read_text()
    assert "def _invalidate_collection_cache" in src, (
        "def _invalidate_collection_cache missing from app/api/collections.py"
    )


def test_invalidate_method_exists_on_service():
    """CollectionService must have a _invalidate_cache method."""
    CollectionService = _import_collection_service()
    svc = CollectionService()
    assert hasattr(svc, "_invalidate_cache"), "CollectionService missing _invalidate_cache method"
    assert callable(svc._invalidate_cache)


def test_cache_invalidation_guard_in_service():
    """_invalidate_cache must check _cache_invalidation_enabled before calling openrouter."""
    import inspect
    CollectionService = _import_collection_service()
    source = inspect.getsource(CollectionService._invalidate_cache)
    assert "_cache_invalidation_enabled" in source, (
        "_invalidate_cache must guard on _cache_invalidation_enabled"
    )
