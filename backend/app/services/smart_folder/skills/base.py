"""Base skill interface for the Smart Folder Agent.

All skills must inherit from BaseSkill and implement the `analyze` method.
"""

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SkillResult:
    """Standard output format for every skill execution."""

    skill_id: str
    success: bool = True
    text_summary: str = ""
    data_tables: list[dict[str, Any]] = field(default_factory=list)
    visualisations: list[dict[str, Any]] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 1.0
    error: str | None = None
    raw_output: dict[str, Any] = field(default_factory=dict)


class BaseSkill:
    """Abstract base class for all Smart Folder skills."""

    skill_id: str = "base"
    skill_name: str = "Base Skill"
    description: str = ""
    required_tools: list[str] = field(default_factory=list)

    async def analyze(self, parameters: dict[str, Any], context: dict[str, Any]) -> SkillResult:
        """Execute the skill.

        Args:
            parameters: Skill-specific parameters from the planner.
            context: Shared execution context (retrieved assets, entity info, etc.).

        Returns:
            SkillResult with structured output.
        """
        raise NotImplementedError
