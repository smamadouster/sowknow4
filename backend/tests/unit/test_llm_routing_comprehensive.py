"""
Unit tests for LLM Routing Logic - Complete Coverage
Tests dual-LLM routing based on confidential context detection per PRD table

NOTE: These tests are obsolete. The functions they tested
(determine_llm_provider, _should_use_ollama_for_clarification) were removed
when routing was centralized in app.services.llm_router.LLMRouter.
Current routing is tested in test_llm_router.py.
"""
import pytest
pytest.skip("Disabled during Ollama removal (Sep 4)", allow_module_level=True)

pytestmark = pytest.mark.skip(reason="Obsolete — routing moved to LLMRouter (see test_llm_router.py)")
