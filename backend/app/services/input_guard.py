"""
InputGuard Middleware — Sprint 3.1

Pre-processes all user input before LLM routing.  Provides:
  - Language detection (FR/EN heuristic)
  - PII scanning (delegates to pii_detection_service)
  - Intent classification (keyword-based)
  - Vault context determination (public vs confidential)
  - Deduplication via Redis (30s window)
  - Token budget check with truncation
"""

import hashlib
import logging
import re
from dataclasses import dataclass

import redis.asyncio as aioredis

from app.core.redis_url import safe_redis_url
from app.services.pii_detection_service import pii_detection_service

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class GuardResult:
    query: str
    language: str           # "fr" or "en"
    intent: str             # "search", "chat", "report", "admin", "collection"
    vault_hint: str         # "public" or "confidential"
    pii_detected: bool
    is_duplicate: bool
    token_count: int


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_TOKEN_BUDGET = 4096
_TOKEN_RATIO = 1.3          # words -> approximate token count
_DEDUP_TTL_SECONDS = 30
_DEDUP_KEY_PREFIX = "sowknow:dedup:"

# French indicator words — common enough to distinguish FR from EN reliably.
_FRENCH_INDICATORS: set[str] = {
    "le", "la", "les", "un", "une", "des", "du", "de", "et", "est",
    "en", "je", "tu", "il", "elle", "nous", "vous", "ils", "elles",
    "ce", "cette", "ces", "mon", "ma", "mes", "ton", "ta", "tes",
    "son", "sa", "ses", "qui", "que", "quoi", "dont", "où",
    "ne", "pas", "plus", "dans", "sur", "avec", "pour", "par",
    "au", "aux", "mais", "ou", "donc", "car", "ni",
    "aussi", "très", "bien", "peu", "trop", "ici",
    "cherche", "trouve", "comment", "pourquoi", "quand",
    "bonjour", "merci", "oui", "non",
}

# Intent keyword map — first match wins.
_INTENT_KEYWORDS: list[tuple[str, list[str]]] = [
    ("search",     ["search", "find", "cherche", "trouve", "recherche", "trouver"]),
    ("report",     ["report", "rapport"]),
    ("collection", ["collection", "groupe"]),
    ("admin",      ["admin", "user", "manage", "utilisateur", "gestion"]),
]

# Pre-compile a word-boundary pattern for each intent for speed.
_INTENT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (intent, re.compile(
        r"\b(?:" + "|".join(re.escape(kw) for kw in keywords) + r")\b",
        re.IGNORECASE,
    ))
    for intent, keywords in _INTENT_KEYWORDS
]


# ---------------------------------------------------------------------------
# InputGuard
# ---------------------------------------------------------------------------

