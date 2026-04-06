"""Unit tests for PipelineStage model, StageEnum, and StageStatus."""
import uuid

import pytest

from app.models.pipeline import PipelineStage, StageEnum, StageStatus


class TestStageEnum:
    def test_has_all_8_stages(self):
        stages = list(StageEnum)
        assert len(stages) == 8
        assert StageEnum.UPLOADED in stages
        assert StageEnum.OCR in stages
        assert StageEnum.CHUNKED in stages
        assert StageEnum.EMBEDDED in stages
        assert StageEnum.INDEXED in stages
        assert StageEnum.ARTICLES in stages
        assert StageEnum.ENTITIES in stages
        assert StageEnum.ENRICHED in stages

    def test_ordering_uploaded_first(self):
        members = list(StageEnum)
        assert members[0] == StageEnum.UPLOADED

    def test_ordering_enriched_last(self):
        members = list(StageEnum)
        assert members[-1] == StageEnum.ENRICHED

    def test_next_stage_returns_next(self):
        assert StageEnum.UPLOADED.next_stage() == StageEnum.OCR
        assert StageEnum.OCR.next_stage() == StageEnum.CHUNKED
        assert StageEnum.CHUNKED.next_stage() == StageEnum.EMBEDDED
        assert StageEnum.EMBEDDED.next_stage() == StageEnum.INDEXED
        assert StageEnum.INDEXED.next_stage() == StageEnum.ARTICLES
        assert StageEnum.ARTICLES.next_stage() == StageEnum.ENTITIES
        assert StageEnum.ENTITIES.next_stage() == StageEnum.ENRICHED

    def test_next_stage_returns_none_for_enriched(self):
        assert StageEnum.ENRICHED.next_stage() is None

    def test_values_are_lowercase(self):
        for stage in StageEnum:
            assert stage.value == stage.value.lower()
            assert stage.value == stage.name.lower()


class TestStageStatus:
    def test_has_5_statuses(self):
        statuses = list(StageStatus)
        assert len(statuses) == 5
        assert StageStatus.PENDING in statuses
        assert StageStatus.RUNNING in statuses
        assert StageStatus.COMPLETED in statuses
        assert StageStatus.FAILED in statuses
        assert StageStatus.SKIPPED in statuses

    def test_values_are_lowercase(self):
        for status in StageStatus:
            assert status.value == status.value.lower()


class TestPipelineStageModel:
    def test_can_be_instantiated(self):
        doc_id = uuid.uuid4()
        stage = PipelineStage(
            document_id=doc_id,
            stage=StageEnum.OCR,
            status=StageStatus.PENDING,
        )
        assert stage.document_id == doc_id
        assert stage.stage == StageEnum.OCR
        assert stage.status == StageStatus.PENDING

    def test_default_attempt_is_zero(self):
        stage = PipelineStage(
            document_id=uuid.uuid4(),
            stage=StageEnum.UPLOADED,
            status=StageStatus.PENDING,
        )
        assert stage.attempt == 0

    def test_default_max_attempts_is_three(self):
        stage = PipelineStage(
            document_id=uuid.uuid4(),
            stage=StageEnum.UPLOADED,
            status=StageStatus.PENDING,
        )
        assert stage.max_attempts == 3

    def test_repr_includes_stage_name_and_status(self):
        doc_id = uuid.uuid4()
        stage = PipelineStage(
            document_id=doc_id,
            stage=StageEnum.CHUNKED,
            status=StageStatus.RUNNING,
        )
        r = repr(stage)
        assert "CHUNKED" in r
        assert "RUNNING" in r


class TestStageRetryConfig:
    def test_configured_stages(self):
        from app.models.pipeline import STAGE_RETRY_CONFIG, StageEnum
        expected = {StageEnum.OCR, StageEnum.CHUNKED, StageEnum.EMBEDDED, StageEnum.INDEXED, StageEnum.ARTICLES, StageEnum.ENTITIES}
        assert set(STAGE_RETRY_CONFIG.keys()) == expected

    def test_no_config_for_terminal_stages(self):
        from app.models.pipeline import STAGE_RETRY_CONFIG, StageEnum
        assert StageEnum.UPLOADED not in STAGE_RETRY_CONFIG
        assert StageEnum.ENRICHED not in STAGE_RETRY_CONFIG

    def test_required_keys(self):
        from app.models.pipeline import STAGE_RETRY_CONFIG
        required_keys = {"max_attempts", "backoff", "soft_timeout", "hard_timeout"}
        for stage, config in STAGE_RETRY_CONFIG.items():
            assert set(config.keys()) == required_keys, f"Missing keys in {stage}"
