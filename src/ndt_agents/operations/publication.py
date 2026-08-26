"""S6-10 authorized idempotent publication and post-publication verification."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime, timedelta
from enum import StrEnum
from threading import RLock
from typing import Any, Literal, Protocol, Self

from pydantic import Field, model_validator

from ndt_agents.contracts.v1 import StrictModel
from ndt_agents.operations.release import (
    ReleaseKeyRegistry,
    ReleaseStatus,
    SealedReleaseCandidate,
    assess_release_candidate,
)


class Tg06Evidence(StrictModel):
    candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    passed: bool
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_uri: str = Field(min_length=1, max_length=1024)


class AuthorizedReleaseDecision(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_set_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    tg06_evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approver_id: str = Field(min_length=1, max_length=128)
    approver_role: Literal["RELEASE_AUTHORITY"]
    permission_version: str = Field(min_length=1, max_length=128)
    target: Literal["commercial-production"]
    approved: bool
    residual_risk_accepted: bool
    decided_at: datetime
    expires_at: datetime
    decision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_decision(self) -> Self:
        for value in (self.decided_at, self.expires_at):
            if value.tzinfo is None or value.utcoffset() != timedelta(0):
                raise ValueError("release decision times must use UTC")
        if self.expires_at <= self.decided_at:
            raise ValueError("release decision expiry must follow the decision")
        if self.decision_sha256 != release_decision_sha256(self):
            raise ValueError("release decision hash is invalid")
        return self


class PublicationRequest(StrictModel):
    candidate: SealedReleaseCandidate
    tg06: Tg06Evidence
    decision: AuthorizedReleaseDecision
    target: Literal["commercial-production"]
    idempotency_key: str = Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")


class PublisherResult(StrictModel):
    deployed_candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    deployment_id: str = Field(min_length=1, max_length=256)
    deployment_uri: str = Field(min_length=1, max_length=1024)
    immutable: bool
    published_at: datetime

    @model_validator(mode="after")
    def validate_time(self) -> Self:
        if self.published_at.tzinfo is None or self.published_at.utcoffset() != timedelta(0):
            raise ValueError("publication time must use UTC")
        return self


class PublicationState(StrEnum):
    PUBLISHED_PENDING_SMOKE = "PUBLISHED_PENDING_SMOKE"
    COMPLETE = "COMPLETE"
    ROLLBACK_REQUIRED = "ROLLBACK_REQUIRED"


class PublicationRecord(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    target: Literal["commercial-production"]
    deployment_id: str
    deployment_uri: str
    published_at: datetime
    state: PublicationState
    publication_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_hash(self) -> Self:
        if self.publication_sha256 != publication_record_sha256(self):
            raise ValueError("publication record hash is invalid")
        return self


class PublicationError(RuntimeError):
    def __init__(self, code: str, next_action: str) -> None:
        self.code = code
        self.next_action = next_action
        super().__init__("Publication request was denied.")


class PostPublicationCheck(StrEnum):
    HEALTH = "HEALTH"
    IDENTITY = "IDENTITY"
    TENANT_ISOLATION = "TENANT_ISOLATION"
    TASK_STREAM = "TASK_STREAM"
    REVIEW = "REVIEW"
    APPROVAL_CONTROL = "APPROVAL_CONTROL"
    CACHE_ISOLATION = "CACHE_ISOLATION"
    TOOL_DENIAL = "TOOL_DENIAL"
    ARTIFACT_VERSION = "ARTIFACT_VERSION"


class PostPublicationCheckResult(StrictModel):
    check: PostPublicationCheck
    passed: bool
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class PostPublicationSmoke(StrictModel):
    publication_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    deployment_id: str = Field(min_length=1, max_length=256)
    live_execution: bool
    completed_at: datetime
    checks: tuple[PostPublicationCheckResult, ...] = Field(min_length=9, max_length=9)
    p0_findings: int = Field(ge=0)
    p1_findings: int = Field(ge=0)
    tenant_leaks: int = Field(ge=0)
    duplicate_committed_side_effects: int = Field(ge=0)
    correctness_failures: int = Field(ge=0)
    isolation_failures: int = Field(ge=0)
    evidence_uri: str = Field(min_length=1, max_length=1024)

    @model_validator(mode="after")
    def validate_smoke(self) -> Self:
        if self.completed_at.tzinfo is None or self.completed_at.utcoffset() != timedelta(0):
            raise ValueError("post-publication smoke time must use UTC")
        if tuple(item.check for item in self.checks) != tuple(PostPublicationCheck):
            raise ValueError("post-publication smoke checks must be complete and in stable order")
        return self


def artifact_set_sha256(candidate: SealedReleaseCandidate) -> str:
    payload = [
        {
            "artifact_id": item.artifact_id,
            "size_bytes": item.size_bytes,
            "sha256": item.sha256,
        }
        for item in candidate.manifest.artifacts
    ]
    return _sha256(payload)


def release_decision_sha256(decision: AuthorizedReleaseDecision) -> str:
    return _sha256(decision.model_dump(mode="json", exclude={"decision_sha256"}))


def build_release_decision(**values: object) -> AuthorizedReleaseDecision:
    payload: dict[str, Any] = dict(values)
    provisional = AuthorizedReleaseDecision.model_construct(**payload, decision_sha256="0" * 64)
    return AuthorizedReleaseDecision.model_validate(
        {**payload, "decision_sha256": release_decision_sha256(provisional)}
    )


class PublicationAuthority(Protocol):
    """Trusted lookup boundary for immutable gate and release-decision records."""

    def resolve_tg06(self, evidence_sha256: str) -> Tg06Evidence | None: ...

    def resolve_decision(self, decision_sha256: str) -> AuthorizedReleaseDecision | None: ...

    def decision_is_revoked(self, decision_sha256: str) -> bool: ...


class StaticPublicationAuthority:
    """Deterministic authority snapshot for local tests and configuration adapters."""

    def __init__(
        self,
        *,
        tg06_records: tuple[Tg06Evidence, ...],
        decisions: tuple[AuthorizedReleaseDecision, ...],
        revoked_decision_sha256s: frozenset[str] = frozenset(),
    ) -> None:
        if len({item.evidence_sha256 for item in tg06_records}) != len(tg06_records):
            raise ValueError("TG-06 evidence hashes must be unique")
        if len({item.decision_sha256 for item in decisions}) != len(decisions):
            raise ValueError("release decision hashes must be unique")
        self._tg06 = {item.evidence_sha256: item for item in tg06_records}
        self._decisions = {item.decision_sha256: item for item in decisions}
        self._revoked = revoked_decision_sha256s

    def resolve_tg06(self, evidence_sha256: str) -> Tg06Evidence | None:
        return self._tg06.get(evidence_sha256)

    def resolve_decision(self, decision_sha256: str) -> AuthorizedReleaseDecision | None:
        return self._decisions.get(decision_sha256)

    def decision_is_revoked(self, decision_sha256: str) -> bool:
        return decision_sha256 in self._revoked


def publication_request_sha256(request: PublicationRequest) -> str:
    return _sha256(request.model_dump(mode="json", exclude={"idempotency_key"}))


def publication_record_sha256(record: PublicationRecord) -> str:
    return _sha256(record.model_dump(mode="json", exclude={"publication_sha256", "state"}))


class PublicationService:
    """Call one injected publisher only after exact-candidate authorization preflight."""

    def __init__(
        self,
        publisher: Callable[[PublicationRequest], PublisherResult],
        key_registry: ReleaseKeyRegistry,
        authority: PublicationAuthority,
    ) -> None:
        self._publisher = publisher
        self._key_registry = key_registry
        self._authority = authority
        self._records: dict[str, tuple[str, PublicationRecord]] = {}
        self._lock = RLock()

    def publish(self, request: PublicationRequest, *, now: datetime) -> PublicationRecord:
        digest = publication_request_sha256(request)
        with self._lock:
            existing = self._records.get(request.idempotency_key)
            if existing is not None:
                if existing[0] != digest:
                    raise PublicationError(
                        "PUBLICATION_IDEMPOTENCY_CONFLICT",
                        "Use a new idempotency key for changed publication input.",
                    )
                return existing[1]
            self._preflight(request, now=now)
            result = self._publisher(request)
            if (
                result.deployed_candidate_sha256 != request.candidate.manifest.candidate_sha256
                or not result.immutable
            ):
                raise PublicationError(
                    "PUBLICATION_DEPLOYMENT_MISMATCH",
                    "Stop and reconcile the publisher without promoting the deployment.",
                )
            provisional = PublicationRecord.model_construct(
                candidate_sha256=request.candidate.manifest.candidate_sha256,
                decision_sha256=request.decision.decision_sha256,
                target=request.target,
                deployment_id=result.deployment_id,
                deployment_uri=result.deployment_uri,
                published_at=result.published_at,
                state=PublicationState.PUBLISHED_PENDING_SMOKE,
                publication_sha256="0" * 64,
            )
            record = PublicationRecord(
                **provisional.model_dump(exclude={"publication_sha256"}),
                publication_sha256=publication_record_sha256(provisional),
            )
            self._records[request.idempotency_key] = (digest, record)
            return record

    def _preflight(self, request: PublicationRequest, *, now: datetime) -> None:
        if now.tzinfo is None or now.utcoffset() != timedelta(0):
            raise ValueError("publication preflight time must use UTC")
        trusted_tg06 = self._authority.resolve_tg06(request.tg06.evidence_sha256)
        trusted_decision = self._authority.resolve_decision(request.decision.decision_sha256)
        if (
            trusted_tg06 != request.tg06
            or trusted_decision != request.decision
            or self._authority.decision_is_revoked(request.decision.decision_sha256)
        ):
            raise PublicationError(
                "PUBLICATION_AUTHORITY_INVALID",
                "Provide active immutable TG-06 and release-decision authority records.",
            )
        release = assess_release_candidate(request.candidate, self._key_registry)
        candidate_sha256 = request.candidate.manifest.candidate_sha256
        valid = (
            release.status is ReleaseStatus.PASS
            and request.tg06.passed
            and request.tg06.candidate_sha256 == candidate_sha256
            and request.decision.candidate_sha256 == candidate_sha256
            and request.decision.artifact_set_sha256 == artifact_set_sha256(request.candidate)
            and request.decision.tg06_evidence_sha256 == request.tg06.evidence_sha256
            and request.decision.approved
            and request.decision.residual_risk_accepted
            and request.decision.target == request.target
            and request.decision.decided_at <= now <= request.decision.expires_at
        )
        if not valid:
            raise PublicationError(
                "PUBLICATION_PREREQUISITE_MISSING",
                "Provide exact PASS candidate, TG-06, and fresh authorized release evidence.",
            )


def finalize_post_publication(
    record: PublicationRecord,
    smoke: PostPublicationSmoke,
    *,
    maximum_delay: timedelta = timedelta(minutes=30),
) -> PublicationRecord:
    binding_valid = (
        smoke.publication_sha256 == record.publication_sha256
        and smoke.candidate_sha256 == record.candidate_sha256
        and smoke.deployment_id == record.deployment_id
        and record.published_at <= smoke.completed_at <= record.published_at + maximum_delay
    )
    safe = (
        smoke.live_execution
        and all(item.passed for item in smoke.checks)
        and not smoke.p0_findings
        and not smoke.p1_findings
        and not smoke.tenant_leaks
        and not smoke.duplicate_committed_side_effects
        and not smoke.correctness_failures
        and not smoke.isolation_failures
    )
    state = (
        PublicationState.COMPLETE if binding_valid and safe else PublicationState.ROLLBACK_REQUIRED
    )
    return record.model_copy(update={"state": state})


def _sha256(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()