class InputGuard:
    """Lightweight, async-safe input guard.  All operations are designed to
    complete in well under 50 ms for typical query lengths."""

    def __init__(self) -> None:
        self._redis: aioredis.Redis | None = None

    # -- Redis (lazy) -------------------------------------------------------

    async def _get_redis(self) -> aioredis.Redis | None:
        """Return an async Redis client, or ``None`` if unavailable."""
        if self._redis is not None:
            return self._redis
        try:
            url = safe_redis_url()
            self._redis = aioredis.from_url(
                url,
                decode_responses=True,
                socket_connect_timeout=1,
                socket_timeout=1,
            )
            # Quick connectivity test
            await self._redis.ping()
            return self._redis
        except Exception:
            logger.warning("InputGuard: Redis unavailable — dedup disabled")
            self._redis = None
            return None

    # -- Public API ---------------------------------------------------------

    async def process(
        self,
        query: str,
        user_role: str,
        document_ids: list[str] | None = None,
    ) -> GuardResult:
        """Run all guard checks on *query* and return a ``GuardResult``."""

        # 1. Language detection
        language = self._detect_language(query)

        # 2. PII scan
        pii_detected = self._scan_pii(query)

        # 3. Intent classification
        intent = self._classify_intent(query)

        # 4. Vault context
        vault_hint = self._determine_vault(
            pii_detected=pii_detected,
            document_ids=document_ids,
            user_role=user_role,
        )

        # 5. Deduplication
        is_duplicate = await self._check_duplicate(query)

        # 6. Token budget — truncate if needed
        query, token_count = self._enforce_token_budget(query)

        result = GuardResult(
            query=query,
            language=language,
            intent=intent,
            vault_hint=vault_hint,
            pii_detected=pii_detected,
            is_duplicate=is_duplicate,
            token_count=token_count,
        )

        logger.info(
            "InputGuard: lang=%s intent=%s vault=%s pii=%s dup=%s tokens=%d",
            language, intent, vault_hint, pii_detected, is_duplicate, token_count,
        )
        return result

    # -- Internal helpers ---------------------------------------------------

    @staticmethod
    def _detect_language(query: str) -> str:
        """Heuristic language detection.  Returns ``"fr"`` or ``"en"``."""
        words = set(query.lower().split())
        french_hits = words & _FRENCH_INDICATORS
        # If >= 2 French indicator words found, classify as French.
        if len(french_hits) >= 2:
            return "fr"
        # Single-word queries: check if that word is French.
        if len(words) == 1 and french_hits:
            return "fr"
        # Very short queries with no indicators default to French (per spec).
        if len(words) <= 2:
            return "fr"
        return "en"

    @staticmethod
    def _scan_pii(query: str) -> bool:
        """Delegate to the existing PII detection service."""
        try:
            return pii_detection_service.detect_pii(query)
        except Exception:
            logger.debug("InputGuard: PII scan failed — assuming no PII")
            return False

    @staticmethod
    def _classify_intent(query: str) -> str:
        """Keyword-based intent classification.  First match wins."""
        for intent, pattern in _INTENT_PATTERNS:
            if pattern.search(query):
                return intent
        return "chat"

    @staticmethod
    def _determine_vault(
        *,
        pii_detected: bool,
        document_ids: list[str] | list[dict] | None,
        user_role: str,
    ) -> str:
        """Decide whether the query context is public or confidential.

        Rules (in priority order):
          1. PII in query text -> confidential.
          2. Any document_id marked confidential -> confidential.
          3. Otherwise -> public.
        """
        if pii_detected:
            logger.debug("InputGuard: vault=confidential (PII in query)")
            return "confidential"

        if document_ids:
            for doc in document_ids:
                # Accept dicts with a bucket/confidential key
                if isinstance(doc, dict):
                    bucket = doc.get("bucket", "public")
                    if bucket == "confidential" or doc.get("confidential"):
                        logger.debug("InputGuard: vault=confidential (doc bucket)")
                        return "confidential"

        return "public"

    async def _check_duplicate(self, query: str) -> bool:
        """Check Redis for a duplicate query within the TTL window."""
        try:
            r = await self._get_redis()
            if r is None:
                return False
            h = hashlib.sha256(query.encode("utf-8")).hexdigest()[:16]
            key = f"{_DEDUP_KEY_PREFIX}{h}"
            existing = await r.get(key)
            if existing is not None:
                logger.debug("InputGuard: duplicate query detected (key=%s)", key)
                return True
            await r.set(key, "1", ex=_DEDUP_TTL_SECONDS)
            return False
        except Exception:
            logger.debug("InputGuard: dedup check failed — skipping")
            return False

    @staticmethod
    def _enforce_token_budget(query: str) -> tuple[str, int]:
        """Approximate token count and truncate if over budget.

        Uses a simple heuristic: ``tokens ~ words * 1.3``.
        Returns ``(possibly_truncated_query, token_count)``.
        """
        words = query.split()
        token_count = int(len(words) * _TOKEN_RATIO)

        if token_count <= _MAX_TOKEN_BUDGET:
            return query, token_count

        # Truncate to fit budget
        max_words = int(_MAX_TOKEN_BUDGET / _TOKEN_RATIO)
        truncated = " ".join(words[:max_words])
        new_token_count = int(max_words * _TOKEN_RATIO)
        logger.warning(
            "InputGuard: query truncated from %d to %d tokens",
            token_count, new_token_count,
        )
        return truncated, new_token_count


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

input_guard = InputGuard()
