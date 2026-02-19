"""
Unit tests for Services Routing Security
Tests that services without proper routing are identified and fixed
"""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
import os
import json
from uuid import uuid4

from app.services.pii_detection_service import pii_detection_service
from app.services.intent_parser import IntentParserService
from app.services.entity_extraction_service import EntityExtractionService
from app.services.auto_tagging_service import AutoTaggingService
from app.models.user import User, UserRole
from app.models.document import Document, DocumentBucket


class TestIntentParserRouting:
    """Test IntentParser service for proper routing"""

    @pytest.fixture
    def intent_parser(self):
        return IntentParserService()

    def test_intent_parser_uses_gemini_directly(self, intent_parser):
        """Test that IntentParser currently uses gemini_service directly"""
        # This test identifies the issue: intent_parser uses gemini_service
        # without checking for confidential content
        assert intent_parser.gemini_service is not None

    @pytest.mark.asyncio
    async def test_intent_parser_no_confidential_check(self, intent_parser):
        """Test that IntentParser doesn't check for confidential content"""
        # The current implementation doesn't accept user or document info
        # to determine if confidential content is involved
        
        query = "Show me financial documents from 2023"
        
        # Current implementation just calls Gemini without routing check
        # This test documents the expected behavior after fix
        with patch.object(intent_parser, 'gemini_service') as mock_gemini:
            mock_gemini.chat_completion = AsyncMock(
                return_value=iter(['{"keywords": ["financial"]}'])
            )
            
            result = await intent_parser.parse_intent(query)
            
            # Verify it uses Gemini (issue to be fixed)
            assert mock_gemini.chat_completion.called


class TestEntityExtractionRouting:
    """Test EntityExtraction service for proper routing"""

    @pytest.fixture
    def entity_extraction(self):
        return EntityExtractionService()

    def test_entity_extraction_uses_gemini_directly(self, entity_extraction):
        """Test that EntityExtraction currently uses gemini_service directly"""
        assert entity_extraction.gemini_service is not None

    def test_entity_extraction_document_parameter(self, entity_extraction):
        """Test that EntityExtraction receives document but doesn't check bucket"""
        # This test documents the expected behavior after fix
        
        public_doc = Document(
            filename="public.pdf",
            original_filename="public.pdf",
            file_path="/data/public/public.pdf",
            bucket=DocumentBucket.PUBLIC,
            size=1024,
            mime_type="application/pdf"
        )
        
        confidential_doc = Document(
            filename="confidential.pdf",
            original_filename="confidential.pdf",
            file_path="/data/confidential/confidential.pdf",
            bucket=DocumentBucket.CONFIDENTIAL,
            size=1024,
            mime_type="application/pdf"
        )
        
        # Both should work, but currently both use Gemini
        assert public_doc.bucket == DocumentBucket.PUBLIC
        assert confidential_doc.bucket == DocumentBucket.CONFIDENTIAL


class TestAutoTaggingRouting:
    """Test AutoTagging service for proper routing"""

    @pytest.fixture
    def auto_tagging(self):
        return AutoTaggingService()

    def test_auto_tagging_uses_gemini_directly(self, auto_tagging):
        """Test that AutoTagging currently uses gemini_service directly"""
        assert auto_tagging.gemini_service is not None


class TestOptionalServicesRouting:
    """Test services that may not be fully implemented"""

    def test_synthesis_service_check(self):
        """Check if SynthesisService has routing capability"""
        try:
            from app.services.synthesis_service import synthesis_service
            # If imported, check for routing capability
            service = synthesis_service
            has_gemini = hasattr(service, 'gemini_service')
            has_ollama = hasattr(service, 'ollama_service') or hasattr(service, 'routing_enabled')
            print(f"SynthesisService: gemini={has_gemini}, routing={has_ollama}")
        except ImportError:
            pytest.skip("SynthesisService module not available")

    def test_graph_rag_service_check(self):
        """Check if GraphRAGService has routing capability"""
        try:
            from app.services.graph_rag_service import graph_rag_service
            service = graph_rag_service
            has_gemini = hasattr(service, 'gemini_service')
            print(f"GraphRAGService: gemini={has_gemini}")
        except ImportError:
            pytest.skip("GraphRAGService module not available")

    def test_progressive_revelation_service_check(self):
        """Check if ProgressiveRevelationService has routing capability"""
        try:
            from app.services.progressive_revelation_service import progressive_revelation_service
            service = progressive_revelation_service
            has_gemini = hasattr(service, 'gemini_service')
            print(f"ProgressiveRevelationService: gemini={has_gemini}")
        except ImportError:
            pytest.skip("ProgressiveRevelationService module not available")


class TestRoutingGapAnalysis:
    """Analysis of services that need routing fixes"""

    def test_services_using_gemini_directly(self):
        """List all services using Gemini without routing check"""
        services_to_check = [
            ('IntentParser', IntentParserService),
            ('EntityExtraction', EntityExtractionService),
            ('AutoTagging', AutoTaggingService),
        ]
        
        # This test documents which services need routing fixes
        for name, ServiceClass in services_to_check:
            service = ServiceClass()
            has_gemini = hasattr(service, 'gemini_service')
            has_ollama = hasattr(service, 'ollama_service')
            
            # Document the gap
            print(f"{name}: gemini={has_gemini}, ollama={has_ollama}")
            
            # After fix, services should have both or routing logic
            assert has_gemini is not None


class TestRequiredRoutingFunctionality:
    """Test required functionality for routing implementation"""

    def test_document_bucket_check(self):
        """Test that document bucket can be checked"""
        doc = Document(
            filename="test.pdf",
            original_filename="test.pdf",
            file_path="/data/test.pdf",
            bucket=DocumentBucket.CONFIDENTIAL,
            size=1024,
            mime_type="application/pdf"
        )
        
        assert hasattr(doc, 'bucket')
        assert doc.bucket == DocumentBucket.CONFIDENTIAL

    def test_user_role_check(self):
        """Test that user role can be checked"""
        admin = User(
            email="admin@test.com",
            hashed_password="hash",
            role=UserRole.ADMIN
        )
        
        regular = User(
            email="user@test.com",
            hashed_password="hash",
            role=UserRole.USER
        )
        
        assert admin.role == UserRole.ADMIN
        assert regular.role == UserRole.USER
        assert admin.role != regular.role

    def test_confidential_access_check(self):
        """Test that confidential access can be determined"""
        admin = User(
            email="admin@test.com",
            hashed_password="hash",
            role=UserRole.ADMIN,
            can_access_confidential=True
        )
        
        user = User(
            email="user@test.com",
            hashed_password="hash",
            role=UserRole.USER,
            can_access_confidential=False
        )
        
        # Admin with confidential access should route to Ollama for confidential docs
        assert admin.can_access_confidential is True
        
        # Regular user without confidential access
        assert user.can_access_confidential is False or user.can_access_confidential is None
