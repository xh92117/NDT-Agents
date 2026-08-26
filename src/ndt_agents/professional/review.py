"""S4-06 deterministic professional checklists and S1-09 review adapter."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal, Self
from uuid import UUID, uuid5

from pydantic import Field, ValidationError, model_validator

from ndt_agents.contracts.v1 import (
    AgentStatus,
    Issue,
    ReviewDecision,
    ReviewResult,
    StrictModel,
    TenantScope,
)
from ndt_agents.orchestration.review import ReviewContext, ReviewKind
from ndt_agents.professional.methods import (
    MethodValidationResult,
    method_validation_result_sha256,
)
from ndt_agents.professional.planning import (
    InspectionPlanResult,
    inspection_plan_result_sha256,
)
from ndt_agents.professional.processing import (
    ProcessingControlResult,
    processing_candidate_sha256,
    processing_result_sha256,
)
from ndt_agents.professional.qa import TechnicalQAResult, technical_qa_result_sha256
from ndt_agents.professional.reporting import (
    ConclusionLevel,
    FindingSeverity,
    InspectionReportResult,
    inspection_report_result_sha256,
)

PROFESSIONAL_REVIEW_CONTRACT_VERSION: Literal["1.0.0"] = "1.0.0"
_REVIEW_NAMESPACE = UUID("40000000-0000-4000-8000-000000000606")


class ProfessionalResultKind(StrEnum):
    TECHNICAL_QA = "TECHNICAL_QA"
    INSPECTION_PLAN = "INSPECTION_PLAN"
    DATA_PROCESSING = "DATA_PROCESSING"
    METHOD_VALIDATION = "METHOD_VALIDATION"
    INSPECTION_REPORT = "INSPECTION_REPORT"


ProfessionalResult = (
    TechnicalQAResult
    | InspectionPlanResult
    | ProcessingControlResult
    | MethodValidationResult
    | InspectionReportResult
)


class ProfessionalChecklistDefinition(StrictModel):
    schema_version: Literal["1.0.0"] = PROFESSIONAL_REVIEW_CONTRACT_VERSION
    result_kind: ProfessionalResultKind
    checklist_id: str = Field(pattern=r"^professional-[a-z-]+-review-v1$")
    checklist_version: Literal["1.0.0"] = PROFESSIONAL_REVIEW_CONTRACT_VERSION
    checks: tuple[str, ...] = Field(min_length=1, max_length=32)
    checklist_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_definition(self) -> Self:
        if self.checks != tuple(dict.fromkeys(self.checks)):
            raise ValueError("professional checklist entries must be unique and ordered")
        if self.checklist_sha256 != professional_checklist_sha256(self):
            raise ValueError("professional checklist hash is invalid")
        return self


class ProfessionalResultEnvelope(StrictModel):
    schema_version: Literal["1.0.0"] = PROFESSIONAL_REVIEW_CONTRACT_VERSION
    result_kind: ProfessionalResultKind
    scope: TenantScope
    task_id: UUID
    run_id: UUID
    payload: dict[str, Any]
    result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    envelope_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_hashes(self) -> Self:
        if self.result_sha256 != _canonical_hash(self.payload):
            raise ValueError("professional envelope result hash is invalid")
        if self.envelope_sha256 != professional_envelope_sha256(self):
            raise ValueError("professional envelope hash is invalid")
        return self


class ProfessionalReviewAssessment(StrictModel):
    schema_version: Literal["1.0.0"] = PROFESSIONAL_REVIEW_CONTRACT_VERSION
    review_kind: ReviewKind
    scope: TenantScope
    task_id: UUID
    result_kinds: tuple[ProfessionalResultKind, ...] = Field(min_length=1, max_length=16)
    target_result_sha256s: tuple[str, ...] = Field(min_length=1, max_length=16)
    checklist_sha256s: tuple[str, ...] = Field(min_length=1, max_length=16)
    decision: ReviewDecision
    findings: tuple[Issue, ...] = Field(max_length=256)
    aggregation_ready: bool
    model_calls: Literal[0] = 0
    tool_calls: Literal[0] = 0
    correction_calls: Literal[0] = 0
    assessment_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_assessment(self) -> Self:
        if self.target_result_sha256s != tuple(sorted(self.target_result_sha256s)):
            raise ValueError("professional review target hashes must be sorted")
        if self.checklist_sha256s != tuple(sorted(set(self.checklist_sha256s))):
            raise ValueError("professional checklist hashes must be sorted and unique")
        if self.aggregation_ready != (self.decision is ReviewDecision.PASS):
            raise ValueError("professional aggregation state must match PASS")
        if self.decision is ReviewDecision.PASS and self.findings:
            raise ValueError("a passed professional assessment cannot retain findings")
        if self.decision is not ReviewDecision.PASS and not self.findings:
            raise ValueError("a non-pass professional assessment requires findings")
        if self.assessment_sha256 != professional_assessment_sha256(self):
            raise ValueError("professional review assessment hash is invalid")
        return self


class ProfessionalChecklistRegistry:
    def __init__(
        self, definitions: tuple[ProfessionalChecklistDefinition, ...] | None = None
    ) -> None:
        resolved = definitions or default_professional_checklists()
        expected = tuple(ProfessionalResultKind)
        if tuple(item.result_kind for item in resolved) != expected:
            raise ValueError("professional checklist registry is incomplete or out of order")
        self._definitions = {item.result_kind: item for item in resolved}

    def definitions(self) -> tuple[ProfessionalChecklistDefinition, ...]:
        return tuple(self._definitions[item] for item in ProfessionalResultKind)

    def get(self, kind: ProfessionalResultKind) -> ProfessionalChecklistDefinition:
        return self._definitions[kind]


class ProfessionalReviewService:
    """Revalidate professional outputs independently and compare interacting results."""

    def __init__(self, registry: ProfessionalChecklistRegistry | None = None) -> None:
        self._registry = registry or ProfessionalChecklistRegistry()

    def review_one(
        self,
        envelope: ProfessionalResultEnvelope,
        *,
        expected_scope: TenantScope | None = None,
        expected_task_id: UUID | None = None,
        expected_run_id: UUID | None = None,
    ) -> ProfessionalReviewAssessment:
        findings: list[Issue] = []
        try:
            validated = ProfessionalResultEnvelope.model_validate(envelope.model_dump(mode="json"))
            result = _parse_result(validated)
        except (ValidationError, ValueError) as error:
            findings.append(
                _issue(
                    "PROFESSIONAL_RESULT_INVALID",
                    "CRITICAL",
                    f"The professional result cannot be revalidated: {error}.",
                    "structured_data.professional_review_envelope",
                    "Restore the exact typed result and all canonical hashes.",
                )
            )
            return self._assessment(
                ReviewKind.PER_RESULT,
                envelope.scope,
                envelope.task_id,
                (envelope.result_kind,),
                (envelope.result_sha256,),
                (self._registry.get(envelope.result_kind).checklist_sha256,),
                ReviewDecision.FAILED,
                findings,
            )

        if (
            (expected_scope is not None and validated.scope != expected_scope)
            or (expected_task_id is not None and validated.task_id != expected_task_id)
            or (expected_run_id is not None and validated.run_id != expected_run_id)
            or _result_scope(result) != validated.scope
            or (
                _result_task_id(result) is not None and _result_task_id(result) != validated.task_id
            )
        ):
            findings.append(
                _issue(
                    "PROFESSIONAL_REVIEW_SCOPE_DENIED",
                    "CRITICAL",
                    "The professional result is not bound to the expected scope, task, or run.",
                    "structured_data.professional_review_envelope",
                    "Restore the exact authorized task and result envelope.",
                )
            )
        self._check_result(validated.result_kind, result, findings)
        decision = _per_result_decision(result, findings)
        if decision is not ReviewDecision.PASS and not findings:
            code, message = {
                ReviewDecision.HUMAN_REQUIRED: (
                    "PROFESSIONAL_HUMAN_CONFIRMATION_REQUIRED",
                    "The result contains an explicit qualified-human confirmation boundary.",
                ),
                ReviewDecision.FAILED: (
                    "PROFESSIONAL_RESULT_FAILED",
                    "The professional result is failed or blocked.",
                ),
            }.get(
                decision,
                (
                    "PROFESSIONAL_RESULT_REVISION_REQUIRED",
                    "The professional result requires one bounded revision.",
                ),
            )
            findings.append(
                _issue(
                    code,
                    "CRITICAL" if decision is ReviewDecision.HUMAN_REQUIRED else "ERROR",
                    message,
                    validated.result_kind.value,
                    "Preserve the evidence and follow the typed review decision.",
                )
            )
        checklist = self._registry.get(validated.result_kind)
        return self._assessment(
            ReviewKind.PER_RESULT,
            validated.scope,
            validated.task_id,
            (validated.result_kind,),
            (validated.result_sha256,),
            (checklist.checklist_sha256,),
            decision,
            findings,
        )

    def review_cross(
        self,
        envelopes: tuple[ProfessionalResultEnvelope, ...],
        *,
        expected_scope: TenantScope,
        expected_task_id: UUID,
    ) -> ProfessionalReviewAssessment:
        if len(envelopes) < 2:
            raise ValueError("cross-result review requires at least two professional results")
        findings: list[Issue] = []
        parsed: list[tuple[ProfessionalResultEnvelope, ProfessionalResult]] = []
        checklist_hashes: list[str] = []
        for envelope in envelopes:
            assessment = self.review_one(
                envelope,
                expected_scope=expected_scope,
                expected_task_id=expected_task_id,
                expected_run_id=envelope.run_id,
            )
            checklist_hashes.extend(assessment.checklist_sha256s)
            if not assessment.aggregation_ready:
                findings.append(
                    _issue(
                        "CROSS_PER_RESULT_NOT_PASSED",
                        "CRITICAL",
                        f"{envelope.result_kind} did not pass independent review.",
                        envelope.result_kind.value,
                        "Resolve the per-result assessment before cross-result review.",
                    )
                )
                continue
            parsed.append((envelope, _parse_result(envelope)))
        if len(parsed) == len(envelopes):
            self._check_cross_relations(parsed, findings)
        decision = ReviewDecision.CONFLICT if findings else ReviewDecision.PASS
        return self._assessment(
            ReviewKind.CROSS_RESULT,
            expected_scope,
            expected_task_id,
            tuple(item.result_kind for item in envelopes),
            tuple(item.result_sha256 for item in envelopes),
            tuple(checklist_hashes),
            decision,
            findings,
        )

    @staticmethod
    def _check_result(
        kind: ProfessionalResultKind,
        result: ProfessionalResult,
        findings: list[Issue],
    ) -> None:
        for issue in result.issues:
            findings.append(issue)
        if kind is ProfessionalResultKind.TECHNICAL_QA:
            assert isinstance(result, TechnicalQAResult)
            if result.result_sha256 != technical_qa_result_sha256(result):
                _append_hash_issue(findings)
            if any(not claim.citations for claim in result.claims):
                findings.append(
                    _issue(
                        "QA_REVIEW_CITATION_MISSING",
                        "ERROR",
                        "A QA claim has no exact citation.",
                        "claims",
                        "Bind the claim to exact published evidence or mark it unsupported.",
                    )
                )
        elif kind is ProfessionalResultKind.INSPECTION_PLAN:
            assert isinstance(result, InspectionPlanResult)
            if result.result_sha256 != inspection_plan_result_sha256(result):
                _append_hash_issue(findings)
            if (
                not result.review_required
                or result.approval_state != "PENDING"
                or result.formal_use_allowed
            ):
                _append_boundary_issue(findings, "plan")
        elif kind is ProfessionalResultKind.DATA_PROCESSING:
            assert isinstance(result, ProcessingControlResult)
            if result.result_sha256 != processing_result_sha256(result):
                _append_hash_issue(findings)
            if (
                not result.review_required
                or result.model_calls
                or result.network_calls
                or result.physical_commands
            ):
                _append_boundary_issue(findings, "processing")
        elif kind is ProfessionalResultKind.METHOD_VALIDATION:
            assert isinstance(result, MethodValidationResult)
            if result.result_sha256 != method_validation_result_sha256(result):
                _append_hash_issue(findings)
            if (
                not result.review_required
                or not result.method_compatible
                or any(
                    (
                        result.algorithm_calls,
                        result.instrument_commands,
                        result.model_calls,
                        result.network_calls,
                        result.approval_calls,
                        result.publication_calls,
                        result.retries,
                    )
                )
            ):
                _append_boundary_issue(findings, "method validation")
        else:
            assert isinstance(result, InspectionReportResult)
            if result.result_sha256 != inspection_report_result_sha256(result):
                _append_hash_issue(findings)
            if (
                not result.review_required
                or result.approval_state != "PENDING"
                or result.formal_release_allowed
            ):
                _append_boundary_issue(findings, "report")

    @staticmethod
    def _check_cross_relations(
        parsed: list[tuple[ProfessionalResultEnvelope, ProfessionalResult]],
        findings: list[Issue],
    ) -> None:
        by_kind: dict[ProfessionalResultKind, list[ProfessionalResult]] = {}
        for envelope, result in parsed:
            by_kind.setdefault(envelope.result_kind, []).append(result)
        singular_kinds = (
            ProfessionalResultKind.TECHNICAL_QA,
            ProfessionalResultKind.INSPECTION_PLAN,
            ProfessionalResultKind.INSPECTION_REPORT,
        )
        duplicates = tuple(kind for kind in singular_kinds if len(by_kind.get(kind, [])) > 1)
        if duplicates:
            _append_conflict(
                findings,
                "CROSS_DUPLICATE_RESULT",
                "Cross-result review received duplicate singular professional results: "
                + ", ".join(item.value for item in duplicates),
                "result_kinds",
            )
            return
        qa = _one(by_kind, ProfessionalResultKind.TECHNICAL_QA, TechnicalQAResult)
        plan = _one(by_kind, ProfessionalResultKind.INSPECTION_PLAN, InspectionPlanResult)
        report = _one(by_kind, ProfessionalResultKind.INSPECTION_REPORT, InspectionReportResult)
        processing_results = _many(
            by_kind, ProfessionalResultKind.DATA_PROCESSING, ProcessingControlResult
        )
        method_results = _many(
            by_kind, ProfessionalResultKind.METHOD_VALIDATION, MethodValidationResult
        )

        if qa is not None and plan is not None:
            citation_pairs = {
                (claim.claim_id, citation.chunk_id)
                for claim in qa.claims
                for citation in claim.citations
            }
            if plan.qa_result_sha256 != qa.result_sha256 or any(
                (basis.qa_claim_id, basis.chunk_id) not in citation_pairs
                for basis in plan.standard_basis
            ):
                _append_conflict(
                    findings,
                    "CROSS_QA_PLAN_CONFLICT",
                    "The plan basis does not bind the reviewed QA result and citations.",
                    "inspection_plan.standard_basis",
                )
        if plan is not None and report is not None and report.plan_sha256 != plan.plan_sha256:
            _append_conflict(
                findings,
                "CROSS_PLAN_REPORT_CONFLICT",
                "The report does not bind the reviewed inspection plan hash.",
                "inspection_report.plan_sha256",
            )
        for processing in processing_results:
            if report is not None and not _processing_matches_report(processing, report):
                _append_conflict(
                    findings,
                    "CROSS_PROCESSING_REPORT_CONFLICT",
                    "Processing source, run, output, or observations do not match the report.",
                    "inspection_report.processing",
                )
            matching_methods = [
                item
                for item in method_results
                if item.method_code == processing.candidate_method_code
            ]
            if method_results and not any(
                item.request_sha256 == processing.request_sha256
                and item.candidate_sha256 == processing_candidate_sha256(processing)
                for item in matching_methods
            ):
                _append_conflict(
                    findings,
                    "CROSS_METHOD_PROCESSING_CONFLICT",
                    "Method validation does not bind the exact processing request and candidate.",
                    "data_processing",
                )
        if report is not None and method_results:
            report_methods = {item.method_code for item in report.sources}
            if any(item.method_code not in report_methods for item in method_results):
                _append_conflict(
                    findings,
                    "CROSS_METHOD_REPORT_CONFLICT",
                    "A reviewed method is absent from the report source evidence.",
                    "inspection_report.sources",
                )

    @staticmethod
    def _assessment(
        review_kind: ReviewKind,
        scope: TenantScope,
        task_id: UUID,
        result_kinds: tuple[ProfessionalResultKind, ...],
        target_hashes: tuple[str, ...],
        checklist_hashes: tuple[str, ...],
        decision: ReviewDecision,
        findings: list[Issue],
    ) -> ProfessionalReviewAssessment:
        payload: dict[str, object] = {
            "schema_version": PROFESSIONAL_REVIEW_CONTRACT_VERSION,
            "review_kind": review_kind,
            "scope": scope,
            "task_id": task_id,
            "result_kinds": result_kinds,
            "target_result_sha256s": tuple(sorted(target_hashes)),
            "checklist_sha256s": tuple(sorted(set(checklist_hashes))),
            "decision": decision,
            "findings": tuple(findings),
            "aggregation_ready": decision is ReviewDecision.PASS,
            "model_calls": 0,
            "tool_calls": 0,
            "correction_calls": 0,
        }
        return ProfessionalReviewAssessment.model_validate(
            {**payload, "assessment_sha256": _canonical_hash(_jsonable(payload))}
        )


class ProfessionalReviewExecutor:
    """S1-09 ReviewExecutor adapter backed by deterministic professional checklists."""

    def __init__(
        self,
        service: ProfessionalReviewService | None = None,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._service = service or ProfessionalReviewService()
        self._clock = clock

    async def review(self, context: ReviewContext) -> Mapping[str, Any]:
        envelopes = tuple(
            _extract_envelope(target.result.structured_data) for target in context.targets
        )
        if context.kind is ReviewKind.PER_RESULT:
            target = context.targets[0]
            assessment = self._service.review_one(
                envelopes[0],
                expected_scope=context.scope,
                expected_task_id=context.task_id,
                expected_run_id=target.run_id,
            )
        else:
            assessment = self._service.review_cross(
                envelopes,
                expected_scope=context.scope,
                expected_task_id=context.task_id,
            )
        return ReviewResult(
            review_id=uuid5(
                _REVIEW_NAMESPACE,
                f"{context.kind}:{context.review_target_sha256}:{context.correction_count}:"
                f"{assessment.assessment_sha256}",
            ),
            task_id=context.task_id,
            target_run_id=context.review_target_run_id,
            target_sha256=context.review_target_sha256,
            reviewer_version=context.reviewer_version,
            decision=assessment.decision,
            findings=assessment.findings,
            correction_count=context.correction_count,
            completed_at=self._clock(),
        ).model_dump(mode="json")


def professional_result_envelope(
    result_kind: ProfessionalResultKind,
    result: ProfessionalResult,
    *,
    task_id: UUID,
    run_id: UUID,
) -> ProfessionalResultEnvelope:
    if _kind_for_result(result) is not result_kind:
        raise ValueError("professional result kind does not match the typed result")
    scope = _result_scope(result)
    inner_task = _result_task_id(result)
    if inner_task is not None and inner_task != task_id:
        raise ValueError("professional result task does not match the envelope")
    payload = result.model_dump(mode="json")
    values: dict[str, object] = {
        "schema_version": PROFESSIONAL_REVIEW_CONTRACT_VERSION,
        "result_kind": result_kind,
        "scope": scope,
        "task_id": task_id,
        "run_id": run_id,
        "payload": payload,
        "result_sha256": _canonical_hash(payload),
    }
    return ProfessionalResultEnvelope.model_validate(
        {**values, "envelope_sha256": _canonical_hash(_jsonable(values))}
    )


def professional_checklist_sha256(definition: ProfessionalChecklistDefinition) -> str:
    return _canonical_hash(definition.model_dump(mode="json", exclude={"checklist_sha256"}))


def professional_envelope_sha256(envelope: ProfessionalResultEnvelope) -> str:
    return _canonical_hash(envelope.model_dump(mode="json", exclude={"envelope_sha256"}))


def professional_assessment_sha256(assessment: ProfessionalReviewAssessment) -> str:
    return _canonical_hash(assessment.model_dump(mode="json", exclude={"assessment_sha256"}))


def default_professional_checklists() -> tuple[ProfessionalChecklistDefinition, ...]:
    values = (
        (
            ProfessionalResultKind.TECHNICAL_QA,
            "professional-technical-qa-review-v1",
            (
                "exact scope, schema, status, and stable result hash",
                "claim applicability, limitations, uncertainty, and human boundary",
                "exact published citation and claim support",
                "unresolved issues and safe escalation",
            ),
        ),
        (
            ProfessionalResultKind.INSPECTION_PLAN,
            "professional-inspection-plan-review-v1",
            (
                "exact scope, schema, status, and stable plan/result hashes",
                "template completeness, methods, quantities, and explicit gaps",
                "QA and standard-basis citation traceability",
                "review-required, approval-pending, and non-formal boundary",
            ),
        ),
        (
            ProfessionalResultKind.DATA_PROCESSING,
            "professional-data-processing-review-v1",
            (
                "exact source, request, candidate, processing, and result hashes",
                "calibration, quality, budget, and observation traceability",
                "explicit origin and report-eligibility boundary",
                "zero model, network, physical-command, and hidden-retry actions",
            ),
        ),
        (
            ProfessionalResultKind.METHOD_VALIDATION,
            "professional-method-validation-review-v1",
            (
                "exact method-definition, request, candidate, and result hashes",
                "metadata, calibration, applicability, input, parameter, and output checks",
                "explicit origin and production-report policy",
                "zero algorithm, instrument, model, network, approval, publication, "
                "and retry actions",
            ),
        ),
        (
            ProfessionalResultKind.INSPECTION_REPORT,
            "professional-inspection-report-review-v1",
            (
                "exact scope, schema, status, and stable report/result hashes",
                "plan, source, processing, observation, calculation, figure, and "
                "finding traceability",
                "citation, unit, numeric, limitation, conclusion, and revision consistency",
                "review-required, approval-pending, non-formal, and human boundary",
            ),
        ),
    )
    return tuple(_checklist(*item) for item in values)


def _checklist(
    kind: ProfessionalResultKind,
    checklist_id: str,
    checks: tuple[str, ...],
) -> ProfessionalChecklistDefinition:
    payload: dict[str, object] = {
        "schema_version": PROFESSIONAL_REVIEW_CONTRACT_VERSION,
        "result_kind": kind,
        "checklist_id": checklist_id,
        "checklist_version": PROFESSIONAL_REVIEW_CONTRACT_VERSION,
        "checks": checks,
    }
    return ProfessionalChecklistDefinition.model_validate(
        {**payload, "checklist_sha256": _canonical_hash(_jsonable(payload))}
    )


def _parse_result(envelope: ProfessionalResultEnvelope) -> ProfessionalResult:
    payload = envelope.payload
    if envelope.result_kind is ProfessionalResultKind.TECHNICAL_QA:
        return TechnicalQAResult.model_validate(payload)
    if envelope.result_kind is ProfessionalResultKind.INSPECTION_PLAN:
        return InspectionPlanResult.model_validate(payload)
    if envelope.result_kind is ProfessionalResultKind.DATA_PROCESSING:
        return ProcessingControlResult.model_validate(payload)
    if envelope.result_kind is ProfessionalResultKind.METHOD_VALIDATION:
        return MethodValidationResult.model_validate(payload)
    return InspectionReportResult.model_validate(payload)


def _extract_envelope(data: Mapping[str, Any]) -> ProfessionalResultEnvelope:
    raw = data.get("professional_review_envelope")
    if not isinstance(raw, Mapping):
        raise ValueError("PROFESSIONAL_REVIEW_ENVELOPE_REQUIRED")
    return ProfessionalResultEnvelope.model_validate(dict(raw))


def _kind_for_result(result: ProfessionalResult) -> ProfessionalResultKind:
    if isinstance(result, TechnicalQAResult):
        return ProfessionalResultKind.TECHNICAL_QA
    if isinstance(result, InspectionPlanResult):
        return ProfessionalResultKind.INSPECTION_PLAN
    if isinstance(result, ProcessingControlResult):
        return ProfessionalResultKind.DATA_PROCESSING
    if isinstance(result, MethodValidationResult):
        return ProfessionalResultKind.METHOD_VALIDATION
    return ProfessionalResultKind.INSPECTION_REPORT


def _result_scope(result: ProfessionalResult) -> TenantScope:
    return result.scope


def _result_task_id(result: ProfessionalResult) -> UUID | None:
    if isinstance(result, MethodValidationResult):
        return None
    return result.task_id


def _per_result_decision(result: ProfessionalResult, findings: list[Issue]) -> ReviewDecision:
    if any(
        item.code in {"PROFESSIONAL_REVIEW_SCOPE_DENIED", "PROFESSIONAL_RESULT_HASH_INVALID"}
        for item in findings
    ):
        return ReviewDecision.FAILED
    if result.status in {AgentStatus.FAILED, AgentStatus.BLOCKED}:
        return ReviewDecision.FAILED
    if result.status in {AgentStatus.HUMAN_REQUIRED, AgentStatus.NEEDS_USER}:
        return ReviewDecision.HUMAN_REQUIRED
    if isinstance(result, TechnicalQAResult) and result.human_confirmation_required:
        return ReviewDecision.HUMAN_REQUIRED
    if isinstance(result, InspectionReportResult) and (
        result.conclusion.level is ConclusionLevel.FORMAL
        or result.conclusion.human_confirmation_required
        or any(
            item.severity is FindingSeverity.CRITICAL or item.human_confirmation_required
            for item in result.findings
        )
    ):
        return ReviewDecision.HUMAN_REQUIRED
    if findings or result.status is AgentStatus.PARTIAL_SUCCESS:
        return ReviewDecision.REVISE
    return ReviewDecision.PASS


def _processing_matches_report(
    processing: ProcessingControlResult,
    report: InspectionReportResult,
) -> bool:
    source = processing.source
    report_source = next(
        (item for item in report.sources if item.dataset_id == source.dataset_id), None
    )
    report_run = next(
        (item for item in report.processing if item.processing_run_id == processing.run_id), None
    )
    if report_source is None or report_run is None:
        return False
    if (
        report_source.scope != source.scope
        or report_source.dataset_sha256 != source.dataset_sha256
        or report_source.method_code != source.method_code
        or report_source.artifact != source.artifact
        or report_run.scope != processing.scope
        or report_run.dataset_id != source.dataset_id
        or report_run.dataset_sha256 != source.dataset_sha256
        or report_run.adapter_version != processing.adapter_version
        or report_run.parser_version != processing.parser_version
        or report_run.algorithm_version != processing.algorithm_version
        or report_run.parameters_sha256 != processing.parameters_sha256
        or report_run.output_sha256 != processing.output_sha256
    ):
        return False
    report_observations = {
        item.observation_id: item
        for item in report.observations
        if item.processing_run_id == processing.run_id
    }
    return all(
        (report_item := report_observations.get(item.observation_id)) is not None
        and report_item.scope == item.scope
        and report_item.dataset_id == item.dataset_id
        and report_item.location_id == item.location_id
        and report_item.name == item.name
        and report_item.dimension == item.dimension
        and report_item.unit == item.unit
        and report_item.value == item.value
        and report_item.evidence_sha256 == item.evidence_sha256
        for item in processing.observations
    )


def _one[T: ProfessionalResult](
    values: dict[ProfessionalResultKind, list[ProfessionalResult]],
    kind: ProfessionalResultKind,
    expected: type[T],
) -> T | None:
    items = values.get(kind, [])
    if not items:
        return None
    if len(items) != 1 or not isinstance(items[0], expected):
        raise ValueError(f"cross-result review requires one {kind}")
    return items[0]


def _many[T: ProfessionalResult](
    values: dict[ProfessionalResultKind, list[ProfessionalResult]],
    kind: ProfessionalResultKind,
    expected: type[T],
) -> tuple[T, ...]:
    items = values.get(kind, [])
    if any(not isinstance(item, expected) for item in items):
        raise ValueError(f"cross-result review contains invalid {kind}")
    return tuple(item for item in items if isinstance(item, expected))


def _append_hash_issue(findings: list[Issue]) -> None:
    findings.append(
        _issue(
            "PROFESSIONAL_RESULT_HASH_INVALID",
            "CRITICAL",
            "The professional result hash does not match its content.",
            "result_sha256",
            "Restore the immutable professional result before review.",
        )
    )


def _append_boundary_issue(findings: list[Issue], name: str) -> None:
    findings.append(
        _issue(
            "PROFESSIONAL_BOUNDARY_INVALID",
            "CRITICAL",
            f"The {name} result bypasses a review, approval, formal-use, or side-effect boundary.",
            name,
            "Restore the provider-neutral review-pending result.",
        )
    )


def _append_conflict(findings: list[Issue], code: str, message: str, path: str) -> None:
    findings.append(
        _issue(
            code,
            "CRITICAL",
            message,
            path,
            "Return the conflicting result to its responsible child for one targeted repair.",
        )
    )


def _issue(
    code: str,
    severity: Literal["INFO", "WARNING", "ERROR", "CRITICAL"],
    message: str,
    affected_path: str | None,
    next_action: str,
) -> Issue:
    return Issue(
        code=code,
        severity=severity,
        message=message,
        affected_path=affected_path,
        next_action=next_action,
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
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
