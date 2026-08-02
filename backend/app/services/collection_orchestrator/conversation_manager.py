"""Conversation Manager — FR1 clarification loop for collection requests.

Responsibilities (spec §FR1):
- FR1.1  Start a clarification session for a SmartFolder collection request.
- FR1.2  Entity/intent extraction: reuses smart_folder ``query_parser`` (LLM,
         tier SIMPLE) for NL parsing and ``entity_resolver`` (vault entities
         table) for canonical resolution — the LLM is never used to resolve
         entities against the vault.
- FR1.3  Clarifying questions always offer concrete options derived from
         resolved entities; never open-ended prompts.
- FR1.5  Round cap (settings.COLLECTION_CLARIFICATION_MAX_ROUNDS): after the
         cap the flow proceeds with explicitly stated assumptions.
- FR1.7  Confidence policy: >= 0.9 applied silently, 0.6-0.9 listed in the
         confirmation, < 0.6 triggers a targeted question.
- FR1.8  Intent classification → analysis types (deterministic keyword map).
- Skip is allowed anytime ("proceed with best interpretation").

Session state is persisted on the ``ClarificationSession`` JSONB columns.
The parsed date range / focus aspects have no dedicated column, so they are
stored under ``rounds[0]["extraction"]`` (JSONB is schemaless); this is the
single documented place ``build_confirmed_params`` reads them from.
"""

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.collection_orchestrator import ClarificationSession
from app.services.collection_orchestrator import audit_logger
from app.services.smart_folder.entity_resolver import entity_resolver
from app.services.smart_folder.query_parser import query_parser

logger = logging.getLogger(__name__)


def _default_max_rounds() -> int:
    """Lazy settings access — keeps module import free of config/env requirements."""
    from app.core.config import settings

    return settings.COLLECTION_CLARIFICATION_MAX_ROUNDS

# ── FR1.7 confidence policy thresholds ──────────────────────────────────────
AUTO_APPLY_THRESHOLD = 0.9   # >= 0.9: applied silently
CONFIRM_THRESHOLD = 0.6      # 0.6-0.9: listed in confirmation; < 0.6: question
MAX_QUESTION_OPTIONS = 5

# ── FR1.8 intent → analysis types (deterministic keyword map) ───────────────
INTENT_KEYWORDS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("trend", "evolution", "évolution", "over time", "progression", "évolu"), "trend"),
    (("compare", "compar", "versus", " vs ", "difference", "différence"), "comparison"),
    (
        ("correlat", "corrélation", "relationship between", "relation between",
         "link between", "lien entre", "association between"),
        "correlation",
    ),
    (
        ("gather all", "all information", "everything about", "collect all",
         "toutes les informations", "tout sur", "rassembler"),
        "gather_all",
    ),
    (
        ("anomal", "unusual", "outlier", "abnormal", "irrégulier", "suspicious",
         "suspect", "fraud", "fraude", "étrange"),
        "anomaly",
    ),
)

INTENT_TO_ANALYSIS_TYPES: dict[str, list[str]] = {
    "trend": ["trend", "descriptive"],
    "comparison": ["comparison", "descriptive"],
    "correlation": ["correlation", "descriptive"],
    "gather_all": ["descriptive"],
    "anomaly": ["anomaly", "descriptive"],
    "general": ["descriptive"],
}


def classify_intent(query_text: str) -> tuple[str, list[str]]:
    """Map a natural-language query to an intent label and analysis types.

    Deterministic (FR1.8): the first matching keyword group wins for the
    label; analysis types are the union of all matched groups.
    """
    text = f" {query_text.lower()} "
    matched: list[str] = []
    for keywords, intent in INTENT_KEYWORDS:
        if any(kw in text for kw in keywords):
            matched.append(intent)
    if not matched:
        return "general", list(INTENT_TO_ANALYSIS_TYPES["general"])
    analysis_types: list[str] = []
    for intent in matched:
        for at in INTENT_TO_ANALYSIS_TYPES[intent]:
            if at not in analysis_types:
                analysis_types.append(at)
    return "+".join(matched), analysis_types


def _entity_option_label(entity: Any) -> str:
    """Concrete option label, e.g. 'Bank A (id 1234, organization)'."""
    entity_id = getattr(entity, "canonical_id", None) or getattr(entity, "id", None)
    entity_type = getattr(entity, "entity_type", None)
    entity_type = getattr(entity_type, "value", entity_type)  # enum → value
    parts = [str(getattr(entity, "name", "?"))]
    suffix = ", ".join(p for p in (f"id {entity_id}" if entity_id else "", str(entity_type) if entity_type else "") if p)
    return f"{parts[0]} ({suffix})" if suffix else parts[0]


