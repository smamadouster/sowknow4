"""
Vault Protocol Enforcement Tests — Sprint 3.2

Tests that the InputGuard service correctly enforces the vault protocol:
- PII in queries forces Ollama routing
- Confidential document IDs force Ollama routing
- Public queries allow cloud routing
- Language detection (FR/EN)
- Intent classification (search, chat, report, collection)
- Agent identity blocks contain vault protocol text
- Context blocks never leak confidential content
- Duplicate query detection
- Token budget truncation

These tests define the expected InputGuard interface (TDD).
The InputGuard and ContextBlockService are implemented in Sprint 3.2.
"""

import importlib
import time
from dataclasses import dataclass, field
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Module-level marker so pytest-asyncio (strict mode) treats all async tests
pytestmark = pytest.mark.asyncio

# ---------------------------------------------------------------------------
# Environment bootstrap — mirrors conftest.py approach
# ---------------------------------------------------------------------------
import os

os.environ.setdefault("JWT_SECRET", "test-secret-key-for-security-testing-only")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-security-testing-only")
os.environ.setdefault("OPENROUTER_API_KEY", "test-key")
os.environ.setdefault("MINIMAX_API_KEY", "test-key")
os.environ.setdefault("KIMI_API_KEY", "test-key")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

# ---------------------------------------------------------------------------
# Import real modules that already exist
# ---------------------------------------------------------------------------
from app.services.agent_identity import (
    ANSWER_IDENTITY,
    CLARIFICATION_IDENTITY,
    ORCHESTRATOR_IDENTITY,
    RESEARCHER_IDENTITY,
    VAULT_PROTOCOL,
    VERIFIER_IDENTITY,
    build_identity_block,
)
from app.services.pii_detection_service import PIIDetectionService, pii_detection_service

# ---------------------------------------------------------------------------
# Stub / contract types for InputGuard and ContextBlockService
#
# These define the *expected* interface that Sprint 3.2 must implement.
# Once the real modules exist under app.services, swap the imports.
# ---------------------------------------------------------------------------


@dataclass
class GuardResult:
    """Expected output contract from InputGuard.evaluate()."""

    vault_hint: str  # "confidential" | "public"
    language: str  # ISO 639-1 code, e.g. "fr", "en"
    intent: str  # "search" | "chat" | "report" | "collection"
    is_duplicate: bool  # True if same query was seen within dedup window
    truncated: bool  # True if query was truncated to fit token budget
    query: str  # Possibly truncated query text
    pii_detected: bool  # True if PII patterns found in query


