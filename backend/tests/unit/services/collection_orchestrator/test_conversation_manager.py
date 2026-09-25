"""Unit tests for ConversationManager (FR1) — no DB, no network."""

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
pytest.skip("Disabled during Ollama removal (Sep 4)", allow_module_level=True)

import app.services.collection_orchestrator.conversation_manager as cm_module
from app.services.collection_orchestrator.conversation_manager import (
    ConversationManager,
    classify_intent,
)
from app.services.smart_folder.entity_resolver import ResolutionResult
from app.services.smart_folder.query_parser import ParsedQuery


def make_user():
    return SimpleNamespace(id=uuid.uuid4(), email="u@example.com", role="user", can_access_confidential=False)


def make_folder(query="Everything about Bank A"):
    return SimpleNamespace(id=uuid.uuid4(), query_text=query)


def make_entity(name="Bank A", entity_type="organization", canonical_id="1234"):
    return SimpleNamespace(id=uuid.uuid4(), name=name, entity_type=entity_type, canonical_id=canonical_id)


@pytest.fixture
def db():
    return AsyncMock()


@pytest.fixture
def audit(monkeypatch):
    mock = AsyncMock()
    monkeypatch.setattr(cm_module.audit_logger, "log_event", mock)
    return mock


@pytest.fixture
def manager():
    return ConversationManager(max_rounds=3)


def patch_parse(monkeypatch, entity="Bank A"):
    parsed = ParsedQuery(
        primary_entity=entity,
        relationship_type="institutional",
        time_range_start=datetime(2020, 1, 1, tzinfo=timezone.utc),
        time_range_end=datetime(2023, 12, 31, tzinfo=timezone.utc),
        focus_aspects=["financial"],
        temporal_scope_description="2020-2023",
    )
    monkeypatch.setattr(cm_module.query_parser, "parse", AsyncMock(return_value=parsed))


class TestIntentClassification:
    @pytest.mark.parametrize(
        "query,expected_intent,expected_types",
        [
            ("Show the trend of payments over time", "trend", {"trend", "descriptive"}),
            ("Compare 2020 vs 2023 expenses", "comparison", {"comparison", "descriptive"}),
            ("Gather all information about Project X", "gather_all", {"descriptive"}),
            ("Find any unusual or suspicious transactions", "anomaly", {"anomaly", "descriptive"}),
            ("Is there a correlation between revenue and costs?", "correlation", {"correlation", "descriptive"}),
            ("Documents about the house", "general", {"descriptive"}),
        ],
    )
    def test_intent_mapping(self, query, expected_intent, expected_types):
        intent, analysis_types = classify_intent(query)
        assert intent == expected_intent
        assert expected_types.issubset(set(analysis_types))


class TestStartSession:
    @pytest.mark.asyncio
    async def test_high_confidence_applied_silently(self, monkeypatch, db, audit, manager):
        patch_parse(monkeypatch)
        monkeypatch.setattr(
            cm_module.entity_resolver,
            "resolve",
            AsyncMock(return_value=ResolutionResult(entity=make_entity(), match_type="exact", confidence=100.0)),
        )
        session = await manager.start_session(make_folder(), make_user(), db)

        assert session.extracted_entities[0]["status"] == "applied"
        assert session.extracted_entities[0]["confidence"] == 1.0
        assert session.rounds[0]["questions"] == []
        audit.assert_awaited_once()
        assert audit.await_args.kwargs["action"] == "clarification_round"

    @pytest.mark.asyncio
    async def test_medium_confidence_listed_for_confirmation(self, monkeypatch, db, audit, manager):
        patch_parse(monkeypatch)
        monkeypatch.setattr(
            cm_module.entity_resolver,
            "resolve",
            AsyncMock(return_value=ResolutionResult(entity=make_entity(), match_type="fuzzy", confidence=75.0)),
        )
        session = await manager.start_session(make_folder(), make_user(), db)

        entity = session.extracted_entities[0]
        assert entity["status"] == "pending_confirmation"
        assert 0.6 <= entity["confidence"] < 0.9
        assert session.rounds[0]["questions"] == []

    @pytest.mark.asyncio
    async def test_low_confidence_triggers_targeted_question(self, monkeypatch, db, audit, manager):
        patch_parse(monkeypatch)
        candidates = [
            make_entity("Bank A", "organization", "1234"),
            make_entity("Bank A", "organization", "9871"),
        ]
        monkeypatch.setattr(
            cm_module.entity_resolver,
            "resolve",
            AsyncMock(return_value=ResolutionResult(
                entity=candidates[0], match_type="fuzzy", confidence=50.0, candidates=candidates,
            )),
        )
        session = await manager.start_session(make_folder(), make_user(), db)

        questions = session.rounds[0]["questions"]
        assert len(questions) == 1
        question = questions[0]
        assert question["kind"] == "entity_disambiguation"
        assert "Did you mean" in question["text"]
        assert len(question["options"]) == 2
        # Options are concrete: name + id + type
        assert "1234" in question["options"][0]["label"]
        assert session.extracted_entities[0]["status"] == "ambiguous"

    @pytest.mark.asyncio
    async def test_unmatched_entity_becomes_assumption(self, monkeypatch, db, audit, manager):
        patch_parse(monkeypatch, entity="Unknown Person")
        monkeypatch.setattr(
            cm_module.entity_resolver,
            "resolve",
            AsyncMock(return_value=ResolutionResult(match_type="none", confidence=0.0)),
        )
        monkeypatch.setattr(cm_module.entity_resolver, "search_candidates", AsyncMock(return_value=[]))

        session = await manager.start_session(make_folder(), make_user(), db)

        assert session.extracted_entities[0]["status"] == "unresolved"
        assert any("Unknown Person" in a for a in session.assumptions)


