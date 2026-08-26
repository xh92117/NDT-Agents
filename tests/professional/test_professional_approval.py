"""S4-07 professional plan, report, and critical-finding approval tests."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from ndt_agents.approval import (
    ApprovalActor,
    ApprovalError,
    ApprovalService,
    ApprovalState,
    InMemoryApprovalRepository,
)
from ndt_agents.contracts.v1 import ApprovalOutcome, TaskContext
from ndt_agents.observability import (
    AuditService,
    InMemoryAuditRepository,
    InMemorySpanExporter,
    TraceService,
)
from ndt_agents.orchestration.budget import BudgetGuard, default_budget_policy
from ndt_agents.orchestration.child_context import ChildContextFactory
from ndt_agents.orchestration.child_models import (
    AgentDefinition,
    ChildAgentKind,
    ChildInput,
    ChildTaskContext,
)
from ndt_agents.orchestration.models import DispatchPlan, ProfessionalAssignment, RouteKind
from ndt_agents.orchestration.registry import AgentRegistry
from ndt_agents.orchestration.review import (
    ReviewerDefinition,
    ReviewWorkflow,
    ReviewWorkflowResult,
    ReviewWorkflowStatus,
)
from ndt_agents.orchestration.scheduler import TaskScheduler
from ndt_agents.professional.approval import (
    PROFESSIONAL_APPROVAL_POLICY_VERSION,
    ProfessionalApprovalCheckpoint,
    ProfessionalApprovalService,
    professional_approval_checkpoint_sha256,
    professional_approval_policy,
    professional_approval_subject_sha256,
)
from ndt_agents.professional.reporting import (
    FindingSeverity,
    InspectionReportResult,
    InspectionReportSkill,
    load_inspection_report_template,
)
from ndt_agents.professional.review import (
    ProfessionalResult,
    ProfessionalResultEnvelope,
    ProfessionalResultKind,
    ProfessionalReviewAssessment,
    ProfessionalReviewExecutor,
    ProfessionalReviewService,
    professional_result_envelope,
)
from tests.professional.test_inspection_plan import TASK, scope
from tests.professional.test_inspection_report import (
    report_candidate,
)
from tests.professional.test_inspection_report import request as report_request
from tests.professional.test_professional_review import agent_result, chain

ROOT = Path(__file__).resolve().parents[2]
APPROVAL_ID = UUID("40000000-0000-4000-8000-000000000801")
DECISION_ID = UUID("40000000-0000-4000-8000-000000000802")
RESUME_ID = UUID("40000000-0000-4000-8000-000000000803")
APPROVER_ID = UUID("40000000-0000-4000-8000-000000000804")
OTHER_APPROVER_ID = UUID("40000000-0000-4000-8000-000000000805")


class FixedClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 8, 25, 8, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: int) -> None:
        self.now += timedelta(seconds=seconds)


class ApprovalRuntime:
    def __init__(self) -> None:
        self.clock = FixedClock()
        self.repository = InMemoryApprovalRepository()
        self.audit_repository = InMemoryAuditRepository()
        self.traces = TraceService(
            service_name="professional-approval-test",
            service_version="1.0.0",
            exporter=InMemorySpanExporter(),
        )
        self.core = ApprovalService(
            self.repository,
            professional_approval_policy(),
            AuditService(self.audit_repository, self.traces),
            clock=self.clock,
        )
        self.service = ProfessionalApprovalService(self.core)

    def actor(self, user_id: UUID, *roles: str) -> ApprovalActor:
        return ApprovalActor(
            scope=scope().model_copy(update={"user_id": user_id, "role_codes": roles})
        )

    def close(self) -> None:
        self.traces.shutdown()


class ResultChild:
    def __init__(self, kind: ProfessionalResultKind, result: ProfessionalResult) -> None:
        self.kind = kind
        self.result = result
        self.envelope: ProfessionalResultEnvelope | None = None

    async def execute(self, context: ChildTaskContext) -> Mapping[str, Any]:
        self.envelope = professional_result_envelope(
            self.kind,
            self.result,
            task_id=context.parent_task_id,
            run_id=context.run_id,
        )
        return agent_result(self.envelope).model_dump(mode="json")


def review_evidence(
    kind: ProfessionalResultKind,
    result: ProfessionalResult,
) -> tuple[ProfessionalReviewAssessment, ReviewWorkflowResult]:
    base_task = TaskContext.model_validate_json(
        (ROOT / "examples/contracts/v1/task-context.valid.json").read_text("utf-8")
    )
    budget = default_budget_policy("P3")
    task = base_task.model_copy(
        update={
            "task_id": TASK,
            "scope": scope(),
            "task_class": "P3",
            "dependency_data": {},
            "artifacts": (),
            "allowed_tools": (),
            "budget": budget,
            "output_schema_id": f"{kind.value}@1.0.0",
            "review_checklist": ("Apply the registered professional checklist.",),
        }
    )
    registry = AgentRegistry(
        definitions=(
            AgentDefinition(
                agent_type="general",
                kind=ChildAgentKind.GENERAL,
                allowed_tools=frozenset(),
                skill_version="general-1",
                prompt_version="general-1",
                model_version="deterministic",
            ),
            AgentDefinition(
                agent_type="professional-result",
                kind=ChildAgentKind.PROFESSIONAL,
                allowed_tools=frozenset(),
                skill_version="professional-result-1",
                prompt_version="professional-result-1",
                model_version="deterministic",
            ),
        )
    )
    dispatch = DispatchPlan(
        task_id=TASK,
        route=RouteKind.ONE_PROFESSIONAL_SYNC_REVIEW,
        general_agent=False,
        professional_assignments=(
            ProfessionalAssignment(
                assignment_id="professional-result",
                agent_type="professional-result",
            ),
        ),
        asynchronous=False,
        review_required=True,
        human_required=False,
    )
    contexts = ChildContextFactory(registry).prepare(
        task,
        dispatch,
        professional_inputs=(
            ChildInput(
                assignment_id="professional-result",
                goal="Return the exact professional review envelope.",
                success_criteria=("Preserve the exact typed result.",),
            ),
        ),
    )
    guard = BudgetGuard(budget)
    child = ResultChild(kind, result)
    schedule = asyncio.run(
        TaskScheduler(budget_guard=guard).run_sync(contexts, {"professional-result": child})
    )
    workflow = asyncio.run(
        ReviewWorkflow().run(
            schedule,
            contexts,
            reviewer=ProfessionalReviewExecutor(
                clock=lambda: datetime(2026, 8, 25, 7, 0, tzinfo=UTC)
            ),
            reviewer_definition=ReviewerDefinition(
                reviewer_version="professional-reviewer-1.0.0",
                prompt_version="professional-review-prompt-1.0.0",
                model_version="deterministic-no-model",
            ),
            correctors={},
            budget_guard=guard,
        )
    )
    assert child.envelope is not None
    assessment = ProfessionalReviewService().review_one(
        child.envelope,
        expected_scope=scope(),
        expected_task_id=TASK,
        expected_run_id=child.envelope.run_id,
    )
    return assessment, workflow


def critical_report() -> InspectionReportResult:
    _, plan, processing, _, _ = chain()
    from ndt_agents.professional.processing import to_report_evidence

    source, processing_evidence, observations = to_report_evidence(processing)
    base = report_candidate(plan)
    finding = base.findings[0].model_copy(
        update={
            "severity": FindingSeverity.CRITICAL,
            "human_confirmation_required": True,
            "observation_ids": (observations[0].observation_id,),
            "calculation_ids": (),
        }
    )
    candidate = base.model_copy(
        update={
            "sources": (source,),
            "processing": (processing_evidence,),
            "observations": observations,
            "calculations": (),
            "figures": (),
            "findings": (finding,),
        }
    )
    template = load_inspection_report_template(
        ROOT / "fixtures/v1/templates/inspection-report.v1.json"
    )
    result = InspectionReportSkill(template).validate(
        scope(), report_request(plan, task_id=TASK), candidate
    )
    assert result.status.value == "HUMAN_REQUIRED"
    return result


def create_plan_checkpoint(runtime: ApprovalRuntime) -> ProfessionalApprovalCheckpoint:
    plan = chain()[1]
    assessment, review = review_evidence(ProfessionalResultKind.INSPECTION_PLAN, plan)
    with runtime.traces.start_span("professional.plan.create"):
        return runtime.service.create_plan(
            approval_id=APPROVAL_ID,
            request_id="professional-plan-approval-1",
            plan=plan,
            assessment=assessment,
            review=review,
        )


def test_professional_policy_uses_separate_action_specific_roles() -> None:
    policy = professional_approval_policy()

    assert policy.policy_version == PROFESSIONAL_APPROVAL_POLICY_VERSION
    assert policy.rules.keys() == professional_approval_policy().rules.keys()
    assert policy.rules[
        next(kind for kind in policy.rules if kind.value == "PLAN")
    ].required_roles == {"QUALIFIED_PLAN_APPROVER"}
    assert policy.rules[
        next(kind for kind in policy.rules if kind.value == "REPORT")
    ].required_roles == {"QUALIFIED_REPORT_APPROVER"}
    assert policy.rules[
        next(kind for kind in policy.rules if kind.value == "CRITICAL_FINDING")
    ].required_roles == {"QUALIFIED_FINDING_APPROVER"}


def test_reviewed_plan_checkpoint_is_stable_idempotent_and_hash_bound() -> None:
    runtime = ApprovalRuntime()
    try:
        plan = chain()[1]
        assessment, review = review_evidence(ProfessionalResultKind.INSPECTION_PLAN, plan)
        with runtime.traces.start_span("professional.plan.create"):
            first = runtime.service.create_plan(
                approval_id=APPROVAL_ID,
                request_id="professional-plan-approval-1",
                plan=plan,
                assessment=assessment,
                review=review,
            )
            replay = runtime.service.create_plan(
                approval_id=APPROVAL_ID,
                request_id="professional-plan-approval-1",
                plan=plan,
                assessment=assessment,
                review=review,
            )

        assert replay == first
        assert first.approval.state is ApprovalState.PENDING
        assert first.binding.kind.value == "PLAN"
        assert first.binding.approval_subject_sha256 == professional_approval_subject_sha256(
            first.binding
        )
        assert first.checkpoint_sha256 == professional_approval_checkpoint_sha256(first)
        assert (
            first.model_calls
            + first.tool_calls
            + first.network_calls
            + first.publication_calls
            + first.user_delivery_calls
            == 0
        )
    finally:
        runtime.close()


def test_plan_requires_plan_role_and_one_exact_resume_grant() -> None:
    runtime = ApprovalRuntime()
    try:
        checkpoint = create_plan_checkpoint(runtime)
        subject = checkpoint.binding.approval_subject_sha256
        with runtime.traces.start_span("professional.plan.decide.denied"):
            with pytest.raises(ApprovalError) as denied:
                runtime.service.decide(
                    decision_id=DECISION_ID,
                    scope=scope(),
                    approval_id=APPROVAL_ID,
                    expected_subject_sha256=subject,
                    actor=runtime.actor(APPROVER_ID, "QUALIFIED_REPORT_APPROVER"),
                    outcome=ApprovalOutcome.APPROVED,
                    reason="Wrong professional role.",
                )
        assert denied.value.code == "APPROVAL_ROLE_DENIED"

        with runtime.traces.start_span("professional.plan.decide"):
            runtime.service.decide(
                decision_id=DECISION_ID,
                scope=scope(),
                approval_id=APPROVAL_ID,
                expected_subject_sha256=subject,
                actor=runtime.actor(APPROVER_ID, "QUALIFIED_PLAN_APPROVER"),
                outcome=ApprovalOutcome.APPROVED,
                reason="Reviewed plan is acceptable.",
            )
        with runtime.traces.start_span("professional.plan.resume"):
            grant = runtime.service.resume(
                resume_id=RESUME_ID,
                scope=scope(),
                approval_id=APPROVAL_ID,
                expected_subject_sha256=subject,
            )
            replay = runtime.service.resume(
                resume_id=RESUME_ID,
                scope=scope(),
                approval_id=APPROVAL_ID,
                expected_subject_sha256=subject,
            )
            with pytest.raises(ApprovalError) as second:
                runtime.service.resume(
                    resume_id=UUID("40000000-0000-4000-8000-000000000899"),
                    scope=scope(),
                    approval_id=APPROVAL_ID,
                    expected_subject_sha256=subject,
                )
        assert replay == grant
        assert second.value.code == "APPROVAL_REPLAYED"
    finally:
        runtime.close()


def test_clean_report_uses_report_role_and_never_implies_formal_release() -> None:
    runtime = ApprovalRuntime()
    try:
        report = chain()[4]
        assessment, review = review_evidence(ProfessionalResultKind.INSPECTION_REPORT, report)
        with runtime.traces.start_span("professional.report.create"):
            checkpoint = runtime.service.create_report(
                approval_id=APPROVAL_ID,
                request_id="professional-report-approval-1",
                report=report,
                assessment=assessment,
                review=review,
            )
        assert checkpoint.binding.kind.value == "REPORT"
        assert checkpoint.binding.content_sha256 == report.report_sha256
        assert report.formal_release_allowed is False
        assert checkpoint.approval.state is ApprovalState.PENDING
    finally:
        runtime.close()


def test_stale_or_unpassed_review_and_tampered_result_fail_closed() -> None:
    runtime = ApprovalRuntime()
    try:
        plan = chain()[1]
        assessment, review = review_evidence(ProfessionalResultKind.INSPECTION_PLAN, plan)
        stale = assessment.model_copy(update={"assessment_sha256": "0" * 64})
        with pytest.raises(ApprovalError) as stale_error:
            runtime.service.create_plan(
                approval_id=APPROVAL_ID,
                request_id="professional-plan-approval-1",
                plan=plan,
                assessment=stale,
                review=review,
            )
        tampered = plan.model_copy(update={"summary": "tampered"})
        with pytest.raises(ApprovalError) as tampered_error:
            runtime.service.create_plan(
                approval_id=APPROVAL_ID,
                request_id="professional-plan-approval-1",
                plan=tampered,
                assessment=assessment,
                review=review,
            )
        assert stale_error.value.code == "PROFESSIONAL_REVIEW_EVIDENCE_INVALID"
        assert tampered_error.value.code == "PROFESSIONAL_PLAN_INVALID"
        assert runtime.repository.list(scope(), APPROVAL_ID) == ()
    finally:
        runtime.close()


def test_critical_findings_require_human_pause_and_finding_role() -> None:
    runtime = ApprovalRuntime()
    try:
        report = critical_report()
        assessment, review = review_evidence(ProfessionalResultKind.INSPECTION_REPORT, report)
        assert review.status is ReviewWorkflowStatus.HUMAN_REQUIRED
        assert review.aggregation_ready is False
        with runtime.traces.start_span("professional.finding.create"):
            checkpoint = runtime.service.create_critical_findings(
                approval_id=APPROVAL_ID,
                request_id="critical-finding-approval-1",
                report=report,
                finding_ids=(report.findings[0].finding_id,),
                assessment=assessment,
                review=review,
            )
        assert checkpoint.binding.kind.value == "CRITICAL_FINDING"
        assert checkpoint.binding.review_decision.value == "HUMAN_REQUIRED"
        assert checkpoint.binding.critical_findings[0].finding_id == report.findings[0].finding_id

        with runtime.traces.start_span("professional.finding.decide"):
            runtime.service.decide(
                decision_id=DECISION_ID,
                scope=scope(),
                approval_id=APPROVAL_ID,
                expected_subject_sha256=checkpoint.binding.approval_subject_sha256,
                actor=runtime.actor(APPROVER_ID, "QUALIFIED_FINDING_APPROVER"),
                outcome=ApprovalOutcome.APPROVED,
                reason="Critical finding evidence and limitations were reviewed.",
            )
        assert runtime.service.status(scope(), APPROVAL_ID).approval.state is ApprovalState.APPROVED
    finally:
        runtime.close()


def test_critical_report_cannot_bypass_through_normal_report_approval() -> None:
    runtime = ApprovalRuntime()
    try:
        report = critical_report()
        assessment, review = review_evidence(ProfessionalResultKind.INSPECTION_REPORT, report)
        with pytest.raises(ApprovalError) as raised:
            runtime.service.create_report(
                approval_id=APPROVAL_ID,
                request_id="professional-report-approval-1",
                report=report,
                assessment=assessment,
                review=review,
            )
        assert raised.value.code == "PROFESSIONAL_REPORT_NOT_APPROVABLE"
        assert runtime.repository.list(scope(), APPROVAL_ID) == ()
    finally:
        runtime.close()


def test_rejected_expired_changed_and_cross_scope_actions_remain_denied() -> None:
    runtime = ApprovalRuntime()
    try:
        checkpoint = create_plan_checkpoint(runtime)
        subject = checkpoint.binding.approval_subject_sha256
        foreign = scope().model_copy(
            update={"project_id": UUID("40000000-0000-4000-8000-000000000899")}
        )
        with runtime.traces.start_span("professional.plan.cross-scope"):
            with pytest.raises(ApprovalError) as cross_scope:
                runtime.service.decide(
                    decision_id=DECISION_ID,
                    scope=scope(),
                    approval_id=APPROVAL_ID,
                    expected_subject_sha256=subject,
                    actor=ApprovalActor(scope=foreign),
                    outcome=ApprovalOutcome.APPROVED,
                    reason="Cross-scope attempt.",
                )
        assert cross_scope.value.code == "APPROVAL_SCOPE_MISMATCH"
        with runtime.traces.start_span("professional.plan.reject"):
            runtime.service.decide(
                decision_id=DECISION_ID,
                scope=scope(),
                approval_id=APPROVAL_ID,
                expected_subject_sha256=subject,
                actor=runtime.actor(OTHER_APPROVER_ID, "QUALIFIED_PLAN_APPROVER"),
                outcome=ApprovalOutcome.REJECTED,
                reason="Plan requires changes.",
            )
        with runtime.traces.start_span("professional.plan.resume.rejected"):
            with pytest.raises(ApprovalError) as rejected:
                runtime.service.resume(
                    resume_id=RESUME_ID,
                    scope=scope(),
                    approval_id=APPROVAL_ID,
                    expected_subject_sha256=subject,
                )
        assert rejected.value.code == "APPROVAL_NOT_APPROVED"
        with pytest.raises(ApprovalError) as changed:
            runtime.service.resume(
                resume_id=RESUME_ID,
                scope=scope(),
                approval_id=APPROVAL_ID,
                expected_subject_sha256="0" * 64,
            )
        assert changed.value.code == "PROFESSIONAL_APPROVAL_SUBJECT_STALE"
    finally:
        runtime.close()


def test_professional_approval_assets_define_roles_hashes_and_nonpublication() -> None:
    skill = (ROOT / "skills/professional/approval/SKILL.md").read_text("utf-8")
    prompt = (ROOT / "prompts/professional/approval.v1.md").read_text("utf-8")
    contract = (ROOT / "docs/contracts/professional-approval-v1.md").read_text("utf-8")

    assert "version: 1.0.0" in skill
    assert "ProfessionalApprovalCheckpoint@1.0.0" in contract
    assert "QUALIFIED_PLAN_APPROVER" in contract
    assert "one exact resume grant" in prompt
    assert "no publication" in prompt
