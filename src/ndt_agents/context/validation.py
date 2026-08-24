"""Critical-field retention validation and bounded compression fallback."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from ndt_agents.context.assembly import canonical_json_bytes
from ndt_agents.context.compression import ContextCompressor
from ndt_agents.context.compression_models import (
    CompressionItemKind,
    CompressionLevel,
    CompressionValidationState,
    ContextCompressionRequest,
    ContextCompressionResult,
    RawContextEvent,
)
from ndt_agents.context.models import ContextModel

_CRITICAL_NAMES = (
    "instruction",
    "security",
    "permission",
    "tenant",
    "conflict",
    "unresolved",
    "open_issue",
    "standard",
    "clause",
    "value",
    "unit",
    "citation",
    "source_hash",
    "sha256",
    "tool_error",
    "error",
    "approval",
    "decision",
)


class CompressionValidationError(RuntimeError):
    def __init__(self, *, code: str, message: str, next_action: str) -> None:
        self.code = code
        self.next_action = next_action
        super().__init__(message)


class ValidationDecision(StrEnum):
    ACCEPT = "ACCEPT"
    FALLBACK = "FALLBACK"


class ContextValidationPolicy(ContextModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    policy_version: str = Field(min_length=1, max_length=128)
    critical_retention: float = Field(default=1.0, ge=1.0, le=1.0)
    noncritical_retention: float = Field(default=0.98, ge=0.98, le=1.0)
    max_quality_degradation_points: float = Field(default=3.0, ge=0.0, le=3.0)


class ContextValidationRequest(ContextModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    compression_request: ContextCompressionRequest
    candidate: ContextCompressionResult
    policy: ContextValidationPolicy
    baseline_quality_score: float = Field(ge=0.0, le=100.0)
    candidate_quality_scores: dict[CompressionLevel, float]

    @model_validator(mode="after")
    def validate_scores(self) -> Self:
        if any(score < 0.0 or score > 100.0 for score in self.candidate_quality_scores.values()):
            raise ValueError("candidate quality scores must be between zero and 100")
        return self


class ContextValidationReport(ContextModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    policy_version: str
    candidate_level: CompressionLevel
    decision: ValidationDecision
    critical_total: int = Field(ge=0)
    critical_retained: int = Field(ge=0)
    noncritical_total: int = Field(ge=0)
    noncritical_retained: int = Field(ge=0)
    critical_retention_ratio: float = Field(ge=0.0, le=1.0)
    noncritical_retention_ratio: float = Field(ge=0.0, le=1.0)
    quality_degradation_points: float = Field(ge=0.0, le=100.0)
    missing_critical: tuple[str, ...]
    missing_noncritical_count: int = Field(ge=0)
    report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ContextValidationResult(ContextModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    result: ContextCompressionResult
    reports: tuple[ContextValidationReport, ...] = Field(min_length=1)
    fallback_levels: tuple[CompressionLevel, ...]


@dataclass(frozen=True, slots=True)
class _Atom:
    event_id: str
    name: str
    value: str
    critical: bool

    @property
    def signature(self) -> str:
        return f"{self.name}={self.value}"


class ContextCompressionValidator:
    """Validate exact raw-event retention and retry only from raw input."""

    async def validate_or_fallback(
        self,
        request: ContextValidationRequest,
        *,
        compressor: ContextCompressor,
    ) -> ContextValidationResult:
        self._validate_binding(request.compression_request, request.candidate)
        reports: list[ContextValidationReport] = []
        fallbacks: list[CompressionLevel] = []
        candidate = request.candidate

        while True:
            report = self._evaluate(
                request.compression_request.raw_events,
                candidate,
                request.policy,
                request.baseline_quality_score,
                request.candidate_quality_scores,
            )
            reports.append(report)
            if report.decision is ValidationDecision.ACCEPT:
                validated = candidate.model_copy(
                    update={
                        "validation_state": CompressionValidationState.READY,
                        "validation_report_sha256": report.report_sha256,
                        "execution_ready": True,
                    }
                )
                return ContextValidationResult(
                    result=validated,
                    reports=tuple(reports),
                    fallback_levels=tuple(fallbacks),
                )

            next_level = _fallback_level(candidate.level)
            if next_level is None:
                raise CompressionValidationError(
                    code="CONTEXT_VALIDATION_EXHAUSTED",
                    message="No safe compression level satisfied the retention policy.",
                    next_action="Keep the uncompressed verified raw context and request review.",
                )
            fallbacks.append(next_level)
            retry = _request_for_level(
                request.compression_request,
                next_level,
                semantic_compressions_used=candidate.semantic_compressions_used,
            )
            candidate = await compressor.compress(retry)
            self._validate_binding(retry, candidate)

    @staticmethod
    def _validate_binding(
        request: ContextCompressionRequest, candidate: ContextCompressionResult
    ) -> None:
        raw_hash = hashlib.sha256(
            canonical_json_bytes([event.model_dump(mode="json") for event in request.raw_events])
        ).hexdigest()
        if (
            candidate.task_id != request.task_id
            or candidate.scope.model_dump(mode="json") != request.scope.model_dump(mode="json")
            or candidate.raw_events_sha256 != raw_hash
        ):
            raise CompressionValidationError(
                code="CONTEXT_VALIDATION_BINDING_MISMATCH",
                message="The compression candidate is not bound to the exact raw context request.",
                next_action="Discard it and rebuild compression from the verified raw events.",
            )
        source_ids = [source for item in candidate.items for source in item.source_event_ids]
        expected = [event.event_id for event in request.raw_events]
        if Counter(source_ids) != Counter(expected):
            raise CompressionValidationError(
                code="CONTEXT_VALIDATION_SOURCE_COVERAGE",
                message="The compression candidate does not cover every raw event exactly once.",
                next_action="Discard it and rebuild from the complete ordered raw-event stream.",
            )

    @staticmethod
    def _evaluate(
        raw_events: tuple[RawContextEvent, ...],
        candidate: ContextCompressionResult,
        policy: ContextValidationPolicy,
        baseline_quality: float,
        quality_scores: dict[CompressionLevel, float],
    ) -> ContextValidationReport:
        atoms = tuple(atom for event in raw_events for atom in _extract_atoms(event))
        recovered_events = {
            source
            for item in candidate.items
            if item.kind is CompressionItemKind.ARTIFACT_REFERENCE
            for source in item.source_event_ids
        }
        output_atoms = Counter(
            (name, value) for item in candidate.items for name, value in _flatten(item.content)
        )
        retained: list[_Atom] = []
        missing: list[_Atom] = []
        available = output_atoms.copy()
        for atom in atoms:
            key = (atom.name, atom.value)
            if atom.event_id in recovered_events:
                retained.append(atom)
            elif available[key] > 0:
                retained.append(atom)
                available[key] -= 1
            else:
                missing.append(atom)

        critical = tuple(atom for atom in atoms if atom.critical)
        noncritical = tuple(atom for atom in atoms if not atom.critical)
        retained_critical = sum(atom.critical for atom in retained)
        retained_noncritical = sum(not atom.critical for atom in retained)
        critical_ratio = _ratio(retained_critical, len(critical))
        noncritical_ratio = _ratio(retained_noncritical, len(noncritical))
        quality = quality_scores.get(candidate.level)
        if candidate.level in {CompressionLevel.C0, CompressionLevel.C1}:
            quality = baseline_quality
        degradation = 100.0 if quality is None else max(0.0, baseline_quality - quality)
        accepted = (
            critical_ratio >= policy.critical_retention
            and noncritical_ratio >= policy.noncritical_retention
            and degradation <= policy.max_quality_degradation_points
        )
        missing_critical = tuple(sorted(atom.signature for atom in missing if atom.critical))
        missing_noncritical_count = sum(not atom.critical for atom in missing)
        decision = ValidationDecision.ACCEPT if accepted else ValidationDecision.FALLBACK
        payload = {
            "policy_version": policy.policy_version,
            "candidate_level": candidate.level.value,
            "decision": decision.value,
            "critical_total": len(critical),
            "critical_retained": retained_critical,
            "noncritical_total": len(noncritical),
            "noncritical_retained": retained_noncritical,
            "critical_retention_ratio": critical_ratio,
            "noncritical_retention_ratio": noncritical_ratio,
            "quality_degradation_points": degradation,
            "missing_critical": missing_critical,
            "missing_noncritical_count": missing_noncritical_count,
        }
        report_hash = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
        return ContextValidationReport(
            policy_version=policy.policy_version,
            candidate_level=candidate.level,
            decision=decision,
            critical_total=len(critical),
            critical_retained=retained_critical,
            noncritical_total=len(noncritical),
            noncritical_retained=retained_noncritical,
            critical_retention_ratio=critical_ratio,
            noncritical_retention_ratio=noncritical_ratio,
            quality_degradation_points=degradation,
            missing_critical=missing_critical,
            missing_noncritical_count=missing_noncritical_count,
            report_sha256=report_hash,
        )


def _extract_atoms(event: RawContextEvent) -> tuple[_Atom, ...]:
    return tuple(
        _Atom(
            event_id=event.event_id,
            name=name,
            value=value,
            critical=event.protected
            or any(marker in name.lower() for marker in _CRITICAL_NAMES)
            or _is_number(value),
        )
        for name, value in _flatten(event.content)
    )


def _flatten(value: Any, name: str = "root") -> tuple[tuple[str, str], ...]:
    rows: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for key in sorted(value):
            rows.extend(_flatten(value[key], str(key)))
    elif isinstance(value, list):
        for item in value:
            rows.extend(_flatten(item, name))
    else:
        rows.append((name, json.dumps(value, ensure_ascii=False, sort_keys=True)))
    return tuple(rows)


def _is_number(value: str) -> bool:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return False
    return isinstance(parsed, int | float) and not isinstance(parsed, bool)


def _ratio(retained: int, total: int) -> float:
    return 1.0 if total == 0 else retained / total


def _fallback_level(level: CompressionLevel) -> CompressionLevel | None:
    return {
        CompressionLevel.C3: CompressionLevel.C2,
        CompressionLevel.C2: CompressionLevel.C1,
    }.get(level)


def _request_for_level(
    request: ContextCompressionRequest,
    level: CompressionLevel,
    *,
    semantic_compressions_used: int,
) -> ContextCompressionRequest:
    policy = request.policy
    pressure = {
        CompressionLevel.C2: (policy.c2_threshold + policy.c3_threshold) / 2,
        CompressionLevel.C1: (policy.c1_threshold + policy.c2_threshold) / 2,
    }[level]
    return request.model_copy(
        update={
            "active_context_tokens": max(1, int(request.active_context_limit * pressure)),
            "semantic_compressions_used": semantic_compressions_used,
        }
    )
