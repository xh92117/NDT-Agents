"""S4-06 professional per-result, cross-result, and S1-09 adapter tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from ndt_agents.contracts.v1 import AgentResult, AgentStatus, ReviewDecision, ReviewResult
from ndt_agents.orchestration.review import (
    ReviewContext,
    ReviewKind,
    ReviewTarget,
    agent_result_sha256,
    review_context_manifest_sha256,
)
from ndt_agents.professional.methods import MethodSkillRegistry, MethodValidationResult
from ndt_agents.professional.planning import InspectionPlanResult
from ndt_agents.professional.processing import (
    DataProcessingControlSkill,
    ProcessingControlResult,
    processing_candidate_sha256,
    to_report_evidence,
)
from ndt_agents.professional.qa import TechnicalQAResult
from ndt_agents.professional.reporting import (
    InspectionReportResult,
    InspectionReportSkill,
    load_inspection_report_template,
)
from ndt_agents.professional.review import (
    ProfessionalChecklistRegistry,
    ProfessionalResult,
    ProfessionalResultEnvelope,
    ProfessionalResultKind,
    ProfessionalReviewExecutor,
    ProfessionalReviewService,
    default_professional_checklists,
    professional_assessment_sha256,
    professional_checklist_sha256,
    professional_result_envelope,
)
from tests.professional.test_inspection_plan import (
    TASK,
    plan_request,
    scope,
    with_standard_id,
)
from tests.professional.test_inspection_plan import candidate as plan_candidate
from tests.professional.test_inspection_plan import runtime as plan_runtime
from tests.professional.test_inspection_report import (
    report_candidate,
)
from tests.professional.test_inspection_report import request as report_request
from tests.professional.test_method_skills import method_boundary

ROOT = Path(__file__).resolve().parents[2]
QA_RUN = UUID("40000000-0000-4000-8000-000000000101")
PLAN_RUN = UUID("40000000-0000-4000-8000-000000000102")
PROCESSING_RUN = UUID("40000000-0000-4000-8000-000000000103")
METHOD_RUN = UUID("40000000-0000-4000-8000-000000000104")
REPORT_RUN = UUID("40000000-0000-4000-8000-000000000105")
SCHEDULE = UUID("40000000-0000-4000-8000-000000000106")


def chain(
    *,
    alternate_plan: bool = False,
) -> tuple[
    TechnicalQAResult,
    InspectionPlanResult,
    ProcessingControlResult,
    MethodValidationResult,
    InspectionReportResult,
]:
    plan_skill, qa, version = plan_runtime()
    typed_plan_candidate = with_standard_id(plan_candidate(qa), version)
    typed_plan_request = plan_request(
        objective=(
            "Verify alternate bridge-deck ultrasonic coverage."
            if alternate_plan
            else "Verify bridge-deck ultrasonic inspection coverage."
        )
    )
    plan = plan_skill.validate(scope(), typed_plan_request, typed_plan_candidate)
    assert plan.status is AgentStatus.SUCCESS

    processing_request, processing_candidate = method_boundary("UT")
    processing_request = processing_request.model_copy(update={"task_id": TASK})
    processing = DataProcessingControlSkill().validate(
        scope(), processing_request, processing_candidate
    )
    method = MethodSkillRegistry().validate(scope(), processing_request, processing_candidate)
    assert method.candidate_sha256 == processing_candidate_sha256(processing)

    report_source, report_processing, observations = to_report_evidence(processing)
    base = report_candidate(plan)
    finding = base.findings[0].model_copy(
        update={
            "observation_ids": (observations[0].observation_id,),
            "calculation_ids": (),
        }
    )
    candidate = base.model_copy(
        update={
            "sources": (report_source,),
            "processing": (report_processing,),
            "observations": observations,
            "calculations": (),
            "figures": (),
            "findings": (finding,),
        }
    )
    template = load_inspection_report_template(
        ROOT / "fixtures/v1/templates/inspection-report.v1.json"
    )
    report = InspectionReportSkill(template).validate(
        scope(), report_request(plan, task_id=TASK), candidate
    )
    assert report.status is AgentStatus.SUCCESS
    return qa, plan, processing, method, report


def envelopes(
    values: tuple[
        TechnicalQAResult,
        InspectionPlanResult,
        ProcessingControlResult,
        MethodValidationResult,
        InspectionReportResult,
    ],
) -> tuple[ProfessionalResultEnvelope, ...]:
    kinds_and_runs = (
        (ProfessionalResultKind.TECHNICAL_QA, QA_RUN),
        (ProfessionalResultKind.INSPECTION_PLAN, PLAN_RUN),
        (ProfessionalResultKind.DATA_PROCESSING, PROCESSING_RUN),
        (ProfessionalResultKind.METHOD_VALIDATION, METHOD_RUN),
        (ProfessionalResultKind.INSPECTION_REPORT, REPORT_RUN),
    )
    return tuple(
        professional_result_envelope(
            kind, cast(ProfessionalResult, result), task_id=TASK, run_id=run_id
        )
        for result, (kind, run_id) in zip(values, kinds_and_runs, strict=True)
    )


def agent_result(envelope: ProfessionalResultEnvelope) -> AgentResult:
    return AgentResult(
        task_id=TASK,
        run_id=envelope.run_id,
        status=AgentStatus.SUCCESS,
        summary=f"Professional {envelope.result_kind} result",
        structured_data={"professional_review_envelope": envelope.model_dump(mode="json")},
        artifacts=(),
        evidence=(),
        confidence=1.0,
        issues=(),
        retryable=False,
        completed_at=datetime(2026, 8, 25, tzinfo=UTC),
    )


def review_context(envelope: ProfessionalResultEnvelope) -> ReviewContext:
    result = agent_result(envelope)
    target = ReviewTarget(
        assignment_id=envelope.result_kind.value.lower(),
        run_id=envelope.run_id,
        result_sha256=agent_result_sha256(result),
        result=result,
    )
    payload: dict[str, Any] = {
        "kind": ReviewKind.PER_RESULT,
        "task_id": TASK,
        "scope": scope(),
        "schedule_id": SCHEDULE,
        "review_target_run_id": envelope.run_id,
        "review_target_sha256": target.result_sha256,
        "targets": (target,),
        "review_checklist": ("Apply the registered professional checklist.",),
        "reviewer_version": "professional-reviewer-1.0.0",
        "prompt_version": "professional-review-prompt-1.0.0",
        "model_version": "deterministic-no-model",
        "correction_count": 0,
        "read_only": True,
        "allowed_tools": (),
        "user_delivery_allowed": False,
    }
    unbound = ReviewContext.model_construct(**payload, context_manifest_sha256="0" * 64)
    return ReviewContext.model_validate(
        {**payload, "context_manifest_sha256": review_context_manifest_sha256(unbound)}
    )


def test_checklist_registry_is_complete_stable_and_hash_bound() -> None:
    first = default_professional_checklists()
    second = default_professional_checklists()

    assert first == second
    assert tuple(item.result_kind for item in first) == tuple(ProfessionalResultKind)
    assert len(ProfessionalChecklistRegistry().definitions()) == 5
    assert all(item.checklist_sha256 == professional_checklist_sha256(item) for item in first)


def test_every_clean_professional_result_passes_independent_review() -> None:
    service = ProfessionalReviewService()

    for envelope in envelopes(chain()):
        first = service.review_one(
            envelope,
            expected_scope=scope(),
            expected_task_id=TASK,
            expected_run_id=envelope.run_id,
        )
        second = service.review_one(
            envelope,
            expected_scope=scope(),
            expected_task_id=TASK,
            expected_run_id=envelope.run_id,
        )
        assert first == second
        assert first.decision is ReviewDecision.PASS
        assert first.aggregation_ready is True
        assert first.findings == ()
        assert first.assessment_sha256 == professional_assessment_sha256(first)
        assert first.model_calls + first.tool_calls + first.correction_calls == 0


def test_tampered_payload_and_cross_scope_envelope_fail_before_aggregation() -> None:
    envelope = envelopes(chain())[0]
    tampered = envelope.model_copy(update={"payload": {**envelope.payload, "summary": "tampered"}})
    wrong_run = UUID("40000000-0000-4000-8000-000000000199")

    tampered_result = ProfessionalReviewService().review_one(tampered)
    wrong_identity = ProfessionalReviewService().review_one(
        envelope,
        expected_scope=scope(permission="permissions-v2"),
        expected_task_id=TASK,
        expected_run_id=wrong_run,
    )

    assert tampered_result.decision is ReviewDecision.FAILED
    assert wrong_identity.decision is ReviewDecision.FAILED
    assert tampered_result.aggregation_ready is False
    assert wrong_identity.aggregation_ready is False


def test_human_required_processing_result_cannot_pass_independent_review() -> None:
    request, candidate = method_boundary("UT")
    invalid_source = request.source.model_copy(
        update={"acquired_at": datetime(2026, 10, 1, tzinfo=UTC)}
    )
    invalid_request = request.model_copy(update={"task_id": TASK, "source": invalid_source})
    result = DataProcessingControlSkill().validate(scope(), invalid_request, candidate)
    envelope = professional_result_envelope(
        ProfessionalResultKind.DATA_PROCESSING,
        result,
        task_id=TASK,
        run_id=PROCESSING_RUN,
    )

    assessment = ProfessionalReviewService().review_one(envelope)

    assert result.status is AgentStatus.HUMAN_REQUIRED
    assert assessment.decision is ReviewDecision.HUMAN_REQUIRED
    assert assessment.aggregation_ready is False


def test_complete_interacting_chain_passes_cross_result_review() -> None:
    typed_envelopes = envelopes(chain())

    first = ProfessionalReviewService().review_cross(
        typed_envelopes,
        expected_scope=scope(),
        expected_task_id=TASK,
    )
    second = ProfessionalReviewService().review_cross(
        typed_envelopes,
        expected_scope=scope(),
        expected_task_id=TASK,
    )

    assert first == second
    assert first.decision is ReviewDecision.PASS
    assert first.aggregation_ready is True
    assert first.findings == ()


def test_plan_report_hash_conflict_is_explicit_and_nonaggregatable() -> None:
    original = chain()
    alternate = chain(alternate_plan=True)
    mixed = (*original[:4], alternate[4])

    assessment = ProfessionalReviewService().review_cross(
        envelopes(mixed),
        expected_scope=scope(),
        expected_task_id=TASK,
    )

    assert assessment.decision is ReviewDecision.CONFLICT
    assert assessment.aggregation_ready is False
    assert "CROSS_PLAN_REPORT_CONFLICT" in {item.code for item in assessment.findings}


def test_processing_report_and_method_processing_conflicts_are_explicit() -> None:
    original = chain()
    changed_request, changed_candidate = method_boundary("UT")
    changed_request = changed_request.model_copy(update={"task_id": TASK})
    changed_observation = changed_candidate.observations[0].model_copy(
        update={"value": Decimal("99")}
    )
    changed_candidate = changed_candidate.model_copy(
        update={"observations": (changed_observation,)}
    )
    changed_processing = DataProcessingControlSkill().validate(
        scope(), changed_request, changed_candidate
    )
    mixed = (original[0], original[1], changed_processing, original[3], original[4])

    assessment = ProfessionalReviewService().review_cross(
        envelopes(mixed),
        expected_scope=scope(),
        expected_task_id=TASK,
    )

    assert assessment.decision is ReviewDecision.CONFLICT
    assert {item.code for item in assessment.findings} >= {
        "CROSS_METHOD_PROCESSING_CONFLICT",
        "CROSS_PROCESSING_REPORT_CONFLICT",
    }


def test_s1_review_executor_returns_strict_deterministic_review_result() -> None:
    envelope = envelopes(chain())[0]
    context = review_context(envelope)
    executor = ProfessionalReviewExecutor(clock=lambda: datetime(2026, 8, 25, tzinfo=UTC))

    first = ReviewResult.model_validate(asyncio.run(executor.review(context)))
    second = ReviewResult.model_validate(asyncio.run(executor.review(context)))

    assert first == second
    assert first.decision is ReviewDecision.PASS
    assert first.target_sha256 == context.review_target_sha256
    assert first.target_run_id == context.review_target_run_id
    assert first.findings == ()


def test_professional_review_assets_define_cross_result_and_zero_call_boundaries() -> None:
    skill = (ROOT / "skills/professional/review/SKILL.md").read_text("utf-8")
    prompt = (ROOT / "prompts/professional/review.v1.md").read_text("utf-8")
    contract = (ROOT / "docs/contracts/professional-review-v1.md").read_text("utf-8")

    assert "version: 1.0.0" in skill
    assert "ProfessionalReviewAssessment@1.0.0" in contract
    assert "per-result PASS" in prompt
    assert "zero model" in prompt
