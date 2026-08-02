"""Unit tests for FR8.5 reproducibility — no DB, no network."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.collection_requests as cr
import app.services.collection_orchestrator.reproducibility as repro
from app.api.deps import get_current_user
from app.database import get_db
from app.services.collection_orchestrator.analysis_engine import (
    ANALYSIS_CODE_VERSION,
    AnalysisEngine,
)
from app.services.collection_orchestrator.reproducibility import (
    CODE_VERSION_CHANGED_NOTE,
    compare_reproduction,
    reproduce_analysis,
)

USER_ID = uuid.uuid4()
FOLDER_ID = uuid.uuid4()
FACTSET_ID = uuid.uuid4()

FACTS = [
    {"name": "revenue", "value": 1000.0, "unit": "XOF",
     "date": "2026-01-15", "confidence": 0.9},
    {"name": "revenue", "value": 2000.0, "unit": "XOF",
     "date": "2026-02-15", "confidence": 0.9},
    {"name": "revenue", "value": 999999.0, "unit": "XOF",
     "date": "2026-03-15", "confidence": 0.3},  # below threshold — excluded
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def one(value):
    mock = MagicMock()
    mock.scalar_one_or_none.return_value = value
    return mock


def first(value):
    mock = MagicMock()
    mock.scalars.return_value.first.return_value = value
    return mock


def many(values):
    mock = MagicMock()
    mock.scalars.return_value.all.return_value = values
    return mock


def make_folder():
    return SimpleNamespace(
        id=FOLDER_ID,
        user_id=USER_ID,
        confirmed_params={"query": "revenue", "analysis_types": ["descriptive"]},
    )


def make_factset():
    return SimpleNamespace(id=FACTSET_ID, request_id=FOLDER_ID, version=1, facts=FACTS)


def make_stored_row(output, code_version=ANALYSIS_CODE_VERSION):
    return SimpleNamespace(
        analysis_type="descriptive",
        output=output,
        thresholds_used={},
        code_version=code_version,
    )


def expected_output():
    """The deterministic output for the above-threshold facts."""
    facts = [f for f in FACTS if f["confidence"] >= 0.7]
    return AnalysisEngine().run(facts, ["descriptive"])[0]["output"]


# ---------------------------------------------------------------------------
# reproduce_analysis (mocked db)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reproduce_reruns_engine_on_stored_facts():
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[
        one(make_folder()),
        first(make_factset()),
        many([make_stored_row(expected_output())]),
    ])

    result = await reproduce_analysis(db, FOLDER_ID)

    assert result["factset_id"] == str(FACTSET_ID)
    assert result["fact_count"] == 2  # below-threshold fact excluded
    assert result["analyses"][0]["analysis_type"] == "descriptive"
    assert result["analyses"][0]["output"] == expected_output()


@pytest.mark.asyncio
async def test_reproduce_missing_factset_raises():
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[one(make_folder()), first(None)])

    with pytest.raises(ValueError, match="No FactSet"):
        await reproduce_analysis(db, FOLDER_ID)


# ---------------------------------------------------------------------------
# compare_reproduction (pure)
# ---------------------------------------------------------------------------

def _reproduction(stored_output, code_version=ANALYSIS_CODE_VERSION):
    return {
        "analyses": AnalysisEngine().run(
            [f for f in FACTS if f["confidence"] >= 0.7], ["descriptive"]
        ),
        "stored": [make_stored_row(stored_output, code_version).__dict__],
    }


def test_identical_reproduction_matches():
    comparison = compare_reproduction(_reproduction(expected_output()))

    assert comparison["matches"] is True
    assert comparison["differences"] == []
    assert comparison["code_version_stored"] == ANALYSIS_CODE_VERSION
    assert comparison["code_version_current"] == ANALYSIS_CODE_VERSION
    assert comparison["note"] is None


def test_tampered_output_detected():
    tampered = expected_output()
    tampered["metrics"][0]["total"] = 424242.0
    comparison = compare_reproduction(_reproduction(tampered))

    assert comparison["matches"] is False
    assert len(comparison["differences"]) == 1
    diff = comparison["differences"][0]
    assert diff["analysis_type"] == "descriptive"
    assert "differs" in diff["reason"]
    assert diff["stored_output"]["metrics"][0]["total"] == 424242.0
    assert diff["fresh_output"]["metrics"][0]["total"] != 424242.0


def test_code_version_change_short_circuits():
    comparison = compare_reproduction(
        _reproduction(expected_output(), code_version="0.9.0")
    )

    assert comparison["matches"] is None
    assert comparison["note"] == CODE_VERSION_CHANGED_NOTE
    assert comparison["code_version_stored"] == "0.9.0"
    assert comparison["code_version_current"] == ANALYSIS_CODE_VERSION


def test_missing_reproduced_type_reported():
    reproduction = _reproduction(expected_output())
    reproduction["analyses"] = []  # nothing reproduced
    comparison = compare_reproduction(reproduction)

    assert comparison["matches"] is False
    assert "not reproduced" in comparison["differences"][0]["reason"]


# ---------------------------------------------------------------------------
# GET /{id}/deliverable/reproducibility
# ---------------------------------------------------------------------------

def make_client(db, user=None):
    app = FastAPI()
    app.include_router(cr.router)

    async def _get_db():
        yield db

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_current_user] = lambda: (
        user or SimpleNamespace(id=USER_ID, email="u@x.c")
    )
    return TestClient(app, raise_server_exceptions=False)


def test_reproducibility_endpoint_matches(monkeypatch):
    folder = SimpleNamespace(id=FOLDER_ID, user_id=USER_ID)
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[one(folder)])
    monkeypatch.setattr(
        repro,
        "reproduce_analysis",
        AsyncMock(return_value=_reproduction(expected_output())),
    )
    client = make_client(db)

    response = client.get(f"/collection-requests/{FOLDER_ID}/deliverable/reproducibility")

    assert response.status_code == 200
    body = response.json()
    assert body["matches"] is True
    assert body["code_version_current"] == ANALYSIS_CODE_VERSION


def test_reproducibility_endpoint_404_without_factset(monkeypatch):
    folder = SimpleNamespace(id=FOLDER_ID, user_id=USER_ID)
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[one(folder)])
    monkeypatch.setattr(
        repro,
        "reproduce_analysis",
        AsyncMock(side_effect=ValueError("No FactSet stored")),
    )
    client = make_client(db)

    response = client.get(f"/collection-requests/{FOLDER_ID}/deliverable/reproducibility")

    assert response.status_code == 404


def test_reproducibility_endpoint_owner_scoped():
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[one(None)])  # not found for this user
    client = make_client(db)

    response = client.get(f"/collection-requests/{FOLDER_ID}/deliverable/reproducibility")

    assert response.status_code == 404
