"""Unit tests for /admin/pipeline-stats assembler logic."""
import pytest

from app.models.pipeline import StageEnum, StageStatus
from app.schemas.admin import PipelineStageStats, PipelineStatsResponse

PIPELINE_STAGE_ORDER = [
    StageEnum.UPLOADED,
    StageEnum.OCR,
    StageEnum.CHUNKED,
    StageEnum.EMBEDDED,
    StageEnum.INDEXED,
    StageEnum.ARTICLES,
    StageEnum.ENTITIES,
    StageEnum.ENRICHED,
]


def _build_response(active_rows, hourly_rows, tenmin_rows):
    """Replicate the assembler logic from the endpoint."""
    counts = {
        s.value: {"pending": 0, "running": 0, "failed": 0} for s in PIPELINE_STAGE_ORDER
    }
    for stage_key, status_key, cnt in active_rows:
        if stage_key in counts and status_key in counts[stage_key]:
            counts[stage_key][status_key] = cnt

    stages = []
    for stage_enum in PIPELINE_STAGE_ORDER:
        key = stage_enum.value
        c = counts[key]
        stages.append(
            PipelineStageStats(
                stage=key,
                pending=c["pending"],
                running=c["running"],
                failed=c["failed"],
                throughput_per_hour=hourly_rows.get(key, 0),
                throughput_per_10min=tenmin_rows.get(key, 0),
            )
        )

    total_active = sum(s.running for s in stages)
    max_pending = max((s.pending for s in stages), default=0)
    bottleneck = None
    if max_pending > 0:
        bottleneck = next(s.stage for s in stages if s.pending == max_pending)

    return PipelineStatsResponse(
        stages=stages,
        total_active=total_active,
        bottleneck_stage=bottleneck,
    )


class TestPipelineStatsAssembler:
    def test_returns_all_8_stages(self):
        result = _build_response([], {}, {})
        assert len(result.stages) == 8

    def test_stages_in_correct_order(self):
        result = _build_response([], {}, {})
        expected = [s.value for s in PIPELINE_STAGE_ORDER]
        assert [s.stage for s in result.stages] == expected

    def test_zero_fill_when_no_data(self):
        result = _build_response([], {}, {})
        for s in result.stages:
            assert s.pending == 0
            assert s.running == 0
            assert s.failed == 0
            assert s.throughput_per_hour == 0
            assert s.throughput_per_10min == 0

    def test_total_active_is_sum_of_running(self):
        active_rows = [
            ("embedded", "running", 5),
            ("ocr", "running", 2),
            ("chunked", "pending", 100),
        ]
        result = _build_response(active_rows, {}, {})
        assert result.total_active == 7

    def test_bottleneck_is_stage_with_highest_pending(self):
        active_rows = [
            ("embedded", "pending", 2200),
            ("ocr", "pending", 10),
            ("chunked", "pending", 50),
        ]
        result = _build_response(active_rows, {}, {})
        assert result.bottleneck_stage == "embedded"

    def test_bottleneck_none_when_all_pending_zero(self):
        active_rows = [("embedded", "running", 3)]
        result = _build_response(active_rows, {}, {})
        assert result.bottleneck_stage is None

    def test_throughput_mapped_correctly(self):
        result = _build_response(
            [],
            {"embedded": 45, "ocr": 100},
            {"embedded": 8},
        )
        embedded = next(s for s in result.stages if s.stage == "embedded")
        assert embedded.throughput_per_hour == 45
        assert embedded.throughput_per_10min == 8
        ocr = next(s for s in result.stages if s.stage == "ocr")
        assert ocr.throughput_per_hour == 100
        assert ocr.throughput_per_10min == 0

    def test_failed_count_populated(self):
        active_rows = [("ocr", "failed", 3)]
        result = _build_response(active_rows, {}, {})
        ocr = next(s for s in result.stages if s.stage == "ocr")
        assert ocr.failed == 3
