"""FR4.2.5 grounding validator tests — pass/fail/strip/regeneration."""

import pytest

from app.services.collection_orchestrator.grounding_validator import (
    GroundingValidator,
    ValidationReport,
)


@pytest.fixture
def validator():
    return GroundingValidator()


@pytest.fixture
def analyses():
    return [
        {
            "analysis_type": "descriptive",
            "output": {
                "metrics": [
                    {
                        "metric": "revenue",
                        "count": 2,
                        "total": 3000.0,
                        "mean": 1500.0,
                        "min": 1000.0,
                        "max": 2000.0,
                        "values": [
                            {"value": 1000.0, "date": "2023",
                             "source_refs": [{"document_id": "d1", "page": 3}]},
                            {"value": 2000.0, "date": "2024",
                             "source_refs": [{"document_id": "d1", "page": 4}]},
                        ],
                    }
                ]
            },
            "provenance": [{"document_id": "d1", "chunk_id": "c1", "page": 3}],
        },
        {
            "analysis_type": "trend",
            "output": {
                "trends": [
                    {
                        "metric": "revenue",
                        "sufficient_data": True,
                        "slope": 12.49,
                        "yoy_changes": [
                            {"from_year": 2023, "to_year": 2024,
                             "change_pct": 12.49}
                        ],
                    }
                ]
            },
            "provenance": [{"document_id": "d1", "chunk_id": "c1", "page": 3}],
        },
    ]


@pytest.fixture
def insights():
    return [
        {
            "statement": "Revenue totalled 3,000 across the period",
            "source_refs": [
                {"document_id": "d1", "chunk_id": "c1", "page": 3,
                 "title": "Annual Report"}
            ],
            "validation_status": "validated",
        }
    ]


GOOD_SENTENCE = "Revenue totalled 3,000 across the period ([source: Annual Report, p. 3])."
BAD_SENTENCE = "Revenue reached 9,999 in the same period ([source: Annual Report, p. 3])."


class TestValidate:
    def test_correct_summary_passes(self, validator, analyses, insights):
        md = f"## Overview\n\n{GOOD_SENTENCE}\n"
        report = validator.validate(md, analyses, insights)
        assert report.passed is True
        assert report.checked_claims == 1
        assert report.failed_claims == []
        assert report.numeric_failures == []

    def test_invented_number_fails(self, validator, analyses, insights):
        md = f"## Overview\n\n{BAD_SENTENCE}\n"
        report = validator.validate(md, analyses, insights)
        assert report.passed is False
        assert len(report.numeric_failures) == 1
        assert report.numeric_failures[0]["value"] == "9,999"
        assert report.numeric_failures[0]["sentence"] == BAD_SENTENCE

    def test_format_number_rounding_tolerated(self, validator, analyses, insights):
        # 12.49 exists in the trend output; format_number renders 12.5%
        md = ("## Trends & Patterns\n\nGrowth was 12.5% year over year "
              "([source: Annual Report, p. 3]).\n")
        report = validator.validate(md, analyses, insights)
        assert report.passed is True

    def test_unknown_citation_fails(self, validator, analyses, insights):
        md = ("## Overview\n\nRevenue totalled 3,000 across the period "
              "([source: Unknown Memo, p. 9]).\n")
        report = validator.validate(md, analyses, insights)
        assert report.passed is False
        assert report.failed_claims[0]["reason"] == (
            "citation matches no validated source ref"
        )

    def test_iso_dates_not_treated_as_numbers(self, validator, analyses, insights):
        md = ("## Overview\n\nThe period ended 2024-12-31 with revenue of "
              "3,000 ([source: Annual Report, p. 3]).\n")
        report = validator.validate(md, analyses, insights)
        # 2024-12-31 must not explode into failing "2024"/"12"/"31" tokens
        assert report.passed is True


class TestStrip:
    def test_strips_exactly_offending_sentences(self, validator, analyses, insights):
        md = (
            "## Overview\n\n"
            f"- {GOOD_SENTENCE}\n"
            f"- {BAD_SENTENCE}\n"
        )
        report = validator.validate(md, analyses, insights)
        assert report.passed is False
        cleaned, removed = validator.strip_ungrounded(md, report)
        assert removed == [BAD_SENTENCE]
        assert GOOD_SENTENCE in cleaned
        assert "9,999" not in cleaned
        # The bullet that held only the bad sentence is gone entirely
        assert f"- {BAD_SENTENCE}" not in cleaned


class TestRegeneration:
    @pytest.mark.asyncio
    async def test_retry_until_valid(self, validator, analyses, insights):
        calls = []

        async def summary_fn():
            calls.append(1)
            if len(calls) == 1:
                return BAD_SENTENCE
            return GOOD_SENTENCE

        final_md, report, removed = await validator.validate_with_regeneration(
            summary_fn, analyses, insights, max_attempts=2
        )
        assert len(calls) == 2
        assert report.passed is True
        assert final_md == GOOD_SENTENCE
        assert removed == []

    @pytest.mark.asyncio
    async def test_exhausts_attempts_then_strips(self, validator, analyses, insights):
        calls = []

        async def summary_fn():
            calls.append(1)
            return f"{GOOD_SENTENCE} {BAD_SENTENCE}"

        final_md, report, removed = await validator.validate_with_regeneration(
            summary_fn, analyses, insights, max_attempts=2
        )
        assert len(calls) == 2  # retried up to max_attempts
        assert report.passed is False
        assert removed == [BAD_SENTENCE]
        assert GOOD_SENTENCE in final_md
        assert "9,999" not in final_md

    @pytest.mark.asyncio
    async def test_none_summary_short_circuits(self, validator, analyses, insights):
        calls = []

        async def summary_fn():
            calls.append(1)
            return None

        final_md, report, removed = await validator.validate_with_regeneration(
            summary_fn, analyses, insights
        )
        assert final_md is None
        assert report.passed is False
        assert removed == []
        assert len(calls) == 1  # no point regenerating a deliberate None

    @pytest.mark.asyncio
    async def test_audit_written_when_db_provided(
        self, validator, analyses, insights, monkeypatch
    ):
        events = []

        async def fake_log_event(db, **kwargs):
            events.append(kwargs)

        monkeypatch.setattr(
            "app.services.collection_orchestrator.grounding_validator.log_event",
            fake_log_event,
        )
        from uuid import uuid4

        async def summary_fn():
            return GOOD_SENTENCE

        await validator.validate_with_regeneration(
            summary_fn, analyses, insights, db=object(), request_id=uuid4()
        )
        assert len(events) == 1
        assert events[0]["stage"] == "validate"
        assert events[0]["action"] == "claims_validated"

    @pytest.mark.asyncio
    async def test_no_audit_without_db(self, validator, analyses, insights):
        # Pure path: no db -> no audit, no error
        async def summary_fn():
            return GOOD_SENTENCE

        final_md, report, _ = await validator.validate_with_regeneration(
            summary_fn, analyses, insights
        )
        assert report.passed is True