def _entity_dict(entity: Any, *, confidence: float, status: str, raw_name: str | None = None) -> dict[str, Any]:
    entity_type = getattr(entity, "entity_type", None)
    entity_type = getattr(entity_type, "value", entity_type)
    return {
        "name": getattr(entity, "name", raw_name),
        "type": entity_type,
        "canonical_id": str(getattr(entity, "canonical_id", None) or getattr(entity, "id", "") or "") or None,
        "confidence": round(confidence, 4),
        "status": status,
        "raw_name": raw_name or getattr(entity, "name", None),
    }


class ConversationManager:
    """Drives the FR1 clarification loop for one collection request."""

    def __init__(self, max_rounds: int | None = None):
        self._max_rounds = max_rounds

    @property
    def max_rounds(self) -> int:
        return self._max_rounds or _default_max_rounds()

    @max_rounds.setter
    def max_rounds(self, value: int | None) -> None:
        self._max_rounds = value

    # ── FR1.1 / FR1.2 / FR1.3 ───────────────────────────────────────────────
    async def start_session(self, smart_folder: Any, user: Any, db: AsyncSession) -> ClarificationSession:
        """Create a ClarificationSession and decide round-1 questions."""
        query_text = smart_folder.query_text

        parsed = await query_parser.parse(query_text)
        intent, analysis_types = classify_intent(query_text)

        entities: list[dict[str, Any]] = []
        questions: list[dict[str, Any]] = []
        ambiguities: list[dict[str, Any]] = []
        assumptions: list[str] = []

        entity_names = [parsed.primary_entity] if parsed.primary_entity else []
        for name in entity_names:
            entity_dict, question = await self._resolve_entity(db, name, user)
            entities.append(entity_dict)
            if question is not None:
                questions.append(question)
                ambiguities.append({"kind": "entity", "name": name, "question_id": question["id"]})
            elif entity_dict["status"] == "unresolved":
                ambiguities.append({"kind": "entity", "name": name, "question_id": None})
                assumptions.append(
                    f"Entity '{name}' not found in the vault; searching by name as free text."
                )

        extraction = {
            "time_range_start": parsed.time_range_start.isoformat() if parsed.time_range_start else None,
            "time_range_end": parsed.time_range_end.isoformat() if parsed.time_range_end else None,
            "temporal_scope_description": parsed.temporal_scope_description,
            "focus_aspects": parsed.focus_aspects or [],
            "relationship_type": parsed.relationship_type,
        }

        session = ClarificationSession(
            request_id=smart_folder.id,
            rounds=[{
                "round": 1,
                "questions": questions,
                "answers": [],
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "extraction": extraction,
            }],
            extracted_entities=entities,
            extracted_intent=intent,
            analysis_types=analysis_types,
            open_ambiguities=ambiguities,
            assumptions=assumptions,
            status="active",
        )
        db.add(session)
        await db.flush()

        await audit_logger.log_event(
            db,
            request_id=smart_folder.id,
            user_id=getattr(user, "id", None),
            stage="clarify",
            action="clarification_round",
            detail={
                "round": 1,
                "question_count": len(questions),
                "entities": [{"name": e["name"], "confidence": e["confidence"], "status": e["status"]} for e in entities],
                "intent": intent,
                "analysis_types": analysis_types,
            },
        )
        return session

    async def _resolve_entity(
        self, db: AsyncSession, name: str, user: Any
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        """FR1.7 confidence policy for one extracted entity name."""
        resolution = await entity_resolver.resolve(db, name, user_id=str(getattr(user, "id", "")))
        confidence = (resolution.confidence or 0.0) / 100.0  # resolver uses 0-100

        if resolution.match_type != "none" and resolution.entity is not None:
            if confidence >= AUTO_APPLY_THRESHOLD:
                return _entity_dict(resolution.entity, confidence=confidence, status="applied", raw_name=name), None
            if confidence >= CONFIRM_THRESHOLD:
                return _entity_dict(resolution.entity, confidence=confidence, status="pending_confirmation", raw_name=name), None
            # < 0.6 → targeted question with the resolver's candidates
            candidates = resolution.candidates or []
            if resolution.entity is not None and resolution.entity not in candidates:
                candidates = [resolution.entity, *candidates]
            if not candidates:
                candidates = list(await entity_resolver.search_candidates(db, name, limit=MAX_QUESTION_OPTIONS))
            question = self._build_entity_question(name, candidates, best=resolution.entity)
            return _entity_dict(resolution.entity, confidence=confidence, status="ambiguous", raw_name=name), question

        # No match at all: offer near-name candidates if any exist
        candidates = list(await entity_resolver.search_candidates(db, name, limit=MAX_QUESTION_OPTIONS))
        unresolved = {"name": name, "type": None, "canonical_id": None, "confidence": 0.0,
                      "status": "unresolved", "raw_name": name}
        if candidates:
            return unresolved, self._build_entity_question(name, candidates, best=None)
        return unresolved, None

    def _build_entity_question(self, raw_name: str, candidates: list[Any], best: Any | None) -> dict[str, Any]:
        """FR1.3: targeted question with concrete candidate options."""
        options = [
            {"value": _entity_option_label(c), "label": _entity_option_label(c),
             "canonical_id": str(getattr(c, "canonical_id", None) or getattr(c, "id", "") or "") or None,
             "name": getattr(c, "name", None)}
            for c in candidates[:MAX_QUESTION_OPTIONS]
        ]
        if len(options) >= 2:
            choice_text = " or ".join(o["label"] for o in options[:2])
            if len(options) > 2:
                choice_text = ", ".join(o["label"] for o in options)
            text = f"Did you mean {choice_text}?"
        elif options:
            text = f"Did you mean {options[0]['label']}?"
        else:
            text = f"Which '{raw_name}' do you mean?"
        return {
            "id": f"entity_{abs(hash(raw_name)) % 100000}",
            "kind": "entity_disambiguation",
            "target": raw_name,
            "text": text,
            "options": options,
            "best_guess": _entity_option_label(best) if best is not None else None,
        }

    # ── FR1.4 / FR1.5 / FR1.6 (skip) ────────────────────────────────────────
    async def process_answer(
        self,
        session: ClarificationSession,
        answers: dict | list | None,
        skip: bool,
        user: Any,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """Apply answers (or a skip) to the current round.

        Returns {"complete": bool, "session": session, "questions": [...]}.
        """
        current_round = (session.rounds or [])[-1] if session.rounds else None

        if skip:
            session.assumptions = list(session.assumptions or []) + [
                "User skipped clarification; proceeding with best interpretation."
            ]
            for ambiguity in session.open_ambiguities or []:
                session.assumptions.append(
                    f"Unresolved ambiguity '{ambiguity.get('name')}' — using best interpretation."
                )
            session.open_ambiguities = []
            session.status = "completed"
            await db.flush()
            await audit_logger.log_event(
                db,
                request_id=session.request_id,
                user_id=getattr(user, "id", None),
                stage="clarify",
                action="clarification_skipped",
                detail={"round": len(session.rounds or []), "assumptions": session.assumptions},
            )
            return {"complete": True, "session": session, "questions": []}

        # Normalise answers to {question_id: value}
        normalized = self._normalize_answers(current_round, answers)
        if current_round is not None:
            current_round["answers"] = [
                {"question_id": qid, "answer": value} for qid, value in normalized.items()
            ]

        # Apply entity answers (FR1.4): the chosen option becomes canonical.
        entities = list(session.extracted_entities or [])
        for question in (current_round or {}).get("questions", []):
            if question.get("kind") != "entity_disambiguation":
                continue
            answer = normalized.get(question["id"])
            if answer is None:
                continue
            self._apply_entity_answer(entities, question, answer)
        session.extracted_entities = entities

        # Structured filter overrides from free-form answer keys
        extras = self._extract_param_overrides(answers)

        # Decide the next step: remaining ambiguities vs round cap (FR1.5)
        remaining = [e for e in entities if e["status"] in ("ambiguous",) ]
        rounds_used = len(session.rounds or [])
        next_questions: list[dict[str, Any]] = []

        if remaining and rounds_used < self.max_rounds:
            for entity in remaining:
                # Re-offer the same candidates; the user may pick again or skip.
                question = self._reoffer_question(entity, session)
                if question is not None:
                    next_questions.append(question)
            session.rounds.append({
                "round": rounds_used + 1,
                "questions": next_questions,
                "answers": [],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            complete = not next_questions
        elif remaining and rounds_used >= self.max_rounds:
            # FR1.5: round cap reached — proceed with stated assumptions
            assumptions = list(session.assumptions or [])
            for entity in remaining:
                assumptions.append(
                    f"Entity '{entity['raw_name']}' unresolved after {rounds_used} rounds; "
                    f"proceeding with best interpretation '{entity['name']}'."
                )
                entity["status"] = "pending_confirmation"
            session.assumptions = assumptions
            session.extracted_entities = entities
            complete = True
        else:
            complete = True

        if complete:
            session.status = "completed"
            session.open_ambiguities = []

        if extras:
            session.rounds[-1]["param_overrides"] = extras

        await db.flush()
        await audit_logger.log_event(
            db,
            request_id=session.request_id,
            user_id=getattr(user, "id", None),
            stage="clarify",
            action="clarification_round",
            detail={
                "round": rounds_used,
                "answers": {k: str(v)[:200] for k, v in normalized.items()},
                "complete": complete,
                "next_question_count": len(next_questions),
                "assumptions": session.assumptions or [],
            },
        )
        return {"complete": complete, "session": session, "questions": next_questions}

    def _reoffer_question(self, entity: dict[str, Any], session: ClarificationSession) -> dict[str, Any] | None:
        """Re-ask for a still-ambiguous entity using options from round 1."""
        for round_ in session.rounds or []:
            for question in round_.get("questions", []):
                if question.get("kind") == "entity_disambiguation" and question.get("target") == entity.get("raw_name"):
                    return {**question, "id": f"{question['id']}_r{len(session.rounds) + 1}"}
        return None

    @staticmethod
    def _normalize_answers(current_round: dict[str, Any] | None, answers: dict | list | None) -> dict[str, Any]:
        if not answers:
            return {}
        if isinstance(answers, dict):
            return {str(k): v for k, v in answers.items()}
        # List form: align positionally with the round's questions
        questions = (current_round or {}).get("questions", [])
        normalized: dict[str, Any] = {}
        for question, answer in zip(questions, answers):
            normalized[question["id"]] = answer
        return normalized

    @staticmethod
    def _apply_entity_answer(entities: list[dict[str, Any]], question: dict[str, Any], answer: Any) -> None:
        target = question.get("target")
        chosen = None
        answer_str = str(answer)
        for option in question.get("options", []):
            if answer_str in (str(option.get("value")), str(option.get("canonical_id")), str(option.get("name"))):
                chosen = option
                break
        for entity in entities:
            if entity.get("raw_name") != target:
                continue
            if chosen is not None:
                entity.update({
                    "name": chosen.get("name") or entity["name"],
                    "canonical_id": chosen.get("canonical_id"),
                    "confidence": 1.0,
                    "status": "applied",
                })
            else:
                # Free-text answer: treat as user-supplied canonical name
                entity.update({"name": answer_str, "confidence": 1.0, "status": "applied"})

    @staticmethod
    def _extract_param_overrides(answers: dict | list | None) -> dict[str, Any]:
        """Pull structured filter overrides out of a dict-shaped answer set."""
        if not isinstance(answers, dict):
            return {}
        extras: dict[str, Any] = {}
        for key in ("date_from", "date_to", "doc_types", "tags", "sources"):
            if answers.get(key):
                extras[key] = answers[key]
        return extras

    # ── Confirmation ────────────────────────────────────────────────────────
    async def confirm(self, session: ClarificationSession, user: Any, db: AsyncSession) -> dict[str, Any]:
        """Freeze parameters (caller writes them to SmartFolder.confirmed_params)."""
        session.status = "completed"
        params = self.build_confirmed_params(session)
        await db.flush()
        await audit_logger.log_event(
            db,
            request_id=session.request_id,
            user_id=getattr(user, "id", None),
            stage="clarify",
            action="parameters_confirmed",
            detail={"confirmed_params": params},
        )
        return params

    def build_confirmed_params(self, session: ClarificationSession) -> dict[str, Any]:
        """Build the immutable confirmed-params dict (FR1.6 output shape)."""
        extraction: dict[str, Any] = {}
        overrides: dict[str, Any] = {}
        for round_ in session.rounds or []:
            if round_.get("extraction"):
                extraction = round_["extraction"]
            if round_.get("param_overrides"):
                overrides.update(round_["param_overrides"])

        entities = [
            {k: e.get(k) for k in ("name", "type", "canonical_id", "confidence")}
            for e in session.extracted_entities or []
            if e.get("status") != "unresolved"
        ]
        return {
            "date_range": {
                "from": overrides.get("date_from") or extraction.get("time_range_start"),
                "to": overrides.get("date_to") or extraction.get("time_range_end"),
            },
            "entities": entities,
            "filters": {
                "doc_types": overrides.get("doc_types") or [],
                "tags": overrides.get("tags") or [],
            },
            "sources": overrides.get("sources") or [],
            "analysis_types": list(session.analysis_types or []),
            "assumptions": list(session.assumptions or []),
        }


# Module-level singleton
conversation_manager = ConversationManager()
