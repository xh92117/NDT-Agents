"""S4-03 inspection-report Skill with traceability and numeric consistency checks."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from ndt_agents.contracts.v1 import AgentStatus, ArtifactRef, Issue, StrictModel, TenantScope
from ndt_agents.professional.planning import (
    InspectionPlanResult,
    PlanSection,
    inspection_plan_result_sha256,
    inspection_plan_sha256,
    is_registered_unit,
)
from ndt_agents.professional.qa import SUPPORTED_METHODS

REPORT_CONTRACT_VERSION: Literal["1.0.0"] = "1.0.0"
REPORT_TEMPLATE_ID = "TPL-INSPECTION-REPORT-V1"
REPORT_REQUIRED_SECTIONS = (
    "identity",
    "scope",
    "plan_reference",
    "source_data",
    "method_equipment_and_calibration",
    "observations",
    "calculations_and_units",
    "figures",
    "findings",
    "limitations",
    "citations",
    "conclusion_boundary",
    "revision_history",
    "review",
    "approval",
)


class CalculationFormula(StrEnum):
    COUNT = "COUNT"
    MAXIMUM = "MAXIMUM"
    MEAN = "MEAN"
    MINIMUM = "MINIMUM"
    RANGE = "RANGE"
    SUM = "SUM"


class FindingSeverity(StrEnum):
    INFORMATIONAL = "INFORMATIONAL"
    MATERIAL = "MATERIAL"
    CRITICAL = "CRITICAL"


class ConclusionLevel(StrEnum):
    PRELIMINARY = "PRELIMINARY"
    FORMAL = "FORMAL"


class InspectionReportTemplate(StrictModel):
    schema_version: Literal["1.0.0"] = REPORT_CONTRACT_VERSION
    template_id: Literal["TPL-INSPECTION-REPORT-V1"] = "TPL-INSPECTION-REPORT-V1"
    required_sections: tuple[str, ...]

    @model_validator(mode="after")
    def validate_sections(self) -> Self:
        if self.required_sections != REPORT_REQUIRED_SECTIONS:
            raise ValueError("inspection-report template sections or order are invalid")
        return self


class InspectionReportRequest(StrictModel):
    schema_version: Literal["1.0.0"] = REPORT_CONTRACT_VERSION
    task_id: UUID
    request_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    report_id: UUID
    revision: int = Field(ge=1, le=10_000)
    title: str = Field(min_length=1, max_length=1_000)
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    template_id: Literal["TPL-INSPECTION-REPORT-V1"] = "TPL-INSPECTION-REPORT-V1"


class ReportSourceDataset(StrictModel):
    dataset_id: UUID
    scope: TenantScope
    artifact: ArtifactRef
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    method_code: str = Field(min_length=1, max_length=32)
    instrument_id: str = Field(min_length=1, max_length=256)
    calibration_id: str = Field(min_length=1, max_length=256)
    calibration_version: str = Field(min_length=1, max_length=128)
    calibration_valid_at_acquisition: bool
    operator_id: UUID
    acquired_at: datetime

    @model_validator(mode="after")
    def validate_source(self) -> Self:
        if self.artifact.scope != self.scope:
            raise ValueError("source dataset and artifact scopes must match exactly")
        if not self.artifact.immutable:
            raise ValueError("report source artifact must be immutable")
        if self.acquired_at.tzinfo is None or self.acquired_at.utcoffset() != UTC.utcoffset(
            self.acquired_at
        ):
            raise ValueError("source acquisition time must use UTC")
        return self


class ReportProcessingEvidence(StrictModel):
    processing_run_id: UUID
    scope: TenantScope
    dataset_id: UUID
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    adapter_version: str = Field(min_length=1, max_length=128)
    parser_version: str = Field(min_length=1, max_length=128)
    algorithm_version: str = Field(min_length=1, max_length=128)
    parameters_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["SUCCESS"] = "SUCCESS"


class ReportObservation(StrictModel):
    observation_id: UUID
    scope: TenantScope
    processing_run_id: UUID
    dataset_id: UUID
    location_id: UUID
    name: str = Field(min_length=1, max_length=256)
    dimension: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,63}$")
    unit: str = Field(min_length=1, max_length=32)
    value: Decimal
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_unit(self) -> Self:
        if not is_registered_unit(self.dimension, self.unit):
            raise ValueError("observation unit is not registered for its dimension")
        return self


class ReportCalculation(StrictModel):
    calculation_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,127}$")
    formula: CalculationFormula
    input_observation_ids: tuple[UUID, ...] = Field(min_length=1, max_length=10_000)
    dimension: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,63}$")
    unit: str = Field(min_length=1, max_length=32)
    reported_value: Decimal

    @model_validator(mode="after")
    def canonical_inputs(self) -> Self:
        if self.input_observation_ids != tuple(sorted(set(self.input_observation_ids), key=str)):
            raise ValueError("calculation input observation IDs must be sorted and unique")
        if not is_registered_unit(self.dimension, self.unit):
            raise ValueError("calculation unit is not registered for its dimension")
        return self


class ReportFigure(StrictModel):
    figure_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,127}$")
    title: str = Field(min_length=1, max_length=1_000)
    artifact: ArtifactRef
    source_observation_ids: tuple[UUID, ...] = Field(min_length=1, max_length=10_000)

    @model_validator(mode="after")
    def canonical_sources(self) -> Self:
        if self.source_observation_ids != tuple(sorted(set(self.source_observation_ids), key=str)):
            raise ValueError("figure observation IDs must be sorted and unique")
        if not self.artifact.immutable:
            raise ValueError("report figure artifact must be immutable")
        return self


class ReportFinding(StrictModel):
    finding_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,127}$")
    statement: str = Field(min_length=1, max_length=8_000)
    severity: FindingSeverity
    observation_ids: tuple[UUID, ...] = Field(min_length=1, max_length=10_000)
    calculation_ids: tuple[str, ...] = Field(default=(), max_length=1_000)
    plan_basis_ids: tuple[str, ...] = Field(min_length=1, max_length=64)
    limitations: tuple[str, ...] = Field(min_length=1, max_length=32)
    human_confirmation_required: bool = False

    @model_validator(mode="after")
    def validate_finding(self) -> Self:
        if self.observation_ids != tuple(sorted(set(self.observation_ids), key=str)):
            raise ValueError("finding observation IDs must be sorted and unique")
        if self.calculation_ids != tuple(sorted(set(self.calculation_ids))):
            raise ValueError("finding calculation IDs must be sorted and unique")
        if self.plan_basis_ids != tuple(sorted(set(self.plan_basis_ids))):
            raise ValueError("finding plan basis IDs must be sorted and unique")
        if self.severity is FindingSeverity.CRITICAL and not self.human_confirmation_required:
            raise ValueError("critical findings require qualified human confirmation")
        return self


class ReportConclusion(StrictModel):
    text: str = Field(min_length=1, max_length=12_000)
    level: ConclusionLevel
    finding_ids: tuple[str, ...] = Field(min_length=1, max_length=1_000)
    limitations: tuple[str, ...] = Field(min_length=1, max_length=32)
    human_confirmation_required: bool = False

    @model_validator(mode="after")
    def validate_boundary(self) -> Self:
        if self.finding_ids != tuple(sorted(set(self.finding_ids))):
            raise ValueError("conclusion finding IDs must be sorted and unique")
        if self.level is ConclusionLevel.FORMAL and not self.human_confirmation_required:
            raise ValueError("formal conclusion requires qualified human confirmation")
        return self


class ReportRevision(StrictModel):
    revision: int = Field(ge=1, le=10_000)
    revision_id: UUID
    previous_report_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    reason: str = Field(min_length=1, max_length=2_000)
    author_id: UUID

    @model_validator(mode="after")
    def validate_previous(self) -> Self:
        if (self.revision == 1) != (self.previous_report_sha256 is None):
            raise ValueError("only the first report revision omits a previous report hash")
        return self


class InspectionReportCandidate(StrictModel):
    schema_version: Literal["1.0.0"] = REPORT_CONTRACT_VERSION
    summary: str = Field(min_length=1, max_length=8_000)
    sections: tuple[PlanSection, ...] = Field(min_length=1, max_length=32)
    sources: tuple[ReportSourceDataset, ...] = Field(min_length=1, max_length=1_000)
    processing: tuple[ReportProcessingEvidence, ...] = Field(min_length=1, max_length=1_000)
    observations: tuple[ReportObservation, ...] = Field(min_length=1, max_length=100_000)
    calculations: tuple[ReportCalculation, ...] = Field(default=(), max_length=10_000)
    figures: tuple[ReportFigure, ...] = Field(default=(), max_length=10_000)
    findings: tuple[ReportFinding, ...] = Field(min_length=1, max_length=10_000)
    conclusion: ReportConclusion
    limitations: tuple[str, ...] = Field(min_length=1, max_length=64)
    revisions: tuple[ReportRevision, ...] = Field(min_length=1, max_length=10_000)
    plan: InspectionPlanResult

    @model_validator(mode="after")
    def unique_ids(self) -> Self:
        groups = (
            ("section", tuple(item.section_id for item in self.sections)),
            ("source", tuple(str(item.dataset_id) for item in self.sources)),
            ("processing", tuple(str(item.processing_run_id) for item in self.processing)),
            ("observation", tuple(str(item.observation_id) for item in self.observations)),
            ("calculation", tuple(item.calculation_id for item in self.calculations)),
            ("figure", tuple(item.figure_id for item in self.figures)),
            ("finding", tuple(item.finding_id for item in self.findings)),
            ("revision", tuple(str(item.revision_id) for item in self.revisions)),
        )
        for name, values in groups:
            if len(values) != len(set(values)):
                raise ValueError(f"report {name} identifiers must be unique")
        return self


class InspectionReportResult(StrictModel):
    schema_version: Literal["1.0.0"] = REPORT_CONTRACT_VERSION
    skill_version: str = Field(min_length=1, max_length=128)
    template_id: Literal["TPL-INSPECTION-REPORT-V1"] = "TPL-INSPECTION-REPORT-V1"
    template_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    scope: TenantScope
    task_id: UUID
    request_id: str
    report_id: UUID
    revision: int = Field(ge=1)
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: AgentStatus
    summary: str
    sections: tuple[PlanSection, ...]
    sources: tuple[ReportSourceDataset, ...]
    processing: tuple[ReportProcessingEvidence, ...]
    observations: tuple[ReportObservation, ...]
    calculations: tuple[ReportCalculation, ...]
    figures: tuple[ReportFigure, ...]
    findings: tuple[ReportFinding, ...]
    conclusion: ReportConclusion
    limitations: tuple[str, ...]
    revisions: tuple[ReportRevision, ...]
    issues: tuple[Issue, ...] = Field(max_length=256)
    review_required: Literal[True] = True
    approval_state: Literal["PENDING"] = "PENDING"
    formal_release_allowed: Literal[False] = False
    report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_hashes(self) -> Self:
        if self.report_sha256 != inspection_report_sha256(self):
            raise ValueError("inspection report hash does not match report content")
        if self.result_sha256 != inspection_report_result_sha256(self):
            raise ValueError("inspection report result hash is invalid")
        return self


def load_inspection_report_template(path: Path) -> InspectionReportTemplate:
    return InspectionReportTemplate.model_validate_json(path.read_text(encoding="utf-8"))


class InspectionReportSkill:
    def __init__(
        self,
        template: InspectionReportTemplate,
        *,
        skill_version: str = "inspection-report-skill-1.0.0",
    ) -> None:
        self._template = template
        self.skill_version = skill_version
        self.template_sha256 = _canonical_hash(template.model_dump(mode="json"))

    def validate(
        self,
        scope: TenantScope,
        request: InspectionReportRequest,
        candidate: InspectionReportCandidate,
    ) -> InspectionReportResult:
        issues: list[Issue] = []
        self._validate_plan(scope, request, candidate.plan, issues)
        section_ids = tuple(item.section_id for item in candidate.sections)
        if section_ids != self._template.required_sections:
            issues.append(
                _issue(
                    "REPORT_SECTION_SET_INVALID",
                    "ERROR",
                    "Report sections are missing, unknown, duplicated, or out of template order.",
                    "sections",
                    "Use every registered report template section exactly once and in order.",
                )
            )

        sources = {item.dataset_id: item for item in candidate.sources}
        processing = {item.processing_run_id: item for item in candidate.processing}
        observations = {item.observation_id: item for item in candidate.observations}
        calculations = {item.calculation_id: item for item in candidate.calculations}
        plan_basis_ids = {item.basis_id for item in candidate.plan.standard_basis}

        for index, source in enumerate(candidate.sources):
            if source.scope != scope or source.artifact.scope != scope:
                issues.append(
                    _issue(
                        "REPORT_SOURCE_SCOPE_DENIED",
                        "CRITICAL",
                        "A source dataset or artifact belongs to another exact scope.",
                        f"sources.{index}",
                        "Use immutable source data from the current authorized scope.",
                    )
                )
            if source.method_code not in SUPPORTED_METHODS:
                issues.append(
                    _issue(
                        "REPORT_SOURCE_METHOD_INVALID",
                        "CRITICAL",
                        "A source dataset uses a method outside the registered V1 ontology.",
                        f"sources.{index}.method_code",
                        "Use a registered method or a versioned Skill extension.",
                    )
                )
            if not source.calibration_valid_at_acquisition:
                issues.append(
                    _issue(
                        "REPORT_CALIBRATION_INVALID",
                        "CRITICAL",
                        "Source calibration was not valid at acquisition time.",
                        f"sources.{index}.calibration_valid_at_acquisition",
                        "Exclude the source or obtain qualified disposition and reacquisition.",
                    )
                )

        for index, run in enumerate(candidate.processing):
            referenced_source = sources.get(run.dataset_id)
            if (
                run.scope != scope
                or referenced_source is None
                or run.dataset_sha256 != referenced_source.dataset_sha256
            ):
                issues.append(
                    _issue(
                        "REPORT_PROCESSING_SOURCE_INVALID",
                        "CRITICAL",
                        "Processing evidence does not bind an exact-scope source dataset and hash.",
                        f"processing.{index}",
                        "Reprocess the immutable source through a registered adapter.",
                    )
                )

        for index, observation in enumerate(candidate.observations):
            referenced_run = processing.get(observation.processing_run_id)
            if (
                observation.scope != scope
                or referenced_run is None
                or referenced_run.dataset_id != observation.dataset_id
                or observation.dataset_id not in sources
            ):
                issues.append(
                    _issue(
                        "REPORT_OBSERVATION_TRACE_INVALID",
                        "CRITICAL",
                        "An observation lacks exact source and processing traceability.",
                        f"observations.{index}",
                        "Bind the observation to the exact scoped processing run and dataset.",
                    )
                )

        for index, calculation in enumerate(candidate.calculations):
            issue = _validate_calculation(calculation, observations)
            if issue is not None:
                issues.append(issue.model_copy(update={"affected_path": f"calculations.{index}"}))

        for index, figure in enumerate(candidate.figures):
            if figure.artifact.scope != scope or any(
                item not in observations for item in figure.source_observation_ids
            ):
                issues.append(
                    _issue(
                        "REPORT_FIGURE_TRACE_INVALID",
                        "CRITICAL",
                        "A figure is cross-scope or references an unknown observation.",
                        f"figures.{index}",
                        "Regenerate the immutable figure from traced observations.",
                    )
                )

        for index, finding in enumerate(candidate.findings):
            if any(item not in observations for item in finding.observation_ids):
                issues.append(
                    _issue(
                        "REPORT_FINDING_OBSERVATION_MISSING",
                        "CRITICAL",
                        "A finding references an unknown observation.",
                        f"findings.{index}.observation_ids",
                        "Bind every finding to exact traced observations.",
                    )
                )
            if any(item not in calculations for item in finding.calculation_ids):
                issues.append(
                    _issue(
                        "REPORT_FINDING_CALCULATION_MISSING",
                        "ERROR",
                        "A finding references an unknown calculation.",
                        f"findings.{index}.calculation_ids",
                        "Add the deterministic calculation or remove the reference.",
                    )
                )
            if any(item not in plan_basis_ids for item in finding.plan_basis_ids):
                issues.append(
                    _issue(
                        "REPORT_FINDING_CITATION_MISSING",
                        "CRITICAL",
                        "A finding lacks an exact applicable plan standard basis.",
                        f"findings.{index}.plan_basis_ids",
                        "Bind the finding to an exact applicable plan citation.",
                    )
                )

        finding_ids = {item.finding_id for item in candidate.findings}
        if any(item not in finding_ids for item in candidate.conclusion.finding_ids):
            issues.append(
                _issue(
                    "REPORT_CONCLUSION_FINDING_MISSING",
                    "CRITICAL",
                    "The conclusion references an unknown finding.",
                    "conclusion.finding_ids",
                    "Build the conclusion only from validated report findings.",
                )
            )
        if candidate.conclusion.level is ConclusionLevel.FORMAL:
            issues.append(
                _issue(
                    "REPORT_FORMAL_CONCLUSION_REQUIRES_APPROVAL",
                    "CRITICAL",
                    "A draft report Skill cannot release a formal conclusion.",
                    "conclusion.level",
                    "Complete independent review and qualified report approval.",
                )
            )

        self._validate_revisions(request, candidate.revisions, issues)
        has_critical = any(item.severity == "CRITICAL" for item in issues)
        has_errors = any(item.severity == "ERROR" for item in issues)
        requires_human = (
            has_critical
            or any(item.human_confirmation_required for item in candidate.findings)
            or candidate.conclusion.human_confirmation_required
        )
        status = (
            AgentStatus.HUMAN_REQUIRED
            if requires_human
            else AgentStatus.NEEDS_USER
            if has_errors
            else AgentStatus.SUCCESS
        )
        return self._result(scope, request, candidate, status, tuple(issues))

    @staticmethod
    def _validate_plan(
        scope: TenantScope,
        request: InspectionReportRequest,
        plan: InspectionPlanResult,
        issues: list[Issue],
    ) -> None:
        if (
            plan.scope != scope
            or plan.plan_sha256 != request.plan_sha256
            or plan.plan_sha256 != inspection_plan_sha256(plan)
            or plan.result_sha256 != inspection_plan_result_sha256(plan)
        ):
            issues.append(
                _issue(
                    "REPORT_PLAN_IDENTITY_INVALID",
                    "CRITICAL",
                    "The report plan scope or immutable hash binding is invalid.",
                    "plan",
                    "Use the exact current reviewed plan candidate.",
                )
            )
        if (
            plan.status not in {AgentStatus.SUCCESS, AgentStatus.PARTIAL_SUCCESS}
            or plan.approval_state != "PENDING"
            or plan.formal_use_allowed
        ):
            issues.append(
                _issue(
                    "REPORT_PLAN_STATE_INVALID",
                    "CRITICAL",
                    "The input plan is not a usable approval-pending non-formal plan.",
                    "plan.status",
                    "Resolve plan findings without fabricating approval or formal-use state.",
                )
            )

    @staticmethod
    def _validate_revisions(
        request: InspectionReportRequest,
        revisions: tuple[ReportRevision, ...],
        issues: list[Issue],
    ) -> None:
        numbers = tuple(item.revision for item in revisions)
        if numbers != tuple(range(1, len(revisions) + 1)) or numbers[-1] != request.revision:
            issues.append(
                _issue(
                    "REPORT_REVISION_SEQUENCE_INVALID",
                    "ERROR",
                    "Revision history is not contiguous or does not end at the requested revision.",
                    "revisions",
                    "Preserve every immutable revision in sequence.",
                )
            )

    def _result(
        self,
        scope: TenantScope,
        request: InspectionReportRequest,
        candidate: InspectionReportCandidate,
        status: AgentStatus,
        issues: tuple[Issue, ...],
    ) -> InspectionReportResult:
        request_hash = _canonical_hash(request.model_dump(mode="json"))
        report_hash = _canonical_hash(
            _report_content(
                scope=scope,
                task_id=request.task_id,
                request_id=request.request_id,
                request_sha256=request_hash,
                report_id=request.report_id,
                revision=request.revision,
                template_sha256=self.template_sha256,
                skill_version=self.skill_version,
                plan_sha256=candidate.plan.plan_sha256,
                candidate_payload=candidate.model_dump(mode="json", exclude={"plan"}),
            )
        )
        payload = {
            "schema_version": REPORT_CONTRACT_VERSION,
            "skill_version": self.skill_version,
            "template_id": self._template.template_id,
            "template_sha256": self.template_sha256,
            "scope": scope,
            "task_id": request.task_id,
            "request_id": request.request_id,
            "report_id": request.report_id,
            "revision": request.revision,
            "request_sha256": request_hash,
            "plan_sha256": candidate.plan.plan_sha256,
            "status": status,
            "summary": candidate.summary,
            "sections": candidate.sections,
            "sources": candidate.sources,
            "processing": candidate.processing,
            "observations": candidate.observations,
            "calculations": candidate.calculations,
            "figures": candidate.figures,
            "findings": candidate.findings,
            "conclusion": candidate.conclusion,
            "limitations": candidate.limitations,
            "revisions": candidate.revisions,
            "issues": issues,
            "review_required": True,
            "approval_state": "PENDING",
            "formal_release_allowed": False,
            "report_sha256": report_hash,
        }
        return InspectionReportResult.model_validate(
            {**payload, "result_sha256": _canonical_hash(_jsonable(payload))}
        )


def inspection_report_sha256(result: InspectionReportResult) -> str:
    candidate_payload: dict[str, object] = {
        "schema_version": REPORT_CONTRACT_VERSION,
        "summary": result.summary,
        "sections": [item.model_dump(mode="json") for item in result.sections],
        "sources": [item.model_dump(mode="json") for item in result.sources],
        "processing": [item.model_dump(mode="json") for item in result.processing],
        "observations": [item.model_dump(mode="json") for item in result.observations],
        "calculations": [item.model_dump(mode="json") for item in result.calculations],
        "figures": [item.model_dump(mode="json") for item in result.figures],
        "findings": [item.model_dump(mode="json") for item in result.findings],
        "conclusion": result.conclusion.model_dump(mode="json"),
        "limitations": list(result.limitations),
        "revisions": [item.model_dump(mode="json") for item in result.revisions],
    }
    return _canonical_hash(
        _report_content(
            scope=result.scope,
            task_id=result.task_id,
            request_id=result.request_id,
            request_sha256=result.request_sha256,
            report_id=result.report_id,
            revision=result.revision,
            template_sha256=result.template_sha256,
            skill_version=result.skill_version,
            plan_sha256=result.plan_sha256,
            candidate_payload=candidate_payload,
        )
    )


def inspection_report_result_sha256(result: InspectionReportResult) -> str:
    return _canonical_hash(result.model_dump(mode="json", exclude={"result_sha256"}))


def _report_content(
    *,
    scope: TenantScope,
    task_id: UUID,
    request_id: str,
    request_sha256: str,
    report_id: UUID,
    revision: int,
    template_sha256: str,
    skill_version: str,
    plan_sha256: str,
    candidate_payload: dict[str, object],
) -> dict[str, object]:
    return {
        "scope": scope.model_dump(mode="json"),
        "request": {
            "task_id": str(task_id),
            "request_id": request_id,
            "request_sha256": request_sha256,
            "report_id": str(report_id),
            "revision": revision,
        },
        "template_sha256": template_sha256,
        "skill_version": skill_version,
        "plan_sha256": plan_sha256,
        "candidate": candidate_payload,
    }


def _validate_calculation(
    calculation: ReportCalculation,
    observations: dict[UUID, ReportObservation],
) -> Issue | None:
    inputs = [observations.get(item) for item in calculation.input_observation_ids]
    if any(item is None for item in inputs):
        return _issue(
            "REPORT_CALCULATION_INPUT_MISSING",
            "ERROR",
            "A calculation references an unknown observation.",
            None,
            "Use only exact report observation IDs.",
        )
    typed_inputs = [item for item in inputs if item is not None]
    if calculation.formula is CalculationFormula.COUNT:
        expected_dimension, expected_unit = "COUNT", "count"
        value = Decimal(len(typed_inputs))
    else:
        dimensions = {(item.dimension, item.unit) for item in typed_inputs}
        if len(dimensions) != 1:
            return _issue(
                "REPORT_CALCULATION_DIMENSION_CONFLICT",
                "CRITICAL",
                "Calculation inputs use incompatible dimensions or units.",
                None,
                "Convert through an approved explicit unit transformation before calculation.",
            )
        expected_dimension, expected_unit = next(iter(dimensions))
        values = [item.value for item in typed_inputs]
        value = {
            CalculationFormula.MAXIMUM: max(values),
            CalculationFormula.MEAN: sum(values, Decimal(0)) / Decimal(len(values)),
            CalculationFormula.MINIMUM: min(values),
            CalculationFormula.RANGE: max(values) - min(values),
            CalculationFormula.SUM: sum(values, Decimal(0)),
        }[calculation.formula]
    if (
        calculation.dimension != expected_dimension
        or calculation.unit != expected_unit
        or calculation.reported_value != value
    ):
        return _issue(
            "REPORT_CALCULATION_MISMATCH",
            "CRITICAL",
            "Reported calculation value, dimension, or unit differs from deterministic "
            "recomputation.",
            None,
            "Use the exact allowlisted formula output and source units.",
        )
    return None


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
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, (UUID, Decimal)):
        return str(value)
    return value


def _canonical_hash(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()
