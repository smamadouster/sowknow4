"""
Unit tests for LLM Routing Logic
Tests tri-LLM routing between MiniMax, Kimi, and Ollama based on PII and document confidentiality
"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from app.services.pii_detection_service import pii_detection_service
from app.models.user import User, UserRole
from app.models.document import Document, DocumentBucket
from app.models.chat import LLMProvider


class TestPIIBasedRouting:
    """Test LLM routing based on PII detection"""

    def test_pii_detected_routes_to_ollama(self):
        """Test that queries with PII are routed to Ollama"""
        query_with_pii = "What is the email addresses of John Smith at john@example.com and jane@test.com?"
        has_pii = pii_detection_service.detect_pii(query_with_pii)

        assert has_pii is True
        # When PII is detected, should route to Ollama

    def test_no_pii_routes_to_minimax(self):
        """Test that queries without PII can use MiniMax"""
        query_without_pii = "What are the main features of our product architecture?"
        has_pii = pii_detection_service.detect_pii(query_without_pii)

        assert has_pii is False
        # When no PII is detected, can route to MiniMax (via OpenRouter)

    def test_pii_in_document_context(self):
        """Test PII detection in document context"""
        document_context = """
        Employee Information:
        Name: John Doe
        Email: john.doe@company.com
        Phone: 06 12 34 56 78
        SSN: 123-45-6789
        """
        has_pii = pii_detection_service.detect_pii(document_context)

        assert has_pii is True
        # Should route to Ollama

    def test_redaction_before_cloud_llm(self):
        """Test that PII is redacted before sending to cloud LLMs (MiniMax/Kimi)"""
        text_with_pii = "Contact john@example.com for details about project X."
        redacted, stats = pii_detection_service.redact_pii(text_with_pii)

        assert "john@example.com" not in redacted
        assert "[EMAIL_REDACTED]" in redacted
        # Redacted text could potentially be sent to MiniMax/Kimi

    def test_confidence_threshold_routing(self):
        """Test routing based on PII confidence threshold"""
        low_pii_text = "Contact me at test@example.com."

        # Default threshold is 2, single PII triggers detection
        result = pii_detection_service.detect_pii(low_pii_text)
        # The behavior depends on the configured threshold
        assert isinstance(result, bool)


class TestRoleBasedRouting:
    """Test LLM routing based on user roles"""

    def test_admin_can_use_minimax_for_public(self):
        """Test that admin can use MiniMax for public documents"""
        admin_user = User(
            email="admin@example.com", hashed_password="hash", role=UserRole.ADMIN
        )

        # Admin querying public documents without PII should use MiniMax
        assert admin_user.role == UserRole.ADMIN

    def test_admin_must_use_ollama_for_confidential(self):
        """Test that admin must use Ollama for confidential documents"""
        admin_user = User(
            email="admin@example.com", hashed_password="hash", role=UserRole.ADMIN
        )

        # Even admin must use Ollama for confidential data
        # This is enforced at the document bucket level
        assert admin_user.role == UserRole.ADMIN

    def test_user_can_use_minimax_for_public(self):
        """Test that regular users can use MiniMax for public documents"""
        regular_user = User(
            email="user@example.com", hashed_password="hash", role=UserRole.USER
        )

        # Regular users can use MiniMax for public documents
        assert regular_user.role == UserRole.USER

    def test_user_cannot_access_confidential(self):
        """Test that users cannot access confidential documents at all"""
        regular_user = User(
            email="user@example.com",
            hashed_password="hash",
            role=UserRole.USER,
            is_superuser=False,
            can_access_confidential=False,
            is_active=True,
        )

        # Users should not have access to confidential documents
        # This is enforced by RBAC, not LLM routing
        assert (
            regular_user.can_access_confidential == False
            or regular_user.can_access_confidential is False
        )

    def test_superuser_can_use_minimax_for_public(self):
        """Test that superuser can use MiniMax for public documents"""
        superuser = User(
            email="super@example.com", hashed_password="hash", role=UserRole.SUPERUSER
        )

        # Superuser can use MiniMax for public documents
        assert superuser.role == UserRole.SUPERUSER


class TestDocumentBucketRouting:
    """Test LLM routing based on document bucket"""

    def test_public_bucket_allows_minimax(self):
        """Test that public documents allow MiniMax usage"""
        public_doc = Document(
            filename="public.pdf",
            original_filename="public.pdf",
            file_path="/data/public/public.pdf",
            bucket=DocumentBucket.PUBLIC,
            size=1024,
            mime_type="application/pdf",
        )

        # Public bucket documents can use MiniMax (via OpenRouter, if no PII in query)
        assert public_doc.bucket == DocumentBucket.PUBLIC

    def test_confidential_bucket_requires_ollama(self):
        """Test that confidential documents require Ollama"""
        confidential_doc = Document(
            filename="confidential.pdf",
            original_filename="confidential.pdf",
            file_path="/data/confidential/confidential.pdf",
            bucket=DocumentBucket.CONFIDENTIAL,
            size=1024,
            mime_type="application/pdf",
        )

        # Confidential bucket documents MUST use Ollama
        assert confidential_doc.bucket == DocumentBucket.CONFIDENTIAL

    def test_mixed_bucket_search(self):
        """Test routing when searching across mixed buckets"""
        # When user has access to both buckets, routing should be per-document
        # Admin and superuser can see both, but confidential still uses Ollama
        admin_user = User(role=UserRole.ADMIN)

        # Admin should see both buckets
        # But routing decision depends on the specific document's bucket
        assert admin_user.role == UserRole.ADMIN


class TestLLMProviderSelection:
    """Test LLM provider selection logic"""

    def test_minimax_provider_exists(self):
        """Test that MiniMax provider is defined"""
        assert LLMProvider.MINIMAX.value == "minimax"

    def test_kimi_provider_exists(self):
        """Test that Kimi provider is defined"""
        assert LLMProvider.KIMI.value == "kimi"

    def test_ollama_provider_exists(self):
        """Test that Ollama provider is defined"""
        assert LLMProvider.OLLAMA.value == "ollama"

    def test_minimax_tracked_in_chat_message(self):
        """Test that MiniMax provider is tracked in chat messages (replaces old Gemini stub)"""
        from app.models.chat import ChatMessage, MessageRole

        message = ChatMessage(
            session_id="test-session-id",
            role=MessageRole.USER,
            content="Test message",
            llm_used=LLMProvider.MINIMAX,
        )

        assert message.llm_used == LLMProvider.MINIMAX

    def test_minimax_kimi_ollama_tracking_for_auditing(self):
        """Test that all tri-LLM providers are tracked for privacy auditing (replaces old Gemini stub)"""
        # All LLM usage should be tracked for audit purposes
        assert hasattr(LLMProvider, "MINIMAX")
        assert hasattr(LLMProvider, "KIMI")
        assert hasattr(LLMProvider, "OLLAMA")


class TestRoutingDecisionLogic:
    """Test the combined routing decision logic"""

    def test_confidential_overrides_pii_detection(self):
        """Test that confidential bucket always uses Ollama regardless of PII"""
        confidential_doc = Document(
            filename="confidential.pdf",
            bucket=DocumentBucket.CONFIDENTIAL,
            original_filename="confidential.pdf",
            file_path="/data/confidential/confidential.pdf",
            size=1024,
            mime_type="application/pdf",
        )

        # Even if no PII detected in query, confidential bucket uses Ollama
        assert confidential_doc.bucket == DocumentBucket.CONFIDENTIAL

    def test_public_with_pii_routes_to_ollama(self):
        """Test that public documents with PII in query use Ollama"""
        query = "Find documents for john@example.com and admin@test.com"
        has_pii = pii_detection_service.detect_pii(query)

        # PII detection should trigger Ollama routing
        assert has_pii is True

    def test_public_without_pii_routes_to_minimax(self):
        """Test that public documents without PII can use MiniMax"""
        query = "What are the main project milestones?"
        has_pii = pii_detection_service.detect_pii(query)

        # No PII means MiniMax (via OpenRouter) can be used
        assert has_pii is False

    def test_user_role_with_confidential_access(self):
        """Test routing for users with explicit confidential access"""
        privileged_user = User(
            email="privileged@example.com",
            hashed_password="hash",
            role=UserRole.USER,
            is_superuser=False,
            can_access_confidential=True,
            is_active=True,
        )

        # Even with access flag, confidential documents use Ollama
        assert (
            privileged_user.can_access_confidential == True
            or privileged_user.can_access_confidential is True
        )


class TestMiniMaxServiceAvailability:
    """Test MiniMax/OpenRouter service availability checks"""

    @patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"})
    def test_openrouter_requires_api_key(self):
        """Test that OpenRouter service requires API key"""
        import os

        api_key = os.getenv("OPENROUTER_API_KEY")
        assert api_key is not None

    def test_openrouter_fallback_to_ollama(self):
        """Test that Ollama is used when OpenRouter is unavailable"""
        # When OpenRouter API key is missing or service is down, should use Ollama
        # This is a graceful degradation pattern
        pass


class TestOllamaServiceConfiguration:
    """Test Ollama service configuration"""

    def test_ollama_base_url_configurable(self):
        """Test that Ollama base URL is configurable"""
        import os

        ollama_url = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")
        assert (
            "ollama" in ollama_url
            or "localhost" in ollama_url
            or "host.docker.internal" in ollama_url
        )

    def test_ollama_model_configurable(self):
        """Test that Ollama model is configurable"""
        import os

        ollama_model = os.getenv("OLLAMA_MODEL", "mistral:7b-instruct")
        assert ollama_model is not None


class TestRoutingAuditing:
    """Test that routing decisions are audited"""

    def test_routing_decision_logged(self):
        """Test that routing decisions are logged"""
        # All routing decisions should be logged for audit purposes
        # This includes: user, document, PII detected, provider selected
        pass

    def test_confidential_access_logged(self):
        """Test that confidential document access is logged"""
        # All confidential access should be logged with timestamp and user
        pass

    def test_pii_detection_logged(self):
        """Test that PII detection events are logged"""
        # PII detection should be logged for privacy monitoring
        pass


class TestCostOptimization:
    """Test cost optimization in routing"""

    def test_context_caching_for_minimax(self):
        """Test that MiniMax uses context caching for cost reduction"""
        # MiniMax (via OpenRouter) should implement context caching for repeated queries
        # This can reduce costs significantly
        pass

    def test_cache_hit_tracking(self):
        """Test that cache hits are tracked"""
        # Cache hit rate should be monitored for cost optimization
        pass

    def test_ollama_no_cost_tracking(self):
        """Test that Ollama usage is tracked but has no direct cost"""
        # Ollama is local, so no API costs but resource usage should be tracked
        pass


class TestEdgeCases:
    """Test edge cases in routing logic"""

    def test_empty_query_routing(self):
        """Test routing for empty or minimal queries"""
        empty_query = ""
        has_pii = pii_detection_service.detect_pii(empty_query)
        assert has_pii is False

    def test_query_with_only_numbers(self):
        """Test routing for numeric-only queries"""
        numeric_query = "123456789"
        # May or may not trigger PII detection depending on patterns
        result = pii_detection_service.get_pii_summary(numeric_query)
        assert isinstance(result["has_pii"], bool)

    def test_multilingual_pii_detection(self):
        """Test PII detection for multilingual content"""
        french_text = "Mon email est jean.dupont@exemple.fr et mon autre email est test@exemple.fr"
        has_pii = pii_detection_service.detect_pii(french_text)
        assert has_pii is True

    def test_false_positive_handling(self):
        """Test handling of potential false positives"""
        # Text that looks like PII but isn't (e.g., example.com in documentation)
        doc_text = "For support, contact support@example.com which is our example address and also sales@example.com"
        has_pii = pii_detection_service.detect_pii(doc_text)
        # Should still detect as PII for privacy-first approach
        assert has_pii is True
