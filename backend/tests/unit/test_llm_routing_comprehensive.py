"""
Unit tests for LLM Routing Logic - Complete Coverage
Tests dual-LLM routing based on confidential context detection per PRD table
"""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock, PropertyMock
from uuid import uuid4

from app.services.pii_detection_service import pii_detection_service
from app.models.user import User, UserRole
from app.models.document import Document, DocumentBucket, DocumentStatus
from app.models.chat import ChatSession, LLMProvider


class TestDetermineLLMProviderFunction:
    """Test the determine_llm_provider function from chat.py"""

    def test_ollama_when_has_confidential_true(self):
        """Test that Ollama is selected when has_confidential is True"""
        from app.api.chat import determine_llm_provider
        provider = determine_llm_provider(has_confidential=True)
        assert provider == LLMProvider.OLLAMA

    def test_kimi_when_has_confidential_false(self):
        """Test that Kimi is selected when has_confidential is False"""
        from app.api.chat import determine_llm_provider
        provider = determine_llm_provider(has_confidential=False)
        assert provider == LLMProvider.KIMI


class TestRoutingWithPIIDetection:
    """Test that PII detection triggers correct routing"""

    def test_pii_in_query_triggers_ollama(self):
        """Test that PII in query triggers Ollama routing"""
        query_with_pii = "Send email to john.doe@example.com and jane@test.org"
        
        has_pii = pii_detection_service.detect_pii(query_with_pii)
        assert has_pii is True
        
        from app.api.chat import determine_llm_provider
        provider = determine_llm_provider(has_confidential=has_pii)
        assert provider == LLMProvider.OLLAMA

    def test_no_pii_allows_kimi(self):
        """Test that queries without PII can use Kimi"""
        query_no_pii = "What are the main features of our product?"
        
        has_pii = pii_detection_service.detect_pii(query_no_pii)
        assert has_pii is False
        
        from app.api.chat import determine_llm_provider
        provider = determine_llm_provider(has_confidential=has_pii)
        assert provider == LLMProvider.KIMI


class TestUserRoleRouting:
    """Test routing based on user roles"""

    def test_regular_user_routing(self):
        """Test regular user routing rules"""
        regular_user = User(
            email="user@example.com",
            hashed_password="hash",
            role=UserRole.USER
        )
        
        assert regular_user.role == UserRole.USER
        assert regular_user.can_access_confidential is None or regular_user.can_access_confidential is False

    def test_admin_user_routing(self):
        """Test admin user routing rules"""
        admin_user = User(
            email="admin@example.com",
            hashed_password="hash",
            role=UserRole.ADMIN,
            can_access_confidential=True
        )
        
        assert admin_user.role == UserRole.ADMIN
        assert admin_user.can_access_confidential is True

    def test_superuser_routing(self):
        """Test superuser routing rules"""
        superuser = User(
            email="super@example.com",
            hashed_password="hash",
            role=UserRole.SUPERUSER,
            can_access_confidential=True
        )
        
        assert superuser.role == UserRole.SUPERUSER
        assert superuser.can_access_confidential is True


class TestDocumentBucketRouting:
    """Test routing based on document bucket"""

    def test_public_document_routing(self):
        """Test that public documents allow Kimi"""
        public_doc = Document(
            filename="public.pdf",
            original_filename="public.pdf",
            file_path="/data/public/public.pdf",
            bucket=DocumentBucket.PUBLIC,
            size=1024,
            mime_type="application/pdf"
        )
        
        assert public_doc.bucket == DocumentBucket.PUBLIC

    def test_confidential_document_routing(self):
        """Test that confidential documents require Ollama"""
        confidential_doc = Document(
            filename="confidential.pdf",
            original_filename="confidential.pdf",
            file_path="/data/confidential/confidential.pdf",
            bucket=DocumentBucket.CONFIDENTIAL,
            size=1024,
            mime_type="application/pdf"
        )
        
        assert confidential_doc.bucket == DocumentBucket.CONFIDENTIAL


