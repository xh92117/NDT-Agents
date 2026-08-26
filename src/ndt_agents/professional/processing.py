"""S4-04 source-data processing control Skill and report-evidence bridge."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from ndt_agents.contracts.v1 import AgentStatus, ArtifactRef, Issue, StrictModel, TenantScope
from ndt_agents.professional.planning import is_registered_unit
from ndt_agents.professional.qa import SUPPORTED_METHODS
from ndt_agents.professional.reporting import (
    ReportObservation,
    ReportProcessingEvidence,
    ReportSourceDataset,
)

PROCESSING_CONTRACT_VERSION: Literal["1.0.0"] = "1.0.0"


class DataOrigin(StrEnum):
    SIMULATED = "SIMULATED"
    LABORATORY = "LABORATORY"
    PRODUCTION = "PRODUCTION"


class CandidateProcessingStatus(StrEnum):
    SUCCESS = "SUCCESS"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


class ProcessingBudget(StrictModel):
    max_duration_ms: int = Field(ge=1, le=7_200_000)
    max_output_bytes: int = Field(ge=1, le=2_000_000_000)
    max_observations: int = Field(ge=1, le=1_000_000)
    max_figures: int = Field(ge=0, le=10_000)
    max_adapter_calls: int = Field(default=1, ge=1, le=1)
    max_attempts: int = Field(default=1, ge=1, le=1)


class ProcessingQualityPolicy(StrictModel):
    policy_version: str = Field(min_length=1, max_length=128)
    minimum_completeness_ratio: Decimal = Field(ge=0, le=1)
    minimum_quality_score: Decimal = Field(ge=0, le=1)
    maximum_corrupted_ratio: Decimal = Field(ge=0, le=1)


class ProcessingSourceManifest(StrictModel):
    schema_version: Literal["1.0.0"] = PROCESSING_CONTRACT_VERSION
    dataset_id: UUID
    scope: TenantScope
    artifact: ArtifactRef
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    origin: DataOrigin
    method_code: str = Field(min_length=1, max_length=32)
    structure_id: UUID
    component_id: UUID
    location_id: UUID
    coordinate_reference: str = Field(min_length=1, max_length=256)
    channel_count: int = Field(ge=1, le=65_536)
    sample_count: int = Field(ge=1, le=1_000_000_000)
    sample_rate_hz: Decimal = Field(gt=0)
    signal_dimension: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,63}$")
    signal_unit: str = Field(min_length=1, max_length=32)
    acquisition_settings: dict[str, Any] = Field(min_length=1, max_length=128)
    instrument_id: str = Field(min_length=1, max_length=256)
    instrument_version: str = Field(min_length=1, max_length=128)
    calibration_id: str = Field(min_length=1, max_length=256)
    calibration_version: str = Field(min_length=1, max_length=128)
    calibration_valid_from: datetime
    calibration_valid_until: datetime
    operator_id: UUID
    acquired_at: datetime

    @model_validator(mode="after")
    def validate_manifest_shape(self) -> Self:
        if self.artifact.scope != self.scope or not self.artifact.immutable:
            raise ValueError("processing source artifact must be immutable and exact-scope")
        for value in (
            self.calibration_valid_from,
            self.calibration_valid_until,
            self.acquired_at,
        ):
            if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
                raise ValueError("processing source times must use UTC")
        if self.calibration_valid_from >= self.calibration_valid_until:
            raise ValueError("calibration validity interval is invalid")
        if not is_registered_unit(self.signal_dimension, self.signal_unit):
            raise ValueError("source signal unit is not registered for its dimension")
        _canonical_json(self.acquisition_settings)
        return self


class ProcessingRequest(StrictModel):
    schema_version: Literal["1.0.0"] = PROCESSING_CONTRACT_VERSION
    task_id: UUID
    run_id: UUID
    request_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    source: ProcessingSourceManifest
    adapter_version: str = Field(min_length=1, max_length=128)
    parser_version: str = Field(min_length=1, max_length=128)
    algorithm_version: str = Field(min_length=1, max_length=128)
    output_schema_id: str = Field(min_length=1, max_length=512)
    parameters: dict[str, Any] = Field(max_length=128)
    budget: ProcessingBudget
    quality_policy: ProcessingQualityPolicy

    @model_validator(mode="after")
    def validate_parameters(self) -> Self:
        _canonical_json(self.parameters)
        return self


class ProcessingObservation(StrictModel):
    observation_id: UUID
    scope: TenantScope
    run_id: UUID
    dataset_id: UUID
    structure_id: UUID
    component_id: UUID
    location_id: UUID
    channel_index: int = Field(ge=0)
    sample_start: int = Field(ge=0)
    sample_end: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=256)
    dimension: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,63}$")
    unit: str = Field(min_length=1, max_length=32)
    value: Decimal
    coordinates: tuple[Decimal, ...] = Field(min_length=1, max_length=4)
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_observation(self) -> Self:
        if self.sample_start >= self.sample_end:
            raise ValueError("observation sample range is invalid")
        if not is_registered_unit(self.dimension, self.unit):
            raise ValueError("processing observation unit is not registered")
        return self


class ProcessingFigure(StrictModel):
    figure_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,127}$")
    artifact: ArtifactRef
    source_observation_ids: tuple[UUID, ...] = Field(min_length=1, max_length=100_000)

    @model_validator(mode="after")
    def validate_figure(self) -> Self:
        if not self.artifact.immutable:
            raise ValueError("processing figure must be immutable")
        if self.source_observation_ids != tuple(sorted(set(self.source_observation_ids), key=str)):
            raise ValueError("processing figure observation IDs must be sorted and unique")
        return self


class ProcessingCandidate(StrictModel):
    schema_version: Literal["1.0.0"] = PROCESSING_CONTRACT_VERSION
    run_id: UUID
    scope: TenantScope
    dataset_id: UUID
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    method_code: str = Field(min_length=1, max_length=32)
    adapter_version: str = Field(min_length=1, max_length=128)
    parser_version: str = Field(min_length=1, max_length=128)
    algorithm_version: str = Field(min_length=1, max_length=128)
    output_schema_id: str = Field(min_length=1, max_length=512)
    parameters_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_artifact: ArtifactRef
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    observations: tuple[ProcessingObservation, ...] = Field(default=(), max_length=1_000_000)
    figures: tuple[ProcessingFigure, ...] = Field(default=(), max_length=10_000)
    completeness_ratio: Decimal = Field(ge=0, le=1)
    quality_score: Decimal = Field(ge=0, le=1)
    corrupted_ratio: Decimal = Field(ge=0, le=1)
    duration_ms: int = Field(ge=0)
    output_bytes: int = Field(ge=0)
    adapter_calls: int = Field(ge=0)
    attempts: int = Field(ge=0)
    model_calls: int = Field(default=0, ge=0)
    network_calls: int = Field(default=0, ge=0)
    physical_commands: int = Field(default=0, ge=0)
    status: CandidateProcessingStatus
    failure_code: str | None = Field(default=None, max_length=128)
    failure_impact: str | None = Field(default=None, max_length=2_000)
    next_action: str | None = Field(default=None, max_length=2_000)

    @model_validator(mode="after")
    def validate_candidate(self) -> Self:
        if self.output_artifact.scope != self.scope or not self.output_artifact.immutable:
            raise ValueError("processing output artifact must be immutable and exact-scope")
        if self.output_sha256 != self.output_artifact.sha256:
            raise ValueError("processing output hash must match its immutable artifact")
        if self.status in {CandidateProcessingStatus.FAILED, CandidateProcessingStatus.BLOCKED}:
            if not self.failure_code or not self.failure_impact or not self.next_action:
                raise ValueError("failed processing must preserve cause, impact, and next action")
        elif self.failure_code is not None:
            raise ValueError("non-failed processing cannot carry a failure code")
        identifiers = tuple(item.observation_id for item in self.observations)
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("processing observation IDs must be unique")
        if len({item.figure_id for item in self.figures}) != len(self.figures):
            raise ValueError("processing figure IDs must be unique")
        return self


class ProcessingControlResult(StrictModel):
    schema_version: Literal["1.0.0"] = PROCESSING_CONTRACT_VERSION
    skill_version: str = Field(min_length=1, max_length=128)
    scope: TenantScope
    task_id: UUID
    run_id: UUID
    request_id: str
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: AgentStatus
    source: ProcessingSourceManifest
    candidate_run_id: UUID
    candidate_scope: TenantScope
    candidate_dataset_id: UUID
    candidate_dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_method_code: str
    adapter_version: str
    parser_version: str
    algorithm_version: str
    output_schema_id: str
    parameters_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_artifact: ArtifactRef
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    observations: tuple[ProcessingObservation, ...]
    figures: tuple[ProcessingFigure, ...]
    completeness_ratio: Decimal
    quality_score: Decimal
    corrupted_ratio: Decimal
    duration_ms: int
    output_bytes: int
    adapter_calls: int
    attempts: int
    model_calls: int
    network_calls: int
    physical_commands: int
    candidate_status: CandidateProcessingStatus
    issues: tuple[Issue, ...] = Field(max_length=256)
    failure_code: str | None = None
    failure_impact: str | None = None
    next_action: str | None = None
    review_required: Literal[True] = True
    report_eligible: bool
    processing_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        if self.status in {AgentStatus.FAILED, AgentStatus.BLOCKED} and (
            not self.failure_code or not self.failure_impact or not self.next_action
        ):
            raise ValueError("failed processing result requires cause, impact, and next action")
        if self.report_eligible and (
            self.status is not AgentStatus.SUCCESS
            or self.source.origin is not DataOrigin.PRODUCTION
            or self.issues
        ):
            raise ValueError("only clean production processing can be report eligible")
        if self.processing_sha256 != processing_output_sha256(self):
            raise ValueError("processing output hash is invalid")
        if self.result_sha256 != processing_result_sha256(self):
            raise ValueError("processing result hash is invalid")
        return self


class DataProcessingControlSkill:
    def __init__(self, *, skill_version: str = "data-processing-control-skill-1.0.0") -> None:
        self.skill_version = skill_version

    def validate(
        self,
        scope: TenantScope,
        request: ProcessingRequest,
        candidate: ProcessingCandidate,
    ) -> ProcessingControlResult:
        issues: list[Issue] = []
        source = request.source
        if source.scope != scope or candidate.scope != scope:
            issues.append(
                _issue(
                    "PROCESSING_SCOPE_DENIED",
                    "CRITICAL",
                    "Source or processing candidate belongs to another exact scope.",
                    "scope",
                    "Use the current tenant, project, user, roles, and permission version.",
                )
            )
        if (
            source.method_code not in SUPPORTED_METHODS
            or candidate.method_code != source.method_code
        ):
            issues.append(
                _issue(
                    "PROCESSING_METHOD_INVALID",
                    "CRITICAL",
                    "The source or candidate method is unsupported or inconsistent.",
                    "method_code",
                    "Use one registered method consistently across the processing boundary.",
                )
            )
        if (
            not source.calibration_valid_from
            <= source.acquired_at
            <= source.calibration_valid_until
        ):
            issues.append(
                _issue(
                    "PROCESSING_CALIBRATION_INVALID",
                    "CRITICAL",
                    "Instrument calibration was not valid at acquisition.",
                    "source.acquired_at",
                    "Reacquire with valid calibration or obtain qualified disposition.",
                )
            )
        if (
            candidate.run_id != request.run_id
            or candidate.dataset_id != source.dataset_id
            or candidate.dataset_sha256 != source.dataset_sha256
        ):
            issues.append(
                _issue(
                    "PROCESSING_SOURCE_IDENTITY_INVALID",
                    "CRITICAL",
                    "Processing output does not bind the exact run and immutable dataset.",
                    "candidate",
                    "Run the registered adapter against the exact source manifest.",
                )
            )
        if (
            candidate.adapter_version != request.adapter_version
            or candidate.parser_version != request.parser_version
            or candidate.algorithm_version != request.algorithm_version
            or candidate.output_schema_id != request.output_schema_id
        ):
            issues.append(
                _issue(
                    "PROCESSING_VERSION_MISMATCH",
                    "CRITICAL",
                    "Adapter, parser, algorithm, or output schema version changed.",
                    "candidate",
                    "Use the exact registered version manifest from the request.",
                )
            )
        expected_parameters = _canonical_hash(request.parameters)
        if candidate.parameters_sha256 != expected_parameters:
            issues.append(
                _issue(
                    "PROCESSING_PARAMETERS_INVALID",
                    "CRITICAL",
                    "Processing parameters do not match the requested canonical hash.",
                    "candidate.parameters_sha256",
                    "Use the exact validated parameter set.",
                )
            )

        budget = request.budget
        if (
            candidate.duration_ms > budget.max_duration_ms
            or candidate.output_bytes > budget.max_output_bytes
            or len(candidate.observations) > budget.max_observations
            or len(candidate.figures) > budget.max_figures
            or candidate.adapter_calls > budget.max_adapter_calls
            or candidate.attempts > budget.max_attempts
            or candidate.adapter_calls != 1
            or candidate.attempts != 1
        ):
            issues.append(
                _issue(
                    "PROCESSING_BUDGET_EXCEEDED",
                    "CRITICAL",
                    "Processing exceeded a budget or violated the one-attempt adapter rule.",
                    "candidate",
                    "Stop processing and return preserved partial evidence for review.",
                )
            )
        if candidate.model_calls or candidate.network_calls or candidate.physical_commands:
            issues.append(
                _issue(
                    "PROCESSING_EXTERNAL_ACTION_DENIED",
                    "CRITICAL",
                    "The control Skill candidate contains an unauthorized external action.",
                    "candidate",
                    "Run only the separately registered offline adapter before validation.",
                )
            )

        policy = request.quality_policy
        if (
            candidate.completeness_ratio < policy.minimum_completeness_ratio
            or candidate.quality_score < policy.minimum_quality_score
            or candidate.corrupted_ratio > policy.maximum_corrupted_ratio
        ):
            issues.append(
                _issue(
                    "PROCESSING_QUALITY_BELOW_THRESHOLD",
                    "ERROR",
                    "Processing quality does not meet the versioned acceptance policy.",
                    "candidate",
                    "Preserve evidence and reacquire or reprocess through an approved path.",
                )
            )

        observation_ids = {item.observation_id for item in candidate.observations}
        for index, observation in enumerate(candidate.observations):
            if (
                observation.scope != scope
                or observation.run_id != request.run_id
                or observation.dataset_id != source.dataset_id
                or observation.structure_id != source.structure_id
                or observation.component_id != source.component_id
                or observation.location_id != source.location_id
                or observation.channel_index >= source.channel_count
                or observation.sample_end > source.sample_count
            ):
                issues.append(
                    _issue(
                        "PROCESSING_OBSERVATION_TRACE_INVALID",
                        "CRITICAL",
                        "An observation exceeds source bounds or loses exact traceability.",
                        f"observations.{index}",
                        "Rebuild the observation from the exact source channel and sample range.",
                    )
                )
        for index, figure in enumerate(candidate.figures):
            if figure.artifact.scope != scope or any(
                item not in observation_ids for item in figure.source_observation_ids
            ):
                issues.append(
                    _issue(
                        "PROCESSING_FIGURE_TRACE_INVALID",
                        "CRITICAL",
                        "A figure is cross-scope or references an unknown observation.",
                        f"figures.{index}",
                        "Regenerate the immutable figure from validated observations.",
                    )
                )

        has_critical = any(item.severity == "CRITICAL" for item in issues)
        has_errors = any(item.severity == "ERROR" for item in issues)
        status = _result_status(candidate.status, has_critical, has_errors)
        report_eligible = (
            status is AgentStatus.SUCCESS and not issues and source.origin is DataOrigin.PRODUCTION
        )
        return self._result(
            scope,
            request,
            candidate,
            status,
            tuple(issues),
            report_eligible,
        )

    def _result(
        self,
        scope: TenantScope,
        request: ProcessingRequest,
        candidate: ProcessingCandidate,
        status: AgentStatus,
        issues: tuple[Issue, ...],
        report_eligible: bool,
    ) -> ProcessingControlResult:
        request_hash = _canonical_hash(request.model_dump(mode="json"))
        processing_hash = _canonical_hash(
            _processing_content(
                skill_version=self.skill_version,
                scope=scope,
                task_id=request.task_id,
                run_id=request.run_id,
                request_id=request.request_id,
                request_sha256=request_hash,
                source=request.source,
                candidate=candidate,
            )
        )
        payload = {
            "schema_version": PROCESSING_CONTRACT_VERSION,
            "skill_version": self.skill_version,
            "scope": scope,
            "task_id": request.task_id,
            "run_id": request.run_id,
            "request_id": request.request_id,
            "request_sha256": request_hash,
            "status": status,
            "source": request.source,
            "candidate_run_id": candidate.run_id,
            "candidate_scope": candidate.scope,
            "candidate_dataset_id": candidate.dataset_id,
            "candidate_dataset_sha256": candidate.dataset_sha256,
            "candidate_method_code": candidate.method_code,
            "adapter_version": candidate.adapter_version,
            "parser_version": candidate.parser_version,
            "algorithm_version": candidate.algorithm_version,
            "output_schema_id": candidate.output_schema_id,
            "parameters_sha256": candidate.parameters_sha256,
            "output_artifact": candidate.output_artifact,
            "output_sha256": candidate.output_sha256,
            "observations": candidate.observations,
            "figures": candidate.figures,
            "completeness_ratio": candidate.completeness_ratio,
            "quality_score": candidate.quality_score,
            "corrupted_ratio": candidate.corrupted_ratio,
            "duration_ms": candidate.duration_ms,
            "output_bytes": candidate.output_bytes,
            "adapter_calls": candidate.adapter_calls,
            "attempts": candidate.attempts,
            "model_calls": candidate.model_calls,
            "network_calls": candidate.network_calls,
            "physical_commands": candidate.physical_commands,
            "candidate_status": candidate.status,
            "issues": issues,
            "failure_code": candidate.failure_code,
            "failure_impact": candidate.failure_impact,
            "next_action": candidate.next_action,
            "review_required": True,
            "report_eligible": report_eligible,
            "processing_sha256": processing_hash,
        }
        return ProcessingControlResult.model_validate(
            {**payload, "result_sha256": _canonical_hash(_jsonable(payload))}
        )


def processing_output_sha256(result: ProcessingControlResult) -> str:
    return _canonical_hash(
        _processing_content(
            skill_version=result.skill_version,
            scope=result.scope,
            task_id=result.task_id,
            run_id=result.run_id,
            request_id=result.request_id,
            request_sha256=result.request_sha256,
            source=result.source,
            candidate_payload=_candidate_payload_from_result(result),
        )
    )


def processing_candidate_sha256(result: ProcessingControlResult) -> str:
    """Reconstruct the exact S4-04 candidate identity preserved by a control result."""

    return _canonical_hash(_candidate_payload_from_result(result))


def _candidate_payload_from_result(result: ProcessingControlResult) -> dict[str, object]:
    return {
        "schema_version": PROCESSING_CONTRACT_VERSION,
        "run_id": str(result.candidate_run_id),
        "scope": result.candidate_scope.model_dump(mode="json"),
        "dataset_id": str(result.candidate_dataset_id),
        "dataset_sha256": result.candidate_dataset_sha256,
        "method_code": result.candidate_method_code,
        "adapter_version": result.adapter_version,
        "parser_version": result.parser_version,
        "algorithm_version": result.algorithm_version,
        "output_schema_id": result.output_schema_id,
        "parameters_sha256": result.parameters_sha256,
        "output_artifact": result.output_artifact.model_dump(mode="json"),
        "output_sha256": result.output_sha256,
        "observations": [item.model_dump(mode="json") for item in result.observations],
        "figures": [item.model_dump(mode="json") for item in result.figures],
        "completeness_ratio": str(result.completeness_ratio),
        "quality_score": str(result.quality_score),
        "corrupted_ratio": str(result.corrupted_ratio),
        "duration_ms": result.duration_ms,
        "output_bytes": result.output_bytes,
        "adapter_calls": result.adapter_calls,
        "attempts": result.attempts,
        "model_calls": result.model_calls,
        "network_calls": result.network_calls,
        "physical_commands": result.physical_commands,
        "status": result.candidate_status.value,
        "failure_code": result.failure_code,
        "failure_impact": result.failure_impact,
        "next_action": result.next_action,
    }


def processing_result_sha256(result: ProcessingControlResult) -> str:
    return _canonical_hash(result.model_dump(mode="json", exclude={"result_sha256"}))


def to_report_evidence(
    result: ProcessingControlResult,
) -> tuple[ReportSourceDataset, ReportProcessingEvidence, tuple[ReportObservation, ...]]:
    if not result.report_eligible or result.status is not AgentStatus.SUCCESS:
        raise ValueError("PROCESSING_NOT_REPORT_ELIGIBLE")
    source = result.source
    report_source = ReportSourceDataset(
        dataset_id=source.dataset_id,
        scope=source.scope,
        artifact=source.artifact,
        dataset_sha256=source.dataset_sha256,
        method_code=source.method_code,
        instrument_id=source.instrument_id,
        calibration_id=source.calibration_id,
        calibration_version=source.calibration_version,
        calibration_valid_at_acquisition=True,
        operator_id=source.operator_id,
        acquired_at=source.acquired_at,
    )
    processing = ReportProcessingEvidence(
        processing_run_id=result.run_id,
        scope=result.scope,
        dataset_id=source.dataset_id,
        dataset_sha256=source.dataset_sha256,
        adapter_version=result.adapter_version,
        parser_version=result.parser_version,
        algorithm_version=result.algorithm_version,
        parameters_sha256=result.parameters_sha256,
        output_sha256=result.output_sha256,
    )
    observations = tuple(
        ReportObservation(
            observation_id=item.observation_id,
            scope=item.scope,
            processing_run_id=item.run_id,
            dataset_id=item.dataset_id,
            location_id=item.location_id,
            name=item.name,
            dimension=item.dimension,
            unit=item.unit,
            value=item.value,
            evidence_sha256=item.evidence_sha256,
        )
        for item in result.observations
    )
    return report_source, processing, observations


def _result_status(
    candidate_status: CandidateProcessingStatus, has_critical: bool, has_errors: bool
) -> AgentStatus:
    if has_critical:
        return AgentStatus.HUMAN_REQUIRED
    if candidate_status is CandidateProcessingStatus.FAILED:
        return AgentStatus.FAILED
    if candidate_status is CandidateProcessingStatus.BLOCKED:
        return AgentStatus.BLOCKED
    if has_errors or candidate_status is CandidateProcessingStatus.PARTIAL_SUCCESS:
        return AgentStatus.PARTIAL_SUCCESS
    return AgentStatus.SUCCESS


def _processing_content(
    *,
    skill_version: str,
    scope: TenantScope,
    task_id: UUID,
    run_id: UUID,
    request_id: str,
    request_sha256: str,
    source: ProcessingSourceManifest,
    candidate: ProcessingCandidate | None = None,
    candidate_payload: dict[str, object] | None = None,
) -> dict[str, object]:
    payload = candidate.model_dump(mode="json") if candidate is not None else candidate_payload
    if payload is None:
        raise ValueError("processing candidate payload is required")
    return {
        "skill_version": skill_version,
        "scope": scope.model_dump(mode="json"),
        "task_id": str(task_id),
        "run_id": str(run_id),
        "request_id": request_id,
        "request_sha256": request_sha256,
        "source": source.model_dump(mode="json"),
        "candidate": payload,
    }


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


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as error:
        raise ValueError("processing metadata must be canonical JSON") from error


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
    return hashlib.sha256(_canonical_json(value).encode()).hexdigest()