class TestProcessAnswer:
    async def _ambiguous_session(self, monkeypatch, db, manager):
        patch_parse(monkeypatch)
        candidates = [make_entity("Bank A", "organization", "1234"), make_entity("Bank A", "organization", "9871")]
        monkeypatch.setattr(
            cm_module.entity_resolver,
            "resolve",
            AsyncMock(return_value=ResolutionResult(
                entity=candidates[0], match_type="fuzzy", confidence=50.0, candidates=candidates,
            )),
        )
        return await manager.start_session(make_folder(), make_user(), db)

    @pytest.mark.asyncio
    async def test_answer_applies_chosen_option(self, monkeypatch, db, audit, manager):
        session = await self._ambiguous_session(monkeypatch, db, manager)
        question = session.rounds[0]["questions"][0]
        chosen = question["options"][1]

        result = await manager.process_answer(session, {question["id"]: chosen["value"]}, False, make_user(), db)

        assert result["complete"] is True
        entity = session.extracted_entities[0]
        assert entity["status"] == "applied"
        assert entity["confidence"] == 1.0
        assert entity["canonical_id"] == "9871"
        assert session.status == "completed"

    @pytest.mark.asyncio
    async def test_skip_proceeds_with_best_interpretation(self, monkeypatch, db, audit, manager):
        session = await self._ambiguous_session(monkeypatch, db, manager)

        result = await manager.process_answer(session, None, True, make_user(), db)

        assert result["complete"] is True
        assert session.status == "completed"
        assert any("best interpretation" in a for a in session.assumptions)
        assert audit.await_args.kwargs["action"] == "clarification_skipped"

    @pytest.mark.asyncio
    async def test_round_cap_forces_assumptions(self, monkeypatch, db, audit):
        manager = ConversationManager(max_rounds=2)
        session = await self._ambiguous_session(monkeypatch, db, manager)

        # Round 1: empty answers keep the entity ambiguous → round 2 offered
        result1 = await manager.process_answer(session, {}, False, make_user(), db)
        assert result1["complete"] is False
        assert len(session.rounds) == 2

        # Round 2: still unresolved → cap reached, assumptions stated
        result2 = await manager.process_answer(session, {}, False, make_user(), db)
        assert result2["complete"] is True
        assert session.status == "completed"
        assert any("unresolved after 2 rounds" in a for a in session.assumptions)

    @pytest.mark.asyncio
    async def test_list_answers_align_with_questions(self, monkeypatch, db, audit, manager):
        session = await self._ambiguous_session(monkeypatch, db, manager)
        question = session.rounds[0]["questions"][0]

        result = await manager.process_answer(session, [question["options"][0]["value"]], False, make_user(), db)

        assert result["complete"] is True
        assert session.extracted_entities[0]["canonical_id"] == "1234"


class TestConfirmedParams:
    @pytest.mark.asyncio
    async def test_build_confirmed_params_shape(self, monkeypatch, db, audit, manager):
        patch_parse(monkeypatch)
        monkeypatch.setattr(
            cm_module.entity_resolver,
            "resolve",
            AsyncMock(return_value=ResolutionResult(entity=make_entity(), match_type="exact", confidence=100.0)),
        )
        session = await manager.start_session(make_folder(), make_user(), db)
        session.assumptions = ["Assumed fiscal-year calendar"]

        params = manager.build_confirmed_params(session)

        assert params["date_range"]["from"].startswith("2020-01-01")
        assert params["date_range"]["to"].startswith("2023-12-31")
        assert params["entities"][0]["name"] == "Bank A"
        assert params["entities"][0]["canonical_id"] == "1234"
        assert params["filters"] == {"doc_types": [], "tags": []}
        assert params["sources"] == []
        assert params["analysis_types"] == ["descriptive"]
        assert params["assumptions"] == ["Assumed fiscal-year calendar"]

    @pytest.mark.asyncio
    async def test_param_overrides_from_answers(self, monkeypatch, db, audit, manager):
        patch_parse(monkeypatch)
        monkeypatch.setattr(
            cm_module.entity_resolver,
            "resolve",
            AsyncMock(return_value=ResolutionResult(entity=make_entity(), match_type="exact", confidence=100.0)),
        )
        session = await manager.start_session(make_folder(), make_user(), db)
        await manager.process_answer(
            session, {"doc_types": ["pdf"], "tags": ["finance"]}, False, make_user(), db
        )
        params = manager.build_confirmed_params(session)
        assert params["filters"]["doc_types"] == ["pdf"]
        assert params["filters"]["tags"] == ["finance"]

    @pytest.mark.asyncio
    async def test_confirm_audits_parameters_confirmed(self, monkeypatch, db, audit, manager):
        patch_parse(monkeypatch)
        monkeypatch.setattr(
            cm_module.entity_resolver,
            "resolve",
            AsyncMock(return_value=ResolutionResult(entity=make_entity(), match_type="exact", confidence=100.0)),
        )
        session = await manager.start_session(make_folder(), make_user(), db)

        params = await manager.confirm(session, make_user(), db)

        assert audit.await_args.kwargs["action"] == "parameters_confirmed"
        assert params["entities"][0]["name"] == "Bank A"
        assert session.status == "completed"