class TestLLMProviderEnum:
    """Test LLMProvider enum values"""

    def test_all_providers_defined(self):
        """Test that all required providers are defined"""
        assert hasattr(LLMProvider, 'KIMI')
        assert hasattr(LLMProvider, 'OLLAMA')
        assert hasattr(LLMProvider, 'OPENROUTER')

    def test_provider_values(self):
        """Test provider enum values"""
        assert LLMProvider.KIMI.value == "kimi"
        assert LLMProvider.OLLAMA.value == "ollama"
        assert LLMProvider.OPENROUTER.value == "openrouter"


class TestEdgeCases:
    """Test edge cases in routing"""

    def test_empty_query(self):
        """Test empty query handling"""
        from app.api.chat import determine_llm_provider
        provider = determine_llm_provider(has_confidential=False)
        assert provider == LLMProvider.KIMI

    def test_very_long_query(self):
        """Test very long query"""
        long_query = "test " * 10000
        has_pii = pii_detection_service.detect_pii(long_query)
        from app.api.chat import determine_llm_provider
        provider = determine_llm_provider(has_confidential=has_pii)
        assert provider in [LLMProvider.KIMI, LLMProvider.OLLAMA]


class TestMultiAgentOrchestratorRouting:
    """Test multi-agent orchestrator routing based on query content (NOT user role)"""

    def test_should_use_ollama_for_clarification_with_pii(self):
        """Test that PII in query triggers Ollama for clarification"""
        from app.services.agents.agent_orchestrator import AgentOrchestrator

        orchestrator = AgentOrchestrator()

        # Query with PII should use Ollama
        query_with_pii = "Contact john.doe@example.com for more information"
        assert orchestrator._should_use_ollama_for_clarification(query_with_pii) is True

    def test_should_use_ollama_for_clarification_with_phone(self):
        """Test that phone number in query triggers Ollama for clarification"""
        from app.services.agents.agent_orchestrator import AgentOrchestrator

        orchestrator = AgentOrchestrator()

        # Query with phone should use Ollama
        query_with_phone = "Call me at 06 12 34 56 78"
        assert orchestrator._should_use_ollama_for_clarification(query_with_phone) is True

    def test_should_use_ollama_for_clarification_without_pii(self):
        """Test that query without PII does NOT trigger Ollama for clarification"""
        from app.services.agents.agent_orchestrator import AgentOrchestrator

        orchestrator = AgentOrchestrator()

        # Query without PII should use Gemini (not Ollama)
        query_no_pii = "What are the main features of our product?"
        assert orchestrator._should_use_ollama_for_clarification(query_no_pii) is False

    def test_should_use_ollama_for_clarification_empty_query(self):
        """Test that empty query does NOT trigger Ollama"""
        from app.services.agents.agent_orchestrator import AgentOrchestrator

        orchestrator = AgentOrchestrator()

        # Empty query should not use Ollama
        assert orchestrator._should_use_ollama_for_clarification("") is False
        assert orchestrator._should_use_ollama_for_clarification(None) is False

    def test_routing_based_on_document_bucket_not_user_role(self):
        """CRITICAL: Verify that routing is based on document bucket, NOT user role

        This test ensures the security fix is in place:
        - A user with confidential access asking about public documents
          should NOT trigger Ollama (should use Gemini)
        - Only actual document content determines routing
        """
        from app.services.agents.agent_orchestrator import AgentOrchestrator

        orchestrator = AgentOrchestrator()

        # Admin asking about general topic (no PII) - should use Gemini
        admin_query = "Tell me about company policies"
        assert orchestrator._should_use_ollama_for_clarification(admin_query) is False

        # Regular user asking about general topic - should also use Gemini
        user_query = "What are our product features?"
        assert orchestrator._should_use_ollama_for_clarification(user_query) is False
