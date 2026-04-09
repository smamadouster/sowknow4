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

    async def process(self, results: dict):
        """Process patrol results: correlate, dedup, alert, log."""
        events: list[AlertEvent] = results.get("events", [])
        level = results.get("level", "standard")

        groups = self._group_events(events)
        current_root_services = set()

        for root_service, root_event, related in groups:
            current_root_services.add(root_service)
            severity = self._highest_severity([root_event] + related)

            if root_service in self.active_incidents:
                # Ongoing — suppress or escalate
                incident = self.active_incidents[root_service]
                incident.patrol_count += 1
                incident.last_seen_at = datetime.now(timezone.utc)
                incident.suppressed_count += 1
                incident.root_cause = root_event
                incident.related_events = related
                incident.severity = severity

                should_escalate = (
                    incident.status != "escalated"
                    and (
                        incident.patrol_count >= ESCALATION_PATROL_THRESHOLD
                        or root_event.restart_suppressed
                    )
                )
                if should_escalate:
                    incident.status = "escalated"
                    incident.escalated_at = datetime.now(timezone.utc)
                    msg = self._format_escalation(incident)
                    await self.alert_manager.send(msg)
                    self._append_jsonl(incident, "escalated")
                    logger.warning("correlator.escalated", incident=incident.incident_id,
                                   service=root_service, patrol_count=incident.patrol_count)
            else:
                # New incident
                should_escalate_immediately = root_event.restart_suppressed
                incident = Incident(
                    incident_id=self._next_incident_id(),
                    severity=severity,
                    root_cause=root_event,
                    related_events=related,
                    status="escalated" if should_escalate_immediately else "open",
                    opened_at=datetime.now(timezone.utc),
                    last_seen_at=datetime.now(timezone.utc),
                    escalated_at=datetime.now(timezone.utc) if should_escalate_immediately else None,
                )
                self.active_incidents[root_service] = incident

                if should_escalate_immediately:
                    msg = self._format_escalation(incident)
                    await self.alert_manager.send(msg)
                    self._append_jsonl(incident, "escalated")
                    logger.warning("correlator.immediate_escalation", incident=incident.incident_id,
                                   service=root_service)
                else:
                    msg = self._format_open(incident)
                    await self.alert_manager.send(msg)
                    self._append_jsonl(incident, "open")
                    logger.info("correlator.opened", incident=incident.incident_id,
                                service=root_service, severity=severity)

        # Resolution: active incidents whose root cause is no longer failing
        resolved_keys = []
        for root_service, incident in self.active_incidents.items():
            if root_service not in current_root_services:
                incident.status = "resolved"
                incident.resolved_at = datetime.now(timezone.utc)
                msg = self._format_resolved(incident)
                await self.alert_manager.send(msg)
                self._append_jsonl(incident, "resolved")
                resolved_keys.append(root_service)
                logger.info("correlator.resolved", incident=incident.incident_id,
                            service=root_service, patrols=incident.patrol_count)

        for key in resolved_keys:
            del self.active_incidents[key]

        # Expire stale incidents (>24h with no activity)
        self._expire_stale()
        self._save_state()

    @staticmethod
    def _highest_severity(events: list[AlertEvent]) -> str:
        order = {"CRITICAL": 0, "HIGH": 1, "WARNING": 2, "INFO": 3}
        return min(events, key=lambda e: order.get(e.severity, 99)).severity

    def _expire_stale(self):
        now = datetime.now(timezone.utc)
        expired = [
            k for k, v in self.active_incidents.items()
            if (now - v.last_seen_at).total_seconds() > INCIDENT_EXPIRY_HOURS * 3600
        ]
        for k in expired:
            logger.info("correlator.expired", incident=self.active_incidents[k].incident_id)
            del self.active_incidents[k]

    def _append_jsonl(self, incident: Incident, event_type: str):
        try:
            Path(JSONL_FILE).parent.mkdir(parents=True, exist_ok=True)
            with open(JSONL_FILE, "a") as f:
                f.write(json.dumps(incident.to_jsonl_dict(event_type)) + "\n")
        except Exception as e:
            logger.warning("correlator.jsonl_write_failed", error=str(e)[:200])

    @staticmethod
    def _format_open(incident: Incident) -> str:
        return f"INCIDENT OPEN — {incident.incident_id}\n{incident.root_cause.summary}"

    @staticmethod
    def _format_escalation(incident: Incident) -> str:
        return f"ESCALATION — {incident.incident_id}\n{incident.root_cause.summary}"

    @staticmethod
    def _format_resolved(incident: Incident) -> str:
        return f"RESOLVED — {incident.incident_id}\n{incident.root_cause.summary}"
