"""
Unit tests for service routing gaps.

NOTE: These tests are obsolete. The service attributes they tested
(minimax_service, _get_openrouter_service) were removed during the
LLM routing refactor. Current routing is tested in test_llm_router.py.
"""
import pytest
pytest.skip("Disabled during Ollama removal (Sep 4)", allow_module_level=True)

pytestmark = pytest.mark.skip(reason="Obsolete — service routing moved to LLMRouter (see test_llm_router.py)")
