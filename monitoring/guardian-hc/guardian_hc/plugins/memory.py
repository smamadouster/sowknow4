"""Memory plugin — incident learning engine (Learner agent)."""

from __future__ import annotations

import json
from pathlib import Path

import structlog

from guardian_hc.plugin import (
    GuardianPlugin, CheckResult, HealResult, Insight,
    CheckContext, AnalysisContext, Severity,
)
from guardian_hc.db import MetricsDB

logger = structlog.get_logger()

CONFIDENCE_THRESHOLD = 0.7


class PatternMatcher:
    """Evaluates current metrics against learned patterns."""

    def __init__(self, db: MetricsDB):
        self._db = db

    async def evaluate(self) -> list[dict]:
        """Return patterns whose trigger conditions match current metrics."""
        patterns = await self._db.get_active_patterns()
        matches = []

        for pattern in patterns:
            if pattern["confidence"] < CONFIDENCE_THRESHOLD:
                continue

            conditions = pattern["trigger_conditions"]
            if isinstance(conditions, str):
                conditions = json.loads(conditions)

            all_match = True
            for metric, rule in conditions.items():
                current = await self._db.get_latest(metric)
                if current is None:
                    all_match = False
                    break

                if isinstance(rule, dict):
                    if ">" in rule and current <= rule[">"]:
                        all_match = False
                        break
                    if "<" in rule and current >= rule["<"]:
                        all_match = False
                        break
                    if "==" in rule and current != rule["=="]:
                        all_match = False
                        break

            if all_match:
                matches.append(pattern)

        return matches


class MemoryPlugin(GuardianPlugin):
    """Learns from incidents and applies preventive patterns."""

    name = "memory"
    enabled = True

    def __init__(self, config: dict):
        self._bootstrap_sources = config.get("bootstrap_sources", [])
        self._bootstrapped = False

    async def check(self, context: CheckContext) -> list[CheckResult]:
        return []

    async def analyze(self, context: AnalysisContext) -> list[Insight]:
        db: MetricsDB | None = context.metrics_db or context.patterns_db
        if not db:
            return []

        if not self._bootstrapped:
            await self._bootstrap(db)
            self._bootstrapped = True

        matcher = PatternMatcher(db)
        matches = await matcher.evaluate()

        insights = []
        for pattern in matches:
            insights.append(Insight(
                plugin=self.name,
                insight_type="pattern_match",
                severity=Severity.WARNING,
                summary=f"Pattern '{pattern['pattern_name']}' matched - {pattern['predicted_outcome']}",
                pattern_name=pattern["pattern_name"],
                confidence=pattern["confidence"],
                recommended_action=pattern["recommended_action"],
            ))
            logger.info(
                "memory.pattern_matched",
                pattern=pattern["pattern_name"],
                confidence=pattern["confidence"],
                action=pattern["recommended_action"],
            )

        return insights

    async def _bootstrap(self, db: MetricsDB):
        """Seed patterns from SOWKNOW history on first run."""
        existing = await db.get_active_patterns()
        if existing:
            logger.info("memory.bootstrap.skipped", reason="patterns already exist", count=len(existing))
            return

        seed_patterns = [
            {
                "pattern_name": "docker-nftables-cascade",
                "trigger_conditions": {"network.probes_failed": {">": 0}},
                "predicted_outcome": "Inter-container routing failure cascade",
                "recommended_action": "flush_iptables_prerouting",
                "confidence": 0.7,
            },
            {
                "pattern_name": "redis-oom-cascade",
                "trigger_conditions": {"redis.memory_rss": {">": 85}},
                "predicted_outcome": "Backend crash and celery worker failure within 20min",
                "recommended_action": "redis_memory_purge_and_pause_ingestion",
                "confidence": 0.7,
            },
            {
                "pattern_name": "backend-restart-loop",
                "trigger_conditions": {"backend.restart_count": {">": 2}},
                "predicted_outcome": "Code-level bug — restarts won't fix it",
                "recommended_action": "stop_restarting_alert_code_bug",
                "confidence": 0.7,
            },
            {
                "pattern_name": "entity-queue-explosion",
                "trigger_conditions": {"celery.queue.document_processing": {">": 500}},
                "predicted_outcome": "Queue backlog causing memory pressure on workers",
                "recommended_action": "apply_backpressure_and_restart_light_worker",
                "confidence": 0.6,
            },
        ]

        for p in seed_patterns:
            await db.create_pattern(**p)
            logger.info("memory.bootstrap.seeded", pattern=p["pattern_name"])

        for source in self._bootstrap_sources:
            try:
                path = Path(source)
                if path.exists() and path.suffix == ".json":
                    data = json.loads(path.read_text())
                    if isinstance(data, list):
                        logger.info("memory.bootstrap.buglog", source=source, entries=len(data))
                    elif isinstance(data, dict) and "bugs" in data:
                        logger.info("memory.bootstrap.buglog", source=source, entries=len(data["bugs"]))
            except Exception as e:
                logger.warning("memory.bootstrap.source_error", source=source, error=str(e)[:200])

        logger.info("memory.bootstrap.complete", patterns_seeded=len(seed_patterns))