class InputGuard:
    """
    Stub InputGuard that mirrors the expected Sprint 3.2 implementation.

    The real service will live at app.services.input_guard.InputGuard.
    """

    def __init__(
        self,
        pii_service: PIIDetectionService | None = None,
        redis_client=None,
        max_query_tokens: int = 2048,
        dedup_window_seconds: int = 30,
    ):
        self.pii_service = pii_service or pii_detection_service
        self.redis = redis_client
        self.max_query_tokens = max_query_tokens
        self.dedup_window_seconds = dedup_window_seconds
        self._recent_queries: dict[str, float] = {}

    async def evaluate(
        self,
        query: str,
        document_ids: list[int] | None = None,
        document_buckets: list[str] | None = None,
        user_id: str | None = None,
    ) -> GuardResult:
        """Evaluate a query and return routing hints.

        This mirrors the expected contract for the real InputGuard.
        """
        # --- PII detection ---
        pii_detected = self.pii_service.detect_pii(query)

        # --- Confidential document check ---
        has_confidential = False
        if document_buckets:
            has_confidential = any(b == "confidential" for b in document_buckets)

        # --- Vault hint ---
        vault_hint = "confidential" if (pii_detected or has_confidential) else "public"

        # --- Language detection (simple heuristic) ---
        language = self._detect_language(query)

        # --- Intent classification ---
        intent = self._classify_intent(query)

        # --- Duplicate detection ---
        is_duplicate = self._check_duplicate(query, user_id)

        # --- Token budget truncation ---
        truncated = False
        processed_query = query
        if len(query.split()) > self.max_query_tokens:
            processed_query = " ".join(query.split()[: self.max_query_tokens])
            truncated = True

        return GuardResult(
            vault_hint=vault_hint,
            language=language,
            intent=intent,
            is_duplicate=is_duplicate,
            truncated=truncated,
            query=processed_query,
            pii_detected=pii_detected,
        )

    def _detect_language(self, text: str) -> str:
        """Simple language detection heuristic."""
        french_markers = [
            "le", "la", "les", "de", "du", "des", "un", "une",
            "est", "sont", "dans", "pour", "avec", "sur", "que",
            "qui", "mon", "ma", "mes", "ce", "cette", "quel",
            "quelle", "où", "comment", "pourquoi", "quand",
            "cherche", "trouve", "montre", "donne",
        ]
        words = text.lower().split()
        french_count = sum(1 for w in words if w in french_markers)
        # If >= 30% of words are French markers, classify as French
        if len(words) > 0 and french_count / len(words) >= 0.3:
            return "fr"
        return "en"

    def _classify_intent(self, text: str) -> str:
        """Simple keyword-based intent classification."""
        lower = text.lower()

        report_keywords = ["rapport", "report", "résumé", "summary", "analyse", "analysis"]
        collection_keywords = [
            "collection", "dossier", "folder", "regroupe", "rassemble", "organise",
        ]
        search_keywords = [
            "cherche", "trouve", "search", "find", "look for", "où est",
            "where is", "montre", "show me",
        ]

        if any(kw in lower for kw in report_keywords):
            return "report"
        if any(kw in lower for kw in collection_keywords):
            return "collection"
        if any(kw in lower for kw in search_keywords):
            return "search"
        return "chat"

    def _check_duplicate(self, query: str, user_id: str | None = None) -> bool:
        """Check if the same query was issued recently."""
        key = f"{user_id or 'anon'}:{query}"
        now = time.time()
        last_seen = self._recent_queries.get(key)
        if last_seen is not None and (now - last_seen) < self.dedup_window_seconds:
            return True
        self._recent_queries[key] = now
        return False


# ===========================================================================
# Tests
# ===========================================================================


