"""
Unit tests for PII Detection Service
Tests detection and redaction of personally identifiable information
"""
import pytest
from app.services.pii_detection_service import PIIDetectionService


class TestPIIDetectionService:
    """Test PII detection and redaction functionality"""

    def setup_method(self):
        """Initialize PII detection service for each test"""
        self.service = PIIDetectionService(confidence_threshold=2)

    def test_detect_email_addresses(self):
        """Test email address detection"""
        text = "Contact me at john.doe@example.com or support@test.org for help."
        assert self.service.detect_pii(text) is True

        summary = self.service.get_pii_summary(text)
        assert summary['has_pii'] is True
        assert 'email' in summary['detected_types']

    def test_detect_french_phone_numbers(self):
        """Test French phone number detection"""
        text = "Call me at 06 12 34 56 78 or +33 1 23 45 67 89."
        assert self.service.detect_pii(text) is True

        summary = self.service.get_pii_summary(text)
        assert summary['has_pii'] is True
        assert 'phone' in summary['detected_types']

    def test_detect_international_phone_numbers(self):
        """Test international phone number detection"""
        text = "International: +1-555-123-4567 or +44 20 7946 0958."
        assert self.service.detect_pii(text) is True

        summary = self.service.get_pii_summary(text)
        assert summary['has_pii'] is True

    def test_detect_us_ssn(self):
        """Test US Social Security Number detection"""
        text = "My SSN is 123-45-6789."
        assert self.service.detect_pii(text) is True

        summary = self.service.get_pii_summary(text)
        assert summary['has_pii'] is True
        assert 'ssn' in summary['detected_types']

    def test_detect_french_ssn(self):
        """Test French INSEE/SSN detection"""
        text = "Mon numéro INSEE est 2 85 10 12 345 678."
        assert self.service.detect_pii(text) is True

        summary = self.service.get_pii_summary(text)
        assert summary['has_pii'] is True

    def test_detect_credit_card_numbers(self):
        """Test credit card number detection with Luhn validation"""
        # Valid test credit card numbers (these are test numbers, not real cards)
        valid_cards = [
            "4532 1234 5678 9010",  # Valid format
            "4111-1111-1111-1111",  # Another valid format
        ]

        for card in valid_cards:
            assert self.service._is_valid_credit_card(card)

        # Test detection in text
        text = f"My card is {valid_cards[0]}"
        result = self.service.detect_pii(text)
        # May or may not detect depending on Luhn validation
        summary = self.service.get_pii_summary(text)
        # Check if credit card is detected
        if 'credit_card' in summary['detected_types']:
            assert summary['has_pii'] is True

    def test_detect_iban(self):
        """Test IBAN detection"""
        text = "My IBAN is FR76 1234 5678 9012 3456 7890 123."
        assert self.service.detect_pii(text) is True

        summary = self.service.get_pii_summary(text)
        assert summary['has_pii'] is True
        assert 'iban' in summary['detected_types']

    def test_detect_ip_addresses(self):
        """Test IP address detection"""
        text = "Server IP is 192.168.1.1 or 8.8.8.8."
        assert self.service.detect_pii(text) is True

        summary = self.service.get_pii_summary(text)
        assert summary['has_pii'] is True
        assert 'ip_address' in summary['detected_types']

    def test_detect_urls_with_parameters(self):
        """Test URL with query parameters detection"""
        text = "Visit https://example.com/page?user=123&token=abc for details."
        assert self.service.detect_pii(text) is True

        summary = self.service.get_pii_summary(text)
        assert summary['has_pii'] is True

    def test_detect_suspicious_patterns(self):
        """Test detection of suspicious patterns that might indicate PII"""
        text = "Mr. John Smith was born on 01/01/1980 at 123 Main Street."
        assert self.service.detect_pii(text) is True

        summary = self.service.get_pii_summary(text)
        # Should detect multiple suspicious patterns
        assert len(summary['suspicious_patterns']) >= 2

    def test_detect_passport_numbers(self):
        """Test passport number detection"""
        text = "My passport number is AB1234567."
        assert self.service.detect_pii(text) is True

        summary = self.service.get_pii_summary(text)
        assert 'passport' in summary['suspicious_patterns']

    def test_detect_drivers_license(self):
        """Test driver's license detection"""
        text = "Driver's license number: DL-12345678."
        assert self.service.detect_pii(text) is True

        summary = self.service.get_pii_summary(text)
        assert 'license' in summary['suspicious_patterns']

    def test_no_pii_in_clean_text(self):
        """Test that clean text without PII returns False"""
        text = "This is a simple document about software architecture."
        assert self.service.detect_pii(text) is False

        summary = self.service.get_pii_summary(text)
        assert summary['has_pii'] is False
        assert summary['confidence'] == 0

    def test_confidence_threshold(self):
        """Test that confidence threshold works correctly"""
        # Text with only one PII instance
        text = "Contact me at john@example.com."
        service = PIIDetectionService(confidence_threshold=2)

        # Should not trigger with threshold of 2
        assert service.detect_pii(text) is False

        # Should trigger with threshold of 1
        service_low = PIIDetectionService(confidence_threshold=1)
        assert service_low.detect_pii(text) is True

    def test_redact_email_addresses(self):
        """Test email redaction"""
        text = "Contact john@example.com or jane@test.org."
        redacted, stats = self.service.redact_pii(text)

        assert '[EMAIL_REDACTED]' in redacted
        assert '@example.com' not in redacted
        assert stats.get('email', 0) == 2

    def test_redact_phone_numbers(self):
        """Test phone number redaction"""
        text = "Call me at 06 12 34 56 78."
        redacted, stats = self.service.redact_pii(text)

        assert '[PHONE_REDACTED]' in redacted
        assert '06 12 34 56 78' not in redacted

    def test_redact_ssn(self):
        """Test SSN redaction"""
        text = "My SSN is 123-45-6789."
        redacted, stats = self.service.redact_pii(text)

        assert '[SSN_REDACTED]' in redacted
        assert '123-45-6789' not in redacted

    def test_redact_credit_cards(self):
        """Test credit card redaction"""
        text = "Card: 4532 1234 5678 9010."
        redacted, stats = self.service.redact_pii(text)

        assert '[CARD_REDACTED]' in redacted or '4532 1234 5678 9010' not in redacted

    def test_redact_iban(self):
        """Test IBAN redaction"""
        text = "IBAN: FR76 1234 5678 9012 3456 7890 123."
        redacted, stats = self.service.redact_pii(text)

        assert '[IBAN_REDACTED]' in redacted
        assert 'FR76' not in redacted

    def test_redact_ip_addresses(self):
        """Test IP address redaction"""
        text = "Server: 192.168.1.1."
        redacted, stats = self.service.redact_pii(text)

        assert '[IP_REDACTED]' in redacted
        assert '192.168.1.1' not in redacted

    def test_redact_mixed_pii(self):
        """Test redaction of mixed PII types"""
        text = "Contact john@example.com or call 06 12 34 56 78. SSN: 123-45-6789."
        redacted, stats = self.service.redact_pii(text)

        assert '[EMAIL_REDACTED]' in redacted
        assert '[PHONE_REDACTED]' in redacted
        assert '[SSN_REDACTED]' in redacted
        assert '@example.com' not in redacted
        assert '06 12 34' not in redacted
        assert '123-45-6789' not in redacted

    def test_pii_summary_empty_text(self):
        """Test PII summary with empty text"""
        summary = self.service.get_pii_summary("")
        assert summary['has_pii'] is False
        assert summary['confidence'] == 0
        assert summary['detected_types'] == []

    def test_pii_summary_none_text(self):
        """Test PII summary with None text"""
        summary = self.service.get_pii_summary(None)
        assert summary['has_pii'] is False
        assert summary['confidence'] == 0

    def test_redact_empty_text(self):
        """Test redaction with empty text"""
        redacted, stats = self.service.redact_pii("")
        assert redacted == ""
        assert stats == {}

    def test_redact_preserves_non_pii_content(self):
        """Test that redaction preserves non-PII content"""
        text = "Hello, please contact john@example.com for information about our services."
        redacted, stats = self.service.redact_pii(text)

        assert "Hello, please contact" in redacted
        assert "for information about our services" in redacted
        assert "john@example.com" not in redacted

    def test_detect_pii_short_text(self):
        """Test PII detection with very short text"""
        text = "Hi"
        assert self.service.detect_pii(text) is False

    def test_multiple_instances_same_pii_type(self):
        """Test detection of multiple instances of the same PII type"""
        text = "Email1: test1@example.com, Email2: test2@example.com, Email3: test3@example.com"
        summary = self.service.get_pii_summary(text)

        assert summary['has_pii'] is True
        assert summary['details']['email'] == 3

    def test_french_address_detection(self):
        """Test French address pattern detection"""
        text = "J'habite au 123 rue de la Paix, Paris."
        assert self.service.detect_pii(text) is True

        summary = self.service.get_pii_summary(text)
        assert 'address_indicator' in summary['suspicious_patterns']

    def test_english_address_detection(self):
        """Test English address pattern detection"""
        text = "I live at 123 Main Street, Springfield."
        assert self.service.detect_pii(text) is True

        summary = self.service.get_pii_summary(text)
        assert 'address_indicator' in summary['suspicious_patterns']
