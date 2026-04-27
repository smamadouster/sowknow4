"""Analysis Service for Smart Folder v2.

Extracts and aggregates structured findings (milestones, patterns, trends,
issues, learnings) for a given entity and query scope.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.milestone import Milestone
from app.models.pattern_insight import PatternInsight, PatternInsightType

logger = logging.getLogger(__name__)


@dataclass
class AnalysisResult:
    """Structured analysis findings for a Smart Folder report."""

    milestones: list[dict[str, Any]] = field(default_factory=list)
    patterns: list[dict[str, Any]] = field(default_factory=list)
    trends: list[dict[str, Any]] = field(default_factory=list)
    issues: list[dict[str, Any]] = field(default_factory=list)
    learnings: list[dict[str, Any]] = field(default_factory=list)
    total_findings: int = 0


class AnalysisService:
    """Gather structured analysis data for a Smart Folder query."""

    async def analyze(
        self,
        db: AsyncSession,
        entity_id: UUID,
        time_range_start: datetime | None = None,
        time_range_end: datetime | None = None,
        focus_aspects: list[str] | None = None,
    ) -> AnalysisResult:
        """Fetch and filter milestones and insights for the given entity.

        Args:
            db: Async database session.
            entity_id: Canonical entity ID.
            time_range_start: Optional temporal filter start.
            time_range_end: Optional temporal filter end.
            focus_aspects: Optional focus aspects to filter descriptions.

        Returns:
            AnalysisResult with categorized findings.
        """
        result = AnalysisResult()

        # --- Milestones ---
        milestone_stmt = (
            select(Milestone)
            .where(Milestone.entity_id == entity_id)
            .order_by(Milestone.date.asc())
        )
        if time_range_start:
            milestone_stmt = milestone_stmt.where(
                Milestone.date.is_(None) | (Milestone.date >= time_range_start)
            )
        if time_range_end:
            milestone_stmt = milestone_stmt.where(
                Milestone.date.is_(None) | (Milestone.date <= time_range_end)
            )

        milestone_result = await db.execute(milestone_stmt)
        milestones = milestone_result.scalars().all()

        for ms in milestones:
            result.milestones.append(
                {
                    "id": str(ms.id),
                    "date": ms.date.isoformat() if ms.date else None,
                    "date_precision": ms.date_precision,
                    "title": ms.title,
                    "description": ms.description,
                    "linked_asset_ids": ms.linked_asset_ids or [],
                    "importance": ms.importance,
                    "confidence": ms.confidence,
                }
            )

        # --- Pattern Insights ---
        insight_stmt = select(PatternInsight).where(PatternInsight.entity_id == entity_id)
        if time_range_start:
            insight_stmt = insight_stmt.where(
                PatternInsight.time_range_end.is_(None)
                | (PatternInsight.time_range_end >= time_range_start)
            )
        if time_range_end:
            insight_stmt = insight_stmt.where(
                PatternInsight.time_range_start.is_(None)
                | (PatternInsight.time_range_start <= time_range_end)
            )

        insight_result = await db.execute(insight_stmt)
        insights = insight_result.scalars().all()

        for ins in insights:
            item = {
                "id": str(ins.id),
                "type": ins.insight_type.value,
                "description": ins.description,
                "linked_asset_ids": ins.linked_asset_ids or [],
                "confidence": ins.confidence,
                "trend_data": ins.trend_data or {},
            }
            if ins.insight_type == PatternInsightType.PATTERN:
                result.patterns.append(item)
            elif ins.insight_type == PatternInsightType.TREND:
                result.trends.append(item)
            elif ins.insight_type == PatternInsightType.ISSUE:
                result.issues.append(item)
            elif ins.insight_type == PatternInsightType.LEARNING:
                result.learnings.append(item)

        # --- Focus-aspect filtering (soft filter on description) ---
        if focus_aspects:
            focus_lower = [f.lower() for f in focus_aspects]
            for category in ["milestones", "patterns", "trends", "issues", "learnings"]:
                items = getattr(result, category)
                filtered = [
                    item
                    for item in items
                    if any(f in item["description"].lower() for f in focus_lower)
                    or any(f in item.get("title", "").lower() for f in focus_lower)
                ]
                setattr(result, category, filtered)

        result.total_findings = (
            len(result.milestones)
            + len(result.patterns)
            + len(result.trends)
            + len(result.issues)
            + len(result.learnings)
        )

        return result


# Module-level singleton
analysis_service = AnalysisService()
