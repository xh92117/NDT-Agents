"""S4-03 report template, traceability, and numeric consistency tests."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from ndt_agents.contracts.v1 import (
    AgentStatus,
    ArtifactRef,
    DataClassification,
    TenantScope,
)
from ndt_agents.professional.planning import InspectionPlanResult, PlanSection
from ndt_agents.professional.reporting import (
    REPORT_REQUIRED_SECTIONS,
    CalculationFormula,
    ConclusionLevel,
    FindingSeverity,
    InspectionReportCandidate,
    InspectionReportRequest,
    InspectionReportSkill,
    ReportCalculation,
    ReportConclusion,
    ReportFigure,
    ReportFinding,
    ReportObservation,
    ReportProcessingEvidence,
    ReportRevision,
    ReportSourceDataset,
    load_inspection_report_template,
)
from tests.professional.test_inspection_plan import (
    candidate as plan_candidate,
)
from tests.professional.test_inspection_plan import (
    plan_request,
    scope,
    with_standard_id,
)
from tests.professional.test_inspection_plan import (
    runtime as plan_runtime,
)

ROOT = Path(__file__).resolve().parents[2]
REPORT_TASK = UUID("20000000-0000-4000-8000-000000000401")
REPORT_ID = UUID("20000000-0000-4000-8000-000000000501")
DATASET_ID = UUID("20000000-0000-4000-8000-000000000601")
PROCESSING_ID = UUID("20000000-0000-4000-8000-000000000701")
OBSERVATION_1 = UUID("20000000-0000-4000-8000-000000000801")
OBSERVATION_2 = UUID("20000000-0000-4000-8000-000000000802")
LOCATION = UUID("20000000-0000-4000-8000-000000000901")
REVISION_ID = UUID("20000000-0000-4000-8000-000000001001")


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def artifact(
    owner: TenantScope,
    key: str,
    *,
    media_type: str = "application/octet-stream",
) -> ArtifactRef:
    return ArtifactRef(
        artifact_id=UUID(key),
        scope=owner,
        artifact_version="v1",
        uri=f"artifact://{key}",
        media_type=media_type,
        size_bytes=128,
        sha256=digest(key),
        classification=DataClassification.INTERNAL,
        immutable=True,
    )


def plan() -> InspectionPlanResult:
    skill, qa, version = plan_runtime()
    typed_candidate = with_standard_id(plan_candidate(qa), version)
    result = skill.validate(scope(), plan_request(), typed_candidate)
    assert result.status is AgentStatus.SUCCESS
    return result


def request(item: InspectionPlanResult, **changes: object) -> InspectionReportRequest:
    values: dict[str, object] = {
        "task_id": REPORT_TASK,
        "request_id": "report-request-1",
        "report_id": REPORT_ID,
        "revision": 1,
        "title": "Synthetic ultrasonic inspection report",
        "plan_sha256": item.plan_sha256,
    }
    values.update(changes)
    return InspectionReportRequest.model_validate(values)


def report_candidate(
    item: InspectionPlanResult,
    *,
    owner: TenantScope | None = None,
    reported_mean: Decimal = Decimal("15"),
    calibration_valid: bool = True,
    conclusion_level: ConclusionLevel = ConclusionLevel.PRELIMINARY,
    conclusion_human: bool = False,
    **changes: object,
) -> InspectionReportCandidate:
    resolved_owner = owner or scope()
    source = ReportSourceDataset(
        dataset_id=DATASET_ID,
        scope=resolved_owner,
        artifact=artifact(resolved_owner, "20000000-0000-4000-8000-000000000011"),
        dataset_sha256=digest("dataset"),
        method_code="UT",
        instrument_id="ut-device-1",
        calibration_id="ut-calibration-1",
        calibration_version="cal-v1",
        calibration_valid_at_acquisition=calibration_valid,
        operator_id=resolved_owner.user_id,
        acquired_at=datetime(2026, 8, 25, 1, 0, tzinfo=UTC),
    )
    processing = ReportProcessingEvidence(
        processing_run_id=PROCESSING_ID,
        scope=resolved_owner,
        dataset_id=DATASET_ID,
        dataset_sha256=source.dataset_sha256,
        adapter_version="adapter-v1",
        parser_version="parser-v1",
        algorithm_version="algorithm-v1",
        parameters_sha256=digest("parameters"),
        output_sha256=digest("output"),
    )
    observations = (
        ReportObservation(
            observation_id=OBSERVATION_1,
            scope=resolved_owner,
            processing_run_id=PROCESSING_ID,
            dataset_id=DATASET_ID,
            location_id=LOCATION,
            name="Indication depth 1",
            dimension="LENGTH",
            unit="mm",
            value=Decimal("10"),
            evidence_sha256=digest("observation-1"),
        ),
        ReportObservation(
            observation_id=OBSERVATION_2,
            scope=resolved_owner,
            processing_run_id=PROCESSING_ID,
            dataset_id=DATASET_ID,
            location_id=LOCATION,
            name="Indication depth 2",
            dimension="LENGTH",
            unit="mm",
            value=Decimal("20"),
            evidence_sha256=digest("observation-2"),
        ),
    )
    calculation = ReportCalculation(
        calculation_id="mean-depth",
        formula=CalculationFormula.MEAN,
        input_observation_ids=(OBSERVATION_1, OBSERVATION_2),
        dimension="LENGTH",
        unit="mm",
        reported_value=reported_mean,
    )
    figure = ReportFigure(
        figure_id="depth-plot",
        title="Indication depth plot",
        artifact=artifact(
            resolved_owner,
            "20000000-0000-4000-8000-000000000012",
            media_type="image/png",
        ),
        source_observation_ids=(OBSERVATION_1, OBSERVATION_2),
    )
    finding = ReportFinding(
        finding_id="finding-1",
        statement="The two traced indications have a mean depth of 15 mm.",
        severity=FindingSeverity.MATERIAL,
        observation_ids=(OBSERVATION_1, OBSERVATION_2),
        calculation_ids=("mean-depth",),
        plan_basis_ids=(item.standard_basis[0].basis_id,),
        limitations=("Only the planned sampled locations are represented.",),
    )
    conclusion = ReportConclusion(
        text="A preliminary traced finding is recorded for qualified review.",
        level=conclusion_level,
        finding_ids=("finding-1",),
        limitations=("No formal release is authorized by this draft.",),
        human_confirmation_required=conclusion_human,
    )
    values: dict[str, object] = {
        "summary": "Draft report with traceable ultrasonic observations.",
        "sections": tuple(
            PlanSection(section_id=name, content=f"Controlled {name} report content.")
            for name in REPORT_REQUIRED_SECTIONS
        ),
        "sources": (source,),
        "processing": (processing,),
        "observations": observations,
        "calculations": (calculation,),
        "figures": (figure,),
        "findings": (finding,),
        "conclusion": conclusion,
        "limitations": ("Synthetic local evidence is not production evidence.",),
        "revisions": (
            ReportRevision(
                revision=1,
                revision_id=REVISION_ID,
                reason="Initial draft.",
                author_id=resolved_owner.user_id,
            ),
        ),
        "plan": item,
    }
    values.update(changes)
    return InspectionReportCandidate.model_validate(values)


def runtime() -> InspectionReportSkill:
    template = load_inspection_report_template(
        ROOT / "fixtures/v1/templates/inspection-report.v1.json"
    )
    return InspectionReportSkill(template)


def test_generated_report_template_contains_required_fields_in_order() -> None:
    template = load_inspection_report_template(
        ROOT / "fixtures/v1/templates/inspection-report.v1.json"
    )

    assert template.required_sections == REPORT_REQUIRED_SECTIONS
    assert len(template.required_sections) == 15


def test_complete_report_is_stable_traceable_and_approval_pending() -> None:
    typed_plan = plan()
    candidate = report_candidate(typed_plan)
    skill = runtime()

    first = skill.validate(scope(), request(typed_plan), candidate)
    second = skill.validate(scope(), request(typed_plan), candidate)

    assert first == second
    assert first.status is AgentStatus.SUCCESS
    assert first.issues == ()
    assert first.review_required is True
    assert first.approval_state == "PENDING"
    assert first.formal_release_allowed is False
    assert first.calculations[0].reported_value == Decimal("15")
    assert first.findings[0].observation_ids == (OBSERVATION_1, OBSERVATION_2)
    assert first.plan_sha256 == typed_plan.plan_sha256


def test_reported_numeric_value_is_recomputed_and_mismatch_requires_human() -> None:
    typed_plan = plan()
    candidate = report_candidate(typed_plan, reported_mean=Decimal("16"))

    result = runtime().validate(scope(), request(typed_plan), candidate)

    assert result.status is AgentStatus.HUMAN_REQUIRED
    assert "REPORT_CALCULATION_MISMATCH" in {item.code for item in result.issues}


def test_incompatible_calculation_units_cannot_be_combined() -> None:
    typed_plan = plan()
    original = report_candidate(typed_plan)
    second = original.observations[1].model_copy(update={"unit": "cm"})
    candidate = original.model_copy(update={"observations": (original.observations[0], second)})

    result = runtime().validate(scope(), request(typed_plan), candidate)

    assert result.status is AgentStatus.HUMAN_REQUIRED
    assert "REPORT_CALCULATION_DIMENSION_CONFLICT" in {item.code for item in result.issues}


def test_cross_scope_source_and_processing_are_rejected() -> None:
    typed_plan = plan()
    foreign = scope(project=UUID("10000000-0000-4000-8000-000000000202"))
    candidate = report_candidate(typed_plan, owner=foreign)

    result = runtime().validate(scope(), request(typed_plan), candidate)

    assert result.status is AgentStatus.HUMAN_REQUIRED
    assert {item.code for item in result.issues} >= {
        "REPORT_SOURCE_SCOPE_DENIED",
        "REPORT_PROCESSING_SOURCE_INVALID",
        "REPORT_OBSERVATION_TRACE_INVALID",
    }


def test_missing_observation_and_finding_references_cannot_pass() -> None:
    typed_plan = plan()
    original = report_candidate(typed_plan)
    missing = UUID("20000000-0000-4000-8000-000000000899")
    finding = original.findings[0].model_copy(
        update={
            "observation_ids": (missing,),
            "calculation_ids": ("missing-calculation",),
            "plan_basis_ids": ("missing-basis",),
        }
    )
    candidate = original.model_copy(update={"findings": (finding,)})

    result = runtime().validate(scope(), request(typed_plan), candidate)

    assert result.status is AgentStatus.HUMAN_REQUIRED
    assert {item.code for item in result.issues} >= {
        "REPORT_FINDING_OBSERVATION_MISSING",
        "REPORT_FINDING_CALCULATION_MISSING",
        "REPORT_FINDING_CITATION_MISSING",
    }


def test_invalid_calibration_and_unknown_method_require_human() -> None:
    typed_plan = plan()
    original = report_candidate(typed_plan, calibration_valid=False)
    source = original.sources[0].model_copy(update={"method_code": "XRF"})
    candidate = original.model_copy(update={"sources": (source,)})

    result = runtime().validate(scope(), request(typed_plan), candidate)

    assert result.status is AgentStatus.HUMAN_REQUIRED
    assert {item.code for item in result.issues} >= {
        "REPORT_CALIBRATION_INVALID",
        "REPORT_SOURCE_METHOD_INVALID",
    }


def test_formal_conclusion_stays_human_required_and_unreleased() -> None:
    typed_plan = plan()
    candidate = report_candidate(
        typed_plan,
        conclusion_level=ConclusionLevel.FORMAL,
        conclusion_human=True,
    )

    result = runtime().validate(scope(), request(typed_plan), candidate)

    assert result.status is AgentStatus.HUMAN_REQUIRED
    assert result.formal_release_allowed is False
    assert "REPORT_FORMAL_CONCLUSION_REQUIRES_APPROVAL" in {item.code for item in result.issues}


def test_revision_history_must_be_contiguous_and_match_request() -> None:
    typed_plan = plan()
    original = report_candidate(typed_plan)
    revision_three = ReportRevision(
        revision=3,
        revision_id=UUID("20000000-0000-4000-8000-000000001003"),
        previous_report_sha256=digest("revision-2"),
        reason="Skipped revision two.",
        author_id=scope().user_id,
    )
    candidate = original.model_copy(update={"revisions": (*original.revisions, revision_three)})

    result = runtime().validate(scope(), request(typed_plan, revision=3), candidate)

    assert result.status is AgentStatus.NEEDS_USER
    assert "REPORT_REVISION_SEQUENCE_INVALID" in {item.code for item in result.issues}


def test_tampered_or_cross_scope_plan_identity_is_rejected() -> None:
    typed_plan = plan()
    tampered = typed_plan.model_copy(update={"summary": "Tampered plan content."})
    candidate = report_candidate(typed_plan).model_copy(update={"plan": tampered})

    result = runtime().validate(scope(), request(typed_plan), candidate)

    assert result.status is AgentStatus.HUMAN_REQUIRED
    assert "REPORT_PLAN_IDENTITY_INVALID" in {item.code for item in result.issues}


def test_candidate_cannot_fabricate_approval_or_release_state() -> None:
    typed_plan = plan()
    payload = report_candidate(typed_plan).model_dump(mode="json")
    payload["approval_state"] = "APPROVED"
    payload["formal_release_allowed"] = True

    with pytest.raises(ValidationError, match="Extra inputs"):
        InspectionReportCandidate.model_validate(payload)


def test_observation_contract_rejects_unregistered_units() -> None:
    with pytest.raises(ValidationError, match="unit is not registered"):
        ReportObservation(
            observation_id=OBSERVATION_1,
            scope=scope(),
            processing_run_id=PROCESSING_ID,
            dataset_id=DATASET_ID,
            location_id=LOCATION,
            name="Invalid unit",
            dimension="LENGTH",
            unit="kg",
            value=Decimal("1"),
            evidence_sha256=digest("invalid"),
        )


def test_versioned_report_skill_and_prompt_assets_match_runtime_contract() -> None:
    skill_text = (ROOT / "skills/professional/inspection-report/SKILL.md").read_text("utf-8")
    prompt_text = (ROOT / "prompts/professional/inspection-report.v1.md").read_text("utf-8")

    assert "version: 1.0.0" in skill_text
    assert "InspectionReportResult@1.0.0" in skill_text
    assert "TPL-INSPECTION-REPORT-V1" in prompt_text
    assert "approval-pending" in prompt_text
