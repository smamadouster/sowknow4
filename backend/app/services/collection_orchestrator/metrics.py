"""Collection Orchestrator metrics + alert evaluation — FR8.2 / FR8.3.

``compute_metrics`` derives operational metrics from the append-only
``collection_audit_events`` trail (plus deliverable disclosures) over a
rolling window. ``evaluate_alerts`` turns those metrics into alert dicts
against the NFR-1 / FR8.3 thresholds; the API layer logs each active alert
at WARNING level, which is the hook point for the existing log-scraping
monitoring (guardian-hc).

Field-source assumptions (documented per FR8.2):

- Stage latency: ``duration_ms`` on audit events, grouped by stage.
  "First results" latency is the ``retrieve`` stage; "full job" latency is
  the per-request SUM of stage durations (stages run sequentially).
- Extraction success: ``extract``-stage ``extract_facts`` events carry
  ``input_ref="items:N"`` and ``detail.unparseable_count``; success rate is
  (items − unparseable) / items. Facts extracted is summed from
  ``detail.fact_count`` for context.
- Grounding-validation failure rate: ``claim_rejected`` events vs
  (``claim_rejected`` + ``claims_validated``) events in stage ``validate``.
- Clarification rounds: ``clarify``-stage events whose detail carries a
  ``round`` number (written by the conversation manager); the distribution
  counts events per round number.
- Truncation / degraded-mode frequency: share of deliverables created in
  the window whose disclosures contain a ``truncation`` disclosure with
  ``truncated=true``, resp. a ``degraded_sources`` disclosure.
- Job failure rate: distinct requests with a ``job_failed`` event over all
  distinct requests seen in the window.
"""

import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.collection_orchestrator import CollectionAuditEvent, Deliverable

logger = logging.getLogger(__name__)

# FR8.3 / NFR-1 alert thresholds.
GROUNDING_FAILURE_RATE_THRESHOLD = 0.05   # > 5% of validation runs
JOB_FAILURE_RATE_THRESHOLD = 0.10         # > 10% of jobs
FIRST_RESULTS_P95_MS = 3000               # NFR-1: first results ≤ 3s
FULL_JOB_P95_MS = 60000                   # NFR-1: full job ≤ 60s at ≤10k items

_TRUNCATION_TYPES = {"truncation"}


def _percentile(values: list[int], pct: float) -> float | None:
    """Nearest-rank percentile; None for an empty sample."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100 * len(ordered)))
    return float(ordered[rank - 1])


def _stage_stats(durations: list[int]) -> dict[str, Any]:
    return {
        "count": len(durations),
        "p50_ms": _percentile(durations, 50),
        "p95_ms": _percentile(durations, 95),
        "max_ms": float(max(durations)) if durations else None,
    }


async def compute_metrics(db: AsyncSession, since_days: int = 30) -> dict[str, Any]:
    """FR8.2 operational metrics over the trailing ``since_days`` window."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)

    result = await db.execute(
        select(CollectionAuditEvent).where(CollectionAuditEvent.timestamp >= cutoff)
    )
    events = list(result.scalars().all())

    result = await db.execute(
        select(Deliverable).where(Deliverable.created_at >= cutoff)
    )
    deliverables = list(result.scalars().all())

    request_ids = {str(e.request_id) for e in events}
    failed_request_ids = {
        str(e.request_id) for e in events if e.action == "job_failed"
    }

    # ── Stage latency ────────────────────────────────────────────────────
    stage_durations: dict[str, list[int]] = {}
    per_request_duration: dict[str, int] = {}
    for event in events:
        if event.duration_ms is None:
            continue
        stage_durations.setdefault(event.stage or "unknown", []).append(
            event.duration_ms
        )
        key = str(event.request_id)
        per_request_duration[key] = (
            per_request_duration.get(key, 0) + event.duration_ms
        )
    stages = {
        stage: _stage_stats(durations)
        for stage, durations in sorted(stage_durations.items())
    }
    job_durations = list(per_request_duration.values())

    # ── Extraction success ───────────────────────────────────────────────
    items_total = 0
    unparseable_total = 0
    facts_extracted = 0
    for event in events:
        if event.stage != "extract":
            continue
        detail = event.detail or {}
        input_ref = event.input_ref or ""
        if input_ref.startswith("items:"):
            try:
                items_total += int(input_ref.split(":", 1)[1])
            except ValueError:
                pass
        unparseable_total += int(detail.get("unparseable_count") or 0)
        facts_extracted += int(detail.get("fact_count") or 0)
    parseable = max(items_total - unparseable_total, 0)
    extraction = {
        "items_processed": items_total,
        "items_unparseable": unparseable_total,
        "facts_extracted": facts_extracted,
        "success_rate": (parseable / items_total) if items_total else None,
    }

    # ── Grounding validation ─────────────────────────────────────────────
    validated = sum(1 for e in events if e.action == "claims_validated")
    rejected = sum(1 for e in events if e.action == "claim_rejected")
    grounding = {
        "claims_validated_events": validated,
        "claim_rejected_events": rejected,
        "failure_rate": (
            rejected / (validated + rejected) if (validated + rejected) else None
        ),
    }

    # ── Clarification rounds ─────────────────────────────────────────────
    round_distribution: dict[str, int] = {}
    for event in events:
        if event.stage != "clarify":
            continue
        round_no = (event.detail or {}).get("round")
        if isinstance(round_no, int):
            key = str(round_no)
            round_distribution[key] = round_distribution.get(key, 0) + 1

    # ── Deliverable-derived frequencies ──────────────────────────────────
    truncated = 0
    degraded = 0
    for deliverable in deliverables:
        disclosures = deliverable.disclosures or []
        types = {d.get("type") for d in disclosures if isinstance(d, dict)}
        if any(
            d.get("type") in _TRUNCATION_TYPES and d.get("truncated")
            for d in disclosures
            if isinstance(d, dict)
        ):
            truncated += 1
        if "degraded_sources" in types:
            degraded += 1
    deliverable_count = len(deliverables)

    job_count = len(request_ids)
    return {
        "window_days": since_days,
        "since": cutoff.isoformat(),
        "event_count": len(events),
        "job_count": job_count,
        "deliverable_count": deliverable_count,
        "stages": stages,
        "job_duration": {
            "p50_ms": _percentile(job_durations, 50),
            "p95_ms": _percentile(job_durations, 95),
        },
        "extraction": extraction,
        "grounding": grounding,
        "clarification_rounds": round_distribution,
        "truncation_frequency": (
            truncated / deliverable_count if deliverable_count else None
        ),
        "degraded_mode_frequency": (
            degraded / deliverable_count if deliverable_count else None
        ),
        "job_failure_rate": (
            len(failed_request_ids) / job_count if job_count else None
        ),
        "failed_job_count": len(failed_request_ids),
    }


