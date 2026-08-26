"""S4-04 data-processing control, quality, budget, and traceability tests."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from ndt_agents.contracts.v1 import AgentStatus, TenantScope
from ndt_agents.professional.processing import (
    CandidateProcessingStatus,
    DataOrigin,
    DataProcessingControlSkill,
    ProcessingBudget,
    ProcessingCandidate,
    ProcessingFigure,
    ProcessingObservation,
    ProcessingQualityPolicy,
    ProcessingRequest,
    ProcessingSourceManifest,
    to_report_evidence,
)
from tests.professional.test_inspection_plan import scope
from tests.professional.test_inspection_report import artifact

ROOT = Path(__file__).resolve().parents[2]
TASK = UUID("30000000-0000-4000-8000-000000000401")
RUN = UUID("30000000-0000-4000-8000-000000000501")
DATASET = UUID("30000000-0000-4000-8000-000000000601")
STRUCTURE = UUID("30000000-0000-4000-8000-000000000701")
COMPONENT = UUID("30000000-0000-4000-8000-000000000801")
LOCATION = UUID("30000000-0000-4000-8000-000000000901")
OBSERVATION = UUID("30000000-0000-4000-8000-000000001001")


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def source(
    owner: TenantScope | None = None,
    *,
    origin: DataOrigin = DataOrigin.PRODUCTION,
    acquired_at: datetime = datetime(2026, 8, 25, 1, 0, tzinfo=UTC),
) -> ProcessingSourceManifest:
    resolved_owner = owner or scope()
    return ProcessingSourceManifest(
        dataset_id=DATASET,
        scope=resolved_owner,
        artifact=artifact(resolved_owner, "30000000-0000-4000-8000-000000000011"),
        dataset_sha256=digest("processing-dataset"),
        origin=origin,
        method_code="UT",
        structure_id=STRUCTURE,
        component_id=COMPONENT,
        location_id=LOCATION,
        coordinate_reference="local-grid-v1",
        channel_count=2,
        sample_count=1_000,
        sample_rate_hz=Decimal("1000000"),
        signal_dimension="VELOCITY",
        signal_unit="m/s",
        acquisition_settings={"gain_db": 20, "pulse_voltage_v": 100},
        instrument_id="ut-device-1",
        instrument_version="instrument-v1",
        calibration_id="ut-calibration-1",
        calibration_version="calibration-v1",
        calibration_valid_from=datetime(2026, 8, 1, tzinfo=UTC),
        calibration_valid_until=datetime(2026, 9, 1, tzinfo=UTC),
        operator_id=resolved_owner.user_id,
        acquired_at=acquired_at,
    )


def request(item: ProcessingSourceManifest, **changes: object) -> ProcessingRequest:
    values: dict[str, object] = {
        "task_id": TASK,
        "run_id": RUN,
        "request_id": "processing-request-1",
        "source": item,
        "adapter_version": "adapter-v1",
        "parser_version": "parser-v1",
        "algorithm_version": "algorithm-v1",
        "output_schema_id": "inspection-processing-output@1.0.0",
        "parameters": {"threshold": "0.80", "window": 32},
        "budget": ProcessingBudget(
            max_duration_ms=10_000,
            max_output_bytes=10_000,
            max_observations=10,
            max_figures=2,
        ),
        "quality_policy": ProcessingQualityPolicy(
            policy_version="processing-quality-v1",
            minimum_completeness_ratio=Decimal("0.95"),
            minimum_quality_score=Decimal("0.90"),
            maximum_corrupted_ratio=Decimal("0.01"),
        ),
    }
    values.update(changes)
    return ProcessingRequest.model_validate(values)


def parameters_sha256() -> str:
    return digest('{"threshold":"0.80","window":32}')


def candidate(
    item: ProcessingSourceManifest,
    *,
    owner: TenantScope | None = None,
    origin_status: CandidateProcessingStatus = CandidateProcessingStatus.SUCCESS,
    **changes: object,
) -> ProcessingCandidate:
    resolved_owner = owner or item.scope
    output = artifact(
        resolved_owner,
        "30000000-0000-4000-8000-000000000012",
        media_type="application/json",
    )
    observation = ProcessingObservation(
        observation_id=OBSERVATION,
        scope=resolved_owner,
        run_id=RUN,
        dataset_id=DATASET,
        structure_id=STRUCTURE,
        component_id=COMPONENT,
        location_id=LOCATION,
        channel_index=0,
        sample_start=100,
        sample_end=200,
        name="Ultrasonic indication depth",
        dimension="LENGTH",
        unit="mm",
        value=Decimal("12.5"),
        coordinates=(Decimal("1"), Decimal("2"), Decimal("0")),
        evidence_sha256=digest("processing-observation"),
    )
    figure = ProcessingFigure(
        figure_id="ut-waveform",
        artifact=artifact(
            resolved_owner,
            "30000000-0000-4000-8000-000000000013",
            media_type="image/png",
        ),
        source_observation_ids=(OBSERVATION,),
    )
    values: dict[str, object] = {
        "run_id": RUN,
        "scope": resolved_owner,
        "dataset_id": DATASET,
        "dataset_sha256": item.dataset_sha256,
        "method_code": "UT",
        "adapter_version": "adapter-v1",
        "parser_version": "parser-v1",
        "algorithm_version": "algorithm-v1",
        "output_schema_id": "inspection-processing-output@1.0.0",
        "parameters_sha256": parameters_sha256(),
        "output_artifact": output,
        "output_sha256": output.sha256,
        "observations": (observation,),
        "figures": (figure,),
        "completeness_ratio": Decimal("1"),
        "quality_score": Decimal("0.99"),
        "corrupted_ratio": Decimal("0"),
        "duration_ms": 1_000,
        "output_bytes": 128,
        "adapter_calls": 1,
        "attempts": 1,
        "model_calls": 0,
        "network_calls": 0,
        "physical_commands": 0,
        "status": origin_status,
    }
    if origin_status in {CandidateProcessingStatus.FAILED, CandidateProcessingStatus.BLOCKED}:
        values.update(
            {
                "observations": (),
                "figures": (),
                "failure_code": "ADAPTER_FAILED",
                "failure_impact": "No observations are report eligible.",
                "next_action": "Repair the registered adapter and retry as a new run.",
            }
        )
    values.update(changes)
    return ProcessingCandidate.model_validate(values)


def skill() -> DataProcessingControlSkill:
    return DataProcessingControlSkill()


def test_clean_production_processing_is_stable_and_report_evidence_is_exact() -> None:
    item = source()
    typed_candidate = candidate(item)

    first = skill().validate(scope(), request(item), typed_candidate)
    second = skill().validate(scope(), request(item), typed_candidate)

    assert first == second
    assert first.status is AgentStatus.SUCCESS
    assert first.report_eligible is True
    assert first.review_required is True
    assert first.issues == ()
    report_source, report_run, observations = to_report_evidence(first)
    assert report_source.dataset_sha256 == item.dataset_sha256
    assert report_run.output_sha256 == typed_candidate.output_sha256
    assert observations[0].observation_id == OBSERVATION
    assert observations[0].value == Decimal("12.5")


@pytest.mark.parametrize("origin", [DataOrigin.SIMULATED, DataOrigin.LABORATORY])
def test_nonproduction_origin_remains_explicit_and_not_report_eligible(origin: DataOrigin) -> None:
    item = source(origin=origin)
    result = skill().validate(scope(), request(item), candidate(item))

    assert result.status is AgentStatus.SUCCESS
    assert result.source.origin is origin
    assert result.report_eligible is False
    with pytest.raises(ValueError, match="NOT_REPORT_ELIGIBLE"):
        to_report_evidence(result)


def test_invalid_calibration_requires_human_disposition() -> None:
    item = source(acquired_at=datetime(2026, 10, 1, tzinfo=UTC))

    result = skill().validate(scope(), request(item), candidate(item))

    assert result.status is AgentStatus.HUMAN_REQUIRED
    assert result.report_eligible is False
    assert "PROCESSING_CALIBRATION_INVALID" in {issue.code for issue in result.issues}


def test_cross_scope_and_source_identity_are_rejected() -> None:
    item = source()
    foreign = scope(project=UUID("10000000-0000-4000-8000-000000000202"))
    typed_candidate = candidate(
        item,
        owner=foreign,
        dataset_sha256=digest("wrong-dataset"),
    )

    result = skill().validate(scope(), request(item), typed_candidate)

    assert result.status is AgentStatus.HUMAN_REQUIRED
    assert {issue.code for issue in result.issues} >= {
        "PROCESSING_SCOPE_DENIED",
        "PROCESSING_SOURCE_IDENTITY_INVALID",
        "PROCESSING_OBSERVATION_TRACE_INVALID",
        "PROCESSING_FIGURE_TRACE_INVALID",
    }


def test_version_and_parameter_hash_mismatch_cannot_pass() -> None:
    item = source()
    typed_candidate = candidate(
        item,
        adapter_version="adapter-v2",
        parameters_sha256=digest("wrong-parameters"),
    )

    result = skill().validate(scope(), request(item), typed_candidate)

    assert result.status is AgentStatus.HUMAN_REQUIRED
    assert {issue.code for issue in result.issues} >= {
        "PROCESSING_VERSION_MISMATCH",
        "PROCESSING_PARAMETERS_INVALID",
    }


def test_budget_and_one_attempt_rule_stop_hidden_retry() -> None:
    item = source()
    typed_candidate = candidate(item, duration_ms=20_000, adapter_calls=2, attempts=2)

    result = skill().validate(scope(), request(item), typed_candidate)

    assert result.status is AgentStatus.HUMAN_REQUIRED
    assert "PROCESSING_BUDGET_EXCEEDED" in {issue.code for issue in result.issues}


def test_external_actions_are_denied_by_control_skill() -> None:
    item = source()
    typed_candidate = candidate(item, model_calls=1, network_calls=1, physical_commands=1)

    result = skill().validate(scope(), request(item), typed_candidate)

    assert result.status is AgentStatus.HUMAN_REQUIRED
    assert "PROCESSING_EXTERNAL_ACTION_DENIED" in {issue.code for issue in result.issues}


def test_quality_below_policy_returns_typed_partial_evidence() -> None:
    item = source()
    typed_candidate = candidate(
        item,
        completeness_ratio=Decimal("0.80"),
        quality_score=Decimal("0.70"),
        corrupted_ratio=Decimal("0.05"),
    )

    result = skill().validate(scope(), request(item), typed_candidate)

    assert result.status is AgentStatus.PARTIAL_SUCCESS
    assert result.report_eligible is False
    assert "PROCESSING_QUALITY_BELOW_THRESHOLD" in {issue.code for issue in result.issues}


def test_observation_and_figure_must_stay_within_source_bounds() -> None:
    item = source()
    original = candidate(item)
    observation = original.observations[0].model_copy(
        update={"channel_index": 4, "sample_end": 2_000}
    )
    figure = original.figures[0].model_copy(
        update={"source_observation_ids": (UUID("30000000-0000-4000-8000-000000001099"),)}
    )
    typed_candidate = original.model_copy(
        update={"observations": (observation,), "figures": (figure,)}
    )

    result = skill().validate(scope(), request(item), typed_candidate)

    assert result.status is AgentStatus.HUMAN_REQUIRED
    assert {issue.code for issue in result.issues} >= {
        "PROCESSING_OBSERVATION_TRACE_INVALID",
        "PROCESSING_FIGURE_TRACE_INVALID",
    }


def test_failed_processing_preserves_cause_impact_and_next_action() -> None:
    item = source()
    typed_candidate = candidate(item, origin_status=CandidateProcessingStatus.FAILED)

    result = skill().validate(scope(), request(item), typed_candidate)

    assert result.status is AgentStatus.FAILED
    assert result.failure_code == "ADAPTER_FAILED"
    assert result.failure_impact == "No observations are report eligible."
    assert result.next_action is not None
    assert result.report_eligible is False


def test_contracts_reject_invalid_unit_and_incomplete_failure() -> None:
    item = source()
    original = candidate(item).observations[0]
    with pytest.raises(ValidationError, match="unit is not registered"):
        ProcessingObservation.model_validate({**original.model_dump(), "unit": "kg"})
    payload = candidate(item).model_dump(mode="json")
    payload.update({"status": "FAILED", "failure_code": "FAIL"})
    with pytest.raises(ValidationError, match="cause, impact, and next action"):
        ProcessingCandidate.model_validate(payload)


def test_versioned_processing_skill_and_prompt_assets_match_contract() -> None:
    skill_text = (ROOT / "skills/professional/data-processing/SKILL.md").read_text("utf-8")
    prompt_text = (ROOT / "prompts/professional/data-processing.v1.md").read_text("utf-8")

    assert "version: 1.0.0" in skill_text
    assert "ProcessingControlResult@1.0.0" in skill_text
    assert "one attempt" in prompt_text
    assert "no physical command" in prompt_text
