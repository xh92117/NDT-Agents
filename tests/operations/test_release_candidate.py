"""S6-09 immutable release-candidate and signing tests."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import ValidationError

from ndt_agents.operations.release import (
    REQUIRED_ARTIFACTS,
    REQUIRED_PREREQUISITES,
    MigrationEvidence,
    PrerequisiteEvidence,
    ReleaseArtifact,
    ReleaseCandidateManifest,
    ReleaseSmokeEvidence,
    ReleaseStatus,
    SealedReleaseCandidate,
    SigningEnvironment,
    SmokeCheck,
    SmokeCheckResult,
    StaticReleaseKeyRegistry,
    TrustedReleaseKey,
    assess_release_candidate,
    build_release_candidate,
    sign_release_candidate,
)

BUILD = "a" * 64


def sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def artifacts(*, mutable: bool = False) -> tuple[ReleaseArtifact, ...]:
    return tuple(
        ReleaseArtifact(
            artifact_id=artifact_id,
            media_type="application/octet-stream",
            size_bytes=index + 1,
            sha256=sha(artifact_id),
            immutable=not mutable,
        )
        for index, artifact_id in enumerate(REQUIRED_ARTIFACTS)
    )


def prerequisites(*, passed: bool = True) -> tuple[PrerequisiteEvidence, ...]:
    return tuple(
        PrerequisiteEvidence(
            prerequisite_id=prerequisite_id,
            passed=passed,
            build_sha256=BUILD,
            evidence_sha256=sha(prerequisite_id),
            evidence_uri=f"artifact://release/{prerequisite_id}",
        )
        for prerequisite_id in REQUIRED_PREREQUISITES
    )


def migration(
    *, approved: bool = True, live: bool = True, upgrade: bool = True, downgrade: bool = True
) -> MigrationEvidence:
    return MigrationEvidence(
        build_sha256=BUILD,
        environment_id="release-staging-1",
        production_like_approved=approved,
        live_execution=live,
        upgrade_passed=upgrade,
        downgrade_passed=downgrade,
        schema_before_sha256=sha("schema-before"),
        schema_after_sha256=sha("schema-after"),
        schema_rollback_sha256=sha("schema-before"),
        protected_data_before_sha256=sha("protected-data"),
        protected_data_after_sha256=sha("protected-data"),
        protected_data_rollback_sha256=sha("protected-data"),
        evidence_sha256=sha("migration-evidence"),
        evidence_uri="artifact://release/migration",
    )


def smoke(
    *, approved: bool = True, live: bool = True, failed_check: SmokeCheck | None = None
) -> ReleaseSmokeEvidence:
    return ReleaseSmokeEvidence(
        build_sha256=BUILD,
        environment_id="release-staging-1",
        production_like_approved=approved,
        live_execution=live,
        checks=tuple(
            SmokeCheckResult(
                check=check,
                passed=check is not failed_check,
                evidence_sha256=sha(check.value),
            )
            for check in SmokeCheck
        ),
        p0_findings=0,
        p1_findings=0,
        tenant_leaks=0,
        duplicate_committed_side_effects=0,
        correctness_failures=0,
        isolation_failures=0,
        evidence_uri="artifact://release/smoke",
    )


def manifest(**updates: object) -> ReleaseCandidateManifest:
    values: dict[str, object] = {
        "git_commit": "1" * 40,
        "build_sha256": BUILD,
        "artifacts": artifacts(),
        "prerequisites": prerequisites(),
        "migration": migration(),
        "smoke": smoke(),
        "created_at": datetime(2026, 8, 25, tzinfo=UTC),
    }
    values.update(updates)
    return build_release_candidate(**values)


def sealed(
    *,
    signing_environment: SigningEnvironment = SigningEnvironment.APPROVED_EXTERNAL,
    key_approved: bool = True,
    **manifest_updates: object,
) -> SealedReleaseCandidate:
    return sign_release_candidate(
        manifest(**manifest_updates),
        Ed25519PrivateKey.generate(),
        key_reference="kms://release/signing-key-v1",
        environment=signing_environment,
        key_approved=key_approved,
        signed_at=datetime(2026, 8, 25, 1, tzinfo=UTC),
    )


def trusted_registry(
    candidate: SealedReleaseCandidate,
    *,
    enabled: bool = True,
    revoked: bool = False,
    purpose: str = "RELEASE_SIGNING",
) -> StaticReleaseKeyRegistry:
    signature = candidate.signature
    return StaticReleaseKeyRegistry(
        (
            TrustedReleaseKey(
                key_reference=signature.key_reference,
                public_key_base64=signature.public_key_base64,
                public_key_sha256=signature.public_key_sha256,
                environment=signature.environment,
                approved=signature.key_approved,
                enabled=enabled,
                revoked=revoked,
                purpose=purpose,
            ),
        )
    )


def test_complete_external_candidate_passes_contract() -> None:
    candidate = sealed()
    assessment = assess_release_candidate(candidate, trusted_registry(candidate))
    assert assessment.status is ReleaseStatus.PASS
    assert assessment.candidate_sha256 == candidate.manifest.candidate_sha256
    assert "private" not in candidate.model_dump_json().lower()


def test_generated_test_key_and_synthetic_operations_are_blocked() -> None:
    candidate = sealed(
        signing_environment=SigningEnvironment.TEST,
        key_approved=False,
        migration=migration(approved=False, live=False),
        smoke=smoke(approved=False, live=False),
    )
    assessment = assess_release_candidate(candidate, trusted_registry(candidate))
    assert assessment.status is ReleaseStatus.BLOCKED
    assert assessment.reason_code == "RELEASE_TRUSTED_KEY_NOT_ELIGIBLE"


def test_missing_prerequisite_is_blocked_and_failed_smoke_fails() -> None:
    blocked_candidate = sealed(prerequisites=prerequisites(passed=False))
    failed_candidate = sealed(smoke=smoke(failed_check=SmokeCheck.IDENTITY))
    blocked = assess_release_candidate(blocked_candidate, trusted_registry(blocked_candidate))
    failed = assess_release_candidate(failed_candidate, trusted_registry(failed_candidate))
    assert blocked.status is ReleaseStatus.BLOCKED
    assert failed.status is ReleaseStatus.FAILED
    assert failed.reason_code == "RELEASE_GATE_FAILED"


def test_candidate_cannot_substitute_a_key_with_an_approved_reference() -> None:
    trusted_candidate = sealed()
    substituted_candidate = sealed()
    assessment = assess_release_candidate(
        substituted_candidate,
        trusted_registry(trusted_candidate),
    )
    assert assessment.status is ReleaseStatus.FAILED
    assert assessment.reason_code == "RELEASE_SIGNATURE_INVALID"


@pytest.mark.parametrize(
    ("registry", "reason"),
    [
        (StaticReleaseKeyRegistry(()), "RELEASE_TRUSTED_KEY_MISSING"),
        (None, "RELEASE_TRUSTED_KEY_NOT_ELIGIBLE"),
    ],
)
def test_unknown_or_revoked_release_key_is_blocked(
    registry: StaticReleaseKeyRegistry | None,
    reason: str,
) -> None:
    candidate = sealed()
    active_registry = registry or trusted_registry(candidate, revoked=True)
    assessment = assess_release_candidate(candidate, active_registry)
    assert assessment.status is ReleaseStatus.BLOCKED
    assert assessment.reason_code == reason


@pytest.mark.parametrize(
    ("enabled", "purpose"),
    [
        (False, "RELEASE_SIGNING"),
        (True, "MODEL_SIGNING"),
    ],
)
def test_disabled_or_wrong_purpose_release_key_is_blocked(
    enabled: bool,
    purpose: str,
) -> None:
    candidate = sealed()
    assessment = assess_release_candidate(
        candidate,
        trusted_registry(candidate, enabled=enabled, purpose=purpose),
    )
    assert assessment.status is ReleaseStatus.BLOCKED
    assert assessment.reason_code == "RELEASE_TRUSTED_KEY_NOT_ELIGIBLE"


def test_mutable_artifact_and_cross_build_evidence_are_rejected() -> None:
    with pytest.raises(ValidationError):
        manifest(artifacts=artifacts(mutable=True))
    wrong = list(prerequisites())
    wrong[0] = wrong[0].model_copy(update={"build_sha256": "b" * 64})
    with pytest.raises(ValidationError):
        manifest(prerequisites=tuple(wrong))


def test_migration_must_restore_schema_and_protected_data() -> None:
    base = migration().model_dump()
    with pytest.raises(ValidationError):
        MigrationEvidence.model_validate({**base, "schema_rollback_sha256": sha("wrong")})
    with pytest.raises(ValidationError):
        MigrationEvidence.model_validate({**base, "protected_data_after_sha256": sha("changed")})


def test_signature_tamper_is_rejected() -> None:
    candidate = sealed()
    signature = candidate.signature.model_copy(update={"candidate_sha256": "f" * 64})
    with pytest.raises(ValidationError):
        SealedReleaseCandidate(manifest=candidate.manifest, signature=signature)
