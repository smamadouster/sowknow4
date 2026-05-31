"""
Unit tests for LLMGateway — Admin total priority bypasses module-level concurrency caps.
"""
import asyncio
from collections.abc import AsyncGenerator

import pytest

from unittest.mock import MagicMock

from app.services.llm_gateway import LLMGateway, _MODULE_SEMAPHORES
from app.services.llm_router import LLMRouter, TaskTier


@pytest.fixture(autouse=True)
def mock_cost_budget(monkeypatch):
    """Prevent gateway tests from hitting real Redis via the global cost budget."""
    fake_budget = MagicMock()
    fake_budget.check_and_consume = MagicMock(return_value={"allowed": True})
    # Patch the source module because llm_gateway does lazy imports inside
    # the async generator.
    monkeypatch.setattr(
        "app.services.monitoring.get_per_user_cost_budget",
        lambda: fake_budget,
    )


class FakeRouter:
    """Minimal async generator stand-in for LLMRouter."""

    _openrouter = None

    async def generate_completion(self, **kwargs) -> AsyncGenerator[str, None]:
        yield "hello"
        yield " world"


@pytest.fixture(autouse=True)
def reset_semaphores():
    """Restore semaphore defaults after each test so tests don't leak state."""
    original = {
        k: (v._value if hasattr(v, "_value") else v._bound_value)
        for k, v in _MODULE_SEMAPHORES.items()
    }
    yield
    for k, v in _MODULE_SEMAPHORES.items():
        # Reset semaphore to original capacity
        while v.locked():
            try:
                v.release()
            except ValueError:
                break
        # Re-create with original value (simplest way)
        _MODULE_SEMAPHORES[k] = asyncio.Semaphore(original[k])


class TestAdminBypassesSemaphores:
    """Admin must never wait behind module-level concurrency caps."""

    @pytest.mark.asyncio
    async def test_admin_bypasses_zero_capacity_semaphore(self):
        """
        If a module semaphore is exhausted (value=0), an Admin request must
        still flow through immediately.
        """
        # Exhaust the chat semaphore so no regular user can enter
        _MODULE_SEMAPHORES["chat"] = asyncio.Semaphore(0)

        gateway = LLMGateway(router=FakeRouter())
        chunks = []
        async for chunk in gateway.chat_completion(
            messages=[{"role": "user", "content": "hi"}],
            module="chat",
            user_id="admin-1",
            user_role="admin",
            stream=True,
        ):
            chunks.append(chunk)

        assert chunks == ["hello", " world"]

    @pytest.mark.asyncio
    async def test_non_admin_blocked_by_zero_capacity_semaphore(self):
        """
        A regular user must block when the module semaphore is exhausted.
        """
        _MODULE_SEMAPHORES["chat"] = asyncio.Semaphore(0)

        gateway = LLMGateway(router=FakeRouter())

        async def collect_chunks():
            chunks = []
            async for chunk in gateway.chat_completion(
                messages=[{"role": "user", "content": "hi"}],
                module="chat",
                user_id="user-1",
                user_role="user",
                stream=True,
            ):
                chunks.append(chunk)
            return chunks

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(collect_chunks(), timeout=0.1)

    @pytest.mark.asyncio
    async def test_admin_bypasses_non_streaming_semaphore(self):
        """Admin bypass applies to non-streaming paths too."""
        _MODULE_SEMAPHORES["collections"] = asyncio.Semaphore(0)

        gateway = LLMGateway(router=FakeRouter())
        chunks = []
        async for chunk in gateway.chat_completion(
            messages=[{"role": "user", "content": "report"}],
            module="collections",
            user_id="admin-1",
            user_role="admin",
            stream=False,
        ):
            chunks.append(chunk)

        assert chunks == ["hello", " world"]

    @pytest.mark.asyncio
    async def test_no_module_no_semaphore_for_anyone(self):
        """When module is None, no semaphore is applied regardless of role."""
        gateway = LLMGateway(router=FakeRouter())
        chunks = []
        async for chunk in gateway.chat_completion(
            messages=[{"role": "user", "content": "hi"}],
            module=None,
            user_id="user-1",
            user_role="user",
            stream=True,
        ):
            chunks.append(chunk)

        assert chunks == ["hello", " world"]

    @pytest.mark.asyncio
    async def test_all_modules_have_semaphore_defined(self):
        """Every known module from the blueprint has a semaphore entry."""
        expected_modules = {"chat", "collections", "smart_folders", "knowledge_graph"}
        assert set(_MODULE_SEMAPHORES.keys()) == expected_modules

    @pytest.mark.asyncio
    async def test_semaphore_capacities_match_blueprint(self):
        """Semaphore values match the Tier B table in the blueprint."""
        assert _MODULE_SEMAPHORES["chat"]._value == 10
        assert _MODULE_SEMAPHORES["collections"]._value == 2
        assert _MODULE_SEMAPHORES["smart_folders"]._value == 3
        assert _MODULE_SEMAPHORES["knowledge_graph"]._value == 2
