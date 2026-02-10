"""
Temporal Reasoning Service for Knowledge Graph

Enables reasoning about time-based relationships, causality, and
evolution of concepts across documents.
"""
import logging
from typing import List, Dict, Any, Optional, Tuple
from datetime import date, datetime, timedelta
from collections import defaultdict
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc

from app.models.knowledge_graph import (
    Entity,
    TimelineEvent,
    EntityMention,
    EntityType
)
from app.models.document import Document

logger = logging.getLogger(__name__)


class TemporalRelation:
    """Types of temporal relationships between events"""

    BEFORE = "before"           # Event A occurs before Event B
    AFTER = "after"             # Event A occurs after Event B
    DURING = "during"           # Event A occurs during Event B
    OVERLAPS = "overlaps"       # Event A overlaps in time with Event B
    CONTAINS = "contains"       # Event A contains Event B temporally
    IMMEDIATELY_BEFORE = "immediately_before"  # A is just before B
    IMMEDIATELY_AFTER = "immediately_after"    # A is just after B
    SIMULTANEOUS = "simultaneous"  # A and B occur at the same time
    CAUSES = "causes"           # A causes B (inferred)
    ENABLES = "enables"         # A enables B to happen


class TemporalReasoningService:
    """Service for temporal reasoning over knowledge graph"""

    def __init__(self):
        pass

    async def reason_about_temporal_relationships(
        self,
        event_id: str,
        db: Session,
        time_window_days: int = 365
    ) -> Dict[str, Any]:
        """
        Reason about temporal relationships for a specific event

        Args:
            event_id: Timeline event ID
            db: Database session
            time_window_days: How many days before/after to consider

        Returns:
            Temporal relationships and insights
        """
        try:
            # Get the target event
            target_event = db.query(TimelineEvent).get(event_id)
            if not target_event:
                return {"error": "Event not found"}

            if not target_event.event_date:
                return {"error": "Event has no date"}

            # Define time window
            start_date = target_event.event_date - timedelta(days=time_window_days)
            end_date = target_event.event_date + timedelta(days=time_window_days)

            # Get nearby events
            nearby_events = db.query(TimelineEvent).filter(
                and_(
                    TimelineEvent.event_date >= start_date,
                    TimelineEvent.event_date <= end_date,
                    TimelineEvent.id != event_id
                )
            ).order_by(TimelineEvent.event_date).all()

            # Categorize relationships
            before_events = []
            after_events = []
            simultaneous_events = []

            for event in nearby_events:
                days_diff = (event.event_date - target_event.event_date).days

                if days_diff < -1:
                    before_events.append({
                        "id": str(event.id),
                        "title": event.title,
                        "date": event.event_date.isoformat(),
                        "days_before": abs(days_diff),
                        "relation": self._determine_relation(target_event, event, days_diff)
                    })
                elif days_diff > 1:
                    after_events.append({
                        "id": str(event.id),
                        "title": event.title,
                        "date": event.event_date.isoformat(),
                        "days_after": days_diff,
                        "relation": self._determine_relation(target_event, event, days_diff)
                    })
                else:
                    simultaneous_events.append({
                        "id": str(event.id),
                        "title": event.title,
                        "date": event.event_date.isoformat(),
                        "relation": TemporalRelation.SIMULTANEOUS
                    })

            # Check for causal relationships
            causal_candidates = await self._infer_causal_relationships(
                target_event,
                before_events,
                db
            )

            # Get temporal context for entities
            entity_context = await self._get_entity_temporal_context(
                target_event,
                db
            )

            return {
                "target_event": {
                    "id": str(target_event.id),
                    "title": target_event.title,
                    "description": target_event.description,
                    "date": target_event.event_date.isoformat(),
                    "type": target_event.event_type
                },
                "temporal_relationships": {
                    "before": before_events[:10],
                    "after": after_events[:10],
                    "simultaneous": simultaneous_events[:10]
                },
                "causal_inferences": causal_candidates,
                "entity_context": entity_context,
                "time_window_days": time_window_days
            }

        except Exception as e:
            logger.error(f"Temporal reasoning error: {e}")
            return {"error": str(e)}

    def _determine_relation(
        self,
        event1: TimelineEvent,
        event2: TimelineEvent,
        days_diff: int
    ) -> str:
        """Determine the type of temporal relationship"""
        abs_days = abs(days_diff)

        if abs_days <= 1:
            return TemporalRelation.IMMEDIATELY_BEFORE if days_diff < 0 else TemporalRelation.IMMEDIATELY_AFTER
        elif abs_days <= 7:
            return TemporalRelation.BEFORE if days_diff < 0 else TemporalRelation.AFTER
        else:
            return TemporalRelation.BEFORE if days_diff < 0 else TemporalRelation.AFTER

    async def _infer_causal_relationships(
        self,
        target_event: TimelineEvent,
        before_events: List[Dict[str, Any]],
        db: Session
    ) -> List[Dict[str, Any]]:
        """Infer potential causal relationships from earlier events"""
        causal_candidates = []

        # Check for shared entities between events
        target_entity_ids = set(target_event.entity_ids or [])

        for before_event in before_events[:5]:  # Check top 5 candidates
            before_event_obj = db.query(TimelineEvent).get(before_event["id"])
            if before_event_obj:
                before_entity_ids = set(before_event_obj.entity_ids or [])

                # Shared entities increase likelihood of causal relationship
                shared_entities = target_entity_ids & before_entity_ids

                if shared_entities:
                    causal_candidates.append({
                        "event": before_event,
                        "confidence": min(0.9, 0.5 + len(shared_entities) * 0.1),
                        "reason": f"Shares {len(shared_entities)} entities",
                        "shared_entity_count": len(shared_entities)
                    })

        return sorted(causal_candidates, key=lambda x: x["confidence"], reverse=True)

    async def _get_entity_temporal_context(
        self,
        event: TimelineEvent,
        db: Session
    ) -> List[Dict[str, Any]]:
        """Get temporal context for entities involved in the event"""
        context = []

        entity_ids = event.entity_ids or []

        for entity_id in entity_ids[:5]:  # Limit to 5 entities
            entity = db.query(Entity).get(entity_id)
            if entity:
                # Get first and last mentions
                first_mention = db.query(TimelineEvent).filter(
                    TimelineEvent.entity_ids.contains([entity_id])
                ).order_by(TimelineEvent.event_date).first()

                last_mention = db.query(TimelineEvent).filter(
                    TimelineEvent.entity_ids.contains([entity_id])
                ).order_by(desc(TimelineEvent.event_date)).first()

                context.append({
                    "entity": entity.name,
                    "entity_type": entity.entity_type.value,
                    "first_seen": first_mention.event_date.isoformat() if first_mention and first_mention.event_date else None,
                    "last_seen": last_mention.event_date.isoformat() if last_mention and last_mention.event_date else None,
                    "in_event": True
                })

        return context

    async def analyze_evolution(
        self,
        entity_name: str,
        db: Session,
        time_months: int = 12
    ) -> Dict[str, Any]:
        """
        Analyze how an entity/concept evolves over time

        Args:
            entity_name: Name of entity to analyze
            db: Database session
            time_months: Time period in months to analyze

        Returns:
            Evolution analysis with stages and trends
        """
        # Find matching entities
        entities = db.query(Entity).filter(
            Entity.name.ilike(f"%{entity_name}%")
        ).all()

        if not entities:
            return {"error": "Entity not found"}

        entity_ids = [str(e.id) for e in entities]

        # Get events involving these entities
        end_date = date.today()
        start_date = end_date - timedelta(days=time_months * 30)

        events = db.query(TimelineEvent).filter(
            and_(
                TimelineEvent.event_date >= start_date,
                TimelineEvent.event_date <= end_date
            )
        ).all()

        # Filter events involving our entities
        relevant_events = []
        for event in events:
            event_entity_ids = event.entity_ids or []
            if any(eid in entity_ids for eid in event_entity_ids):
                relevant_events.append(event)

        if not relevant_events:
            return {
                "entity": entity_name,
                "message": "No events found for this entity in the specified time period"
            }

        # Sort by date
        relevant_events.sort(key=lambda e: e.event_date or date.min)

        # Analyze evolution stages
        stages = self._identify_evolution_stages(relevant_events)

        # Detect trends
        trends = self._detect_evolution_trends(relevant_events, time_months)

        return {
            "entity": entity_name,
            "time_period_months": time_months,
            "event_count": len(relevant_events),
            "first_event": {
                "date": relevant_events[0].event_date.isoformat() if relevant_events[0].event_date else None,
                "title": relevant_events[0].title
            },
            "last_event": {
                "date": relevant_events[-1].event_date.isoformat() if relevant_events[-1].event_date else None,
                "title": relevant_events[-1].title
            },
            "stages": stages,
            "trends": trends,
            "timeline": [
                {
                    "date": e.event_date.isoformat() if e.event_date else None,
                    "title": e.title,
                    "type": e.event_type
                }
                for e in relevant_events
            ]
        }

    def _identify_evolution_stages(
        self,
        events: List[TimelineEvent]
    ) -> List[Dict[str, Any]]:
        """Identify distinct stages in entity evolution"""
        if len(events) < 3:
            return []

        stages = []
        current_stage_events = [events[0]]
        current_type = events[0].event_type

        for event in events[1:]:
            # Check for significant change in event type
            if event.event_type != current_type:
                # Finalize current stage
                if current_stage_events:
                    stages.append({
                        "type": current_type or "unknown",
                        "event_count": len(current_stage_events),
                        "start_date": current_stage_events[0].event_date.isoformat() if current_stage_events[0].event_date else None,
                        "end_date": current_stage_events[-1].event_date.isoformat() if current_stage_events[-1].event_date else None
                    })

                # Start new stage
                current_stage_events = [event]
                current_type = event.event_type
            else:
                current_stage_events.append(event)

        # Add final stage
        if current_stage_events:
            stages.append({
                "type": current_type or "unknown",
                "event_count": len(current_stage_events),
                "start_date": current_stage_events[0].event_date.isoformat() if current_stage_events[0].event_date else None,
                "end_date": current_stage_events[-1].event_date.isoformat() if current_stage_events[-1].event_date else None
            })

        return stages

    def _detect_evolution_trends(
        self,
        events: List[TimelineEvent],
        time_months: int
    ) -> Dict[str, Any]:
        """Detect trends in entity evolution"""
        if not events or not events[0].event_date or not events[-1].event_date:
            return {"trend": "insufficient_data"}

        # Calculate event frequency
        time_span_days = (events[-1].event_date - events[0].event_date).days
        if time_span_days <= 0:
            return {"trend": "insufficient_data"}

        frequency = len(events) / max(1, time_span_days / 30)  # events per month

        # Analyze event types
        type_counts = defaultdict(int)
        for event in events:
            if event.event_type:
                type_counts[event.event_type] += 1

        dominant_type = max(type_counts.items(), key=lambda x: x[1]) if type_counts else (None, 0)

        # Determine trend
        if len(events) >= time_months * 0.5:  # At least 0.5 events per month on average
            trend = "high_activity"
        elif len(events) >= time_months * 0.2:  # At least 0.2 events per month
            trend = "moderate_activity"
        else:
            trend = "low_activity"

        return {
            "trend": trend,
            "events_per_month": round(frequency, 2),
            "dominant_event_type": dominant_type[0],
            "type_distribution": dict(type_counts)
        }

    async def find_temporal_patterns(
        self,
        db: Session,
        min_occurrences: int = 3
    ) -> List[Dict[str, Any]]:
        """
        Find recurring temporal patterns in the knowledge graph

        Args:
            db: Database session
            min_occurrences: Minimum times a pattern must occur

        Returns:
            List of discovered patterns
        """
        # Get all events
        events = db.query(TimelineEvent).filter(
            TimelineEvent.event_date.isnot(None)
        ).all()

        # Group by month
        monthly_events = defaultdict(list)
        for event in events:
            if event.event_date:
                month_key = event.event_date.strftime("%Y-%m")
                monthly_events[month_key].append(event)

        # Find patterns
        patterns = []

        # Pattern 1: Seasonal events (same month across years)
        month_counts = defaultdict(int)
        for event in events:
            if event.event_date:
                month = event.event_date.month
                month_counts[month] += 1

        for month, count in month_counts.items():
            if count >= min_occurrences:
                patterns.append({
                    "type": "seasonal",
                    "month": month,
                    "occurrence_count": count,
                    "description": f"Activity peaks in month {month}"
                })

        # Pattern 2: Event type sequences
        sequences = defaultdict(int)
        sorted_events = sorted(events, key=lambda e: e.event_date or date.min)

        for i in range(len(sorted_events) - 1):
            if (sorted_events[i].event_date and sorted_events[i+1].event_date and
                (sorted_events[i+1].event_date - sorted_events[i].event_date).days <= 30):

                seq_key = f"{sorted_events[i].event_type}->{sorted_events[i+1].event_type}"
                sequences[seq_key] += 1

        for seq, count in sequences.items():
            if count >= min_occurrences:
                patterns.append({
                    "type": "sequence",
                    "sequence": seq,
                    "occurrence_count": count,
                    "description": f"Event sequence occurs {count} times"
                })

        # Pattern 3: Co-occurring entities
        entity_cooccurrence = defaultdict(int)

        for event in events:
            entity_ids = event.entity_ids or []
            for i, eid1 in enumerate(entity_ids):
                for eid2 in entity_ids[i+1:]:
                    pair = tuple(sorted([eid1, eid2]))
                    entity_cooccurrence[pair] += 1

        for pair, count in entity_cooccurrence.items():
            if count >= min_occurrences:
                e1 = db.query(Entity).get(pair[0])
                e2 = db.query(Entity).get(pair[1])
                if e1 and e2:
                    patterns.append({
                        "type": "co_occurrence",
                        "entities": [e1.name, e2.name],
                        "occurrence_count": count,
                        "description": f"{e1.name} and {e2.name} appear together {count} times"
                    })

        return sorted(patterns, key=lambda x: x["occurrence_count"], reverse=True)


# Global temporal reasoning service instance
temporal_reasoning_service = TemporalReasoningService()
