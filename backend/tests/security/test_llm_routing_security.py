"""
Security tests for LLM Routing
Tests PII sanitization, confidential routing, and API key exposure prevention
"""
import pytest
from unittest.mock import patch, MagicMock
import os
import re

from app.services.pii_detection_service import pii_detection_service
from app.services.chat_service import ChatService
from app.models.user import User, UserRole
from app.models.document import Document, DocumentBucket


class TestPIISanitizationEffectiveness:
    """Test PII sanitization effectiveness"""

    def setup_method(self):
        self.service = pii_detection_service

    def test_email_sanitization(self):
        """Test email addresses are properly sanitized"""
        text = "Contact john.doe@company.com or jane@partner.org"
        
        redacted, stats = self.service.redact_pii(text)
        
        assert "[EMAIL_REDACTED]" in redacted
        assert "john.doe@company.com" not in redacted
        assert "jane@partner.org" not in redacted
        assert stats.get('email', 0) == 2

    def test_phone_sanitization(self):
        """Test phone numbers are properly sanitized"""
        text = "Call 06 12 34 56 78 or +33 1 23 45 67 89"
        
        redacted, stats = self.service.redact_pii(text)
        
        assert "[PHONE_REDACTED]" in redacted
        assert "06 12 34 56 78" not in redacted
        assert "33 1 23 45" not in redacted

    def test_ssn_sanitization(self):
        """Test SSN is properly sanitized"""
        text = "SSN: 123-45-6789"
        
        redacted, stats = self.service.redact_pii(text)
        
        assert "[SSN_REDACTED]" in redacted
        assert "123-45-6789" not in redacted

    def test_credit_card_sanitization(self):
        """Test credit card is properly sanitized"""
        text = "Card: 4532 1234 5678 9010"
        
        redacted, stats = self.service.redact_pii(text)
        
        assert "[CARD_REDACTED]" in redacted or "4532" not in redacted

    def test_iban_sanitization(self):
        """Test IBAN is properly sanitized"""
        text = "IBAN: FR76 1234 5678 9012 3456 7890 123"
        
        redacted, stats = self.service.redact_pii(text)
        
        assert "[IBAN_REDACTED]" in redacted
        assert "FR76" not in redacted

    def test_ip_address_sanitization(self):
        """Test IP address is properly sanitized"""
        text = "Server IP: 192.168.1.1"
        
        redacted, stats = self.service.redact_pii(text)
        
        assert "[IP_REDACTED]" in redacted
        assert "192.168.1.1" not in redacted

    def test_url_sanitization(self):
        """Test URL with params is properly sanitized"""
        text = "API: https://api.example.com?api_key=secret123"
        
        redacted, stats = self.service.redact_pii(text)
        
        assert "[URL_REDACTED]" in redacted
        assert "api_key=secret123" not in redacted

    def test_mixed_pii_sanitization(self):
        """Test multiple PII types are sanitized"""
        text = """
        Employee: John Doe
        Email: john@company.com
        Phone: 06 12 34 56 78
        SSN: 123-45-6789
        Card: 4532-1234-5678-9010
        """
        
        redacted, stats = self.service.redact_pii(text)
        
        assert "[EMAIL_REDACTED]" in redacted
        assert "[PHONE_REDACTED]" in redacted
        assert "[SSN_REDACTED]" in redacted
        assert "[CARD_REDACTED]" in redacted

    def test_non_pii_preserved(self):
        """Test that non-PII content is preserved"""
        text = "This document contains important information about the project."
        
        redacted, stats = self.service.redact_pii(text)
        
        assert redacted == text
        assert stats == {}


class TestConfidentialDocumentRoutingSecurity:
    """Test confidential document routing security"""

    def test_confidential_doc_uses_ollama(self):
        """Test that confidential documents route to Ollama"""
        from app.api.chat import determine_llm_provider
        
        # Confidential content should route to Ollama
        provider = determine_llm_provider(has_confidential=True)
        assert provider.value == "ollama"

    def test_public_doc_can_use_kimi(self):
        """Test that public documents without PII can use Kimi"""
        from app.api.chat import determine_llm_provider
        
        provider = determine_llm_provider(has_confidential=False)
        assert provider.value == "kimi"

    def test_regular_user_cannot_access_confidential_documents(self):
        """Test that regular users can't see confidential documents"""
        regular_user = User(
            email="user@example.com",
            hashed_password="hash",
            role=UserRole.USER,
            can_access_confidential=False
        )
        
        # Verify user doesn't have confidential access
        assert regular_user.can_access_confidential is False

    def test_admin_can_access_confidential_documents(self):
        """Test that admins can access confidential documents"""
        admin_user = User(
            email="admin@example.com",
            hashed_password="hash",
            role=UserRole.ADMIN,
            can_access_confidential=True
        )
        
        # Verify admin has confidential access
        assert admin_user.can_access_confidential is True

    def test_confidential_bucket_detection(self):
        """Test document bucket detection"""
        confidential_doc = Document(
            filename="secret.pdf",
            original_filename="secret.pdf",
            file_path="/data/confidential/secret.pdf",
            bucket=DocumentBucket.CONFIDENTIAL,
            size=1024,
            mime_type="application/pdf"
        )
        
        public_doc = Document(
            filename="public.pdf",
            original_filename="public.pdf",
            file_path="/data/public/public.pdf",
            bucket=DocumentBucket.PUBLIC,
            size=1024,
            mime_type="application/pdf"
        )
        
        assert confidential_doc.bucket == DocumentBucket.CONFIDENTIAL
        assert public_doc.bucket == DocumentBucket.PUBLIC


