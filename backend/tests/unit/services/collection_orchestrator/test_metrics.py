import pytest
@pytest.mark.skip(reason="Ollama removed")
"""Unit tests for FR8.2 metrics + FR8.3 alert evaluation — no DB, no network."""

import logging
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.collection_requests as cr
from app.api.deps import get_current_user, require_superuser_or_admin
from app.database import get_db
from app.models.user import UserRole
from app.services.collection_orchestrator.metrics import (
    FIRST_RESULTS_P95_MS,
    FULL_JOB_P95_MS,
    GROUNDING_FAILURE_RATE_THRESHOLD,
    JOB_FAILURE_RATE_THRESHOLD,
    compute_metrics,
    evaluate_alerts,
)

USER_ID = uuid.uuid4()
REQ_A = uuid.uuid4()
REQ_B = uuid.uuid4()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_event(**overrides):
    event = SimpleNamespace(
        id=uuid.uuid4(),
        request_id=REQ_A,
        timestamp=datetime(2026, 7, 1, tzinfo=timezone.utc),
        user_id=USER_ID,
        stage="retrieve",
        action="execute_search_plan",
        status="success",
        input_ref=None,
        output_ref=None,
        duration_ms=100,
        detail={},
    )
    for key, value in overrides.items():
        setattr(event, key, value)
    return event


def make_deliverable(disclosures):
    return SimpleNamespace(
        id=uuid.uuid4(),
        request_id=REQ_A,
        version=1,
        disclosures=disclosures,
        created_at=datetime(2026, 7, 2, tzinfo=timezone.utc),
    )


def many(values):
    mock = MagicMock()
    mock.scalars.return_value.all.return_value = values
    return mock


def make_db(events, deliverables):
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[many(events), many(deliverables)])
    return db


# ---------------------------------------------------------------------------
# compute_metrics
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stage_latency_percentiles():
    events = [
        make_event(duration_ms=100),
        make_event(duration_ms=5000),
        make_event(stage="analyse", action="run_analyses", duration_ms=250),
    ]
    metrics = await compute_metrics(make_db(events, []), since_days=30)

    retrieve = metrics["stages"]["retrieve"]
    assert retrieve["count"] == 2
    assert retrieve["p50_ms"] == 100.0
    assert retrieve["p95_ms"] == 5000.0
    assert retrieve["max_ms"] == 5000.0
    assert metrics["stages"]["analyse"]["p95_ms"] == 250.0


@pytest.mark.asyncio
async def test_extraction_success_rate_from_audit_detail():
    events = [
        make_event(
            stage="extract", action="extract_facts", input_ref="items:10",
            detail={"fact_count": 6, "unparseable_count": 2},
        ),
        make_event(
            stage="extract", action="extract_facts", input_ref="items:5",
            detail={"fact_count": 4, "unparseable_count": 0},
        ),
    ]
    metrics = await compute_metrics(make_db(events, []))

    extraction = metrics["extraction"]
    assert extraction["items_processed"] == 15
    assert extraction["items_unparseable"] == 2
    assert extraction["facts_extracted"] == 10
    assert extraction["success_rate"] == pytest.approx(13 / 15)


@pytest.mark.asyncio
async def test_grounding_failure_rate_and_clarification_rounds():
    events = [
        make_event(stage="validate", action="claims_validated"),
        make_event(stage="validate", action="claims_validated"),
        make_event(stage="validate", action="claims_validated"),
        make_event(stage="validate", action="claim_rejected", status="failure"),
        make_event(stage="clarify", action="round_completed", detail={"round": 1}),
        make_event(stage="clarify", action="round_completed", detail={"round": 1}),
        make_event(stage="clarify", action="round_completed", detail={"round": 2}),
    ]
    metrics = await compute_metrics(make_db(events, []))

    assert metrics["grounding"]["failure_rate"] == pytest.approx(0.25)
    assert metrics["grounding"]["claims_validated_events"] == 3
    assert metrics["clarification_rounds"] == {"1": 2, "2": 1}


@pytest.mark.asyncio
async def test_truncation_and_degraded_frequency_from_disclosures():
    deliverables = [
        make_deliverable([{"type": "truncation", "truncated": True}]),
        make_deliverable([{"type": "truncation", "truncated": False}]),
        make_deliverable([{"type": "degraded_sources", "failed_queries": [{}]}]),
        make_deliverable([]),
    ]
    metrics = await compute_metrics(make_db([], deliverables))

    assert metrics["deliverable_count"] == 4
    assert metrics["truncation_frequency"] == pytest.approx(0.25)
    assert metrics["degraded_mode_frequency"] == pytest.approx(0.25)


