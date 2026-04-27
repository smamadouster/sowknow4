import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.smart_folder.agent.executor import SkillExecutor
from app.services.smart_folder.agent.planner import Planner, Plan, PlanStep
from app.services.smart_folder.agent.synthesizer import Synthesizer
from app.services.smart_folder.skills.base import SkillResult


class TestPlanner:
    """Unit tests for the agent Planner."""

    @pytest.fixture
    def planner(self):
        return Planner()

    @pytest.mark.asyncio
    async def test_plan_classifies_financial_intent(self, monkeypatch, planner):
        """Test that financial queries are classified correctly."""

        async def mock_generate(*args, **kwargs):
            yield json.dumps({
                "intent": "financial analysis of balance sheets",
                "primary_skill": "financial_analysis",
                "reasoning": "Query mentions balance sheets",
                "steps": [
                    {
                        "step_id": "1",
                        "skill_id": "financial_analysis",
                        "description": "Parse financial documents",
                        "parameters": {},
                        "dependencies": [],
                    }
                ],
            })

        monkeypatch.setattr(
            "app.services.smart_folder.agent.planner.llm_router.generate_completion",
            mock_generate,
        )

        plan = await planner.plan("Analyse the balance sheets of Company X")

        assert plan.primary_skill == "financial_analysis"
        assert plan.intent == "financial analysis of balance sheets"
        assert len(plan.steps) == 1
        assert plan.steps[0].skill_id == "financial_analysis"

    @pytest.mark.asyncio
    async def test_plan_fallback_on_invalid_json(self, monkeypatch, planner):
        """Test fallback to general_narrative on bad LLM output."""

        async def mock_generate(*args, **kwargs):
            yield "not json"

        monkeypatch.setattr(
            "app.services.smart_folder.agent.planner.llm_router.generate_completion",
            mock_generate,
        )

        plan = await planner.plan("Something vague")

        assert plan.primary_skill == "general_narrative"
        assert "parse failed" in plan.reasoning.lower() or "error" in plan.reasoning.lower()

    @pytest.mark.asyncio
    async def test_plan_fallback_on_unknown_skill(self, monkeypatch, planner):
        """Test fallback when LLM returns an unknown skill ID."""

        async def mock_generate(*args, **kwargs):
            yield json.dumps({
                "intent": "unknown",
                "primary_skill": "nonexistent_skill",
                "steps": [],
            })

        monkeypatch.setattr(
            "app.services.smart_folder.agent.planner.llm_router.generate_completion",
            mock_generate,
        )

        plan = await planner.plan("Query")

        assert plan.primary_skill == "general_narrative"


class TestSkillExecutor:
    """Unit tests for the SkillExecutor."""

    @pytest.fixture
    def executor(self):
        return SkillExecutor(max_retries=0)

    @pytest.mark.asyncio
    async def test_execute_successful_skill(self, monkeypatch, executor):
        """Test execution of a skill that succeeds."""

        async def mock_analyze(*args, **kwargs):
            return SkillResult(skill_id="general_narrative", success=True, text_summary="OK")

        monkeypatch.setattr(
            "app.services.smart_folder.skills.general_narrative.GeneralNarrativeSkill.analyze",
            mock_analyze,
        )

        plan = Plan(
            intent="test",
            primary_skill="general_narrative",
            steps=[PlanStep(step_id="1", skill_id="general_narrative", description="Test")],
        )
        results = await executor.execute(plan, {"db": MagicMock(), "user": MagicMock()})

        assert "1" in results
        assert results["1"].success is True
        assert results["1"].text_summary == "OK"

    @pytest.mark.asyncio
    async def test_execute_unknown_skill(self, executor):
        """Test execution with an unknown skill ID."""

        plan = Plan(
            intent="test",
            primary_skill="unknown",
            steps=[PlanStep(step_id="1", skill_id="unknown_skill_xyz", description="Test")],
        )
        results = await executor.execute(plan, {})

        assert "1" in results
        assert results["1"].success is False
        assert "Unknown skill" in results["1"].error

    @pytest.mark.asyncio
    async def test_cache_hit(self, monkeypatch, executor):
        """Test that identical steps are cached."""

        call_count = 0

        async def mock_analyze(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return SkillResult(skill_id="general_narrative", success=True, text_summary="OK")

        monkeypatch.setattr(
            "app.services.smart_folder.skills.general_narrative.GeneralNarrativeSkill.analyze",
            mock_analyze,
        )

        plan = Plan(
            intent="test",
            primary_skill="general_narrative",
            steps=[
                PlanStep(step_id="1", skill_id="general_narrative", description="Test", parameters={"a": 1}),
                PlanStep(step_id="2", skill_id="general_narrative", description="Test", parameters={"a": 1}),
            ],
        )
        await executor.execute(plan, {"db": MagicMock(), "user": MagicMock()})

        assert call_count == 1  # Second step should hit cache


class TestSynthesizer:
    """Unit tests for the Synthesizer."""

    @pytest.fixture
    def synthesizer(self):
        return Synthesizer()

    @pytest.mark.asyncio
    async def test_synthesize_single_skill_output(self, monkeypatch, synthesizer):
        """Test synthesis when one skill returns a complete report."""

        async def mock_generate(*args, **kwargs):
            yield json.dumps({
                "title": "Report",
                "summary": "Summary",
                "timeline": [],
                "patterns": [],
                "trends": [],
                "issues": [],
                "learnings": [],
                "recommendations": [],
                "raw_markdown": "# Report",
            })

        monkeypatch.setattr(
            "app.services.smart_folder.agent.synthesizer.llm_router.generate_completion",
            mock_generate,
        )

        skill_results = {
            "1": SkillResult(
                skill_id="general_narrative",
                success=True,
                text_summary="Summary",
                raw_output={
                    "title": "Report",
                    "summary": "Summary",
                    "timeline": [],
                    "raw_markdown": "# Report",
                },
            ),
        }

        result = await synthesizer.synthesize("Query", "Entity", "general", skill_results)

        assert result["title"] == "Report"
        assert "summary" in result

    @pytest.mark.asyncio
    async def test_synthesize_fallback_on_invalid_json(self, monkeypatch, synthesizer):
        """Test fallback when synthesizer returns invalid JSON."""

        async def mock_generate(*args, **kwargs):
            yield "not json"

        monkeypatch.setattr(
            "app.services.smart_folder.agent.synthesizer.llm_router.generate_completion",
            mock_generate,
        )

        skill_results = {
            "1": SkillResult(skill_id="custom_query", success=True, text_summary="Found docs"),
        }

        result = await synthesizer.synthesize("Query", None, "general", skill_results)

        assert "title" in result
        assert "could not be fully synthesized" in result["summary"].lower() or "failed" in result["summary"].lower()