def evaluate_alerts(metrics: dict[str, Any]) -> list[dict[str, Any]]:
    """FR8.3 threshold evaluation. Each alert:
    {kind, severity, message, value, threshold}."""
    alerts: list[dict[str, Any]] = []

    def _alert(kind, severity, message, value, threshold):
        alerts.append({
            "kind": kind,
            "severity": severity,
            "message": message,
            "value": value,
            "threshold": threshold,
        })

    grounding_rate = (metrics.get("grounding") or {}).get("failure_rate")
    if grounding_rate is not None and grounding_rate > GROUNDING_FAILURE_RATE_THRESHOLD:
        _alert(
            "grounding_failure_rate",
            "critical",
            f"Grounding-validation failure rate {grounding_rate:.1%} exceeds "
            f"{GROUNDING_FAILURE_RATE_THRESHOLD:.0%} — generated summaries are "
            "frequently failing grounding checks.",
            grounding_rate,
            GROUNDING_FAILURE_RATE_THRESHOLD,
        )

    job_failure_rate = metrics.get("job_failure_rate")
    if job_failure_rate is not None and job_failure_rate > JOB_FAILURE_RATE_THRESHOLD:
        _alert(
            "job_failure_rate",
            "critical",
            f"Collection job failure rate {job_failure_rate:.1%} exceeds "
            f"{JOB_FAILURE_RATE_THRESHOLD:.0%}.",
            job_failure_rate,
            JOB_FAILURE_RATE_THRESHOLD,
        )

    retrieve_p95 = ((metrics.get("stages") or {}).get("retrieve") or {}).get("p95_ms")
    if retrieve_p95 is not None and retrieve_p95 > FIRST_RESULTS_P95_MS:
        _alert(
            "first_results_latency_p95",
            "warning",
            f"Retrieve-stage p95 latency {retrieve_p95:.0f}ms breaches the "
            f"NFR-1 first-results budget of {FIRST_RESULTS_P95_MS}ms.",
            retrieve_p95,
            FIRST_RESULTS_P95_MS,
        )

    job_p95 = (metrics.get("job_duration") or {}).get("p95_ms")
    if job_p95 is not None and job_p95 > FULL_JOB_P95_MS:
        _alert(
            "full_job_latency_p95",
            "warning",
            f"Full-job p95 latency {job_p95:.0f}ms breaches the NFR-1 "
            f"{FULL_JOB_P95_MS}ms budget (≤10k items).",
            job_p95,
            FULL_JOB_P95_MS,
        )

    return alerts
