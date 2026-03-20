"""
SOWKNOW Agentic Search — Test Suite
Run: pytest backend/tests/test_search_agent.py -v
"""

import pytest
from app.services.search_models import (
    AgenticSearchRequest,
    SearchMode,
)


class TestSearchRequestValidation:
    def test_empty_query_rejected(self):
        with pytest.raises(Exception):
            AgenticSearchRequest(query="")

    def test_whitespace_query_stripped(self):
        req = AgenticSearchRequest(query="  bilan financier  ")
        assert req.query == "bilan financier"

    def test_default_mode_is_auto(self):
        req = AgenticSearchRequest(query="test")
        assert req.mode == SearchMode.AUTO

    def test_top_k_default(self):
        req = AgenticSearchRequest(query="test")
        assert req.top_k == 10

    def test_top_k_max_enforced(self):
        with pytest.raises(Exception):
            AgenticSearchRequest(query="test", top_k=51)