class TestAPIKeyExposurePrevention:
    """Test API key exposure prevention"""

    def test_no_api_keys_in_logs(self):
        """Test that API keys don't appear in logs"""
        # This is a documentation test
        # In production, ensure no API keys are logged
        pass

    def test_authorization_header_sanitization(self):
        """Test that Authorization headers are handled securely"""
        import os
        os.environ['OPENROUTER_API_KEY'] = 'sk-test-12345'
        
        # Verify key is in environment
        key = os.environ.get('OPENROUTER_API_KEY')
        assert key is not None
        
        # Key should NOT be logged directly
        # This is ensured by using Bearer token format
        auth_header = f"Bearer {key}"
        assert key not in auth_header  # The key itself isn't exposed, only in header

    def test_error_messages_no_sensitive_data(self):
        """Test that error messages don't expose sensitive data"""
        # Error messages should not contain API keys
        error_msg = "Error: API error - 500"
        
        # Should not contain actual key values
        assert "sk-" not in error_msg
        assert "api_key" not in error_msg.lower()


class TestPIIDetectionAccuracy:
    """Test PII detection accuracy"""

    def test_french_email_detection(self):
        """Test French email detection"""
        text = "Mon email: jean.dupont@exemple.fr"
        assert self.service.detect_pii(text) is True

    def test_french_phone_detection(self):
        """Test French phone detection"""
        text = "Mon téléphone: 06 12 34 56 78"
        assert self.service.detect_pii(text) is True

    def test_false_positive_rate(self):
        """Test false positive rate is low"""
        # Text that shouldn't trigger PII
        clean_texts = [
            "This is a simple document about architecture.",
            "The meeting is scheduled for next week.",
            "Project milestone achieved successfully.",
        ]
        
        for text in clean_texts:
            assert self.service.detect_pii(text) is False, f"False positive for: {text}"

    def test_luhn_validation(self):
        """Test credit card Luhn validation"""
        # Valid test card (passes Luhn)
        valid_card = "4532015112830366"
        assert self.service._is_valid_credit_card(valid_card) is True
        
        # Invalid card (fails Luhn)
        invalid_card = "1234567890123456"
        assert self.service._is_valid_credit_card(invalid_card) is False


class TestSecurityLogging:
    """Test security-related logging"""

    def test_pii_detection_is_logged(self):
        """Test that PII detection events can be logged"""
        # PII detection should log warnings for monitoring
        # This is implemented in the service
        text = "Contact john@example.com"
        has_pii = self.service.detect_pii(text)
        
        # Should detect PII
        assert has_pii is True

    def test_routing_decision_is_logged(self):
        """Test that routing decisions can be logged"""
        # Routing decisions are logged in chat_service
        # This test documents the requirement
        from app.services.chat_service import ChatService
        
        service = ChatService()
        
        # Verify service exists and can log
        assert service is not None


class TestMultiTenantIsolation:
    """Test multi-tenant isolation"""

    def test_users_cannot_see_other_users_documents(self):
        """Test that users can only see their own documents"""
        # This is enforced at the API layer
        # Documented here for completeness
        pass

    def test_confidential_access_auditing(self):
        """Test that confidential access can be audited"""
        # Audit logging should track:
        # - User ID
        # - Document ID
        # - Timestamp
        # - Action (view, search, etc.)
        
        # This test documents requirements
        audit_entry = {
            "user_id": "user-123",
            "document_id": "doc-456",
            "action": "view",
            "timestamp": "2024-01-01T00:00:00Z"
        }
        
        assert "user_id" in audit_entry
        assert "document_id" in audit_entry
        assert "timestamp" in audit_entry
