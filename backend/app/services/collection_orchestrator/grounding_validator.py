"""Grounding Validator — FR4.2.5.

Rule-based (no LLM) verification that every numeric claim in the generated
narrative traces back to the computed analysis outputs or validated
insights. Tolerance contract: a narrative number is accepted iff it is
exactly equal to a computed value, or it equals a ``format_number``
rendering of a computed value — percentages are rendered with 1 decimal,
non-integer floats with 2 (that rendering is the ONLY sanctioned rounding;
see ``summary_generator.format_number``).
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable
from uuid import UUID

from app.services.collection_orchestrator.audit_logger import log_event
from app.services.collection_orchestrator.summary_generator import format_number

logger = logging.getLogger(__name__)

# Same regex family as extraction_pipeline (keep in sync).
_TOKEN_RE = re.compile(
    r"-?\d{1,3}(?:[ ,]\d{3})+(?:\.\d+)?%?|-?\d+(?:\.\d+)?%?"
)
_ISO_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_CITATION_RE = re.compile(r"\(\[source:([^\]]*)\]\)")
_LIST_MARKER_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")


@dataclass
class ValidationReport:
    passed: bool
    checked_claims: int = 0
    failed_claims: list[dict] = field(default_factory=list)
    numeric_failures: list[dict] = field(default_factory=list)


class GroundingValidator:
    """FR4.2.5: verify / strip / regenerate grounded narratives."""

    # ------------------------------------------------------------------
    # validate
    # ------------------------------------------------------------------

    def validate(
        self,
        summary_md: str,
        analyses: list[dict],
        insights: list[dict],
    ) -> ValidationReport:
        computed = self._computed_numbers(analyses, insights)
        accepted_strings = self._accepted_strings(computed)
        known_refs = self._known_refs(analyses, insights)
        insight_numbers = [
            self._numbers_in(insight.get("statement", "")) for insight in insights
        ]

        checked = 0
        failed_claims: list[dict] = []
        numeric_failures: list[dict] = []

        for sentence in self._sentences(summary_md):
            tokens = self._number_tokens(sentence)
            if not tokens:
                continue
            checked += 1

            bad = [
                t for t in tokens
                if not self._token_accepted(t, computed, accepted_strings)
            ]
            if bad:
                for token in bad:
                    numeric_failures.append(
                        {
                            "sentence": sentence,
                            "value": token,
                            "reason": (
                                f"number '{token}' matches no computed analysis "
                                "output or validated insight"
                            ),
                        }
                    )
                failed_claims.append(
                    {"sentence": sentence, "reason": "ungrounded numeric value(s)"}
                )
                continue

            # Claim mapping (FR4.2.5): the sentence must share a number with
            # a validated insight statement or an analysis output, or cite a
            # known source ref.
            sentence_numbers = {self._token_float(t) for t in tokens}
            mapped = any(
                sentence_numbers & set(nums) for nums in insight_numbers
            ) or bool(sentence_numbers & computed)
            citation = _CITATION_RE.search(sentence)
            if citation and not self._citation_known(citation.group(1), known_refs):
                failed_claims.append(
                    {
                        "sentence": sentence,
                        "reason": "citation matches no validated source ref",
                    }
                )
            elif not mapped and not citation:
                failed_claims.append(
                    {
                        "sentence": sentence,
                        "reason": "claim maps to no validated insight or analysis output",
                    }
                )

        return ValidationReport(
            passed=not failed_claims and not numeric_failures,
            checked_claims=checked,
            failed_claims=failed_claims,
            numeric_failures=numeric_failures,
        )

    # ------------------------------------------------------------------
    # strip
    # ------------------------------------------------------------------

    def strip_ungrounded(
        self, summary_md: str, report: ValidationReport
    ) -> tuple[str, list[str]]:
        """Remove exactly the failing sentences. The caller appends the
        FR4.2.5 disclosure footer ('N statement(s) removed ...')."""
        removed: list[str] = []
        for entry in report.failed_claims + report.numeric_failures:
            sentence = entry["sentence"]
            if sentence not in removed:
                removed.append(sentence)
        cleaned = summary_md
        for sentence in removed:
            cleaned = cleaned.replace(sentence, "")
        # Drop lines hollowed out to an empty bullet / stray punctuation.
        kept_lines = []
        for line in cleaned.splitlines():
            stripped = _LIST_MARKER_RE.sub("", line).strip(" .-\t")
            if not line.strip():
                kept_lines.append(line)
            elif stripped:
                kept_lines.append(line)
            # else: line was only the removed sentence -> drop it
        return "\n".join(kept_lines), removed

    # ------------------------------------------------------------------
    # validate with regeneration (orchestration helper)
    # ------------------------------------------------------------------

    async def validate_with_regeneration(
        self,
        summary_fn: Callable[[], Awaitable[str | None]],
        analyses: list[dict],
        insights: list[dict],
        max_attempts: int = 2,
        db: Any = None,
        request_id: UUID | None = None,
        user_id: UUID | None = None,
    ) -> tuple[str | None, ValidationReport, list[str]]:
        """Generate → validate → retry up to ``max_attempts``; on final
        failure strip the ungrounded sentences and return what remains.

        Returns (final_md, report, removed_sentences). Audit events are
        written only when a db session is provided (stage="validate").
        """
        last_md: str | None = None
        last_report = ValidationReport(passed=False)
        for attempt in range(1, max_attempts + 1):
            md = await summary_fn()
            if md is None:
                # FR6.1 — nothing validated to narrate; do not fabricate.
                report = ValidationReport(passed=False, checked_claims=0)
                return None, report, []
            report = self.validate(md, analyses, insights)
            last_md, last_report = md, report
            await self._audit(
                db, request_id, user_id,
                action="claims_validated" if report.passed else "claim_rejected",
                status="success" if report.passed else "failure",
                detail={
                    "attempt": attempt,
                    "checked_claims": report.checked_claims,
                    "failed_claims": len(report.failed_claims),
                    "numeric_failures": len(report.numeric_failures),
                },
            )
            if report.passed:
                return md, report, []

        cleaned, removed = self.strip_ungrounded(last_md or "", last_report)
        return cleaned, last_report, removed

    async def _audit(
        self, db: Any, request_id: UUID | None, user_id: UUID | None,
        *, action: str, status: str, detail: dict,
    ) -> None:
        if db is None or request_id is None:
            return
        await log_event(
            db,
            request_id=request_id,
            user_id=user_id,
            stage="validate",
            action=action,
            status=status,
            detail=detail,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @classmethod
    def _sentences(cls, md: str) -> list[str]:
        sentences: list[str] = []
        for line in md.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            line = _LIST_MARKER_RE.sub("", line)  # drop bullet markers
            # Protect citations before splitting — "p. 3" must not break a
            # sentence in two.
            citations: dict[str, str] = {}

            def _protect(match: re.Match) -> str:
                key = f"\x00{len(citations)}\x00"
                citations[key] = match.group(0)
                return key

            protected = _CITATION_RE.sub(_protect, line)
            # Split on sentence terminators followed by whitespace; keep the
            # terminator attached to the preceding sentence.
            for part in re.split(r"(?<=[.!?])\s+", protected):
                sentence = part
                for key, original in citations.items():
                    sentence = sentence.replace(key, original)
                if cls._number_tokens(sentence):
                    sentences.append(sentence)
        return sentences

    @staticmethod
    def _number_tokens(text: str) -> list[str]:
        """Numeric tokens, excluding citations and ISO dates."""
        scrubbed = _CITATION_RE.sub(" ", text)
        scrubbed = _ISO_DATE_RE.sub(" ", scrubbed)
        return [m.group(0) for m in _TOKEN_RE.finditer(scrubbed)]

    @staticmethod
    def _token_float(token: str) -> float:
        return float(
            token.rstrip("%").replace(",", "").replace(" ", "").replace(" ", "")
        )

    @classmethod
    def _numbers_in(cls, text: str) -> list[float]:
        return [cls._token_float(t) for t in cls._number_tokens(text)]

    @classmethod
    def _computed_numbers(
        cls, analyses: list[dict], insights: list[dict]
    ) -> set[float]:
        numbers: set[float] = set()

        def walk(node: Any) -> None:
            if isinstance(node, bool):
                return
            if isinstance(node, (int, float)):
                numbers.add(float(node))
            elif isinstance(node, dict):
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)

        for analysis in analyses:
            walk(analysis.get("output", {}))
        for insight in insights:
            numbers.update(cls._numbers_in(insight.get("statement", "")))
        return numbers

    @staticmethod
    def _accepted_strings(computed: set[float]) -> set[str]:
        """The exact strings the generator may legitimately print."""
        accepted: set[str] = set()
        for value in computed:
            accepted.add(format_number(value))
            accepted.add(format_number(value) + "%")
            accepted.add(format_number(value, "%"))
        return accepted

    @classmethod
    def _token_accepted(
        cls, token: str, computed: set[float], accepted_strings: set[str]
    ) -> bool:
        normalized = token.replace(" ", ",").replace(" ", ",")
        if normalized in accepted_strings:
            return True
        try:
            return cls._token_float(token) in computed
        except ValueError:
            return False

    @staticmethod
    def _known_refs(analyses: list[dict], insights: list[dict]) -> list[dict]:
        refs: list[dict] = []
        for insight in insights:
            refs.extend(r for r in insight.get("source_refs", []) if isinstance(r, dict))
        for analysis in analyses:
            refs.extend(r for r in analysis.get("provenance", []) if isinstance(r, dict))
        return refs

    @staticmethod
    def _citation_known(citation_text: str, known_refs: list[dict]) -> bool:
        text = citation_text.lower()
        for ref in known_refs:
            title = str(ref.get("title") or "").lower()
            if title and title in text:
                return True
            doc_id = str(ref.get("document_id") or "").lower()
            if doc_id and doc_id in text:
                return True
            page = ref.get("page")
            if page is not None and (
                f"p. {page}" in text or f"page {page}" in text
            ):
                return True
        return False
