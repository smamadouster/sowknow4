"""Skill Executor for the Smart Folder Agent.

Executes plan steps sequentially or in parallel, caches intermediate results,
and handles retry/replan on skill failure.
"""

import json
import logging
from typing import Any

from app.services.smart_folder.agent.planner import Plan, PlanStep
from app.services.smart_folder.skills import SKILL_REGISTRY
from app.services.smart_folder.skills.base import SkillResult

logger = logging.getLogger(__name__)


class SkillExecutor:
    """Execute a plan by invoking skills and managing intermediate state."""

    def __init__(self, max_retries: int = 1) -> None:
        self.max_retries = max_retries
        self._cache: dict[str, SkillResult] = {}

    async def execute(
        self,
        plan: Plan,
        context: dict[str, Any],
    ) -> dict[str, SkillResult]:
        """Execute all steps in a plan.

        Args:
            plan: The execution plan from the planner.
            context: Shared execution context (db, user, entity info, etc.).

        Returns:
            Mapping of step_id → SkillResult.
        """
        results: dict[str, SkillResult] = {}

        for step in plan.steps:
            # Check dependencies
            for dep_id in step.dependencies:
                if dep_id not in results:
                    logger.warning("Step %s depends on %s which has not executed yet", step.step_id, dep_id)

            # Check cache
            cache_key = f"{step.skill_id}:{json.dumps(step.parameters, sort_keys=True)}"
            if cache_key in self._cache:
                results[step.step_id] = self._cache[cache_key]
                continue

            # Execute with retry
            result = await self._execute_step(step, context)
            results[step.step_id] = result
            self._cache[cache_key] = result

        return results

    async def _execute_step(
        self,
        step: PlanStep,
        context: dict[str, Any],
    ) -> SkillResult:
        """Execute a single plan step with optional retry."""
        skill_cls = SKILL_REGISTRY.get(step.skill_id)
        if not skill_cls:
            return SkillResult(
                skill_id=step.skill_id,
                success=False,
                error=f"Unknown skill: {step.skill_id}",
            )

        skill = skill_cls()
        last_error = None

        for attempt in range(self.max_retries + 1):
            try:
                result = await skill.analyze(
                    parameters=step.parameters,
                    context=context,
                )
                if result.success:
                    return result
                last_error = result.error
                logger.warning("Skill %s returned failure (attempt %d): %s", step.skill_id, attempt + 1, result.error)
            except Exception as exc:
                last_error = str(exc)
                logger.exception("Skill %s crashed (attempt %d): %s", step.skill_id, attempt + 1, exc)

        return SkillResult(
            skill_id=step.skill_id,
            success=False,
            error=f"Failed after {self.max_retries + 1} attempts: {last_error}",
        )

    def clear_cache(self) -> None:
        """Clear the intermediate result cache."""
        self._cache.clear()


# Module-level singleton
executor = SkillExecutor()
