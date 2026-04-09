"""
AlertIQ-SOWKNOW Incident Correlator.

Groups patrol check results into structured incidents, deduplicates alerts
(alert-once + escalation reminder), outputs to Telegram + JSONL log.
"""

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import structlog

logger = structlog.get_logger()

# Causal dependency map: if key service is down, value services will also fail.
# Used to group related failures into a single incident.
DEPENDENCY_MAP = {
    "postgres": ["backend", "celery-light", "celery-heavy", "celery-collections"],
    "redis": ["backend", "celery-light", "celery-heavy", "celery-collections", "celery-beat"],
    "backend": ["frontend"],
    "network": ["postgres", "redis", "vault", "nats", "backend", "frontend",
                "celery-light", "celery-heavy", "celery-collections"],
    "vault": ["backend"],
}

ESCALATION_PATROL_THRESHOLD = 5
INCIDENT_EXPIRY_HOURS = 24
STATE_FILE = os.environ.get("GUARDIAN_STATE_DIR", "/tmp") + "/guardian-active-incidents.json"
JSONL_FILE = os.environ.get("GUARDIAN_LOG_DIR", "/var/docker/sowknow4/logs") + "/incidents.jsonl"


@dataclass
class AlertEvent:
    event_id: str
    severity: str
    service: str
    container: str | None
    check_type: str
    patrol_level: str
    timestamp: datetime
    summary: str
    details: str
    heal_attempted: bool
    heal_success: bool | None
    heal_action: str | None
    restart_attempts: int
    restart_suppressed: bool

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "severity": self.severity,
            "service": self.service,
            "container": self.container,
            "check_type": self.check_type,
            "patrol_level": self.patrol_level,
            "timestamp": self.timestamp.isoformat(),
            "summary": self.summary,
            "details": self.details,
            "heal_attempted": self.heal_attempted,
            "heal_success": self.heal_success,
            "heal_action": self.heal_action,
            "restart_attempts": self.restart_attempts,
            "restart_suppressed": self.restart_suppressed,
        }


@dataclass
class Incident:
    incident_id: str
    severity: str
    root_cause: AlertEvent
    related_events: list[AlertEvent] = field(default_factory=list)
    status: str = "open"
    opened_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_seen_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    patrol_count: int = 1
    escalated_at: datetime | None = None
    resolved_at: datetime | None = None
    suppressed_count: int = 0
    owner: str = "Platform Admin"

    def to_jsonl_dict(self, event_type: str) -> dict:
        d = {
            "incident_id": self.incident_id,
            "event_type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "severity": self.severity,
            "root_cause": {
                "service": self.root_cause.service,
                "container": self.root_cause.container,
                "check_type": self.root_cause.check_type,
                "summary": self.root_cause.summary,
                "details": self.root_cause.details,
            },
            "related_services": [
                {"service": e.service, "check_type": e.check_type, "summary": e.summary}
                for e in self.related_events
            ],
            "heal": {
                "attempted": self.root_cause.heal_attempted,
                "action": self.root_cause.heal_action,
                "success": self.root_cause.heal_success,
                "restart_attempts": self.root_cause.restart_attempts,
                "suppressed": self.root_cause.restart_suppressed,
            },
            "patrol_level": self.root_cause.patrol_level,
            "patrol_count": self.patrol_count,
            "suppressed_count": self.suppressed_count,
            "owner": self.owner,
        }
        if event_type == "resolved":
            d["duration_seconds"] = int((datetime.now(timezone.utc) - self.opened_at).total_seconds())
            d["related_services"] = [e.service for e in self.related_events]
        return d


class IncidentCorrelator:
    """Groups patrol AlertEvents into Incidents, deduplicates, and routes alerts."""

    def __init__(self, alert_manager):
        self.alert_manager = alert_manager
        self.active_incidents: dict[str, Incident] = {}
        self._sequence = {"date": "", "counter": 0}
        self._load_state()

    @staticmethod
    def _group_events(events: list[AlertEvent]) -> list[tuple[str, AlertEvent, list[AlertEvent]]]:
        """
        Group events by causal dependency.

        Returns list of (root_service, root_event, related_events) tuples.
        """
        if not events:
            return []

        event_by_service: dict[str, AlertEvent] = {}
        for e in events:
            event_by_service[e.service] = e

        services = set(event_by_service.keys())

        # Network override: if network is failing, everything groups under it
        if "network" in services:
            root_event = event_by_service["network"]
            related = [e for s, e in event_by_service.items() if s != "network"]
            return [("network", root_event, related)]

        # Build: for each service, find its ultimate root cause
        assigned: dict[str, str] = {}  # service -> root_service

        def find_root(service: str) -> str:
            """Walk up dependency chain to find the ultimate upstream cause."""
            for candidate, dependents in DEPENDENCY_MAP.items():
                if service in dependents and candidate in services:
                    # candidate is a potential root cause — check if it has its own root
                    upstream = find_root(candidate)
                    return upstream
            return service

        for svc in services:
            assigned[svc] = find_root(svc)

        # Group by root
        groups: dict[str, list[str]] = {}
        for svc, root in assigned.items():
            groups.setdefault(root, []).append(svc)

        result = []
        for root_svc, members in groups.items():
            root_event = event_by_service[root_svc]
            related = [event_by_service[s] for s in members if s != root_svc]
            result.append((root_svc, root_event, related))

        return result

    def _next_incident_id(self) -> str:
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        if self._sequence["date"] != today:
            self._sequence = {"date": today, "counter": 0}
        self._sequence["counter"] += 1
        return f"INC-{today}-{self._sequence['counter']:03d}"

    def _load_state(self):
        try:
            if os.path.exists(STATE_FILE):
                with open(STATE_FILE) as f:
                    data = json.load(f)
                self._sequence = data.get("sequence", {"date": "", "counter": 0})
                logger.info("correlator.state_loaded", sequence=self._sequence)
        except Exception as e:
            logger.warning("correlator.state_load_failed", error=str(e)[:200])

    def _save_state(self):
        try:
            Path(STATE_FILE).parent.mkdir(parents=True, exist_ok=True)
            data = {"sequence": self._sequence}
            with open(STATE_FILE, "w") as f:
                json.dump(data, f)
        except Exception as e:
            logger.warning("correlator.state_save_failed", error=str(e)[:200])
