"""S6-09 immutable release-candidate, signing, and qualification contracts."""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Literal, Protocol, Self

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from pydantic import Field, model_validator

from ndt_agents.contracts.v1 import StrictModel

REQUIRED_PREREQUISITES = tuple(
    [f"S6-{index:02d}" for index in range(1, 9)] + [f"TG-{index:02d}" for index in range(6)]
)
REQUIRED_ARTIFACTS = (
    "source",
    "dependency-lock",
    "sbom",
    "schemas",
    "configuration",
    "server-package",
    "web-client",
    "migration-set",
    "prompt-bundle",
    "skill-bundle",
    "tool-registry",
    "model-registry",
    "release-evidence",
)


class ReleaseArtifact(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    artifact_id: str = Field(min_length=1, max_length=128)
    media_type: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(ge=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    immutable: bool


class PrerequisiteEvidence(StrictModel):
    prerequisite_id: str = Field(min_length=1, max_length=128)
    passed: bool
    build_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_uri: str = Field(min_length=1, max_length=1024)


class MigrationEvidence(StrictModel):
    build_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    environment_id: str = Field(min_length=1, max_length=128)
    production_like_approved: bool
    live_execution: bool
    upgrade_passed: bool
    downgrade_passed: bool
    schema_before_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    schema_after_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    schema_rollback_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    protected_data_before_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    protected_data_after_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    protected_data_rollback_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_uri: str = Field(min_length=1, max_length=1024)

    @model_validator(mode="after")
    def validate_integrity(self) -> Self:
        if self.schema_rollback_sha256 != self.schema_before_sha256:
            raise ValueError("rollback schema hash must restore the prior schema")
        if (
            len(
                {
                    self.protected_data_before_sha256,
                    self.protected_data_after_sha256,
                    self.protected_data_rollback_sha256,
                }
            )
            != 1
        ):
            raise ValueError("migration and rollback must preserve protected data hashes")
        return self


class SmokeCheck(StrEnum):
    HEALTH = "HEALTH"
    IDENTITY = "IDENTITY"
    TENANT_ISOLATION = "TENANT_ISOLATION"
    TASK_CREATE_STREAM = "TASK_CREATE_STREAM"
    REVIEW = "REVIEW"
    APPROVAL_DENIAL = "APPROVAL_DENIAL"
    CACHE_ISOLATION = "CACHE_ISOLATION"
    TOOL_DENIAL = "TOOL_DENIAL"
    BACKUP_READINESS = "BACKUP_READINESS"
    MIGRATION_STATE = "MIGRATION_STATE"
    ROLLBACK_READINESS = "ROLLBACK_READINESS"


class SmokeCheckResult(StrictModel):
    check: SmokeCheck
    passed: bool
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ReleaseSmokeEvidence(StrictModel):
    build_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    environment_id: str = Field(min_length=1, max_length=128)
    production_like_approved: bool
    live_execution: bool
    checks: tuple[SmokeCheckResult, ...] = Field(min_length=11, max_length=11)
    p0_findings: int = Field(ge=0)
    p1_findings: int = Field(ge=0)
    tenant_leaks: int = Field(ge=0)
    duplicate_committed_side_effects: int = Field(ge=0)
    correctness_failures: int = Field(ge=0)
    isolation_failures: int = Field(ge=0)
    evidence_uri: str = Field(min_length=1, max_length=1024)

    @model_validator(mode="after")
    def validate_checks(self) -> Self:
        if tuple(item.check for item in self.checks) != tuple(SmokeCheck):
            raise ValueError("release smoke checks must be complete and in stable order")
        return self


class ReleaseCandidateManifest(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    release_version: Literal["1.0.0"] = "1.0.0"
    git_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    build_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifacts: tuple[ReleaseArtifact, ...] = Field(min_length=13)
    prerequisites: tuple[PrerequisiteEvidence, ...] = Field(min_length=14, max_length=14)
    migration: MigrationEvidence
    smoke: ReleaseSmokeEvidence
    created_at: datetime
    candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_manifest(self) -> Self:
        if self.created_at.tzinfo is None or self.created_at.utcoffset() != timedelta(0):
            raise ValueError("release candidate time must use UTC")
        if tuple(item.artifact_id for item in self.artifacts) != REQUIRED_ARTIFACTS:
            raise ValueError("release artifacts must be complete and in stable order")
        if any(not item.immutable for item in self.artifacts):
            raise ValueError("release artifacts must be immutable")
        if tuple(item.prerequisite_id for item in self.prerequisites) != REQUIRED_PREREQUISITES:
            raise ValueError("release prerequisites must be complete and in stable order")
        if any(item.build_sha256 != self.build_sha256 for item in self.prerequisites):
            raise ValueError("release prerequisite build binding is invalid")
        if (
            self.migration.build_sha256 != self.build_sha256
            or self.smoke.build_sha256 != self.build_sha256
        ):
            raise ValueError("release operation build binding is invalid")
        if self.candidate_sha256 != release_candidate_sha256(self):
            raise ValueError("release candidate hash is invalid")
        return self


class SigningEnvironment(StrEnum):
    TEST = "TEST"
    APPROVED_EXTERNAL = "APPROVED_EXTERNAL"


class TrustedReleaseKey(StrictModel):
    """Application-owned trust metadata; never sourced from a release candidate."""

    key_reference: str = Field(min_length=1, max_length=256)
    public_key_base64: str = Field(min_length=1, max_length=256)
    public_key_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    purpose: str = Field(min_length=1, max_length=128)
    environment: SigningEnvironment
    approved: bool
    enabled: bool
    revoked: bool

    @model_validator(mode="after")
    def validate_key_identity(self) -> Self:
        public_key = base64.b64decode(self.public_key_base64, validate=True)
        if hashlib.sha256(public_key).hexdigest() != self.public_key_sha256:
            raise ValueError("trusted release public key hash is invalid")
        return self


class ReleaseKeyRegistry(Protocol):
    def resolve(self, key_reference: str) -> TrustedReleaseKey | None: ...


class StaticReleaseKeyRegistry:
    """Deterministic registry adapter for local tests and configuration snapshots."""

    def __init__(self, keys: tuple[TrustedReleaseKey, ...]) -> None:
        if len({key.key_reference for key in keys}) != len(keys):
            raise ValueError("trusted release key references must be unique")
        self._keys = {key.key_reference: key for key in keys}

    def resolve(self, key_reference: str) -> TrustedReleaseKey | None:
        return self._keys.get(key_reference)


class ReleaseSignature(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    algorithm: Literal["Ed25519"] = "Ed25519"
    candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    key_reference: str = Field(min_length=1, max_length=256)
    public_key_base64: str = Field(min_length=1, max_length=256)
    public_key_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    signature_base64: str = Field(min_length=1, max_length=256)
    environment: SigningEnvironment
    key_approved: bool
    signed_at: datetime

    @model_validator(mode="after")
    def validate_signature_fields(self) -> Self:
        if self.signed_at.tzinfo is None or self.signed_at.utcoffset() != timedelta(0):
            raise ValueError("signature time must use UTC")
        public_key = base64.b64decode(self.public_key_base64, validate=True)
        if hashlib.sha256(public_key).hexdigest() != self.public_key_sha256:
            raise ValueError("public key hash is invalid")
        return self


class SealedReleaseCandidate(StrictModel):
    manifest: ReleaseCandidateManifest
    signature: ReleaseSignature

    @model_validator(mode="after")
    def validate_seal(self) -> Self:
        if self.signature.candidate_sha256 != self.manifest.candidate_sha256:
            raise ValueError("signature candidate binding is invalid")
        if not verify_release_signature(self.signature):
            raise ValueError("release signature is invalid")
        return self


class ReleaseStatus(StrEnum):
    PASS = "PASS"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


class ReleaseAssessment(StrictModel):
    status: ReleaseStatus
    reason_code: str
    next_action: str
    candidate_sha256: str


def release_candidate_sha256(manifest: ReleaseCandidateManifest) -> str:
    payload = manifest.model_dump(mode="json", exclude={"candidate_sha256"})
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def build_release_candidate(**values: object) -> ReleaseCandidateManifest:
    payload: dict[str, Any] = dict(values)
    provisional = ReleaseCandidateManifest.model_construct(**payload, candidate_sha256="0" * 64)
    return ReleaseCandidateManifest.model_validate(
        {**payload, "candidate_sha256": release_candidate_sha256(provisional)}
    )


def sign_release_candidate(
    manifest: ReleaseCandidateManifest,
    private_key: Ed25519PrivateKey,
    *,
    key_reference: str,
    environment: SigningEnvironment,
    key_approved: bool,
    signed_at: datetime,
) -> SealedReleaseCandidate:
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    signature = private_key.sign(bytes.fromhex(manifest.candidate_sha256))
    record = ReleaseSignature(
        candidate_sha256=manifest.candidate_sha256,
        key_reference=key_reference,
        public_key_base64=base64.b64encode(public_key).decode(),
        public_key_sha256=hashlib.sha256(public_key).hexdigest(),
        signature_base64=base64.b64encode(signature).decode(),
        environment=environment,
        key_approved=key_approved,
        signed_at=signed_at,
    )
    return SealedReleaseCandidate(manifest=manifest, signature=record)


def verify_release_signature(
    signature: ReleaseSignature,
    trusted_key: TrustedReleaseKey | None = None,
) -> bool:
    verification_key = trusted_key
    if verification_key is not None and (
        verification_key.key_reference != signature.key_reference
        or verification_key.public_key_base64 != signature.public_key_base64
        or verification_key.public_key_sha256 != signature.public_key_sha256
    ):
        return False
    try:
        public_key = Ed25519PublicKey.from_public_bytes(
            base64.b64decode(
                (
                    verification_key.public_key_base64
                    if verification_key is not None
                    else signature.public_key_base64
                ),
                validate=True,
            )
        )
        public_key.verify(
            base64.b64decode(signature.signature_base64, validate=True),
            bytes.fromhex(signature.candidate_sha256),
        )
    except (InvalidSignature, ValueError):
        return False
    return True


def assess_release_candidate(
    candidate: SealedReleaseCandidate,
    key_registry: ReleaseKeyRegistry,
) -> ReleaseAssessment:
    manifest = candidate.manifest
    trusted_key = key_registry.resolve(candidate.signature.key_reference)
    if trusted_key is None:
        return _assessment(
            ReleaseStatus.BLOCKED,
            "RELEASE_TRUSTED_KEY_MISSING",
            "Register the exact approved release-signing key before qualification.",
            manifest,
        )
    trusted_key_eligible = (
        trusted_key.purpose == "RELEASE_SIGNING"
        and trusted_key.environment is SigningEnvironment.APPROVED_EXTERNAL
        and trusted_key.approved
        and trusted_key.enabled
        and not trusted_key.revoked
    )
    if not trusted_key_eligible:
        return _assessment(
            ReleaseStatus.BLOCKED,
            "RELEASE_TRUSTED_KEY_NOT_ELIGIBLE",
            "Approve and enable a non-revoked external release-signing key.",
            manifest,
        )
    if not verify_release_signature(candidate.signature, trusted_key):
        return _assessment(
            ReleaseStatus.FAILED,
            "RELEASE_SIGNATURE_INVALID",
            "Reject the candidate and investigate signing-key substitution or corruption.",
            manifest,
        )
    unsafe = (
        not manifest.migration.upgrade_passed
        or not manifest.migration.downgrade_passed
        or any(not check.passed for check in manifest.smoke.checks)
        or manifest.smoke.p0_findings
        or manifest.smoke.p1_findings
        or manifest.smoke.tenant_leaks
        or manifest.smoke.duplicate_committed_side_effects
        or manifest.smoke.correctness_failures
        or manifest.smoke.isolation_failures
    )
    if unsafe:
        return _assessment(
            ReleaseStatus.FAILED,
            "RELEASE_GATE_FAILED",
            "Correct the failed migration, rollback, smoke, or safety result.",
            manifest,
        )
    external_missing = (
        any(not item.passed for item in manifest.prerequisites)
        or not manifest.migration.production_like_approved
        or not manifest.migration.live_execution
        or not manifest.smoke.production_like_approved
        or not manifest.smoke.live_execution
    )
    if external_missing:
        return _assessment(
            ReleaseStatus.BLOCKED,
            "RELEASE_EXTERNAL_EVIDENCE_MISSING",
            "Pass every exact-build prerequisite and rerun live migration, rollback, smoke, "
            "and approved external signing.",
            manifest,
        )
    return _assessment(
        ReleaseStatus.PASS,
        "RELEASE_CANDIDATE_ACCEPTED",
        "Preserve the sealed candidate for TG-06 release decision.",
        manifest,
    )


def _assessment(
    status: ReleaseStatus,
    reason: str,
    action: str,
    manifest: ReleaseCandidateManifest,
) -> ReleaseAssessment:
    return ReleaseAssessment(
        status=status,
        reason_code=reason,
        next_action=action,
        candidate_sha256=manifest.candidate_sha256,
    )
