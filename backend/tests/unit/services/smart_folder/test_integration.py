"""Integration tests for the Smart Folder v2 pipeline.

Tests the full flow: query → parser → resolver → retrieval → analysis → report.
LLM calls are mocked to avoid external dependencies.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge_graph import Entity, EntityType
from app.models.smart_folder import SmartFolder, SmartFolderStatus
from app.models.user import User, UserRole
from app.services.smart_folder.agent_runner import SmartFolderAgentRunner


class TestSmartFolderPipeline:
    """End-to-end pipeline integration tests."""

    @pytest.fixture
    def agent_runner(self):
        return SmartFolderAgentRunner()

    @pytest.fixture
    def mock_user(self):
        user = MagicMock(spec=User)
        user.id = uuid.uuid4()
        user.email = "test@example.com"
        user.role = UserRole.USER
        user.can_access_confidential = False
        return user

    @pytest.fixture
    def mock_db(self):
        db = MagicMock(spec=AsyncSession)
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        return db

    @pytest.mark.asyncio
    async def test_full_pipeline_creates_smart_folder_and_report(
        self, agent_runner, mock_user, mock_db, monkeypatch
    ):
        """Test that a complete run creates a SmartFolder and SmartFolderReport."""

        from app.services.smart_folder.query_parser import ParsedQuery
        from app.services.smart_folder.entity_resolver import ResolutionResult
        from app.services.smart_folder.agent.planner import Plan, PlanStep
        from app.services.smart_folder.skills.base import SkillResult

        # Mock query parser
        async def mock_parse(query):
            return ParsedQuery(
                primary_entity="Bank A",
                relationship_type="institutional",
                temporal_scope_description="all time",
                focus_aspects=["financial"],
            )

        monkeypatch.setattr(
            "app.services.smart_folder.agent_runner.query_parser.parse",
            mock_parse,
        )

        entity = Entity(
            id=uuid.uuid4(),
            name="Bank A",
            entity_type=EntityType.ORGANIZATION,
            aliases=["BankA"],
        )

        # Mock entity resolver
        async def mock_resolve(db, name):
            return ResolutionResult(entity=entity, match_type="exact", confidence=100.0)

        monkeypatch.setattr(
            "app.services.smart_folder.agent_runner.entity_resolver.resolve",
            mock_resolve,
        )

        # Mock planner on instance
        agent_runner.planner.plan = AsyncMock(return_value=Plan(
            intent="test",
            primary_skill="general_narrative",
            steps=[PlanStep(step_id="1", skill_id="general_narrative", description="Test")],
        ))

        # Mock executor on instance
        agent_runner.executor.execute = AsyncMock(return_value={
            "1": SkillResult(
                skill_id="general_narrative",
                success=True,
                text_summary="Bank A relationship summary",
                raw_output={
                    "title": "Smart Folder: Bank A",
                    "summary": "Test summary [asset-123]",
                    "timeline": [],
                    "patterns": [],
                    "trends": [],
                    "issues": [],
                    "learnings": [],
                    "recommendations": [],
                    "raw_markdown": "# Smart Folder: Bank A\n\nTest summary [asset-123]",
                },
                citations=[{"asset_id": "asset-123", "preview": "Test snippet"}],
            ),
        })

        smart_folder = SmartFolder(
            id=uuid.uuid4(),
            user_id=mock_user.id,
            name="Test",
            query_text="Tell me about Bank A",
            status=SmartFolderStatus.GENERATING,
        )

        result = await agent_runner.run(
            db=mock_db,
            user=mock_user,
            query="Tell me about Bank A",
            smart_folder=smart_folder,
        )

        assert result["status"] == "completed"
        assert result["smart_folder_id"] == str(smart_folder.id)
        assert result["source_count"] == 1
        assert smart_folder.status == SmartFolderStatus.READY
        assert smart_folder.entity_id == entity.id
        assert mock_db.commit.called

    @pytest.mark.asyncio
    async def test_pipeline_handles_entity_not_found(
        self, agent_runner, mock_user, mock_db, monkeypatch
    ):
        """Test graceful handling when entity is not recognised."""

        from app.services.smart_folder.query_parser import ParsedQuery
        from app.services.smart_folder.entity_resolver import ResolutionResult

        async def mock_parse(query):
            return ParsedQuery(primary_entity="UnknownEntityXYZ")

        monkeypatch.setattr(
            "app.services.smart_folder.agent_runner.query_parser.parse",
            mock_parse,
        )

        async def mock_resolve(db, name):
            return ResolutionResult(match_type="none", confidence=0.0)

        monkeypatch.setattr(
            "app.services.smart_folder.agent_runner.entity_resolver.resolve",
            mock_resolve,
        )

        smart_folder = SmartFolder(
            id=uuid.uuid4(),
            user_id=mock_user.id,
            name="Test",
            query_text="Tell me about UnknownEntityXYZ",
            status=SmartFolderStatus.GENERATING,
        )

        result = await agent_runner.run(
            db=mock_db,
            user=mock_user,
            query="Tell me about UnknownEntityXYZ",
            smart_folder=smart_folder,
        )

        assert result["status"] == "failed"
        assert result["entity_not_recognised"] is True
        assert smart_folder.status == SmartFolderStatus.FAILED

    @pytest.mark.asyncio
    async def test_pipeline_handles_skill_failure_with_fallback(
        self, agent_runner, mock_user, mock_db, monkeypatch
    ):
        """Test that when the primary skill fails, the pipeline reports failure."""

        from app.services.smart_folder.query_parser import ParsedQuery
        from app.services.smart_folder.entity_resolver import ResolutionResult
        from app.services.smart_folder.agent.planner import Plan, PlanStep
        from app.services.smart_folder.skills.base import SkillResult

        entity = Entity(id=uuid.uuid4(), name="Bank A", entity_type=EntityType.ORGANIZATION)

        async def mock_parse(query):
            return ParsedQuery(primary_entity="Bank A", relationship_type="institutional")

        monkeypatch.setattr(
            "app.services.smart_folder.agent_runner.query_parser.parse",
            mock_parse,
        )

        async def mock_resolve(db, name):
            return ResolutionResult(entity=entity, match_type="exact", confidence=100.0)

        monkeypatch.setattr(
            "app.services.smart_folder.agent_runner.entity_resolver.resolve",
            mock_resolve,
        )

        agent_runner.planner.plan = AsyncMock(return_value=Plan(
            intent="test",
            primary_skill="financial_analysis",
            steps=[PlanStep(step_id="1", skill_id="financial_analysis", description="Test")],
        ))

        agent_runner.executor.execute = AsyncMock(return_value={
            "1": SkillResult(
                skill_id="financial_analysis",
                success=False,
                error="No financial documents found",
            ),
        })

        smart_folder = SmartFolder(
            id=uuid.uuid4(),
            user_id=mock_user.id,
            name="Test",
            query_text="Analyse balance sheets",
            status=SmartFolderStatus.GENERATING,
        )

        result = await agent_runner.run(
            db=mock_db,
            user=mock_user,
            query="Analyse balance sheets",
            smart_folder=smart_folder,
        )

        assert result["status"] == "failed"
        assert "All skills failed" in result["error"]
        assert smart_folder.status == SmartFolderStatus.FAILED

    @pytest.mark.asyncio
    async def test_refinement_preserves_entity_context(
        self, agent_runner, mock_user, mock_db
    ):
        """Test that refinement reuses the stored entity_id."""

        from app.services.smart_folder.agent.planner import Plan, PlanStep
        from app.services.smart_folder.skills.base import SkillResult

        entity = Entity(id=uuid.uuid4(), name="Bank A", entity_type=EntityType.ORGANIZATION)

        smart_folder = SmartFolder(
            id=uuid.uuid4(),
            user_id=mock_user.id,
            name="Smart Folder: Bank A",
            query_text="Tell me about Bank A",
            entity_id=entity.id,
            relationship_type="institutional",
            status=SmartFolderStatus.READY,
        )

        # Mock entity access
        smart_folder.entity = entity

        call_count = {"plan": 0}

        async def mock_plan(query, entity_name, relationship_type):
            call_count["plan"] += 1
            return Plan(
                intent="refinement",
                primary_skill="general_narrative",
                steps=[PlanStep(step_id="1", skill_id="general_narrative", description="Refine")],
            )

        agent_runner.planner.plan = mock_plan

        agent_runner.executor.execute = AsyncMock(return_value={
            "1": SkillResult(
                skill_id="general_narrative",
                success=True,
                text_summary="Refined summary",
                raw_output={
                    "title": "Refined Report",
                    "summary": "Refined [asset-456]",
                    "timeline": [],
                    "patterns": [],
                    "trends": [],
                    "issues": [],
                    "learnings": [],
                    "recommendations": [],
                },
                citations=[{"asset_id": "asset-456", "preview": "Snippet"}],
            ),
        })

        result = await agent_runner.run(
            db=mock_db,
            user=mock_user,
            query="Tell me about Bank A | Refinement: Only show disputes",
            smart_folder=smart_folder,
            refinement_query="Only show disputes",
        )

        assert result["status"] == "completed"
        assert call_count["plan"] == 1
        assert smart_folder.status == SmartFolderStatus.READY
