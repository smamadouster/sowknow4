"""
Timeline Construction Service for Knowledge Graph

Builds timelines from documents to enable temporal reasoning
and thought evolution tracking.
"""
import logging
from typing import List, Dict, Any, Optional
from datetime import date, datetime
from collections import defaultdict

from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc

from app.models.knowledge_graph import (
    TimelineEvent,
    Entity,
    EntityType
)
from app.models.document import Document, DocumentStatus

logger = logging.getLogger(__name__)


class TimelineEventType:
    """Types of timeline events"""
    FOUNDING = "founding"
    APPOINTMENT = "appointment"
    MERGER = "merger"
    MILESTONE = "milestone"
    LAUNCH = "launch"
    MEETING = "meeting"
    CONTRACT = "contract"
    CERTIFICATION = "certification"
    AWARD = "award"
    OTHER = "other"


class TimelineConstructionService:
    """Service for building and managing timelines"""

    async def build_document_timeline(
        self,
        document_id: str,
        db: Session
    ) -> List[Dict[str, Any]]:
        """
        Build timeline from events in a document

        Args:
            document_id: Document to extract timeline from
            db: Database session

        Returns:
            List of timeline events sorted by date
        """
        # Get events for this document
        events = db.query(TimelineEvent).filter(
            TimelineEvent.document_id == document_id
        ).order_by(TimelineEvent.event_date).all()

        timeline = []
        for event in events:
            timeline.append({
                "id": str(event.id),
                "title": event.title,
                "description": event.description,
                "date": event.event_date.isoformat() if event.event_date else None,
                "precision": event.event_date_precision,
                "type": event.event_type,
                "importance": event.importance,
                "entity_ids": event.entity_ids,
                "color": event.color
            })

        return timeline

    async def build_entity_timeline(
        self,
        entity_name: str,
        db: Session
    ) -> List[Dict[str, Any]]:
        """
        Build timeline for a specific entity across all documents

        Args:
            entity_name: Entity to build timeline for
            db: Database session

        Returns:
            List of events involving this entity
        """
        # Find entity
        entity = db.query(Entity).filter(
            Entity.name.ilike(f"%{entity_name}%")
        ).first()

        if not entity:
            return []

        # Get events where this entity is mentioned
        event_ids = []
        mentions = db.query(TimelineEvent).all()

        for event in mentions:
            if str(entity.id) in event.entity_ids:
                event_ids.append(event.id)

        # Build timeline
        events = db.query(TimelineEvent).filter(
            TimelineEvent.id.in_(event_ids)
        ).order_by(TimelineEvent.event_date).all()

        timeline = []
        for event in events:
            timeline.append({
                "id": str(event.id),
                "title": event.title,
                "description": event.description,
                "date": event.event_date.isoformat() if event.event_date else None,
                "type": event.event_type,
                "importance": event.importance,
                "document_id": str(event.document_id)
            })

        return timeline

    async def detect_evolution_patterns(
        self,
        concept_name: str,
        db: Session,
        time_window_months: int = 12
    ) -> Dict[str, Any]:
        """
        Detect how a concept or thought evolved over time

        Args:
            concept_name: Concept to analyze
            db: Database session
            time_window_months: Time period to analyze

        Returns:
            Evolution analysis with stages and trends
        """
        # Get all entities matching the concept
        entities = db.query(Entity).filter(
            and_(
                Entity.name.ilike(f"%{concept_name}%"),
                Entity.entity_type == EntityType.CONCEPT
            )
        ).all()

        if not entities:
            return {"error": "Concept not found"}

        # Get related documents over time
        # Find documents mentioning these entities
        from app.models.knowledge_graph import EntityMention
        from app.models.document import Document

        entity_ids = [str(e.id) for e in entities]

        # Get mentions with documents
        mentions = db.query(EntityMention).filter(
            EntityMention.entity_id.in_(entity_ids)
        ).all()

        # Group by document date
        monthly_mentions = defaultdict(int)
        for mention in mentions:
            doc = db.query(Document).get(mention.document_id)
            if doc and doc.created_at:
                month_key = doc.created_at.strftime("%Y-%m")
                monthly_mentions[month_key] += 1

        # Sort chronologically
        sorted_mentions = sorted(monthly_mentions.items())

        # Detect trends
        if len(sorted_mentions) > 1:
            first_count = sorted_mentions[0][1]
            last_count = sorted_mentions[-1][1]
            total = sum(count for _, count in sorted_mentions)

            if last_count > first_count * 1.5:
                trend = "increasing"
            elif last_count < first_count * 0.5:
                trend = "decreasing"
            else:
                trend = "stable"
        else:
            trend = "insufficient_data"

        # Identify stages
        stages = self._identify_evolution_stages(sorted_mentions)

        return {
            "concept": concept_name,
            "time_window_months": time_window_months,
            "total_mentions": sum(count for _, count in sorted_mentions),
            "trend": trend,
            "stages": stages,
            "timeline": [
                {"month": month, "count": count}
                for month, count in sorted_mentions
            ]
        }

    def _identify_evolution_stages(
        self,
        monthly_mentions: List[tuple]
    ) -> List[Dict[str, Any]]:
        """
        Identify distinct stages in concept evolution

        Args:
            monthly_mentions: List of (month, count) tuples

        Returns:
            List of identified stages
        """
        if len(monthly_mentions) < 3:
            return []

        stages = []
        current_stage_start = 0
        current_count = monthly_mentions[0][1]

        for i, (month, count) in enumerate(monthly_mentions):
            # Check if significant change (30% increase/decrease)
            if count > current_count * 1.3 or count < current_count * 0.7:
                # New stage
                if i > current_stage_start:
                    stages.append({
                        "from_month": monthly_mentions[current_stage_start][0],
                        "to_month": monthly_mentions[i - 1][0],
                        "average_count": sum(
                            c for _, c in monthly_mentions[current_stage_start:i]
                        ) / (i - current_stage_start),
                        "stage_type": "growth" if count > current_count else "decline"
                    })
                    current_stage_start = i
                    current_count = count

        # Add final stage
        if current_stage_start < len(monthly_mentions) - 1:
            stages.append({
                "from_month": monthly_mentions[current_stage_start][0],
                "to_month": monthly_mentions[-1][0],
                "average_count": sum(
                    c for _, c in monthly_mentions[current_stage_start:]
                ) / (len(monthly_mentions) - current_stage_start),
                "stage_type": "final"
            })

        return stages

    async def get_timeline_for_period(
        self,
        start_date: date,
        end_date: date,
        db: Session
    ) -> List[Dict[str, Any]]:
        """
        Get all timeline events within a date range

        Args:
            start_date: Start date
            end_date: End date
            db: Database session

        Returns:
            List of timeline events
        """
        events = db.query(TimelineEvent).filter(
            and_(
                TimelineEvent.event_date >= start_date,
                TimelineEvent.event_date <= end_date
            )
        ).order_by(TimelineEvent.event_date).all()

        return [
            {
                "id": str(event.id),
                "title": event.title,
                "description": event.description,
                "date": event.event_date.isoformat(),
                "type": event.event_type,
                "importance": event.importance
            }
            for event in events
        ]

    async def suggest_timeline_insights(
        self,
        db: Session,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Suggest interesting timeline insights and patterns

        Args:
            db: Database session
            limit: Maximum insights to return

        Returns:
            List of timeline insights
        """
        insights = []

        # Find most connected entities over time
        from sqlalchemy import func

        # Get top entities by relationship count
        top_entities = db.query(Entity).order_by(
            Entity.relationship_count.desc()
        ).limit(20).all()

        for entity in top_entities[:5]:
            # Get first and last mentions
            mentions = db.query(TimelineEvent).filter(
                TimelineEvent.entity_ids.contains([str(entity.id)])
            ).order_by(TimelineEvent.event_date).all()

            if mentions:
                first = mentions[0]
                last = mentions[-1]

                insights.append({
                    "entity": entity.name,
                    "entity_type": entity.entity_type.value,
                    "first_mentioned": first.event_date.isoformat(),
                    "last_mentioned": last.event_date.isoformat(),
                    "span_days": (last.event_date - first.event_date).days if first.event_date and last.event_date else 0,
                    "total_mentions": len(mentions),
                    "insight": f"{entity.name} has been tracked for {len(mentions)} events over {(last.event_date - first.event_date).days if first.event_date and last.event_date else 0} days"
                })

        return insights[:limit]


# Global timeline service instance
timeline_service = TimelineConstructionService()