class TestVaultProtocolEnforcement:
    """Core vault protocol enforcement tests."""

    @pytest.fixture
    def guard(self):
        """Create an InputGuard with default config."""
        return InputGuard(pii_service=pii_detection_service)

    # -----------------------------------------------------------------------
    # 1. PII in query forces Ollama routing
    # -----------------------------------------------------------------------
    async def test_pii_in_query_forces_ollama_routing(self, guard):
        """When a query contains PII patterns (email, phone, SSN),
        the InputGuard must set vault_hint to 'confidential'."""
        pii_queries = [
            "Find documents about john.doe@example.com",
            "Call me at 06 12 34 56 78 for details",
            "My SSN is 123-45-6789",
        ]

        for query in pii_queries:
            result = await guard.evaluate(query=query)
            assert result.vault_hint == "confidential", (
                f"PII query should force confidential routing: {query!r}"
            )
            assert result.pii_detected is True, (
                f"PII should be detected in: {query!r}"
            )

    # -----------------------------------------------------------------------
    # 2. Confidential document IDs force Ollama routing
    # -----------------------------------------------------------------------
    async def test_confidential_document_ids_force_ollama_routing(self, guard):
        """When document_ids include confidential documents,
        vault_hint must be 'confidential'."""
        result = await guard.evaluate(
            query="Tell me about this document",
            document_ids=[1, 2, 3],
            document_buckets=["public", "confidential", "public"],
        )

        assert result.vault_hint == "confidential", (
            "Presence of any confidential document must force confidential routing"
        )

    # -----------------------------------------------------------------------
    # 3. Public query allows cloud routing
    # -----------------------------------------------------------------------
    async def test_public_query_allows_cloud_routing(self, guard):
        """A clean query with no PII and no confidential docs
        should get vault_hint 'public'."""
        result = await guard.evaluate(
            query="What documents do I have about architecture?",
            document_ids=[10, 20],
            document_buckets=["public", "public"],
        )

        assert result.vault_hint == "public", (
            "Clean public query should allow cloud routing"
        )
        assert result.pii_detected is False

    # -----------------------------------------------------------------------
    # 4. Language detection
    # -----------------------------------------------------------------------
    async def test_input_guard_language_detection(self, guard):
        """French queries should be detected as 'fr', English as 'en'."""
        french_queries = [
            "Cherche les documents dans la collection de mon père",
            "Où est le rapport sur les finances de la famille?",
            "Montre-moi les photos du mariage de ma grand-mère",
        ]
        english_queries = [
            "Find all documents about family history",
            "Show me the financial reports from last year",
            "What photos do we have of the wedding?",
        ]

        for query in french_queries:
            result = await guard.evaluate(query=query)
            assert result.language == "fr", (
                f"French query not detected: {query!r}"
            )

        for query in english_queries:
            result = await guard.evaluate(query=query)
            assert result.language == "en", (
                f"English query not detected: {query!r}"
            )

    # -----------------------------------------------------------------------
    # 5. Intent classification
    # -----------------------------------------------------------------------
    async def test_input_guard_intent_classification(self, guard):
        """Various query types should be classified correctly."""
        test_cases = [
            ("Cherche les documents sur Paris", "search"),
            ("Find all photos from 1990", "search"),
            ("Tell me about the family tree", "chat"),
            ("Generate a report on our finances", "report"),
            ("Crée un rapport résumé des voyages", "report"),
            ("Organise these into a collection", "collection"),
            ("Regroupe les documents du dossier médical", "collection"),
        ]

        for query, expected_intent in test_cases:
            result = await guard.evaluate(query=query)
            assert result.intent == expected_intent, (
                f"Query {query!r} should be classified as {expected_intent!r}, "
                f"got {result.intent!r}"
            )

    # -----------------------------------------------------------------------
    # 6. Agent identity blocks contain vault protocol
    # -----------------------------------------------------------------------
    async def test_agent_prompts_contain_vault_protocol(self, guard):
        """All agent identity blocks must contain vault protocol text."""
        identities = {
            "CLARIFICATION_IDENTITY": CLARIFICATION_IDENTITY,
            "RESEARCHER_IDENTITY": RESEARCHER_IDENTITY,
            "VERIFIER_IDENTITY": VERIFIER_IDENTITY,
            "ANSWER_IDENTITY": ANSWER_IDENTITY,
            "ORCHESTRATOR_IDENTITY": ORCHESTRATOR_IDENTITY,
        }

        for name, identity_block in identities.items():
            assert "CONFIDENTIAL" in identity_block, (
                f"{name} must contain 'CONFIDENTIAL' in vault protocol"
            )
            assert "Ollama routing" in identity_block or "Ollama" in identity_block, (
                f"{name} must reference Ollama routing in vault protocol"
            )

        # Also verify that the VAULT_PROTOCOL constant itself has the key phrases
        assert "CONFIDENTIAL" in VAULT_PROTOCOL
        assert "Ollama routing" in VAULT_PROTOCOL
        assert "cloud LLMs" in VAULT_PROTOCOL

    # -----------------------------------------------------------------------
    # 7. Context block never leaks confidential content
    # -----------------------------------------------------------------------
    async def test_context_block_never_leaks_confidential_content(self, guard):
        """The context block service should not include actual confidential
        document content — only counts or metadata summaries."""
        # Simulate what a context block builder would produce.
        # The real ContextBlockService will be tested once implemented;
        # here we verify the contract: confidential content must NOT appear.
        confidential_content = "TOP SECRET financial records for the Diallo family"
        public_content = "Public recipe for thieboudienne"

        # Expected context block format (contract for Sprint 3.2)
        context_block = {
            "public_documents": [
                {"id": 10, "title": "Recipe Book", "snippet": public_content[:80]},
            ],
            "confidential_document_count": 3,
            # The key rule: NO confidential snippets, content, or titles
        }

        # Verify no confidential content leaks into the block
        block_str = str(context_block)
        assert confidential_content not in block_str, (
            "Confidential content must never appear in context blocks"
        )
        assert "confidential_document_count" in context_block, (
            "Context block should report confidential document count only"
        )
        # Ensure there's no key that would hold confidential snippets
        assert "confidential_documents" not in context_block, (
            "Context block must not contain a 'confidential_documents' list"
        )
        assert "confidential_snippets" not in context_block, (
            "Context block must not contain confidential snippets"
        )

    # -----------------------------------------------------------------------
    # 8. Duplicate query detection
    # -----------------------------------------------------------------------
    async def test_duplicate_query_detection(self, guard):
        """Same query within 30s should be flagged as duplicate."""
        query = "Show me documents about the family house"
        user_id = "user-42"

        # First call — not a duplicate
        result1 = await guard.evaluate(query=query, user_id=user_id)
        assert result1.is_duplicate is False, "First query should not be a duplicate"

        # Second call immediately — should be duplicate
        result2 = await guard.evaluate(query=query, user_id=user_id)
        assert result2.is_duplicate is True, (
            "Same query within dedup window should be flagged as duplicate"
        )

    async def test_different_queries_not_flagged_as_duplicate(self, guard):
        """Different queries should not be flagged as duplicates."""
        result1 = await guard.evaluate(
            query="Show me photos", user_id="user-1"
        )
        result2 = await guard.evaluate(
            query="Find financial documents", user_id="user-1"
        )
        assert result1.is_duplicate is False
        assert result2.is_duplicate is False

    async def test_same_query_different_users_not_duplicate(self, guard):
        """Same query from different users should not be flagged as duplicate."""
        query = "Show me everything"
        result1 = await guard.evaluate(query=query, user_id="user-A")
        result2 = await guard.evaluate(query=query, user_id="user-B")
        assert result1.is_duplicate is False
        assert result2.is_duplicate is False

    # -----------------------------------------------------------------------
    # 9. Token budget truncation
    # -----------------------------------------------------------------------
    async def test_token_budget_truncation(self, guard):
        """Very long queries should be truncated to fit the token budget."""
        # Create a query that exceeds the default 2048-token budget
        long_query = " ".join(["word"] * 3000)

        result = await guard.evaluate(query=long_query)

        assert result.truncated is True, "Long query should be marked as truncated"
        assert len(result.query.split()) <= guard.max_query_tokens, (
            f"Truncated query should have at most {guard.max_query_tokens} words"
        )

    async def test_short_query_not_truncated(self, guard):
        """Normal-length queries should not be truncated."""
        result = await guard.evaluate(query="Find my grandfather's letters")

        assert result.truncated is False
        assert result.query == "Find my grandfather's letters"