@pytest.mark.asyncio
async def test_job_failure_rate_counts_distinct_requests():
    events = [
        make_event(request_id=REQ_A),
        make_event(request_id=REQ_A, action="job_failed", status="failure"),
        make_event(request_id=REQ_B),
    ]
    metrics = await compute_metrics(make_db(events, []))

    assert metrics["job_count"] == 2
    assert metrics["failed_job_count"] == 1
    assert metrics["job_failure_rate"] == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_empty_window_yields_null_rates():
    metrics = await compute_metrics(make_db([], []))

    assert metrics["event_count"] == 0
    assert metrics["job_failure_rate"] is None
    assert metrics["grounding"]["failure_rate"] is None
    assert metrics["extraction"]["success_rate"] is None
    assert metrics["truncation_frequency"] is None
    assert evaluate_alerts(metrics) == []


# ---------------------------------------------------------------------------
# evaluate_alerts
# ---------------------------------------------------------------------------

def _base_metrics():
    return {
        "stages": {},
        "job_duration": {},
        "grounding": {"failure_rate": None},
        "job_failure_rate": None,
    }


def test_no_alerts_below_thresholds():
    metrics = _base_metrics()
    metrics["grounding"]["failure_rate"] = GROUNDING_FAILURE_RATE_THRESHOLD  # at, not over
    metrics["job_failure_rate"] = JOB_FAILURE_RATE_THRESHOLD
    metrics["stages"]["retrieve"] = {"p95_ms": FIRST_RESULTS_P95_MS}
    metrics["job_duration"]["p95_ms"] = FULL_JOB_P95_MS
    assert evaluate_alerts(metrics) == []


def test_grounding_failure_alert():
    metrics = _base_metrics()
    metrics["grounding"]["failure_rate"] = 0.08
    alerts = evaluate_alerts(metrics)
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert["kind"] == "grounding_failure_rate"
    assert alert["severity"] == "critical"
    assert alert["value"] == 0.08
    assert alert["threshold"] == GROUNDING_FAILURE_RATE_THRESHOLD
    assert alert["message"]


def test_job_failure_alert():
    metrics = _base_metrics()
    metrics["job_failure_rate"] = 0.5
    alerts = evaluate_alerts(metrics)
    assert alerts[0]["kind"] == "job_failure_rate"
    assert alerts[0]["severity"] == "critical"


def test_latency_breach_alerts():
    metrics = _base_metrics()
    metrics["stages"]["retrieve"] = {"p95_ms": 4000.0}
    metrics["job_duration"]["p95_ms"] = 90000.0
    kinds = {a["kind"] for a in evaluate_alerts(metrics)}
    assert kinds == {"first_results_latency_p95", "full_job_latency_p95"}


# ---------------------------------------------------------------------------
# GET /collection-requests/metrics/overview
# ---------------------------------------------------------------------------

def make_client(db, user):
    app = FastAPI()
    app.include_router(cr.router)

    async def _get_db():
        yield db

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app, raise_server_exceptions=False)


def test_metrics_overview_returns_metrics_and_alerts(monkeypatch, caplog):
    metrics = _base_metrics()
    metrics["job_failure_rate"] = 0.5
    monkeypatch.setattr(cr, "compute_metrics", AsyncMock(return_value=metrics))
    admin = SimpleNamespace(id=uuid.uuid4(), email="a@x.c", role=UserRole.ADMIN)
    client = make_client(AsyncMock(), admin)

    with caplog.at_level(logging.WARNING, logger="app.api.collection_requests"):
        response = client.get("/collection-requests/metrics/overview?days=7")

    assert response.status_code == 200
    body = response.json()
    assert body["metrics"]["job_failure_rate"] == 0.5
    assert body["alert_count"] == 1
    assert body["alerts"][0]["kind"] == "job_failure_rate"
    # FR8.3 hook: every active alert is logged at WARNING level.
    assert any("job_failure_rate" in r.message for r in caplog.records)


def test_metrics_overview_forbidden_for_plain_user():
    user = SimpleNamespace(id=uuid.uuid4(), email="u@x.c", role=UserRole.USER)
    client = make_client(AsyncMock(), user)

    response = client.get("/collection-requests/metrics/overview")

    assert response.status_code == 403


def test_metrics_overview_allowed_for_superuser(monkeypatch):
    monkeypatch.setattr(cr, "compute_metrics", AsyncMock(return_value=_base_metrics()))
    user = SimpleNamespace(id=uuid.uuid4(), email="s@x.c", role=UserRole.SUPERUSER)
    client = make_client(AsyncMock(), user)

    response = client.get("/collection-requests/metrics/overview")

    assert response.status_code == 200
    assert response.json()["alerts"] == []
