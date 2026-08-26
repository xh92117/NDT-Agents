"""S4-02 inspection-plan Skill, template, and deterministic completeness checks."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from ndt_agents.contracts.v1 import AgentStatus, Issue, StrictModel, TenantScope
from ndt_agents.knowledge.retrieval import IndexRecord, IndexStatus, InMemoryKnowledgeIndex
from ndt_agents.knowledge.standards import (
    StandardApplicabilityRequest,
    StandardApplicabilityService,
    StandardCatalog,
)
from ndt_agents.professional.qa import (
    SUPPORTED_MATERIALS,
    SUPPORTED_METHODS,
    SUPPORTED_STRUCTURES,
    ClaimApplicability,
    QACitation,
    TechnicalQAResult,
    technical_qa_result_sha256,
)

PLAN_CONTRACT_VERSION: Literal["1.0.0"] = "1.0.0"
PLAN_TEMPLATE_ID = "TPL-INSPECTION-PLAN-V1"
PLAN_REQUIRED_SECTIONS = (
    "objective",
    "scope",
    "structure_and_component",
    "applicable_basis",
    "method_and_layout",
    "equipment_and_calibration",
    "procedure",
    "sampling_and_coverage",
    "acceptance_criteria",
    "safety",
    "data_management",
    "quality_control",
    "schedule",
    "deliverables",
    "limitations",
    "review_and_approval",
    "missing_input_handling",
)
_DIMENSION_UNITS = {
    "AMPLITUDE": frozenset({"V", "dB", "level", "mV"}),
    "AREA": frozenset({"mm2", "cm2", "m2"}),
    "COUNT": frozenset({"count", "point", "sample"}),
    "FREQUENCY": frozenset({"Hz", "kHz", "MHz"}),
    "INDEX": frozenset({"index"}),
    "LENGTH": frozenset({"mm", "cm", "m", "km"}),
    "PERCENTAGE": frozenset({"%"}),
    "TIME": frozenset({"ns", "us", "ms", "s", "min", "h", "day"}),
    "VELOCITY": frozenset({"m/s"}),
}


def is_registered_unit(dimension: str, unit: str) -> bool:
    return unit in _DIMENSION_UNITS.get(dimension, frozenset())


class PlanScenario(StrEnum):
    NEW_BUILD = "NEW_BUILD"
    OPERATION = "OPERATION"
    INCIDENT = "INCIDENT"
    ACCEPTANCE = "ACCEPTANCE"
    OTHER = "OTHER"


class InspectionPlanTemplate(StrictModel):
    schema_version: Literal["1.0.0"] = PLAN_CONTRACT_VERSION
    template_id: Literal["TPL-INSPECTION-PLAN-V1"] = "TPL-INSPECTION-PLAN-V1"
    required_sections: tuple[str, ...]

    @model_validator(mode="after")
    def validate_sections(self) -> Self:
        if self.required_sections != PLAN_REQUIRED_SECTIONS:
            raise ValueError("inspection-plan template sections or order are invalid")
        return self


class InspectionPlanRequest(StrictModel):
    schema_version: Literal["1.0.0"] = PLAN_CONTRACT_VERSION
    task_id: UUID
    request_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    scenario: PlanScenario
    objective: str | None = Field(default=None, max_length=4_000)
    structure_id: UUID | None = None
    component_ids: tuple[UUID, ...] = Field(default=(), max_length=1_000)
    structure_class: str | None = Field(default=None, max_length=128)
    material_class: str | None = Field(default=None, max_length=128)
    requested_methods: tuple[str, ...] = Field(default=(), max_length=6)
    region: str = Field(pattern=r"^(?:GLOBAL|[A-Z]{2}(?:-[A-Z0-9]{1,8})*)$")
    as_of: date
    standard_types: tuple[str, ...] = Field(default=(), max_length=32)
    template_id: Literal["TPL-INSPECTION-PLAN-V1"] = "TPL-INSPECTION-PLAN-V1"

    @model_validator(mode="after")
    def canonical_sets(self) -> Self:
        if self.component_ids != tuple(sorted(set(self.component_ids), key=str)):
            raise ValueError("component IDs must be sorted and unique")
        if self.requested_methods != tuple(sorted(set(self.requested_methods))):
            raise ValueError("requested methods must be sorted and unique")
        if self.standard_types != tuple(sorted(set(self.standard_types))):
            raise ValueError("standard types must be sorted and unique")
        return self


class PlanSection(StrictModel):
    section_id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    content: str = Field(min_length=1, max_length=20_000)


class PlanQuantity(StrictModel):
    quantity_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,127}$")
    name: str = Field(min_length=1, max_length=256)
    dimension: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,63}$")
    unit: str = Field(min_length=1, max_length=32)
    lower: Decimal | None = None
    target: Decimal
    upper: Decimal | None = None

    @model_validator(mode="after")
    def validate_quantity(self) -> Self:
        if not is_registered_unit(self.dimension, self.unit):
            raise ValueError("quantity unit is not registered for its dimension")
        if self.target < 0 or (self.lower is not None and self.lower < 0):
            raise ValueError("plan quantities cannot be negative")
        if self.lower is not None and self.lower > self.target:
            raise ValueError("quantity lower bound exceeds target")
        if self.upper is not None and self.target > self.upper:
            raise ValueError("quantity target exceeds upper bound")
        return self


class PlanInputGap(StrictModel):
    field_path: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,255}$")
    reason: str = Field(min_length=1, max_length=2_000)
    impact: str = Field(min_length=1, max_length=2_000)
    owner_role: str = Field(min_length=1, max_length=128)
    blocking: bool


class PlanStandardBasis(StrictModel):
    basis_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,127}$")
    standard_version_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    qa_claim_id: str = Field(pattern=r"^claim-[0-9a-f]{16}$")
    chunk_id: str = Field(pattern=r"^[0-9a-f]{64}$")


class PlannedMethod(StrictModel):
    method_code: str = Field(min_length=1, max_length=32)
    purpose: str = Field(min_length=1, max_length=2_000)
    layout: str = Field(min_length=1, max_length=4_000)
    equipment_ids: tuple[str, ...] = Field(min_length=1, max_length=64)
    calibration_procedure: str = Field(min_length=1, max_length=4_000)
    procedure: str = Field(min_length=1, max_length=8_000)
    sampling_quantity_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,127}$")
    acceptance_basis_ids: tuple[str, ...] = Field(min_length=1, max_length=16)
    safety_controls: tuple[str, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def canonical_references(self) -> Self:
        if self.equipment_ids != tuple(sorted(set(self.equipment_ids))):
            raise ValueError("equipment IDs must be sorted and unique")
        if self.acceptance_basis_ids != tuple(sorted(set(self.acceptance_basis_ids))):
            raise ValueError("acceptance basis IDs must be sorted and unique")
        if self.safety_controls != tuple(dict.fromkeys(self.safety_controls)):
            raise ValueError("safety controls must be unique and ordered")
        return self


class InspectionPlanCandidate(StrictModel):
    schema_version: Literal["1.0.0"] = PLAN_CONTRACT_VERSION
    summary: str = Field(min_length=1, max_length=8_000)
    sections: tuple[PlanSection, ...] = Field(min_length=1, max_length=32)
    quantities: tuple[PlanQuantity, ...] = Field(min_length=1, max_length=256)
    methods: tuple[PlannedMethod, ...] = Field(min_length=1, max_length=6)
    standard_basis: tuple[PlanStandardBasis, ...] = Field(min_length=1, max_length=64)
    input_gaps: tuple[PlanInputGap, ...] = Field(default=(), max_length=64)
    limitations: tuple[str, ...] = Field(min_length=1, max_length=32)
    deliverables: tuple[str, ...] = Field(min_length=1, max_length=32)
    qa_result: TechnicalQAResult

    @model_validator(mode="after")
    def unique_identifiers(self) -> Self:
        collections = (
            ("section", tuple(item.section_id for item in self.sections)),
            ("quantity", tuple(item.quantity_id for item in self.quantities)),
            ("method", tuple(item.method_code for item in self.methods)),
            ("basis", tuple(item.basis_id for item in self.standard_basis)),
            ("gap", tuple(item.field_path for item in self.input_gaps)),
        )
        for name, values in collections:
            if len(set(values)) != len(values):
                raise ValueError(f"plan {name} identifiers must be unique")
        return self


class InspectionPlanResult(StrictModel):
    schema_version: Literal["1.0.0"] = PLAN_CONTRACT_VERSION
    skill_version: str = Field(min_length=1, max_length=128)
    template_id: Literal["TPL-INSPECTION-PLAN-V1"] = "TPL-INSPECTION-PLAN-V1"
    template_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    scope: TenantScope
    task_id: UUID
    request_id: str
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: AgentStatus
    summary: str = Field(min_length=1, max_length=8_000)
    sections: tuple[PlanSection, ...]
    quantities: tuple[PlanQuantity, ...]
    methods: tuple[PlannedMethod, ...]
    standard_basis: tuple[PlanStandardBasis, ...]
    input_gaps: tuple[PlanInputGap, ...]
    limitations: tuple[str, ...]
    deliverables: tuple[str, ...]
    qa_result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    issues: tuple[Issue, ...] = Field(max_length=128)
    review_required: Literal[True] = True
    approval_state: Literal["PENDING"] = "PENDING"
    formal_use_allowed: Literal[False] = False
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_hashes(self) -> Self:
        if self.plan_sha256 != inspection_plan_sha256(self):
            raise ValueError("inspection plan hash does not match plan content")
        if self.result_sha256 != inspection_plan_result_sha256(self):
            raise ValueError("inspection plan result hash is invalid")
        return self


def load_inspection_plan_template(path: Path) -> InspectionPlanTemplate:
    return InspectionPlanTemplate.model_validate_json(path.read_text(encoding="utf-8"))


class InspectionPlanSkill:
    def __init__(
        self,
        template: InspectionPlanTemplate,
        index: InMemoryKnowledgeIndex,
        standards: StandardCatalog,
        *,
        skill_version: str = "inspection-plan-skill-1.0.0",
    ) -> None:
        self._template = template
        self._index = index
        self._standards = standards
        self.skill_version = skill_version
        self.template_sha256 = _canonical_hash(template.model_dump(mode="json"))

    def validate(
        self,
        scope: TenantScope,
        request: InspectionPlanRequest,
        candidate: InspectionPlanCandidate,
    ) -> InspectionPlanResult:
        issues: list[Issue] = []
        required_gaps = _request_gaps(request)
        declared_gaps = {item.field_path: item for item in candidate.input_gaps}
        for field_path in required_gaps:
            if field_path not in declared_gaps:
                issues.append(
                    _issue(
                        "PLAN_MISSING_INPUT_UNDECLARED",
                        "ERROR",
                        f"Required input '{field_path}' is absent and not declared as a gap.",
                        field_path,
                        "Declare the gap, impact, owner, and whether it blocks execution.",
                    )
                )

        section_ids = tuple(item.section_id for item in candidate.sections)
        if section_ids != self._template.required_sections:
            missing = tuple(item for item in PLAN_REQUIRED_SECTIONS if item not in section_ids)
            unknown = tuple(item for item in section_ids if item not in PLAN_REQUIRED_SECTIONS)
            issues.append(
                _issue(
                    "PLAN_SECTION_SET_INVALID",
                    "ERROR",
                    "Plan section order or membership is invalid; "
                    f"missing={missing}, unknown={unknown}.",
                    "sections",
                    "Use every registered template section exactly once in template order.",
                )
            )

        if candidate.qa_result.result_sha256 != technical_qa_result_sha256(candidate.qa_result):
            issues.append(
                _issue(
                    "PLAN_QA_HASH_INVALID",
                    "CRITICAL",
                    "The Technical QA evidence hash does not match its immutable content.",
                    "qa_result.result_sha256",
                    "Stop and reload the exact reviewed Technical QA result.",
                )
            )
        if candidate.qa_result.scope != scope:
            issues.append(
                _issue(
                    "PLAN_QA_SCOPE_DENIED",
                    "CRITICAL",
                    "The Technical QA evidence belongs to another exact scope.",
                    "qa_result.scope",
                    "Run Technical QA in the plan task's current authorized scope.",
                )
            )
        if candidate.qa_result.status not in {AgentStatus.SUCCESS, AgentStatus.PARTIAL_SUCCESS}:
            issues.append(
                _issue(
                    "PLAN_QA_NOT_READY",
                    "CRITICAL",
                    "The Technical QA evidence is not ready for plan use.",
                    "qa_result.status",
                    "Resolve QA findings and complete independent review before planning.",
                )
            )

        quantities = {item.quantity_id: item for item in candidate.quantities}
        bases = {item.basis_id: item for item in candidate.standard_basis}
        for index, method in enumerate(candidate.methods):
            if method.method_code not in SUPPORTED_METHODS:
                issues.append(
                    _issue(
                        "PLAN_METHOD_OUT_OF_SCOPE",
                        "CRITICAL",
                        f"Method '{method.method_code}' is outside the registered V1 ontology.",
                        f"methods.{index}.method_code",
                        "Use a registered method or obtain a versioned Skill extension.",
                    )
                )
            if method.sampling_quantity_id not in quantities:
                issues.append(
                    _issue(
                        "PLAN_QUANTITY_REFERENCE_MISSING",
                        "ERROR",
                        "A method references an unknown sampling quantity.",
                        f"methods.{index}.sampling_quantity_id",
                        "Define the exact quantity with a registered dimension and unit.",
                    )
                )
            for basis_id in method.acceptance_basis_ids:
                if basis_id not in bases:
                    issues.append(
                        _issue(
                            "PLAN_BASIS_REFERENCE_MISSING",
                            "ERROR",
                            "A method references an unknown acceptance basis.",
                            f"methods.{index}.acceptance_basis_ids",
                            "Bind the method to a validated applicable standard basis.",
                        )
                    )

        missing_methods = tuple(
            item
            for item in request.requested_methods
            if item not in {m.method_code for m in candidate.methods}
        )
        if missing_methods:
            issues.append(
                _issue(
                    "PLAN_REQUESTED_METHOD_MISSING",
                    "ERROR",
                    f"Requested methods are absent from the plan: {missing_methods}.",
                    "methods",
                    "Add each requested method or record an explicit approved scope change.",
                )
            )

        for index, basis in enumerate(candidate.standard_basis):
            issue = self._validate_basis(scope, request, candidate.qa_result, basis)
            if issue is not None:
                issues.append(issue.model_copy(update={"affected_path": f"standard_basis.{index}"}))

        if (
            request.structure_class is not None
            and request.structure_class not in SUPPORTED_STRUCTURES
        ):
            issues.append(
                _issue(
                    "PLAN_STRUCTURE_OUT_OF_SCOPE",
                    "CRITICAL",
                    "The requested structure class is outside the registered V1 ontology.",
                    "request.structure_class",
                    "Obtain a versioned ontology and Skill extension.",
                )
            )
        if request.material_class is not None and request.material_class not in SUPPORTED_MATERIALS:
            issues.append(
                _issue(
                    "PLAN_MATERIAL_OUT_OF_SCOPE",
                    "CRITICAL",
                    "The requested material class is outside the registered V1 ontology.",
                    "request.material_class",
                    "Obtain a versioned ontology and Skill extension.",
                )
            )

        has_critical = any(item.severity == "CRITICAL" for item in issues)
        has_errors = any(item.severity == "ERROR" for item in issues)
        has_blocking_gap = any(item.blocking for item in candidate.input_gaps)
        status = (
            AgentStatus.HUMAN_REQUIRED
            if has_critical
            else AgentStatus.NEEDS_USER
            if has_errors or has_blocking_gap
            else AgentStatus.PARTIAL_SUCCESS
            if candidate.input_gaps
            else AgentStatus.SUCCESS
        )
        return self._result(scope, request, candidate, status, tuple(issues))

    def _validate_basis(
        self,
        scope: TenantScope,
        request: InspectionPlanRequest,
        qa_result: TechnicalQAResult,
        basis: PlanStandardBasis,
    ) -> Issue | None:
        claim = next(
            (item for item in qa_result.claims if item.claim_id == basis.qa_claim_id), None
        )
        if claim is None or claim.applicability not in {
            ClaimApplicability.APPLICABLE,
            ClaimApplicability.CONDITIONAL,
        }:
            return _issue(
                "PLAN_BASIS_QA_CLAIM_INVALID",
                "CRITICAL",
                "The basis does not bind an applicable validated QA claim.",
                None,
                "Use a reviewed applicable QA claim with exact evidence.",
            )
        citation = next((item for item in claim.citations if item.chunk_id == basis.chunk_id), None)
        if citation is None:
            return _issue(
                "PLAN_BASIS_CITATION_MISSING",
                "CRITICAL",
                "The basis chunk is not cited by the bound QA claim.",
                None,
                "Bind the basis to an exact citation from the validated QA result.",
            )
        snapshot = next(
            (
                item
                for item in self._index.list_for_scope(scope)
                if item.snapshot_id == citation.snapshot_id
            ),
            None,
        )
        if (
            snapshot is None
            or snapshot.scope != scope
            or snapshot.status is not IndexStatus.PUBLISHED
            or snapshot.metadata.get("standard_version_id") != basis.standard_version_id
        ):
            return _issue(
                "PLAN_BASIS_SNAPSHOT_INVALID",
                "CRITICAL",
                "The basis snapshot is unavailable, unpublished, cross-scope, or "
                "differently bound.",
                None,
                "Retrieve the current published standard in the exact scope.",
            )
        record = next((item for item in snapshot.records if item.chunk_id == basis.chunk_id), None)
        if record is None or not _citation_matches_record(citation, record):
            return _issue(
                "PLAN_BASIS_CITATION_INVALID",
                "CRITICAL",
                "The standard citation failed exact record reconstruction.",
                None,
                "Stop and recreate the QA evidence from current published knowledge.",
            )
        version = self._standards.get(scope, basis.standard_version_id)
        if version is None:
            return _issue(
                "PLAN_STANDARD_UNREGISTERED",
                "CRITICAL",
                "The cited standard version is not registered in the exact scope.",
                None,
                "Register and approve the exact standard version before plan use.",
            )
        decision = StandardApplicabilityService(self._standards).evaluate(
            scope,
            version,
            StandardApplicabilityRequest(
                as_of=request.as_of,
                region=request.region,
                standard_types=request.standard_types,
            ),
        )
        if not decision.applicable:
            return _issue(
                "PLAN_STANDARD_NOT_APPLICABLE",
                "CRITICAL",
                "The cited standard is not applicable: "
                f"{[item.value for item in decision.reasons]}.",
                None,
                "Select a current, authorized, region/date/type-applicable standard.",
            )
        return None

    def _result(
        self,
        scope: TenantScope,
        request: InspectionPlanRequest,
        candidate: InspectionPlanCandidate,
        status: AgentStatus,
        issues: tuple[Issue, ...],
    ) -> InspectionPlanResult:
        request_hash = _canonical_hash(request.model_dump(mode="json"))
        plan_hash = _canonical_hash(
            {
                "scope": scope.model_dump(mode="json"),
                "request": {
                    "task_id": str(request.task_id),
                    "request_id": request.request_id,
                    "request_sha256": request_hash,
                },
                "candidate": {
                    "summary": candidate.summary,
                    "sections": [item.model_dump(mode="json") for item in candidate.sections],
                    "quantities": [item.model_dump(mode="json") for item in candidate.quantities],
                    "methods": [item.model_dump(mode="json") for item in candidate.methods],
                    "standard_basis": [
                        item.model_dump(mode="json") for item in candidate.standard_basis
                    ],
                    "input_gaps": [item.model_dump(mode="json") for item in candidate.input_gaps],
                    "limitations": list(candidate.limitations),
                    "deliverables": list(candidate.deliverables),
                },
                "qa_result_sha256": candidate.qa_result.result_sha256,
                "template_sha256": self.template_sha256,
                "skill_version": self.skill_version,
            }
        )
        payload = {
            "schema_version": PLAN_CONTRACT_VERSION,
            "skill_version": self.skill_version,
            "template_id": self._template.template_id,
            "template_sha256": self.template_sha256,
            "scope": scope,
            "task_id": request.task_id,
            "request_id": request.request_id,
            "request_sha256": request_hash,
            "status": status,
            "summary": candidate.summary,
            "sections": candidate.sections,
            "quantities": candidate.quantities,
            "methods": candidate.methods,
            "standard_basis": candidate.standard_basis,
            "input_gaps": candidate.input_gaps,
            "limitations": candidate.limitations,
            "deliverables": candidate.deliverables,
            "qa_result_sha256": candidate.qa_result.result_sha256,
            "issues": issues,
            "review_required": True,
            "approval_state": "PENDING",
            "formal_use_allowed": False,
            "plan_sha256": plan_hash,
        }
        result_hash = _canonical_hash(_jsonable(payload))
        return InspectionPlanResult.model_validate({**payload, "result_sha256": result_hash})


def inspection_plan_sha256(result: InspectionPlanResult) -> str:
    return _canonical_hash(
        {
            "scope": result.scope.model_dump(mode="json"),
            "request": {
                "task_id": str(result.task_id),
                "request_id": result.request_id,
                "request_sha256": result.request_sha256,
            },
            "candidate": {
                "summary": result.summary,
                "sections": [item.model_dump(mode="json") for item in result.sections],
                "quantities": [item.model_dump(mode="json") for item in result.quantities],
                "methods": [item.model_dump(mode="json") for item in result.methods],
                "standard_basis": [item.model_dump(mode="json") for item in result.standard_basis],
                "input_gaps": [item.model_dump(mode="json") for item in result.input_gaps],
                "limitations": list(result.limitations),
                "deliverables": list(result.deliverables),
            },
            "qa_result_sha256": result.qa_result_sha256,
            "template_sha256": result.template_sha256,
            "skill_version": result.skill_version,
        }
    )


def inspection_plan_result_sha256(result: InspectionPlanResult) -> str:
    return _canonical_hash(result.model_dump(mode="json", exclude={"result_sha256"}))


def _request_gaps(request: InspectionPlanRequest) -> tuple[str, ...]:
    return tuple(
        field
        for field, missing in (
            ("request.objective", request.objective is None),
            ("request.structure_id", request.structure_id is None),
            ("request.component_ids", not request.component_ids),
            ("request.structure_class", request.structure_class is None),
            ("request.material_class", request.material_class is None),
            ("request.requested_methods", not request.requested_methods),
        )
        if missing
    )


def _citation_matches_record(citation: QACitation, record: IndexRecord) -> bool:
    return (
        citation.chunk_id == record.chunk_id
        and citation.content_sha256 == record.content_sha256
        and citation.document_id == record.document_id
        and citation.document_sha256 == record.document_sha256
        and citation.artifact_id == record.artifact_id
        and citation.artifact_version == record.artifact_version
        and citation.source_sha256 == record.source_sha256
        and citation.source_title == record.source_title
        and citation.source_media_type == record.source_media_type
        and citation.parser_name == record.parser_name
        and citation.parser_version == record.parser_version
        and citation.normalizer_version == record.normalizer_version
        and citation.page_index == record.page_index
        and citation.locator_type == record.locator_type.value
        and citation.locator == record.locator
        and citation.quote.casefold() in record.text.casefold()
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
    if isinstance(value, (StrEnum, date)):
        return value.isoformat() if isinstance(value, date) else value.value
    if isinstance(value, (UUID, Decimal)):
        return str(value)
    return value


def _canonical_hash(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()
