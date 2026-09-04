import pytest
@pytest.mark.skip(reason="Ollama removed")
"""Unit tests for the learned-skill model + skill extraction guard logic."""

from app.models.learned_skill import LearnedSkill, SkillStatus


class TestLearnedSkillModel:
    def test_defaults_draft(self):
        from uuid import uuid4

        skill = LearnedSkill(
            id=uuid4(),
            owner_id=uuid4(),
            title="Collection audit",
            trigger="when x",
            steps=["a", "b"],
            validation=["ok?"],
            source_type="collection",
        )
        # The column default is applied by the DB; the model column default
        # enum constant is what matters for the review-gating contract.
        assert SkillStatus.DRAFT.value == "draft"
        assert skill.status in (None, SkillStatus.DRAFT.value)


class TestSkillExtractionGuards:
    def test_min_stages(self):
        from app.services.skill_extraction_service import SkillExtractionService

        svc = SkillExtractionService()
        assert svc.MIN_STAGES == 3

    def test_poor_trace_returns_none(self):
        """A trace too poor to distill must yield None, never a guess."""
        import asyncio

        from app.services.skill_extraction_service import SkillExtractionService

        # _distill with a tiny/garbage trace exercises the failure path.
        result = asyncio.run(SkillExtractionService()._distill([]))
        assert result is None
