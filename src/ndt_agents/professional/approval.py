"""S4-07 professional plan, report, and critical-finding approval boundary."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Literal, Never, Self
from uuid import UUID, uuid5

from pydantic import Field, model_validator

from ndt_agents.approval.service import (
    ApprovalActor,
    ApprovalDecision,
    ApprovalError,
    ApprovalGrant,
    ApprovalKind,
    ApprovalPolicy,
    ApprovalRule,
    ApprovalService,
    ApprovalStatus,
    default_approval_policy,
)
from ndt_agents.contracts.v1 import (
    AgentStatus,
    ApprovalOutcome,
    ReviewDecision,
    StrictModel,
    TenantScope,
)
from ndt_agents.orchestration.review import (
    ReviewWorkflowResult,
    ReviewWorkflowStatus,
    review_manifest_sha256,
)
from ndt_agents.professional.planning import (
    InspectionPlanResult,
    inspection_plan_result_sha256,
)
from ndt_agents.professional.reporting import (
    ConclusionLevel,
    FindingSeverity,
    InspectionReportResult,
    ReportFinding,
    inspection_report_result_sha256,
)
from ndt_agents.professional.review import (
    ProfessionalResultEnvelope,
    ProfessionalResultKind,
    ProfessionalReviewAssessment,
    professional_assessment_sha256,
)

PROFESSIONAL_APPROVAL_CONTRACT_VERSION: Literal["1.0.0"] = "1.0.0"
PROFESSIONAL_APPROVAL_POLICY_VERSION = "professional-approval-policy-1.0.0"
_CRITICAL_TARGET_NAMESPACE = UUID("40000000-0000-4000-8000-000000000707")


class CriticalFindingBinding(StrictModel):
    finding_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,127}$")
    statement_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    observation_ids: tuple[UUID, ...] = Field(min_length=1)
    calculation_ids: tuple[str, ...]
    plan_basis_ids: tuple[str, ...] = Field(min_length=1)
    limitations_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    human_confirmation_required: Literal[True] = True


class ProfessionalApprovalBinding(StrictModel):
    schema_version: Literal["1.0.0"] = PROFESSIONAL_APPROVAL_CONTRACT_VERSION
    kind: Literal[ApprovalKind.PLAN, ApprovalKind.REPORT, ApprovalKind.CRITICAL_FINDING]
    action: Literal[
        "inspection_plan.approve",
        "inspection_report.approve",
        "critical_finding.confirm",
    ]
    target_type: Literal["inspection-plan", "inspection-report", "critical-finding-set"]
    target_id: UUID
    target_version: str = Field(min_length=1, max_length=128)
    scope: TenantScope
    task_id: UUID
    result_kind: Literal[
        ProfessionalResultKind.INSPECTION_PLAN,
        ProfessionalResultKind.INSPECTION_REPORT,
    ]
    result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    review_envelope_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    assessment_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    review_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    review_decision: Literal[ReviewDecision.PASS, ReviewDecision.HUMAN_REQUIRED]
    critical_findings: tuple[CriticalFindingBinding, ...] = Field(max_length=10_000)
    approval_subject_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_binding(self) -> Self:
        expected_boundary = {
            ApprovalKind.PLAN: ("inspection_plan.approve", "inspection-plan"),
            ApprovalKind.REPORT: ("inspection_report.approve", "inspection-report"),
            ApprovalKind.CRITICAL_FINDING: (
                "critical_finding.confirm",
                "critical-finding-set",
            ),
        }[self.kind]
        if (self.action, self.target_type) != expected_boundary:
            raise ValueError("professional approval action or target type is invalid")
        if self.kind is ApprovalKind.CRITICAL_FINDING:
            if (
                self.action != "critical_finding.confirm"
                or self.target_type != "critical-finding-set"
                or not self.critical_findings
                or self.review_decision is not ReviewDecision.HUMAN_REQUIRED
            ):
                raise ValueError("critical-finding approval binding is invalid")
        elif (
            self.critical_findings
            or self.review_decision is not ReviewDecision.PASS
            or (self.kind is ApprovalKind.PLAN)
            != (self.result_kind is ProfessionalResultKind.INSPECTION_PLAN)
        ):
            raise ValueError("plan or report approval binding is invalid")
        if self.approval_subject_sha256 != professional_approval_subject_sha256(self):
            raise ValueError("professional approval subject hash is invalid")
        return self


class ProfessionalApprovalCheckpoint(StrictModel):
    schema_version: Literal["1.0.0"] = PROFESSIONAL_APPROVAL_CONTRACT_VERSION
    binding: ProfessionalApprovalBinding
    approval: ApprovalStatus
    model_calls: Literal[0] = 0
    tool_calls: Literal[0] = 0
    network_calls: Literal[0] = 0
    publication_calls: Literal[0] = 0
    user_delivery_calls: Literal[0] = 0
    checkpoint_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_checkpoint(self) -> Self:
        candidate = self.approval.candidate
        binding = self.binding
        if (
            candidate.scope != binding.scope
            or candidate.task_id != binding.task_id
            or candidate.kind is not binding.kind
            or candidate.action != binding.action
            or candidate.target_type != binding.target_type
            or candidate.target_id != binding.target_id
            or candidate.target_version != binding.target_version
            or candidate.candidate_sha256 != binding.approval_subject_sha256
            or candidate.policy_version != PROFESSIONAL_APPROVAL_POLICY_VERSION
        ):
            raise ValueError("professional checkpoint does not match the core approval candidate")
        if self.checkpoint_sha256 != professional_approval_checkpoint_sha256(self):
            raise ValueError("professional approval checkpoint hash is invalid")
        return self


def professional_approval_policy() -> ApprovalPolicy:
    base = default_approval_policy()
    rules = dict(base.rules)
    rules[ApprovalKind.PLAN] = ApprovalRule(
        required_roles=frozenset({"QUALIFIED_PLAN_APPROVER"}),
        delegation_allowed=True,
        validity_seconds=86_400,
    )
    rules[ApprovalKind.REPORT] = ApprovalRule(
        required_roles=frozenset({"QUALIFIED_REPORT_APPROVER"}),
        validity_seconds=86_400,
    )
    rules[ApprovalKind.CRITICAL_FINDING] = ApprovalRule(
        required_roles=frozenset({"QUALIFIED_FINDING_APPROVER"}),
        validity_seconds=21_600,
    )
    return ApprovalPolicy(policy_version=PROFESSIONAL_APPROVAL_POLICY_VERSION, rules=rules)


class ProfessionalApprovalService:
    """Validate professional review evidence before calling the generic approval service."""

    def __init__(self, approvals: ApprovalService) -> None:
        self._approvals = approvals

    def create_plan(
        self,
        *,
        approval_id: UUID,
        request_id: str,
        plan: InspectionPlanResult,
        assessment: ProfessionalReviewAssessment,
        review: ReviewWorkflowResult,
    ) -> ProfessionalApprovalCheckpoint:
        try:
            plan = InspectionPlanResult.model_validate(plan.model_dump(mode="json"))
        except ValueError:
            _deny(
                "PROFESSIONAL_PLAN_INVALID",
                "The inspection plan failed strict contract or hash revalidation.",
            )
        if (
            plan.status is not AgentStatus.SUCCESS
            or plan.issues
            or not plan.review_required
            or plan.approval_state != "PENDING"
            or plan.formal_use_allowed
            or plan.result_sha256 != inspection_plan_result_sha256(plan)
        ):
            _deny(
                "PROFESSIONAL_PLAN_NOT_APPROVABLE",
                "The inspection plan is not a clean review-pending approval candidate.",
            )
        envelope = _validate_review_evidence(
            plan.scope,
            plan.task_id,
            ProfessionalResultKind.INSPECTION_PLAN,
            plan.result_sha256,
            assessment,
            review,
            ReviewDecision.PASS,
        )
        binding = _binding(
            kind=ApprovalKind.PLAN,
            action="inspection_plan.approve",
            target_type="inspection-plan",
            target_id=plan.task_id,
            target_version=plan.skill_version,
            scope=plan.scope,
            task_id=plan.task_id,
            result_kind=ProfessionalResultKind.INSPECTION_PLAN,
            result_sha256=plan.result_sha256,
            content_sha256=plan.plan_sha256,
            envelope=envelope,
            assessment=assessment,
            review=review,
            critical_findings=(),
        )
        return self._create(approval_id, request_id, binding)

    def create_report(
        self,
        *,
        approval_id: UUID,
        request_id: str,
        report: InspectionReportResult,
        assessment: ProfessionalReviewAssessment,
        review: ReviewWorkflowResult,
    ) -> ProfessionalApprovalCheckpoint:
        try:
            report = InspectionReportResult.model_validate(report.model_dump(mode="json"))
        except ValueError:
            _deny(
                "PROFESSIONAL_REPORT_INVALID",
                "The inspection report failed strict contract or hash revalidation.",
            )
        has_human_boundary = (
            report.conclusion.level is ConclusionLevel.FORMAL
            or report.conclusion.human_confirmation_required
            or any(
                item.severity is FindingSeverity.CRITICAL or item.human_confirmation_required
                for item in report.findings
            )
        )
        if (
            report.status is not AgentStatus.SUCCESS
            or report.issues
            or not report.review_required
            or report.approval_state != "PENDING"
            or report.formal_release_allowed
            or has_human_boundary
            or report.result_sha256 != inspection_report_result_sha256(report)
        ):
            _deny(
                "PROFESSIONAL_REPORT_NOT_APPROVABLE",
                "The report is not a clean reviewed non-formal approval candidate.",
            )
        envelope = _validate_review_evidence(
            report.scope,
            report.task_id,
            ProfessionalResultKind.INSPECTION_REPORT,
            report.result_sha256,
            assessment,
            review,
            ReviewDecision.PASS,
        )
        binding = _binding(
            kind=ApprovalKind.REPORT,
            action="inspection_report.approve",
            target_type="inspection-report",
            target_id=report.report_id,
            target_version=f"revision-{report.revision}",
            scope=report.scope,
            task_id=report.task_id,
            result_kind=ProfessionalResultKind.INSPECTION_REPORT,
            result_sha256=report.result_sha256,
            content_sha256=report.report_sha256,
            envelope=envelope,
            assessment=assessment,
            review=review,
            critical_findings=(),
        )
        return self._create(approval_id, request_id, binding)

    def create_critical_findings(
        self,
        *,
        approval_id: UUID,
        request_id: str,
        report: InspectionReportResult,
        finding_ids: tuple[str, ...],
        assessment: ProfessionalReviewAssessment,
        review: ReviewWorkflowResult,
    ) -> ProfessionalApprovalCheckpoint:
        try:
            report = InspectionReportResult.model_validate(report.model_dump(mode="json"))
        except ValueError:
            _deny(
                "PROFESSIONAL_REPORT_INVALID",
                "The inspection report failed strict contract or hash revalidation.",
            )
        if finding_ids != tuple(sorted(set(finding_ids))) or not finding_ids:
            _deny(
                "PROFESSIONAL_FINDING_SET_INVALID",
                "Critical finding IDs must be non-empty, sorted, and unique.",
            )
        by_id = {item.finding_id: item for item in report.findings}
        selected = tuple(by_id.get(item) for item in finding_ids)
        if (
            report.status is not AgentStatus.HUMAN_REQUIRED
            or any(item is None for item in selected)
            or any(
                item is not None
                and (
                    item.severity is not FindingSeverity.CRITICAL
                    or not item.human_confirmation_required
                )
                for item in selected
            )
        ):
            _deny(
                "PROFESSIONAL_FINDING_NOT_CONFIRMABLE",
                "The selected report findings do not form an exact human-required critical set.",
            )
        envelope = _validate_review_evidence(
            report.scope,
            report.task_id,
            ProfessionalResultKind.INSPECTION_REPORT,
            report.result_sha256,
            assessment,
            review,
            ReviewDecision.HUMAN_REQUIRED,
        )
        finding_bindings = tuple(
            _critical_finding_binding(item) for item in selected if item is not None
        )
        target_id = uuid5(_CRITICAL_TARGET_NAMESPACE, f"{report.report_id}:{':'.join(finding_ids)}")
        binding = _binding(
            kind=ApprovalKind.CRITICAL_FINDING,
            action="critical_finding.confirm",
            target_type="critical-finding-set",
            target_id=target_id,
            target_version=f"report-revision-{report.revision}",
            scope=report.scope,
            task_id=report.task_id,
            result_kind=ProfessionalResultKind.INSPECTION_REPORT,
            result_sha256=report.result_sha256,
            content_sha256=report.report_sha256,
            envelope=envelope,
            assessment=assessment,
            review=review,
            critical_findings=finding_bindings,
        )
        return self._create(approval_id, request_id, binding)

    def status(self, scope: TenantScope, approval_id: UUID) -> ProfessionalApprovalCheckpoint:
        return _checkpoint(self._approvals.status(scope, approval_id))

    def decide(
        self,
        *,
        decision_id: UUID,
        scope: TenantScope,
        approval_id: UUID,
        expected_subject_sha256: str,
        actor: ApprovalActor,
        outcome: Literal[
            ApprovalOutcome.APPROVED,
            ApprovalOutcome.REJECTED,
            ApprovalOutcome.CHANGES_REQUESTED,
        ],
        reason: str,
        actor_role: str | None = None,
    ) -> ApprovalDecision:
        return self._approvals.decide(
            decision_id=decision_id,
            scope=scope,
            approval_id=approval_id,
            expected_candidate_sha256=expected_subject_sha256,
            actor=actor,
            outcome=outcome,
            reason=reason,
            actor_role=actor_role,
        )

    def resume(
        self,
        *,
        resume_id: UUID,
        scope: TenantScope,
        approval_id: UUID,
        expected_subject_sha256: str,
    ) -> ApprovalGrant:
        checkpoint = self.status(scope, approval_id)
        if checkpoint.binding.approval_subject_sha256 != expected_subject_sha256:
            _deny(
                "PROFESSIONAL_APPROVAL_SUBJECT_STALE",
                "The professional approval subject changed before resume.",
            )
        return self._approvals.resume(
            resume_id=resume_id,
            scope=scope,
            approval_id=approval_id,
            expected_candidate_sha256=expected_subject_sha256,
        )

    def _create(
        self,
        approval_id: UUID,
        request_id: str,
        binding: ProfessionalApprovalBinding,
    ) -> ProfessionalApprovalCheckpoint:
        status = self._approvals.create(
            approval_id=approval_id,
            scope=binding.scope,
            task_id=binding.task_id,
            request_id=request_id,
            kind=binding.kind,
            action=binding.action,
            target_type=binding.target_type,
            target_id=binding.target_id,
            target_version=binding.target_version,
            candidate_sha256=binding.approval_subject_sha256,
            preview={
                "professional_approval_binding": binding.model_dump(mode="json"),
                "summary": "Hash-bound professional approval candidate; full evidence is external.",
            },
        )
        return _checkpoint(status)


def professional_approval_subject_sha256(binding: ProfessionalApprovalBinding) -> str:
    return _canonical_hash(binding.model_dump(mode="json", exclude={"approval_subject_sha256"}))


def professional_approval_checkpoint_sha256(checkpoint: ProfessionalApprovalCheckpoint) -> str:
    return _canonical_hash(checkpoint.model_dump(mode="json", exclude={"checkpoint_sha256"}))


def _binding(
    *,
    kind: Literal[ApprovalKind.PLAN, ApprovalKind.REPORT, ApprovalKind.CRITICAL_FINDING],
    action: Literal[
        "inspection_plan.approve",
        "inspection_report.approve",
        "critical_finding.confirm",
    ],
    target_type: Literal["inspection-plan", "inspection-report", "critical-finding-set"],
    target_id: UUID,
    target_version: str,
    scope: TenantScope,
    task_id: UUID,
    result_kind: Literal[
        ProfessionalResultKind.INSPECTION_PLAN,
        ProfessionalResultKind.INSPECTION_REPORT,
    ],
    result_sha256: str,
    content_sha256: str,
    envelope: ProfessionalResultEnvelope,
    assessment: ProfessionalReviewAssessment,
    review: ReviewWorkflowResult,
    critical_findings: tuple[CriticalFindingBinding, ...],
) -> ProfessionalApprovalBinding:
    payload: dict[str, object] = {
        "schema_version": PROFESSIONAL_APPROVAL_CONTRACT_VERSION,
        "kind": kind,
        "action": action,
        "target_type": target_type,
        "target_id": target_id,
        "target_version": target_version,
        "scope": scope,
        "task_id": task_id,
        "result_kind": result_kind,
        "result_sha256": result_sha256,
        "content_sha256": content_sha256,
        "review_envelope_sha256": envelope.envelope_sha256,
        "assessment_sha256": assessment.assessment_sha256,
        "review_manifest_sha256": review.review_manifest_sha256,
        "review_decision": assessment.decision,
        "critical_findings": critical_findings,
    }
    return ProfessionalApprovalBinding.model_validate(
        {**payload, "approval_subject_sha256": _canonical_hash(_jsonable(payload))}
    )


def _validate_review_evidence(
    scope: TenantScope,
    task_id: UUID,
    kind: ProfessionalResultKind,
    result_sha256: str,
    assessment: ProfessionalReviewAssessment,
    review: ReviewWorkflowResult,
    expected_decision: Literal[ReviewDecision.PASS, ReviewDecision.HUMAN_REQUIRED],
) -> ProfessionalResultEnvelope:
    try:
        assessment = ProfessionalReviewAssessment.model_validate(assessment.model_dump(mode="json"))
        review = ReviewWorkflowResult.model_validate(review.model_dump(mode="json"))
    except ValueError:
        _deny(
            "PROFESSIONAL_REVIEW_EVIDENCE_INVALID",
            "Professional assessment or S1-09 review evidence failed strict revalidation.",
        )
    if (
        assessment.scope != scope
        or assessment.task_id != task_id
        or assessment.decision is not expected_decision
        or assessment.assessment_sha256 != professional_assessment_sha256(assessment)
        or review.scope != scope
        or review.task_id != task_id
        or review.review_manifest_sha256 != review_manifest_sha256(review)
    ):
        _deny(
            "PROFESSIONAL_REVIEW_EVIDENCE_INVALID",
            "Professional assessment or S1-09 review evidence is stale or mismatched.",
        )
    if expected_decision is ReviewDecision.PASS:
        if (
            not assessment.aggregation_ready
            or not review.aggregation_ready
            or review.status
            not in {
                ReviewWorkflowStatus.APPROVED,
                ReviewWorkflowStatus.PARTIAL,
            }
        ):
            _deny(
                "PROFESSIONAL_REVIEW_NOT_PASSED",
                "Plan or report approval requires completed aggregation-ready review.",
            )
    elif (
        assessment.aggregation_ready
        or review.aggregation_ready
        or review.status is not ReviewWorkflowStatus.HUMAN_REQUIRED
    ):
        _deny(
            "PROFESSIONAL_HUMAN_REVIEW_BOUNDARY_INVALID",
            "Critical findings require an exact human-required review pause.",
        )

    matches: list[ProfessionalResultEnvelope] = []
    for assignment in review.assignments:
        raw = assignment.current_result.structured_data.get("professional_review_envelope")
        if not isinstance(raw, Mapping):
            continue
        try:
            envelope = ProfessionalResultEnvelope.model_validate(dict(raw))
        except ValueError:
            continue
        if (
            envelope.result_kind is kind
            and envelope.scope == scope
            and envelope.task_id == task_id
            and envelope.payload.get("result_sha256") == result_sha256
            and envelope.result_sha256 in assessment.target_result_sha256s
        ):
            matches.append(envelope)
    if len(matches) != 1:
        _deny(
            "PROFESSIONAL_REVIEW_TARGET_INVALID",
            "Review evidence does not bind exactly one requested professional result.",
        )
    return matches[0]


def _critical_finding_binding(finding: ReportFinding) -> CriticalFindingBinding:
    evidence_payload = {
        "observation_ids": [str(item) for item in finding.observation_ids],
        "calculation_ids": finding.calculation_ids,
        "plan_basis_ids": finding.plan_basis_ids,
    }
    return CriticalFindingBinding(
        finding_id=finding.finding_id,
        statement_sha256=_canonical_hash(finding.statement),
        observation_ids=finding.observation_ids,
        calculation_ids=finding.calculation_ids,
        plan_basis_ids=finding.plan_basis_ids,
        limitations_sha256=_canonical_hash(finding.limitations),
        evidence_sha256=_canonical_hash(evidence_payload),
        human_confirmation_required=True,
    )


def _checkpoint(status: ApprovalStatus) -> ProfessionalApprovalCheckpoint:
    if status.candidate.policy_version != PROFESSIONAL_APPROVAL_POLICY_VERSION:
        _deny(
            "PROFESSIONAL_APPROVAL_POLICY_INVALID",
            "The core approval service is not using the professional approval policy.",
        )
    raw = status.candidate.preview.get("professional_approval_binding")
    if not isinstance(raw, Mapping):
        _deny(
            "PROFESSIONAL_APPROVAL_BINDING_MISSING",
            "The core approval candidate has no professional binding.",
        )
    try:
        binding = ProfessionalApprovalBinding.model_validate(dict(raw))
    except ValueError:
        _deny(
            "PROFESSIONAL_APPROVAL_BINDING_INVALID",
            "The professional approval binding failed strict hash revalidation.",
        )
    payload: dict[str, object] = {
        "schema_version": PROFESSIONAL_APPROVAL_CONTRACT_VERSION,
        "binding": binding,
        "approval": status,
        "model_calls": 0,
        "tool_calls": 0,
        "network_calls": 0,
        "publication_calls": 0,
        "user_delivery_calls": 0,
    }
    return ProfessionalApprovalCheckpoint.model_validate(
        {**payload, "checkpoint_sha256": _canonical_hash(_jsonable(payload))}
    )


def _deny(code: str, message: str) -> Never:
    raise ApprovalError(
        code,
        message,
        "Restore exact reviewed evidence, authority, scope, hash, or approval state.",
    )


def _jsonable(value: object) -> object:
    if isinstance(value, StrictModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, UUID):
        return str(value)
    return value


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
        ).encode()
    ).hexdigest()