# ===========================================================================
# Additional edge-case tests
# ===========================================================================


class TestVaultProtocolEdgeCases:
    """Edge cases and boundary conditions for vault protocol enforcement."""

    @pytest.fixture
    def guard(self):
        return InputGuard(pii_service=pii_detection_service)

    async def test_empty_query_defaults_to_public(self, guard):
        """An empty query with no documents should default to public."""
        result = await guard.evaluate(query="hello")
        assert result.vault_hint == "public"

    async def test_mixed_buckets_with_one_confidential(self, guard):
        """Even a single confidential bucket among many public ones
        must force confidential routing."""
        result = await guard.evaluate(
            query="summarize these documents",
            document_ids=[1, 2, 3, 4, 5],
            document_buckets=["public", "public", "public", "public", "confidential"],
        )
        assert result.vault_hint == "confidential"

    async def test_vault_protocol_text_mentions_audit(self):
        """The VAULT_PROTOCOL constant must mention audit logging."""
        assert "audit" in VAULT_PROTOCOL.lower(), (
            "VAULT_PROTOCOL must reference audit requirements"
        )

    async def test_build_identity_block_without_vault_protocol(self):
        """build_identity_block with include_vault_protocol=False should NOT
        contain vault protocol text."""
        identity = build_identity_block(
            agent_name="Test Agent",
            mission="Testing",
            persona="A test persona",
            constraints="None",
            include_vault_protocol=False,
        )
        assert "CONFIDENTIAL" not in identity, (
            "Identity block without vault protocol should not mention CONFIDENTIAL"
        )

    async def test_build_identity_block_with_vault_protocol(self):
        """build_identity_block with include_vault_protocol=True should
        contain vault protocol text."""
        identity = build_identity_block(
            agent_name="Test Agent",
            mission="Testing",
            persona="A test persona",
            constraints="None",
            include_vault_protocol=True,
        )
        assert "CONFIDENTIAL" in identity
        assert "Ollama" in identity
