"""
PII (Personally Identifiable Information) Detection Service

Detects and redacts sensitive information to prevent PII from being sent to cloud APIs.
Routes confidential documents to local Ollama when PII is detected.
"""
import re
import logging
from typing import List, Dict, Tuple, Optional, Any

logger = logging.getLogger(__name__)


class PIIDetectionService:
    """
    Service for detecting and redacting PII in text content.

    Implements privacy-first architecture by detecting sensitive information
    before it's sent to cloud APIs (Gemini Flash) and routing to local Ollama instead.
    """

    # Compiled regex patterns for PII detection
    PATTERNS = {
        'email': re.compile(
            r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
            re.IGNORECASE
        ),
        'ssn': re.compile(
            r'\b\d{3}-\d{2}-\d{4}\b',  # US SSN pattern (more specific with dashes)
        ),
        'ssn_french': re.compile(
            r'\b[12]\s?\d{2}\s?\d{2}\s?\d{3}\s?\d{3}\s?\d{2}\b',  # French INSEE/SSN
            re.IGNORECASE
        ),
        'phone': re.compile(
            r'(?:(?:\+|00)33|0)\s*[1-9](?:[\s.-]*\d{2}){4}\b',  # French phone numbers
            re.IGNORECASE
        ),
        'phone_intl': re.compile(
            r'(?:(?:\+|00)[1-9]\d{0,2})?[-.\s]?\(?\d{1,4}\)?[-.\s]?\d{1,4}[-.\s]?\d{1,9}',  # International
            re.IGNORECASE
        ),
        'credit_card': re.compile(
            r'\b(?:\d[ -]*?){13,16}\b',  # Credit card pattern (13-16 digits)
            re.IGNORECASE
        ),
        'iban': re.compile(
            r'\b[A-Z]{2}[0-9]{2}[A-Z0-9]{11,35}\b',  # IBAN pattern (more specific length)
            re.IGNORECASE
        ),
        'ip_address': re.compile(
            r'\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b',
            re.IGNORECASE
        ),
        'url_with_params': re.compile(
            r'https?://[^\s<>"]+?[?&][^\s<>"]+=[^\s<>"]+',  # URLs with query parameters
            re.IGNORECASE
        ),
    }

    # Patterns that might indicate PII (lower confidence)
    SUSPICIOUS_PATTERNS = {
        'address_indicator': re.compile(
            r'\b(?:\d+\s+)?(?:street|avenue|boulevard|road|lane|rue|av|bd|chemin|place|allée|circuit|impasse|square)\s+[A-Z][a-z]+',
            re.IGNORECASE
        ),
        'full_address': re.compile(
            r'\b\d{1,5}\s+(?:rue|avenue|boulevard|road|lane|chemin|place|allée|circuit|impasse|square|street|avenue|blvd|dr|circle|court)[\s,]+[A-Z][a-z]+[\s,]+\d{5}?\b',
            re.IGNORECASE
        ),
        'french_postal_code': re.compile(
            r'\b\d{5}\b(?:\s+(?:Paris|Lyon|Marseille|Bordeaux|Toulouse|Nice|Nantes|Strasbourg|Montpellier|Lille|Rennes|Reims|Le\s+Havre|Grenoble|Dijon|Angers|Nîmes|Villeurbanne|Le\s+Mans|Clermont-Ferrand|Aix-en-Provence|Brest|Limoges|Tours|Orléans|Caen|Mulhouse|Poitiers|Pau|Souel|Quimper|Créteil|Versailles))?',
            re.IGNORECASE
        ),
        'name_indicator': re.compile(
            r'\b(?:Mr|Mrs|Ms|Dr|Pr|M|Mme|Mlle)\.?\s+[A-Z][a-z]+',
            re.IGNORECASE
        ),
        'birth_date': re.compile(
            r'\b(?:born|naissance|né|née|birthday|birth|date of birth)[:\s]+(?:\d{1,2}[-/]\d{1,2}[-/]\d{2,4}|\d{2,4}[-/]\d{1,2}[-/]\d{1,2})',
            re.IGNORECASE
        ),
        'passport': re.compile(
            r'\b(?:passport|passeport)\s*(?:card|document)?[:\s]?\s*[A-Z0-9]{6,12}',
            re.IGNORECASE
        ),
        'passport_number': re.compile(
            r'\b[A-Z]{1,2}\d{6,9}\b',  # US/UK passport format
            re.IGNORECASE
        ),
        'french_national_id': re.compile(
            r'\b\d{2}\s?\d{2}\s?\d{2}\s?\d{3}\s?\d{3}\s?[A-Z]{2}\b',  # French CNI
            re.IGNORECASE
        ),
        'license': re.compile(
            r'\b(?:driver\'s|driving|permis)\s*(?:license|licence)\s*(?:number|no|#)?[:\s]*[A-Z0-9]{5,15}',
            re.IGNORECASE
        ),
    }

    # Redaction placeholders
    REDACTION_PLACEHOLDERS = {
        'email': '[EMAIL_REDACTED]',
        'phone': '[PHONE_REDACTED]',
        'phone_intl': '[PHONE_REDACTED]',
        'ssn': '[SSN_REDACTED]',
        'ssn_french': '[SSN_REDACTED]',
        'credit_card': '[CARD_REDACTED]',
        'iban': '[IBAN_REDACTED]',
        'ip_address': '[IP_REDACTED]',
        'url_with_params': '[URL_REDACTED]',
    }

    def __init__(self, confidence_threshold: int = 1):
        """
        Initialize PII detection service.

        Args:
            confidence_threshold: Number of PII matches needed to trigger routing to Ollama
        """
        self.confidence_threshold = confidence_threshold

    def detect_pii(self, text: str) -> bool:
        """
        Detect if text contains PII.

        Args:
            text: Text to analyze

        Returns:
            True if PII detected above threshold, False otherwise
        """
        if not text or len(text) < 10:
            return False

        pii_count = 0

        # Check high-confidence patterns
        for pattern_name, pattern in self.PATTERNS.items():
            matches = pattern.findall(text)
            if matches:
                # For credit cards, verify it's not just any long number
                if pattern_name == 'credit_card':
                    for match in matches:
                        if self._is_valid_credit_card(match):
                            pii_count += 1
                            logger.debug(f"PII detected: {pattern_name} in text")
                            if pii_count >= self.confidence_threshold:
                                return True
                else:
                    pii_count += len(matches)
                    logger.debug(f"PII detected: {pattern_name} ({len(matches)} matches) in text")
                    if pii_count >= self.confidence_threshold:
                        return True

        # Check suspicious patterns (lower confidence)
        suspicious_count = 0
        for pattern_name, pattern in self.SUSPICIOUS_PATTERNS.items():
            if pattern.search(text):
                suspicious_count += 1

        # If multiple suspicious patterns found, consider it PII
        if suspicious_count >= 2:
            logger.debug(f"Multiple suspicious patterns found: {suspicious_count}")
            return True

        return pii_count >= self.confidence_threshold

    def redact_pii(self, text: str) -> Tuple[str, Dict[str, int]]:
        """
        Redact PII from text.

        Args:
            text: Text to redact

        Returns:
            Tuple of (redacted_text, stats) where stats contains counts of each redaction type
        """
        if not text:
            return text, {}

        redacted_text = text
        stats = {}

        # Redact high-confidence patterns
        for pattern_name, pattern in self.PATTERNS.items():
            matches = pattern.findall(redacted_text)
            if matches:
                placeholder = self.REDACTION_PLACEHOLDERS.get(pattern_name, '[REDACTED]')
                redacted_text = pattern.sub(placeholder, redacted_text)
                stats[pattern_name] = len(matches)
                logger.debug(f"Redacted {len(matches)} instances of {pattern_name}")

        # Redact suspicious patterns
        for pattern_name, pattern in self.SUSPICIOUS_PATTERNS.items():
            matches = pattern.findall(redacted_text)
            if matches:
                placeholder = '[SUSPICIOUS_REDACTED]'
                redacted_text = pattern.sub(placeholder, redacted_text)
                stats[f'suspicious_{pattern_name}'] = len(matches)

        return redacted_text, stats

    def get_pii_summary(self, text: str) -> Dict[str, Any]:
        """
        Get summary of PII detection in text.

        Args:
            text: Text to analyze

        Returns:
            Dictionary with detection results and details
        """
        if not text:
            return {
                'has_pii': False,
                'confidence': 0,
                'detected_types': [],
                'details': {}
            }

        detected_types = []
        details = {}
        confidence_score = 0

        # Check high-confidence patterns
        for pattern_name, pattern in self.PATTERNS.items():
            matches = pattern.findall(text)
            if matches:
                # Verify credit cards
                if pattern_name == 'credit_card':
                    valid_matches = [m for m in matches if self._is_valid_credit_card(m)]
                    if valid_matches:
                        detected_types.append(pattern_name)
                        details[pattern_name] = len(valid_matches)
                        confidence_score += len(valid_matches) * 2
                else:
                    detected_types.append(pattern_name)
                    details[pattern_name] = len(matches)
                    confidence_score += len(matches)

        # Check suspicious patterns
        suspicious_found = []
        for pattern_name, pattern in self.SUSPICIOUS_PATTERNS.items():
            if pattern.search(text):
                suspicious_found.append(pattern_name)
                confidence_score += 0.5

        if suspicious_found:
            details['suspicious_patterns'] = suspicious_found

        has_pii = confidence_score >= self.confidence_threshold

        return {
            'has_pii': has_pii,
            'confidence': confidence_score,
            'detected_types': detected_types,
            'suspicious_patterns': suspicious_found,
            'details': details
        }

    def _is_valid_credit_card(self, number: str) -> bool:
        """
        Validate credit card number using Luhn algorithm.

        Args:
            number: Credit card number string

        Returns:
            True if valid credit card number
        """
        # Remove spaces and dashes
        num = re.sub(r'[^\d]', '', number)

        # Must be 13-16 digits
        if not 13 <= len(num) <= 16:
            return False

        # Luhn algorithm
        total = 0
        for i, digit in enumerate(reversed(num)):
            d = int(digit)
            if i % 2 == 1:
                d *= 2
                if d > 9:
                    d -= 9
            total += d

        return total % 10 == 0


# Global PII detection service instance
pii_detection_service = PIIDetectionService()
